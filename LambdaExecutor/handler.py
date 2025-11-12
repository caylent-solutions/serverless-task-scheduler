"""
Lambda Executioner - Handles scheduled task execution from EventBridge Scheduler.

This Lambda is invoked by EventBridge Scheduler with schedule execution details.
It resolves the tenant's target and invokes the appropriate AWS service (Lambda, ECS, Step Functions).

Event Structure from EventBridge Scheduler:
{
    "tenant_id": "jer",
    "target_alias": "calculator",
    "schedule_id": "daily-calculation",
    "execution_time": "2025-01-15T10:00:00Z",
    "payload": {...}
}
"""

import json
import logging
import os
import boto3
from typing import Dict, Any
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
ecs_client = boto3.client('ecs')
sfn_client = boto3.client('stepfunctions')
logs_client = boto3.client('logs')

# Environment variables
TENANT_MAPPINGS_TABLE = os.environ['DYNAMODB_TENANT_TABLE']
TARGETS_TABLE = os.environ['DYNAMODB_TABLE']
EXECUTIONS_TABLE = os.environ['DYNAMODB_EXECUTIONS_TABLE']
APP_ENV = os.environ.get('APP_ENV', 'prod').lower()

# Determine if we should log sensitive information (non-production environments)
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


def handler(event, context):
    """
    Main Lambda handler for scheduled task execution.

    Args:
        event: EventBridge Scheduler event with execution details
        context: Lambda context

    Returns:
        Execution result
    """
    logger.info(f"Received execution request: {json.dumps(event, default=str)}")

    try:
        # Extract execution parameters
        tenant_id = event['tenant_id']
        target_alias = event['target_alias']
        schedule_id = event.get('schedule_id', 'unknown')
        runtime_payload = event.get('payload', {})

        # Resolve target from tenant mapping
        target_info = resolve_target(tenant_id, target_alias)
        if not target_info:
            raise ValueError(f"Target not found: {tenant_id}/{target_alias}")

        # Merge default payload with runtime payload (runtime overrides defaults)
        default_payload = target_info.get('default_payload', {})
        merged_payload = {**default_payload, **runtime_payload}

        if VERBOSE_LOGGING:
            logger.info(f"Payload merge: default={json.dumps(default_payload)}, runtime={json.dumps(runtime_payload)}, merged={json.dumps(merged_payload)}")
        else:
            logger.info(f"Merged payload with {len(default_payload)} default keys and {len(runtime_payload)} runtime keys")

        # Execute the target
        execution_result = execute_target(target_info, merged_payload)

        # Record execution in DynamoDB
        record_execution(
            tenant_id=tenant_id,
            target_alias=target_alias,
            schedule_id=schedule_id,
            result=execution_result,
            status='SUCCESS'
        )

        logger.info(f"Successfully executed {target_alias} for tenant {tenant_id}")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'SUCCESS',
                'execution_id': execution_result.get('execution_id'),
                'message': 'Target executed successfully'
            })
        }

    except Exception as e:
        logger.error(f"Execution failed: {str(e)}", exc_info=True)

        # Record failed execution
        try:
            record_execution(
                tenant_id=event.get('tenant_id', 'unknown'),
                target_alias=event.get('target_alias', 'unknown'),
                schedule_id=event.get('schedule_id', 'unknown'),
                result={'error': str(e)},
                status='FAILED'
            )
        except Exception as record_error:
            logger.error(f"Failed to record execution: {record_error}")

        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'FAILED',
                'error': str(e)
            })
        }


