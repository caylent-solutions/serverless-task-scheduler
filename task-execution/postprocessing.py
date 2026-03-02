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
