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
from typing import Dict, Any, Optional
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
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# Determine if we should log sensitive information (non-production environments)
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


def generate_console_url(
    target_arn: str,
    execution_arn: str,
    cloudwatch_logs_url: Optional[str] = None
) -> Optional[str]:
    """
    Generate appropriate console URL based on target type.
    
    Args:
        target_arn: The target ARN (lambda, states, ecs, etc.)
        execution_arn: Step Functions execution ARN or name
        cloudwatch_logs_url: CloudWatch URL for Lambda (if available)
        
    Returns:
        Console URL for viewing execution details, or None if not available
    """
    # If CloudWatch URL exists (Lambda with logs), use it
    if cloudwatch_logs_url:
        return cloudwatch_logs_url
    
    # Detect target type from ARN
    if target_arn and ':states:' in target_arn:
        # Step Functions target - link to Step Functions console
        # Format: https://region.console.aws.amazon.com/states/home?region=region#/v2/executions/details/execution-arn
        # Need to construct full execution ARN if we only have the name
        try:
            if not execution_arn.startswith('arn:'):
                # Extract region and account from target ARN
                # target_arn format: arn:aws:states:region:account:stateMachine:name
                arn_parts = target_arn.split(':')
                if len(arn_parts) >= 5:
                    region = arn_parts[3]
                    account = arn_parts[4]
                    # Execution ARN format: arn:aws:states:region:account:execution:stateMachineName:executionName
                    state_machine_name = arn_parts[6] if len(arn_parts) > 6 else 'unknown'
                    execution_arn = f"arn:aws:states:{region}:{account}:execution:{state_machine_name}:{execution_arn}"
            
            # Extract region from execution ARN or use default
            if execution_arn.startswith('arn:'):
                arn_parts = execution_arn.split(':')
                region = arn_parts[3] if len(arn_parts) > 3 else AWS_REGION
            else:
                region = AWS_REGION
            
            return f"https://{region}.console.aws.amazon.com/states/home?region={region}#/v2/executions/details/{execution_arn}"
        except (IndexError, ValueError) as e:
            logger.warning(f"Failed to parse Step Functions ARN: {e}. Target ARN: {target_arn}, Execution ARN: {execution_arn}")
            return None
    
    elif target_arn and ':ecs:' in target_arn:
        # ECS target - no direct logs URL available
        # Could potentially link to ECS task console, but would need task ARN
        return None
    
    # Unknown or unsupported target type
    return None


def handler(event, context):
    """
    Postprocessing handler for ExecutorStepFunction.
    Handles EventBridge Step Functions execution status change events.

    Args:
        event: EventBridge event with Step Functions execution status
        context: Lambda context

    Returns:
        Confirmation of recorded execution
    """
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