def resolve_target(tenant_id: str, target_alias: str) -> Dict[str, Any]:
    """
    Resolve target ARN and configuration from tenant mapping.

    Args:
        tenant_id: Tenant identifier
        target_alias: Target alias name

    Returns:
        Target configuration with ARN and type
    """
    try:
        # Get tenant mapping
        mappings_table = dynamodb.Table(TENANT_MAPPINGS_TABLE)
        mapping_response = mappings_table.get_item(
            Key={
                'tenant_id': tenant_id,
                'target_alias': target_alias
            }
        )

        if 'Item' not in mapping_response:
            logger.error(f"Tenant mapping not found: {tenant_id}/{target_alias}")
            return None

        mapping = mapping_response['Item']
        target_id = mapping['target_id']
        default_payload = mapping.get('default_payload', {})

        # Get target details
        targets_table = dynamodb.Table(TARGETS_TABLE)
        target_response = targets_table.get_item(
            Key={'target_id': target_id}
        )

        if 'Item' not in target_response:
            logger.error(f"Target not found: {target_id}")
            return None

        target = target_response['Item']
        logger.info(f"Resolved target: {target_alias} -> {target['target_arn']}")

        return {
            'target_id': target_id,
            'target_arn': target['target_arn'],
            'target_type': target.get('target_type', 'lambda'),
            'config': target.get('config', {}),
            'default_payload': default_payload
        }

    except ClientError as e:
        logger.error(f"DynamoDB error resolving target: {e}")
        return None


