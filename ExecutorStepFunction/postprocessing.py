"""
Postprocessing Lambda for ExecutorStepFunction
Records execution results to DynamoDB with redrive information.

Input Event (Success):
{
    "tenant_id": "jer",
    "target_alias": "calculator",
    "schedule_id": "daily-calculation",
    "execution_result": {...},
    "status": "SUCCESS",
    "state_machine_execution_arn": "execution-name",
    "execution_start_time": "2025-01-15T10:00:00.000Z"
}

Input Event (Failure):
{
    "tenant_id": "jer",
    "target_alias": "calculator",
    "schedule_id": "daily-calculation",
    "execution_result": {
        "Error": "...",
        "Cause": "..."
    },
    "status": "FAILED",
    "state_machine_execution_arn": "execution-name",
    "execution_start_time": "2025-01-15T10:00:00.000Z",
    "failed_state": "ExecuteLambdaTarget",
    "redrive_info": {
        "can_redrive": true,
        "redrive_from_state": "ExecuteLambdaTarget"
    }
}

Output:
{
    "status": "recorded",
    "execution_id": "01234567-89ab-cdef-0123-456789abcdef"
}
"""

import json
import logging
import os
import boto3
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
sfn_client = boto3.client('stepfunctions')

# Environment variables
EXECUTIONS_TABLE = os.environ['DYNAMODB_EXECUTIONS_TABLE']
APP_ENV = os.environ.get('APP_ENV', 'prod').lower()

# Determine if we should log sensitive information (non-production environments)
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


def handler(event, context):
    """
    Postprocessing handler for ExecutorStepFunction.

    Args:
        event: Execution result from Step Functions
        context: Lambda context

    Returns:
        Confirmation of recorded execution
    """
    if VERBOSE_LOGGING:
        logger.info(f"Recording execution: {json.dumps(event, default=str)}")
    else:
        logger.info(f"Recording execution for tenant={event.get('tenant_id')}, status={event.get('status')}")

    try:
        # Extract parameters
        tenant_id = event['tenant_id']
        target_alias = event['target_alias']
        schedule_id = event.get('schedule_id', 'unknown')
        execution_result = event.get('execution_result', {})
        status = event['status']
        state_machine_execution_arn = event.get('state_machine_execution_arn', 'unknown')
        execution_start_time = event.get('execution_start_time', datetime.now(timezone.utc).isoformat())

        # Additional failure information
        failed_state = event.get('failed_state')
        redrive_info = event.get('redrive_info', {})

        # Record execution
        execution_id = record_execution(
            tenant_id=tenant_id,
            target_alias=target_alias,
            schedule_id=schedule_id,
            result=execution_result,
            status=status,
            state_machine_execution_arn=state_machine_execution_arn,
            execution_start_time=execution_start_time,
            failed_state=failed_state,
            redrive_info=redrive_info
        )

        logger.info(f"Successfully recorded execution: {execution_id}")
        return {
            'status': 'recorded',
            'execution_id': execution_id
        }

    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise ValueError(f"Missing required field: {e}")
    except Exception as e:
        logger.error(f"Failed to record execution: {str(e)}", exc_info=True)
        raise