def handle_eventbridge_event(event, context):
    """
    Handle EventBridge Step Functions execution status change event.

    Args:
        event: EventBridge event
        context: Lambda context

    Returns:
        Confirmation of recorded execution
    """
    detail = event['detail']
    execution_arn = detail['executionArn']
    status = detail['status']  # SUCCEEDED, FAILED, TIMED_OUT, ABORTED

    # Get execution details from Step Functions
    execution_details = sfn_client.describe_execution(executionArn=execution_arn)

    # Parse input to get tenant_id, target_alias, schedule_id
    input_data = json.loads(execution_details['input'])

    # Map Step Functions status to our status
    if status == 'SUCCEEDED':
        our_status = 'SUCCESS'
        # Get output for successful executions
        output_data = json.loads(execution_details.get('output', '{}'))
        execution_result = output_data.get('execution_result', {})
        target_arn = output_data.get('target_arn', '')
        failed_state = None
        redrive_info = None
    else:
        our_status = 'FAILED'
        # For failures, get error details
        execution_result = {
            'Error': detail.get('error', status),
            'Cause': detail.get('cause', f'Execution {status.lower()}')
        }
        # Try to get target_arn from output (may be partial), or fall back to input
        output_data = json.loads(execution_details.get('output', '{}'))
        target_arn = output_data.get('target_arn', input_data.get('target_arn', ''))
        
        # If still no target_arn, try to look it up from DynamoDB using tenant_id and target_alias
        if not target_arn:
            try:
                tenant_mappings_table_name = os.environ.get('DYNAMODB_TENANT_TABLE')
                targets_table_name = os.environ.get('DYNAMODB_TABLE')
                
                if tenant_mappings_table_name and targets_table_name:
                    tenant_id = input_data.get('tenant_id')
                    target_alias = input_data.get('target_alias')
                    
                    if tenant_id and target_alias:
                        # Query tenant mapping to get target_id
                        mappings_table = dynamodb.Table(tenant_mappings_table_name)
                        mapping_response = mappings_table.get_item(
                            Key={'tenant_id': tenant_id, 'target_alias': target_alias}
                        )
                        
                        if 'Item' in mapping_response:
                            target_id = mapping_response['Item'].get('target_id')
                            
                            # Get target details to get target_arn
                            targets_table = dynamodb.Table(targets_table_name)
                            target_response = targets_table.get_item(
                                Key={'target_id': target_id}
                            )
                            
                            if 'Item' in target_response:
                                target_arn = target_response['Item'].get('target_arn', '')
                                logger.info(f"Retrieved target_arn from DynamoDB for failed execution: {target_arn}")
            except Exception as e:
                logger.warning(f"Failed to retrieve target_arn from DynamoDB: {e}")
        
        failed_state = detail.get('stopDate', 'Unknown')
        
        # Build redrive info
        redrive_info = {
            'can_redrive': True,
            'redrive_from_state': 'ExecuteTargetWithErrorHandling',
            'message': f'Execution {status.lower()}. Can be redriven from the Parallel state.'
        }
        
        # For nested Step Functions, construct the child execution ARN
        # We use the parent execution name with "-nested" suffix for the child
        if target_arn and ':states:' in target_arn:
            try:
                # Extract execution name from parent execution ARN
                execution_name = execution_arn.split(':')[-1]
                
                # Parse nested state machine ARN to construct child execution ARN
                arn_parts = target_arn.split(':')
                if len(arn_parts) >= 7:
                    region = arn_parts[3]
                    account = arn_parts[4]
                    state_machine_name = arn_parts[6]
                    
                    # Construct nested execution ARN (uses parent execution name + "-nested" suffix)
                    nested_execution_arn = f"arn:aws:states:{region}:{account}:execution:{state_machine_name}:{execution_name}-nested"
                    
                    redrive_info['nested_execution_arn'] = nested_execution_arn
                    redrive_info['message'] = (
                        f'Execution {status.lower()}. Redrive will automatically target the nested Step Functions execution: {nested_execution_arn}'
                    )
                    logger.info(f"Constructed nested execution ARN for redrive: {nested_execution_arn}")
            except (IndexError, ValueError) as e:
                logger.warning(f"Failed to construct nested execution ARN: {e}")

    tenant_id = input_data.get('tenant_id')
    target_alias = input_data.get('target_alias')
    schedule_id = input_data.get('schedule_id', 'unknown')

    # Extract execution name (UUID) from ARN with error handling
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

    # Record execution
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
    return {
        'status': 'recorded',
        'execution_id': execution_id
    }