def execute_target(target_info: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the target based on its type (Lambda, ECS, Step Functions).

    Args:
        target_info: Target configuration
        payload: Execution payload

    Returns:
        Execution result with execution ID and response
    """
    target_type = target_info['target_type'].lower()
    target_arn = target_info['target_arn']

    if target_type == 'lambda':
        return execute_lambda(target_arn, payload)
    elif target_type == 'ecs':
        return execute_ecs(target_info, payload)
    elif target_type in ['stepfunctions', 'step-functions']:
        return execute_step_function(target_arn, payload)
    else:
        raise ValueError(f"Unsupported target type: {target_type}")


def find_log_stream_url(function_name: str, request_id: str, region: str) -> str:
    """
    Find the actual CloudWatch log stream for a Lambda execution by request ID.

    Args:
        function_name: Lambda function name
        request_id: Lambda request ID
        region: AWS region

    Returns:
        CloudWatch Logs console URL
    """
    log_group_name = f"/aws/lambda/{function_name}"

    try:
        # Get the current date for log stream prefix
        now = datetime.now(timezone.utc)
        log_stream_prefix = f"{now.year}/{now.month:02d}/{now.day:02d}/"

        # Search for log streams that might contain our request
        response = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            logStreamNamePrefix=log_stream_prefix,
            orderBy='LastEventTime',
            descending=True,
            limit=50  # Check recent streams
        )

        # Search through log streams to find the one with our request ID
        for stream in response.get('logStreams', []):
            stream_name = stream['logStreamName']

            # Query the log stream for the request ID
            try:
                filter_response = logs_client.filter_log_events(
                    logGroupName=log_group_name,
                    logStreamNames=[stream_name],
                    filterPattern=f'"{request_id}"',
                    limit=1
                )

                # If we found the request ID in this stream, use it
                if filter_response.get('events'):
                    # URL-encode the log group and stream names
                    log_group_encoded = log_group_name.replace('/', '%252F')
                    log_stream_encoded = stream_name.replace('/', '%252F').replace('[', '%255B').replace(']', '%255D').replace('$', '%2524')

                    return f"https://console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{log_group_encoded}/log-events/{log_stream_encoded}"

            except ClientError as e:
                # Continue to next stream if this one fails
                logger.debug(f"Error checking stream {stream_name}: {e}")
                continue

        # If we couldn't find the specific stream, return a link to the log group
        logger.warning(f"Could not find log stream for request {request_id}, returning log group URL")
        log_group_encoded = log_group_name.replace('/', '%252F')
        return f"https://console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{log_group_encoded}"

    except ClientError as e:
        logger.error(f"Error finding log stream: {e}")
        # Fallback to log group URL
        log_group_encoded = log_group_name.replace('/', '%252F')
        return f"https://console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{log_group_encoded}"


def execute_lambda(function_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Lambda function."""
    if VERBOSE_LOGGING:
        logger.info(f"Invoking Lambda: {function_arn} with payload: {json.dumps(payload)}")
    else:
        logger.info(f"Invoking Lambda: {function_arn}")

    response = lambda_client.invoke(
        FunctionName=function_arn,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )

    response_payload = json.loads(response['Payload'].read())
    request_id = response['ResponseMetadata']['RequestId']

    if VERBOSE_LOGGING:
        logger.info(f"Lambda invocation completed. Status: {response['StatusCode']}, Response: {json.dumps(response_payload)}")
    else:
        logger.info(f"Lambda invocation completed. Status: {response['StatusCode']}")

    # Extract function name from ARN (format: arn:aws:lambda:region:account:function:name)
    function_name = function_arn.split(':')[-1] if ':' in function_arn else function_arn
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Find the actual log stream by searching for the request ID
    cloudwatch_url = find_log_stream_url(function_name, request_id, region)

    return {
        'execution_id': request_id,
        'target_type': 'lambda',
        'response': response_payload,
        'status_code': response['StatusCode'],
        'function_name': function_name,
        'cloudwatch_logs_url': cloudwatch_url
    }


def execute_ecs(target_info: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute ECS task."""
    config = target_info['config']

    logger.info(f"Running ECS task: {config.get('task_definition')}")

    response = ecs_client.run_task(
        cluster=config.get('cluster', 'default'),
        taskDefinition=config['task_definition'],
        launchType=config.get('launch_type', 'FARGATE'),
        networkConfiguration=config.get('network_configuration', {}),
        overrides={
            'containerOverrides': [{
                'name': config.get('container_name', 'main'),
                'environment': [
                    {'name': 'EXECUTION_PAYLOAD', 'value': json.dumps(payload)}
                ]
            }]
        }
    )

    task_arn = response['tasks'][0]['taskArn'] if response['tasks'] else None

    return {
        'execution_id': task_arn,
        'target_type': 'ecs',
        'task_arn': task_arn,
        'response': response
    }


def execute_step_function(state_machine_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Step Functions state machine."""
    logger.info(f"Starting Step Function: {state_machine_arn}")

    execution_name = f"scheduled-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    response = sfn_client.start_execution(
        stateMachineArn=state_machine_arn,
        name=execution_name,
        input=json.dumps(payload)
    )

    return {
        'execution_id': response['executionArn'],
        'target_type': 'stepfunctions',
        'execution_arn': response['executionArn'],
        'start_date': response['startDate'].isoformat()
    }


def record_execution(tenant_id: str, target_alias: str, schedule_id: str,
                    result: Dict[str, Any], status: str):
    """
    Record execution in DynamoDB executions table.

    Args:
        tenant_id: Tenant identifier
        target_alias: Target alias
        schedule_id: Schedule identifier (can be recurring schedule or ad-hoc schedule)
        result: Execution result (includes execution_id from Lambda RequestId)
        status: Execution status (SUCCESS/FAILED/PENDING)
    """
    try:
        executions_table = dynamodb.Table(EXECUTIONS_TABLE)

        timestamp = datetime.now(timezone.utc).isoformat()
        tenant_schedule = f"{tenant_id}#{schedule_id}"
        tenant_target = f"{tenant_id}#{target_alias}"
        lambda_request_id = result.get('execution_id', 'unknown')

        # Create sortable execution_id: ISO8601-timestamp#lambda-request-id
        # This ensures chronological ordering while maintaining uniqueness
        execution_id = f"{timestamp}#{lambda_request_id}"

        executions_table.put_item(
            Item={
                'tenant_schedule': tenant_schedule,
                'execution_id': execution_id,
                'tenant_target': tenant_target,
                'timestamp': timestamp,
                'status': status,
                'result': result,
                'executed_at': timestamp,
                'lambda_request_id': lambda_request_id  # Store separately for reference
            }
        )

        logger.info(f"Recorded execution: tenant_schedule={tenant_schedule}, execution={execution_id}, status={status}")

    except ClientError as e:
        logger.error(f"Failed to record execution: {e}")
        raise
