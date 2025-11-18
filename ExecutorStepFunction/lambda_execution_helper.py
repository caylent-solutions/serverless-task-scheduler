"""
Lambda Execution Helper for ExecutorStepFunction
Invokes Lambda functions and captures CloudWatch logs URL.

This Lambda is needed because Step Functions' native Lambda integration
doesn't provide the RequestId which is needed to find the CloudWatch log stream.

Input Event:
{
    "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:calculator",
    "merged_payload": {...}
}

Output:
{
    "execution_id": "a1b2c3d4-...",
    "target_type": "lambda",
    "response": {...},
    "status_code": 200,
    "function_name": "calculator",
    "cloudwatch_logs_url": "https://console.aws.amazon.com/cloudwatch/..."
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
lambda_client = boto3.client('lambda')
logs_client = boto3.client('logs')

# Environment variables
APP_ENV = os.environ.get('APP_ENV', 'prod').lower()
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# Determine if we should log sensitive information (non-production environments)
VERBOSE_LOGGING = APP_ENV in ['dev', 'qa', 'uat']


def handler(event, context):
    """
    Execute Lambda target and capture CloudWatch logs URL.

    Args:
        event: Contains target_arn and merged_payload
        context: Lambda context

    Returns:
        Execution result with CloudWatch logs URL
    """
    if VERBOSE_LOGGING:
        logger.info(f"Lambda execution request: {json.dumps(event, default=str)}")
    else:
        logger.info(f"Lambda execution request for target: {event.get('target_arn')}")

    try:
        target_arn = event['target_arn']
        payload = event['merged_payload']

        # Execute Lambda
        result = execute_lambda(target_arn, payload)

        logger.info(f"Lambda execution completed successfully: {result['execution_id']}")
        return result

    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise ValueError(f"Missing required field: {e}")
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}", exc_info=True)
        raise


def execute_lambda(function_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute Lambda function and capture CloudWatch logs URL.

    Args:
        function_arn: Lambda function ARN or name
        payload: Execution payload

    Returns:
        Execution result with CloudWatch logs URL
    """
    if VERBOSE_LOGGING:
        logger.info(f"Invoking Lambda: {function_arn} with payload: {json.dumps(payload)}")
    else:
        logger.info(f"Invoking Lambda: {function_arn}")

    try:
        response = lambda_client.invoke(
            FunctionName=function_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )

        response_payload = json.loads(response['Payload'].read())
        request_id = response['ResponseMetadata']['RequestId']
        status_code = response['StatusCode']

        if VERBOSE_LOGGING:
            logger.info(f"Lambda invocation completed. Status: {status_code}, Response: {json.dumps(response_payload)}")
        else:
            logger.info(f"Lambda invocation completed. Status: {status_code}")

        # Check for function errors
        if 'FunctionError' in response:
            logger.error(f"Lambda function error: {response_payload}")
            raise Exception(f"Lambda function error: {json.dumps(response_payload)}")

        # Extract function name from ARN (format: arn:aws:lambda:region:account:function:name)
        function_name = function_arn.split(':')[-1] if ':' in function_arn else function_arn

        # Find the actual log stream by searching for the request ID
        cloudwatch_url = find_log_stream_url(function_name, request_id, AWS_REGION)

        return {
            'execution_id': request_id,
            'target_type': 'lambda',
            'response': response_payload,
            'status_code': status_code,
            'function_name': function_name,
            'cloudwatch_logs_url': cloudwatch_url
        }

    except ClientError as e:
        logger.error(f"Lambda invocation failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Error executing Lambda: {e}")
        raise


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