def record_execution(
    tenant_id: str,
    target_alias: str,
    schedule_id: str,
    result: Dict[str, Any],
    status: str,
    state_machine_execution_arn: str,
    execution_start_time: str,
    failed_state: str = None,
    redrive_info: Dict[str, Any] = None
) -> str:
    """
    Record execution in DynamoDB executions table.

    Args:
        tenant_id: Tenant identifier
        target_alias: Target alias
        schedule_id: Schedule identifier (can be recurring schedule or ad-hoc schedule)
        result: Execution result (includes execution_id from Lambda RequestId or error details)
        status: Execution status (SUCCESS/FAILED)
        state_machine_execution_arn: Step Functions execution ARN or name
        execution_start_time: ISO 8601 timestamp of execution start
        failed_state: Name of the state that failed (for FAILED executions)
        redrive_info: Information about redrive capability

    Returns:
        The execution_id that was recorded
    """
    try:
        executions_table = dynamodb.Table(EXECUTIONS_TABLE)

        timestamp = datetime.now(timezone.utc).isoformat()
        tenant_schedule = f"{tenant_id}#{schedule_id}"
        tenant_target = f"{tenant_id}#{target_alias}"

        # Use the Step Functions execution name (UUIDv7) directly as execution_id
        # UUIDv7 is time-ordered so we get chronological sorting automatically
        execution_id = state_machine_execution_arn

        # Calculate TTL: 45 days from now (in seconds since epoch)
        ttl_date = datetime.now(timezone.utc) + timedelta(days=45)
        ttl = int(ttl_date.timestamp())

        # Build the item to store
        item = {
            'tenant_schedule': tenant_schedule,
            'execution_id': execution_id,
            'tenant_target': tenant_target,
            'timestamp': timestamp,
            'status': status,
            'result': result,
            'executed_at': timestamp,
            'state_machine_execution_arn': state_machine_execution_arn,
            'execution_start_time': execution_start_time,
            'ttl': ttl
        }

        # Add failure-specific information
        if status == 'FAILED':
            if failed_state:
                item['failed_state'] = failed_state

            if redrive_info:
                item['redrive_info'] = redrive_info
                item['can_redrive'] = redrive_info.get('can_redrive', True)
                item['redrive_from_state'] = redrive_info.get('redrive_from_state', failed_state)
            else:
                # Default redrive info for failures
                item['can_redrive'] = True
                item['redrive_info'] = {
                    'can_redrive': True,
                    'message': 'This execution can be redriven from the failed state using Step Functions redrive capability'
                }

        # Add CloudWatch logs URL if present (for Lambda executions)
        if 'cloudwatch_logs_url' in result:
            item['cloudwatch_logs_url'] = result['cloudwatch_logs_url']
        # For failed executions, try to extract CloudWatch URL from error Cause
        # The lambda_execution_helper includes the CloudWatch URL in the error JSON
        elif status == 'FAILED' and 'Cause' in result:
            try:
                if VERBOSE_LOGGING:
                    logger.info(f"Attempting to parse Cause for CloudWatch URL. Cause type: {type(result['Cause'])}, Cause: {result['Cause'][:500] if isinstance(result['Cause'], str) else result['Cause']}")

                # Parse the Cause field - it contains an object with errorMessage
                cause_data = json.loads(result['Cause'])

                # Check if cloudwatch_logs_url is at the top level
                if 'cloudwatch_logs_url' in cause_data:
                    item['cloudwatch_logs_url'] = cause_data['cloudwatch_logs_url']
                    logger.info(f"Extracted CloudWatch URL from error Cause: {item['cloudwatch_logs_url']}")
                # If not, check if it's nested in the errorMessage field (double-encoded JSON)
                elif 'errorMessage' in cause_data:
                    try:
                        # Parse the nested JSON in errorMessage
                        error_message_data = json.loads(cause_data['errorMessage'])
                        if 'cloudwatch_logs_url' in error_message_data:
                            item['cloudwatch_logs_url'] = error_message_data['cloudwatch_logs_url']
                            logger.info(f"Extracted CloudWatch URL from nested errorMessage: {item['cloudwatch_logs_url']}")
                        elif VERBOSE_LOGGING:
                            logger.info(f"No cloudwatch_logs_url in nested errorMessage. Keys: {list(error_message_data.keys())}")
                    except (json.JSONDecodeError, TypeError) as nested_error:
                        if VERBOSE_LOGGING:
                            logger.warning(f"Failed to parse nested errorMessage: {nested_error}")
                elif VERBOSE_LOGGING:
                    logger.info(f"No cloudwatch_logs_url in parsed Cause. Keys: {list(cause_data.keys())}")
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                # If parsing fails, continue without CloudWatch URL
                if VERBOSE_LOGGING:
                    logger.warning(f"Failed to parse Cause for CloudWatch URL: {e}")

        executions_table.put_item(Item=item)

        logger.info(f"Recorded execution: tenant_schedule={tenant_schedule}, execution={execution_id}, status={status}")
        return execution_id

    except ClientError as e:
        logger.error(f"Failed to record execution: {e}")
        raise