def record_execution(
    tenant_id: str,
    target_alias: str,
    schedule_id: str,
    result: Dict[str, Any],
    status: str,
    state_machine_execution_arn: str,
    execution_start_time: str,
    failed_state: str = None,
    redrive_info: Optional[Dict[str, Any]] = None,
    target_arn: str = ''
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

        # Calculate TTL: 15 days from now (in seconds since epoch)
        # This aligns with the 14-day redrive limit, giving 1 day buffer
        ttl_date = datetime.now(timezone.utc) + timedelta(days=15)
        ttl = int(ttl_date.timestamp())

        # Build the item to store
        # Serialize result as JSON string to handle any data types that DynamoDB doesn't support
        result_json = json.dumps(result, default=str) if result else '{}'
        
        item = {
            'tenant_schedule': tenant_schedule,
            'execution_id': execution_id,
            'tenant_target': tenant_target,
            'timestamp': timestamp,
            'status': status,
            'result': result_json, 
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

        # Check if cloudwatch_logs_url already exists from preprocessing (Step Functions targets)
        # If so, preserve it. Otherwise, generate it based on target type.
        existing_url = None
        try:
            # Try to get existing execution record to check for pre-generated URL
            existing_item = executions_table.get_item(
                Key={
                    'tenant_schedule': tenant_schedule,
                    'execution_id': execution_id
                }
            )
            if 'Item' in existing_item:
                existing_url = existing_item['Item'].get('cloudwatch_logs_url')
                if existing_url:
                    logger.info(f"Preserving existing cloudwatch_logs_url from preprocessing: {existing_url}")
        except Exception as e:
            logger.warning(f"Failed to check for existing cloudwatch_logs_url: {e}")
        
        # Generate console URL if not already present
        if existing_url:
            # Use existing URL from preprocessing (Step Functions)
            item['cloudwatch_logs_url'] = existing_url
        else:
            # Generate URL for Lambda (with CloudWatch request ID) or other targets
            cloudwatch_url = result.get('cloudwatch_logs_url')
            
            # For Step Functions targets, use the actual execution ARN from the result if available
            target_execution_arn = state_machine_execution_arn
            if ':states:' in target_arn and 'ExecutionArn' in result:
                target_execution_arn = result['ExecutionArn']
            
            console_url = generate_console_url(
                target_arn=target_arn,
                execution_arn=target_execution_arn,
                cloudwatch_logs_url=cloudwatch_url
            )
            
            if console_url:
                item['cloudwatch_logs_url'] = console_url
                if VERBOSE_LOGGING:
                    logger.info(f"Generated console URL for target type: {console_url}")
            # For failed Lambda executions, try to extract CloudWatch URL from error Cause
            # The lambda_execution_helper includes the CloudWatch URL in the error JSON
            elif status == 'FAILED' and 'Cause' in result and not cloudwatch_url:
                try:
                    if VERBOSE_LOGGING:
                        logger.info(f"Attempting to parse Cause for CloudWatch URL from failed Lambda")

                    # Parse the Cause field - it contains an object with errorMessage
                    cause_data = json.loads(result['Cause'])

                    # Check if cloudwatch_logs_url is at the top level
                    if 'cloudwatch_logs_url' in cause_data:
                        # Re-run generate_console_url with the extracted URL
                        console_url = generate_console_url(
                            target_arn=target_arn,
                            execution_arn=state_machine_execution_arn,
                            cloudwatch_logs_url=cause_data['cloudwatch_logs_url']
                        )
                        if console_url:
                            item['cloudwatch_logs_url'] = console_url
                            logger.info(f"Extracted CloudWatch URL from error Cause: {console_url}")
                    # If not, check if it's nested in the errorMessage field (double-encoded JSON)
                    elif 'errorMessage' in cause_data:
                        try:
                            # Parse the nested JSON in errorMessage
                            error_message_data = json.loads(cause_data['errorMessage'])
                            if 'cloudwatch_logs_url' in error_message_data:
                                console_url = generate_console_url(
                                    target_arn=target_arn,
                                    execution_arn=state_machine_execution_arn,
                                    cloudwatch_logs_url=error_message_data['cloudwatch_logs_url']
                                )
                                if console_url:
                                    item['cloudwatch_logs_url'] = console_url
                                    logger.info(f"Extracted CloudWatch URL from nested errorMessage: {console_url}")
                        except (json.JSONDecodeError, TypeError) as nested_error:
                            if VERBOSE_LOGGING:
                                logger.warning(f"Failed to parse nested errorMessage: {nested_error}")
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
