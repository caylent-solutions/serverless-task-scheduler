"""
Shared execution recording logic used by both postprocessing.py and
record_redrive_result.py.

Provides DynamoDB write, target ARN lookup, and console URL generation
so neither Lambda duplicates this logic.
"""

import json
import logging
import os
import boto3
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError

logger = logging.getLogger()

dynamodb = boto3.resource('dynamodb')

EXECUTIONS_TABLE = os.environ['DYNAMODB_EXECUTIONS_TABLE']
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
APP_ENV = os.environ.get('APP_ENV', 'prod').lower()
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']

STATES_SERVICE_IDENTIFIER = ':states:'
ECS_SERVICE_IDENTIFIER = ':ecs:'


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


def _build_full_execution_arn(target_arn: str, execution_name: str) -> Optional[str]:
    if execution_name.startswith('arn:'):
        return execution_name
    arn_components = _parse_stepfunctions_arn(target_arn)
    if not arn_components:
        return execution_name
    return (f"arn:aws:states:{arn_components['region']}:{arn_components['account']}:"
            f"execution:{arn_components['state_machine_name']}:{execution_name}")


def _extract_region_from_arn(arn: str, default_region: str = AWS_REGION) -> str:
    if not arn.startswith('arn:'):
        return default_region
    try:
        return arn.split(':')[3] or default_region
    except (IndexError, ValueError):
        return default_region



def generate_console_url(
    target_arn: str,
    execution_arn: str,
    cloudwatch_logs_url: Optional[str] = None
) -> Optional[str]:
    if cloudwatch_logs_url:
        return cloudwatch_logs_url

    if target_arn and STATES_SERVICE_IDENTIFIER in target_arn:
        try:
            full_execution_arn = _build_full_execution_arn(target_arn, execution_arn)
            region = _extract_region_from_arn(full_execution_arn)
            return (f"https://{region}.console.aws.amazon.com/states/home"
                    f"?region={region}#/v2/executions/details/{full_execution_arn}")
        except Exception as e:
            logger.warning(f"Failed to generate Step Functions console URL: {e}")
            return None

    if target_arn and ECS_SERVICE_IDENTIFIER in target_arn:
        # ECS CloudWatch URL is built in postprocessing.py (requires SFN history lookup)
        # and injected into execution_result before record_execution is called.
        # If it was successfully injected it will have been returned above via cloudwatch_logs_url.
        return None

    return None


def lookup_target_arn_from_dynamodb(tenant_id: str, target_alias: str) -> str:
    try:
        tenant_mappings_table_name = os.environ.get('DYNAMODB_TENANT_TABLE')
        targets_table_name = os.environ.get('DYNAMODB_TABLE')

        if not tenant_mappings_table_name or not targets_table_name:
            return ''
        if not tenant_id or not target_alias:
            return ''

        mappings_table = dynamodb.Table(tenant_mappings_table_name)
        mapping_response = mappings_table.get_item(
            Key={'tenant_id': tenant_id, 'target_alias': target_alias}
        )
        if 'Item' not in mapping_response:
            return ''

        target_id = mapping_response['Item'].get('target_id')
        if not target_id:
            return ''

        targets_table = dynamodb.Table(targets_table_name)
        target_response = targets_table.get_item(Key={'target_id': target_id})
        if 'Item' in target_response:
            target_arn = target_response['Item'].get('target_arn', '')
            if target_arn:
                logger.info(f"Retrieved target_arn from DynamoDB: {target_arn}")
            return target_arn

        return ''
    except Exception as e:
        logger.warning(f"Failed to retrieve target_arn from DynamoDB: {e}")
        return ''


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
    Write execution result to TargetExecutionsTable.

    Uses put_item so it overwrites any existing record at the same key —
    intentional for the redrive flow where IN_PROGRESS is replaced with the
    final status.

    state_machine_execution_arn is used as the execution_id (DynamoDB SK).
    For normal runs this is the parent execution name (UUID).
    For redrives this is also the parent execution name, derived from the child ARN.
    """
    try:
        executions_table = dynamodb.Table(EXECUTIONS_TABLE)

        timestamp = datetime.now(timezone.utc).isoformat()
        tenant_schedule = f"{tenant_id}#{schedule_id}"
        tenant_target = f"{tenant_id}#{target_alias}"
        execution_id = state_machine_execution_arn

        ttl_date = datetime.now(timezone.utc) + timedelta(days=15)
        ttl = int(ttl_date.timestamp())

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

        if status == 'FAILED':
            if failed_state:
                item['failed_state'] = failed_state
            if redrive_info:
                item['redrive_info'] = redrive_info
                item['can_redrive'] = redrive_info.get('can_redrive', True)
                item['redrive_from_state'] = redrive_info.get('redrive_from_state', failed_state)
            else:
                item['can_redrive'] = True
                item['redrive_info'] = {
                    'can_redrive': True,
                    'message': 'This execution can be redriven using Step Functions redrive capability'
                }

        # Preserve cloudwatch_logs_url written by preprocessing (Step Functions targets
        # have the URL pre-generated before execution begins)
        existing_url = None
        try:
            existing_item = executions_table.get_item(
                Key={'tenant_schedule': tenant_schedule, 'execution_id': execution_id}
            )
            if 'Item' in existing_item:
                existing_url = existing_item['Item'].get('cloudwatch_logs_url')
                if existing_url:
                    logger.info(f"Preserving existing cloudwatch_logs_url from preprocessing: {existing_url}")
        except Exception as e:
            logger.warning(f"Failed to check for existing cloudwatch_logs_url: {e}")

        if existing_url:
            item['cloudwatch_logs_url'] = existing_url
        else:
            cloudwatch_url = result.get('cloudwatch_logs_url') if isinstance(result, dict) else None
            target_execution_arn = state_machine_execution_arn
            
            # For Step Functions targets, extract the nested execution ARN
            if isinstance(result, dict) and STATES_SERVICE_IDENTIFIER in target_arn and 'ExecutionArn' in result:
                target_execution_arn = result['ExecutionArn']

            console_url = generate_console_url(
                target_arn=target_arn,
                execution_arn=target_execution_arn,
                cloudwatch_logs_url=cloudwatch_url
            )
            if console_url:
                item['cloudwatch_logs_url'] = console_url
                if VERBOSE_LOGGING:
                    logger.info(f"Generated console URL: {console_url}")
            elif status == 'FAILED' and isinstance(result, dict) and 'Cause' in result and not cloudwatch_url:
                try:
                    cause_data = json.loads(result['Cause'])
                    if 'cloudwatch_logs_url' in cause_data:
                        console_url = generate_console_url(
                            target_arn=target_arn,
                            execution_arn=state_machine_execution_arn,
                            cloudwatch_logs_url=cause_data['cloudwatch_logs_url']
                        )
                        if console_url:
                            item['cloudwatch_logs_url'] = console_url
                    elif 'errorMessage' in cause_data:
                        error_message_data = json.loads(cause_data['errorMessage'])
                        if 'cloudwatch_logs_url' in error_message_data:
                            console_url = generate_console_url(
                                target_arn=target_arn,
                                execution_arn=state_machine_execution_arn,
                                cloudwatch_logs_url=error_message_data['cloudwatch_logs_url']
                            )
                            if console_url:
                                item['cloudwatch_logs_url'] = console_url
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

        executions_table.put_item(Item=item)
        logger.info(f"Recorded execution: tenant_schedule={tenant_schedule}, execution={execution_id}, status={status}")
        return execution_id

    except ClientError as e:
        logger.error(f"Failed to record execution: {e}")
        raise
