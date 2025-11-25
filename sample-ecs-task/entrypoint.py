#!/usr/bin/env python3
"""
ECS Task Entrypoint for Serverless Task Scheduler
Accepts input via EXECUTION_PAYLOAD environment variable in the same format as Lambda functions.
Supports Step Functions task token callback for passing results to downstream states.
"""

import json
import logging
import os
import sys
from datetime import datetime

import boto3

# Import the calculator handler
from lambda_handler_calculator import lambda_handler

# Configure logging to stderr so stdout is clean for JSON output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class MockContext:
    """Mock Lambda context for compatibility with Lambda handlers"""
    def __init__(self):
        self.function_name = os.environ.get('ECS_TASK_DEFINITION', 'ecs-calculator-task')
        self.function_version = '$LATEST'
        self.invoked_function_arn = os.environ.get('ECS_TASK_ARN', 'arn:aws:ecs:us-east-1:123456789012:task/cluster/task-id')
        self.memory_limit_in_mb = '512'
        self.aws_request_id = os.environ.get('ECS_TASK_ID', 'ecs-task-' + datetime.now().isoformat())
        self.log_group_name = '/ecs/calculator-task'
        self.log_stream_name = f"{datetime.now().strftime('%Y/%m/%d')}/task-{self.aws_request_id}"


def main():
    """
    Main entrypoint that:
    1. Reads JSON payload from EXECUTION_PAYLOAD environment variable
    2. Invokes the Lambda handler with the payload
    3. Sends result back to Step Functions via task token callback (if available)
    4. Outputs result as JSON to stdout (fallback/logging)
    5. Exits with appropriate status code
    """
    task_token = os.environ.get('TASK_TOKEN')
    sfn_client = None

    # Initialize Step Functions client if task token is present
    if task_token:
        logger.info("Task token detected - will send results via Step Functions callback")
        sfn_client = boto3.client('stepfunctions')
    else:
        logger.warning("No task token found - results will only be logged to stdout")

    try:
        # Get the payload from environment variable (set by Step Function)
        payload_json = os.environ.get('EXECUTION_PAYLOAD')

        if not payload_json:
            logger.error("EXECUTION_PAYLOAD environment variable not set")
            error_result = {
                "status": "error",
                "error": "EXECUTION_PAYLOAD environment variable not set",
                "result": None
            }

            if task_token and sfn_client:
                sfn_client.send_task_failure(
                    taskToken=task_token,
                    error='MissingPayload',
                    cause='EXECUTION_PAYLOAD environment variable not set'
                )

            print(json.dumps(error_result))
            sys.exit(1)

        # Parse the JSON payload
        try:
            event = json.loads(payload_json)
            logger.info(f"Received payload: {json.dumps(event)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in EXECUTION_PAYLOAD: {e}")
            error_result = {
                "status": "error",
                "error": f"Invalid JSON in EXECUTION_PAYLOAD: {str(e)}",
                "result": None
            }

            if task_token and sfn_client:
                sfn_client.send_task_failure(
                    taskToken=task_token,
                    error='InvalidPayload',
                    cause=f'Invalid JSON in EXECUTION_PAYLOAD: {str(e)}'
                )

            print(json.dumps(error_result))
            sys.exit(1)

        # Create mock context
        context = MockContext()

        # Invoke the Lambda handler
        logger.info("Invoking calculator handler")
        handler_result = lambda_handler(event, context)

        # Wrap the result in a structure that matches Lambda execution pattern
        result = {
            "status": "success",
            "result": handler_result,
            "execution_id": context.aws_request_id,
            "timestamp": datetime.now().isoformat()
        }

        # Send result back to Step Functions via task token
        if task_token and sfn_client:
            logger.info("Sending task success to Step Functions")
            sfn_client.send_task_success(
                taskToken=task_token,
                output=json.dumps(result)
            )
            logger.info("Successfully sent result to Step Functions")

        # Also output to stdout for logging/debugging
        logger.info(f"Task completed successfully: {json.dumps(result)}")
        print(json.dumps(result))
        sys.exit(0)

    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}", exc_info=True)
        error_result = {
            "status": "error",
            "error": str(e),
            "result": None,
            "timestamp": datetime.now().isoformat()
        }

        # Send failure back to Step Functions via task token
        if task_token and sfn_client:
            logger.info("Sending task failure to Step Functions")
            try:
                sfn_client.send_task_failure(
                    taskToken=task_token,
                    error='TaskExecutionError',
                    cause=str(e)
                )
                logger.info("Successfully sent failure to Step Functions")
            except Exception as callback_error:
                logger.error(f"Failed to send failure callback: {str(callback_error)}")

        # Also output to stdout for logging/debugging
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == '__main__':
    main()
