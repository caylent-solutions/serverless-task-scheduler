"""
Preprocessing Lambda for ExecutorStepFunction
Resolves target from tenant mapping and merges payloads.

Input Event:
{
    "tenant_id": "jer",
    "target_alias": "calculator",
    "schedule_id": "daily-calculation",
    "payload": {...}
}

Output:
{
    "tenant_id": "jer",
    "target_alias": "calculator",
    "schedule_id": "daily-calculation",
    "target_id": "calc-target",
    "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:calculator",
    "target_type": "lambda",
    "target_config": {...},
    "merged_payload": {...},
    "default_payload": {...},
    "runtime_payload": {...}
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

# Environment variables
TENANT_MAPPINGS_TABLE = os.environ['DYNAMODB_TENANT_TABLE']
TARGETS_TABLE = os.environ['DYNAMODB_TABLE']
EXECUTIONS_TABLE = os.environ.get('DYNAMODB_EXECUTIONS_TABLE')
APP_ENV = os.environ.get('APP_ENV', 'prod').lower()

# Determine if we should log sensitive information (non-production environments)
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


def parse_target_type_from_arn(target_arn: str) -> str:
    """
    Parse the target type from an AWS ARN.
    
    Supported ARN patterns:
    - Lambda: arn:aws:lambda:region:account:function:name
    - ECS: arn:aws:ecs:region:account:task-definition/name:version
    - Step Functions: arn:aws:states:region:account:stateMachine:name
    
    Args:
        target_arn: AWS resource ARN
        
    Returns:
        Target type: 'lambda', 'ecs', or 'stepfunctions'
        
    Raises:
        ValueError: If ARN format is invalid or service is not supported
    """
    if not target_arn or not isinstance(target_arn, str):
        raise ValueError(f"Invalid target ARN: {target_arn}")
    
    # ARN format: arn:partition:service:region:account-id:resource
    arn_parts = target_arn.split(':')
    
    if len(arn_parts) < 6 or arn_parts[0] != 'arn':
        raise ValueError(f"Invalid ARN format: {target_arn}")
    
    service = arn_parts[2]
    
    if service == 'lambda':
        return 'lambda'
    elif service == 'ecs':
        return 'ecs'
    elif service == 'states':
        return 'stepfunctions'
    else:
        raise ValueError(f"Unsupported target service in ARN: {service}. Must be one of: lambda, ecs, states")


def handler(event, context):
    """
    Preprocessing handler for ExecutorStepFunction.

    Args:
        event: Input from EventBridge Scheduler or Step Functions execution
        context: Lambda context

    Returns:
        Enriched event with target information and merged payload
    """
    logger.info(f"Preprocessing event: {json.dumps(event, default=str)}")

    try:
        # Extract execution parameters
        tenant_id = event['tenant_id']
        target_alias = event['target_alias']
        schedule_id = event.get('schedule_id', 'unknown')
        runtime_payload = event.get('payload', {})

        # Get execution ID from context
        # For Step Functions, AWS provides the execution name as context.aws_request_id in the Lambda context
        # However, the actual Step Functions execution name is passed separately
        # We'll extract it from the Step Functions execution ARN if available in context
        execution_id = context.aws_request_id  # This is the Lambda request ID, not what we want

        # Try to get the execution name from the Step Functions context
        # When Lambda is invoked by Step Functions, the execution details are in $$.Execution
        # However, those are only available in the Step Functions state input, not in Lambda context
        # The execution name should be extracted from the Lambda context's invoked function ARN
        # or we need to look for it in the event itself

        # For now, we'll look for execution_id in the event (passed from Step Functions)
        # or derive it from context if available
        if 'execution_id' in event:
            execution_id = event['execution_id']
        else:
            # Fallback to Lambda request ID (not ideal but prevents failures)
            execution_id = context.aws_request_id
            logger.warning(f"No execution_id in event, using Lambda request ID: {execution_id}")

        # Record initial IN_PROGRESS status
        record_initial_execution(
            execution_id=execution_id,
            tenant_id=tenant_id,
            target_alias=target_alias,
            schedule_id=schedule_id
        )

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

        # Build output event
        output = {
            'tenant_id': tenant_id,
            'target_alias': target_alias,
            'schedule_id': schedule_id,
            'target_id': target_info['target_id'],
            'target_arn': target_info['target_arn'],
            'target_type': target_info['target_type'],
            'target_config': target_info.get('config', {}),
            'merged_payload': merged_payload,
            'default_payload': default_payload,
            'runtime_payload': runtime_payload
        }

        logger.info(f"Preprocessing completed successfully for {tenant_id}/{target_alias}")
        return output

    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise ValueError(f"Missing required field: {e}")
    except Exception as e:
        logger.error(f"Preprocessing failed: {str(e)}", exc_info=True)
        raise


def record_initial_execution(
    execution_id: str,
    tenant_id: str,
    target_alias: str,
    schedule_id: str
) -> None:
    """
    Record the initial IN_PROGRESS status for an execution in DynamoDB.

    Args:
        execution_id: The Step Functions execution ID (UUID)
        tenant_id: Tenant identifier
        target_alias: Target alias
        schedule_id: Schedule identifier
    """
    if not EXECUTIONS_TABLE:
        logger.warning("DYNAMODB_EXECUTIONS_TABLE not configured, skipping initial execution record")
        return

    try:
        executions_table = dynamodb.Table(EXECUTIONS_TABLE)

        timestamp = datetime.now(timezone.utc).isoformat()
        tenant_schedule = f"{tenant_id}#{schedule_id}"
        tenant_target = f"{tenant_id}#{target_alias}"

        # Calculate TTL: 15 days from now (in seconds since epoch)
        # This aligns with the 14-day redrive limit, giving 1 day buffer
        ttl_date = datetime.now(timezone.utc) + timedelta(days=15)
        ttl = int(ttl_date.timestamp())

        item = {
            'tenant_schedule': tenant_schedule,
            'execution_id': execution_id,
            'tenant_target': tenant_target,
            'timestamp': timestamp,
            'status': 'IN_PROGRESS',
            'result': {},
            'executed_at': timestamp,
            'state_machine_execution_arn': execution_id,
            'execution_start_time': timestamp,
            'ttl': ttl
        }

        executions_table.put_item(Item=item)
        logger.info(f"Recorded initial IN_PROGRESS execution: {execution_id}")
    except Exception as e:
        logger.error(f"Failed to record initial execution status: {e}", exc_info=True)
        # Don't raise - this is not critical to execution flow


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
            raise ValueError(f"Tenant mapping not found: {tenant_id}/{target_alias}")

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
            raise ValueError(f"Target not found: {target_id}")

        target = target_response['Item']
        target_arn = target['target_arn']
        logger.info(f"Resolved target: {target_alias} -> {target_arn}")

        # Derive target_type from ARN
        target_type = parse_target_type_from_arn(target_arn)

        return {
            'target_id': target_id,
            'target_arn': target_arn,
            'target_type': target_type,
            'config': target.get('config', {}),
            'default_payload': default_payload
        }

    except ClientError as e:
        logger.error(f"DynamoDB error resolving target: {e}")
        raise ValueError(f"DynamoDB error resolving target: {e}")
