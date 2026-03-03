"""
RecordRedriveResultLambda — terminal state of RedriveMonitorStateMachine.

Called when a redriven child Step Functions execution reaches a terminal state.
Records the final result to DynamoDB, overwriting the IN_PROGRESS record that
was set by the redrive API endpoint.

Input (from monitor state machine payload):
{
    "child_execution_arn":  "arn:aws:states:...:execution:target-sm:uuid-nested",
    "tenant_id":            "tenant_id",
    "target_alias":         "target_alias",
    "schedule_id":          "schedule_id",
    "child_status_check": {
        "Status": "SUCCEEDED"   # terminal status from DescribeExecution
    }
}
"""

import json
import logging
import boto3
from botocore.exceptions import ClientError

from execution_recorder import lookup_target_arn_from_dynamodb, record_execution

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn_client = boto3.client('stepfunctions')

NESTED_SUFFIX = '-nested'


def _derive_parent_execution_name(child_execution_arn: str) -> str:
    """Derive parent execution name from nested child execution ARN safely."""
    if not child_execution_arn or not child_execution_arn.startswith('arn:'):
        raise ValueError(f"Invalid child execution ARN: {child_execution_arn}")
    if ':execution:' not in child_execution_arn:
        raise ValueError(f"Child ARN is not a Step Functions execution ARN: {child_execution_arn}")

    child_execution_name = child_execution_arn.split(':')[-1]
    if not child_execution_name:
        raise ValueError(f"Unable to parse execution name from ARN: {child_execution_arn}")
    if not child_execution_name.endswith(NESTED_SUFFIX):
        raise ValueError(
            f"Child execution name does not end with '{NESTED_SUFFIX}': {child_execution_name}"
        )

    parent_execution_name = child_execution_name[:-len(NESTED_SUFFIX)]
    if not parent_execution_name:
        raise ValueError(f"Derived parent execution name is empty: {child_execution_arn}")

    return parent_execution_name


def handler(event, context):
    # SAM wraps the payload under Payload when using :::lambda:invoke
    payload = event.get('Payload', event)

    child_execution_arn = payload['child_execution_arn']
    child_status        = payload['child_status_check']['Status']
    tenant_id           = payload['tenant_id']
    target_alias        = payload['target_alias']
    schedule_id         = payload['schedule_id']

    # Derive the parent execution name (= DynamoDB SK / execution_id) from the child ARN.
    # Child execution name is always "{parent_uuid}-nested" (set by executor_step_function.json).
    parent_execution_name = _derive_parent_execution_name(child_execution_arn)

    logger.info(
        f"Recording redriven execution: child={child_execution_arn} "
        f"status={child_status} parent_execution={parent_execution_name}"
    )

    # Describe the child to get result details
    try:
        child_execution = sfn_client.describe_execution(executionArn=child_execution_arn)
    except ClientError as e:
        logger.error(f"Failed to describe child execution {child_execution_arn}: {e}")
        raise

    # target_arn is not present in child output — always look it up from DynamoDB
    target_arn = lookup_target_arn_from_dynamodb(tenant_id, target_alias)

    execution_start_time = child_execution['startDate'].isoformat()

    if child_status == 'SUCCEEDED':
        result       = json.loads(child_execution.get('output', '{}'))
        our_status   = 'SUCCESS'
        failed_state = None
        redrive_info = None
    else:
        result = {
            'Error': child_execution.get('error', child_status),
            'Cause': child_execution.get('cause', f'Execution {child_status.lower()}')
        }
        our_status   = 'FAILED'
        failed_state = str(child_execution.get('stopDate', 'Unknown'))
        # nested_execution_arn points back to the same child ARN for future redrives
        redrive_info = {
            'can_redrive': True,
            'nested_execution_arn': child_execution_arn,
            'redrive_from_state': 'ExecuteTargetWithErrorHandling',
            'message': (
                f'Execution {child_status.lower()}. '
                f'Can be redriven again targeting: {child_execution_arn}'
            )
        }

    execution_id = record_execution(
        tenant_id=tenant_id,
        target_alias=target_alias,
        schedule_id=schedule_id,
        result=result,
        status=our_status,
        state_machine_execution_arn=parent_execution_name,
        execution_start_time=execution_start_time,
        failed_state=failed_state,
        redrive_info=redrive_info,
        target_arn=target_arn
    )

    logger.info(f"Recorded redriven execution: execution_id={execution_id} status={our_status}")
    return {'status': 'recorded', 'execution_id': execution_id}
