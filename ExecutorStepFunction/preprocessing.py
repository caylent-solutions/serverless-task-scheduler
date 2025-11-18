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
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
TENANT_MAPPINGS_TABLE = os.environ['DYNAMODB_TENANT_TABLE']
TARGETS_TABLE = os.environ['DYNAMODB_TABLE']
APP_ENV = os.environ.get('APP_ENV', 'prod').lower()

# Determine if we should log sensitive information (non-production environments)
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


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
        raise ValueError(f"DynamoDB error resolving target: {e}")
