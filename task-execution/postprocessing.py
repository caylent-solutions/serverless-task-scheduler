"""
Postprocessing Lambda for ExecutorStepFunction.
Records execution results to DynamoDB with redrive information.

Triggered by EventBridge when the ExecutorStateMachine reaches a terminal state
(SUCCEEDED, FAILED, TIMED_OUT, ABORTED).

Input Event (from EventBridge):
{
    "detail": {
        "executionArn": "arn:aws:states:region:account:execution:stateMachine:uuid",
        "status": "SUCCEEDED" | "FAILED" | "TIMED_OUT" | "ABORTED",
        "error": "optional error code",
        "cause": "optional error message",
        "stopDate": "timestamp"
    }
}
"""

import json
import logging
import os
import boto3
from typing import Optional

from execution_recorder import (
    lookup_target_arn_from_dynamodb,
    record_execution,
    generate_console_url,
    STATES_SERVICE_IDENTIFIER,
    ECS_SERVICE_IDENTIFIER,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn_client = boto3.client('stepfunctions')

APP_ENV = os.environ.get('APP_ENV', 'prod').lower()
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


def _parse_stepfunctions_arn(arn: str) -> Optional[dict]:
    try:
        arn_parts = arn.split(':')
        if len(arn_parts) < 5:
            return None
        return {
            'region': arn_parts[3],
            'account': arn_parts[4],
            'state_machine_name': arn_parts[6] if len(arn_parts) > 6 else 'unknown'
        }
    except (IndexError, ValueError):
        return None


def construct_nested_execution_arn(target_arn: str, execution_arn: str) -> Optional[str]:
    if not target_arn or STATES_SERVICE_IDENTIFIER not in target_arn:
        return None
    try:
        execution_name = execution_arn.split(':')[-1]
        arn_parts = target_arn.split(':')
        if len(arn_parts) < 7:
            return None
        region = arn_parts[3]
        account = arn_parts[4]
        state_machine_name = arn_parts[6]
        nested_execution_arn = (
            f"arn:aws:states:{region}:{account}:execution:{state_machine_name}:{execution_name}-nested"
        )
        logger.info(f"Constructed nested execution ARN for redrive: {nested_execution_arn}")
        return nested_execution_arn
    except (IndexError, ValueError) as e:
        logger.warning(f"Failed to construct nested execution ARN: {e}")
        return None


def _get_ecs_cloudwatch_url(sfn_execution_arn: str, target_arn: str) -> Optional[str]:
    """
    Build a CloudWatch log stream URL for an ECS task execution.

    The ECS task ARN is only available in the SFN execution history's
    TaskSubmitted event — it is not propagated to the execution output because
    the ECS step uses a task token (SendTaskSuccess) whose payload is the custom
    task result, not the raw runTask response.

    Uses reverseOrder=True so that in a redriven execution (where the history
    contains events from both the original run and the redrive) we find the
    most recent TaskSubmitted event and therefore point to the correct log stream.
    """
    try:
        history = sfn_client.get_execution_history(
            executionArn=sfn_execution_arn,
            reverseOrder=True
        )
        for event in history.get('events', []):
            if event['type'] != 'TaskSubmitted':
                continue
            details = event.get('taskSubmittedEventDetails', {})
            if details.get('resourceType') != 'ecs':
                continue
            output = json.loads(details.get('output', '{}'))
            tasks = output.get('Tasks', [])
            if not tasks:
                continue

            task = tasks[0]
            ecs_task_arn = task.get('TaskArn', '')
            if not ecs_task_arn:
                continue

            # arn:aws:ecs:region:account:task/cluster/task-id
            ecs_slash_parts = ecs_task_arn.split('/')
            ecs_colon_parts = ecs_task_arn.split(':')
            task_id = ecs_slash_parts[-1] if len(ecs_slash_parts) >= 3 else ''
            region = ecs_colon_parts[3] if len(ecs_colon_parts) > 3 else ''
            if not task_id or not region:
                logger.warning(f"Malformed ECS task ARN: {ecs_task_arn}")
                continue

            # Derive task family from target_arn:
            # arn:aws:ecs:region:account:task-definition/family:revision
            target_slash_parts = target_arn.split('/')
            task_family = target_slash_parts[-1].split(':')[0] if len(target_slash_parts) >= 2 else ''
            if not task_family:
                logger.warning(f"Could not derive task family from target ARN: {target_arn}")
                continue

            containers = task.get('Containers', [])
            container_name = containers[0].get('Name', task_family) if containers else task_family

            log_group = f"/ecs/{task_family}"
            log_stream = f"ecs/{container_name}/{task_id}"

            log_group_encoded = log_group.replace('/', '%252F')
            log_stream_encoded = log_stream.replace('/', '%252F')
            url = (
                f"https://console.aws.amazon.com/cloudwatch/home"
                f"?region={region}#logsV2:log-groups/log-group/{log_group_encoded}"
                f"/log-events/{log_stream_encoded}"
            )
            logger.info(f"Generated ECS CloudWatch URL from SFN history: {url}")
            return url

    except Exception as e:
        logger.warning(f"Failed to get ECS CloudWatch URL from SFN history: {e}")
    return None


def process_success_status(execution_details: dict) -> tuple:
    output_data = json.loads(execution_details.get('output', '{}'))
    execution_result = output_data.get('execution_result', {})
    target_arn = output_data.get('target_arn', '')
    return 'SUCCESS', execution_result, target_arn, None, None


def process_failure_status(detail: dict, execution_details: dict, input_data: dict, status: str, execution_arn: str) -> tuple:
    our_status = 'FAILED'
    execution_result = {
        'Error': detail.get('error', status),
        'Cause': detail.get('cause', f'Execution {status.lower()}')
    }

    output_data = json.loads(execution_details.get('output', '{}'))
    target_arn = output_data.get('target_arn', input_data.get('target_arn', ''))

    if not target_arn:
        tenant_id = input_data.get('tenant_id')
        target_alias = input_data.get('target_alias')
        target_arn = lookup_target_arn_from_dynamodb(tenant_id, target_alias)

    failed_state = detail.get('stopDate', 'Unknown')

    redrive_info = {
        'can_redrive': True,
        'redrive_from_state': 'ExecuteTargetWithErrorHandling',
        'message': f'Execution {status.lower()}. Can be redriven from the Parallel state.'
    }

    nested_execution_arn = construct_nested_execution_arn(target_arn, execution_arn)
    if nested_execution_arn:
        redrive_info['nested_execution_arn'] = nested_execution_arn
        redrive_info['message'] = (
            f'Execution {status.lower()}. Redrive will automatically target the nested '
            f'Step Functions execution: {nested_execution_arn}'
        )

    return our_status, execution_result, target_arn, failed_state, redrive_info


def handle_eventbridge_event(event, context):
    detail = event['detail']
    execution_arn = detail['executionArn']
    status = detail['status']

    execution_details = sfn_client.describe_execution(executionArn=execution_arn)
    input_data = json.loads(execution_details['input'])

    if status == 'SUCCEEDED':
        our_status, execution_result, target_arn, failed_state, redrive_info = process_success_status(execution_details)
    else:
        our_status, execution_result, target_arn, failed_state, redrive_info = process_failure_status(
            detail, execution_details, input_data, status, execution_arn
        )

    # For ECS targets, the task ARN isn't in the execution output — look it up from
    # SFN history and inject the CloudWatch URL so record_execution can persist it.
    if target_arn and ECS_SERVICE_IDENTIFIER in target_arn and isinstance(execution_result, dict):
        ecs_url = _get_ecs_cloudwatch_url(execution_arn, target_arn)
        if ecs_url:
            execution_result['cloudwatch_logs_url'] = ecs_url

    tenant_id    = input_data.get('tenant_id')
    target_alias = input_data.get('target_alias')
    schedule_id  = input_data.get('schedule_id', 'unknown')

    try:
        execution_name = execution_arn.split(':')[-1]
        if not execution_name:
            raise ValueError("Execution name is empty after ARN parsing")
    except (IndexError, ValueError) as e:
        logger.error(f"Failed to parse execution name from ARN '{execution_arn}': {e}")
        return {
            'statusCode': 400,
            'error': 'Invalid execution ARN format',
            'message': f'Failed to parse execution ARN: {str(e)}'
        }

    execution_start_time = execution_details['startDate'].isoformat()

    if VERBOSE_LOGGING:
        logger.info(f"Processing EventBridge event: tenant={tenant_id}, status={our_status}, execution_name={execution_name}")

    execution_id = record_execution(
        tenant_id=tenant_id,
        target_alias=target_alias,
        schedule_id=schedule_id,
        result=execution_result,
        status=our_status,
        state_machine_execution_arn=execution_name,
        execution_start_time=execution_start_time,
        failed_state=failed_state,
        redrive_info=redrive_info,
        target_arn=target_arn
    )

    logger.info(f"Successfully recorded execution from EventBridge: {execution_id}")
    return {'status': 'recorded', 'execution_id': execution_id}


def handler(event, context):
    if VERBOSE_LOGGING:
        logger.info(f"Received event: {json.dumps(event, default=str)}")

    try:
        return handle_eventbridge_event(event, context)
    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise ValueError(f"Missing required field: {e}")
    except Exception as e:
        logger.error(f"Failed to record execution: {str(e)}", exc_info=True)
        raise
