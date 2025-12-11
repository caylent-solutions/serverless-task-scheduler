"""
AWS Lambda adapter for executing Lambda functions.

This module provides a client/adapter for invoking AWS Lambda functions
both synchronously and asynchronously.
"""

import json
import logging
import uuid
from typing import Any, Dict

from . import get_session


logger = logging.getLogger("app.awssdk.lambda_adapter")


class LambdaAdapter:
    """Adapter for executing AWS Lambda functions."""

    def __init__(self):
        """Initialize the Lambda adapter."""
        session = get_session()
        self._lambda_client = session.client("lambda")

    def invoke_async(self, function_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an AWS Lambda function with the given payload asynchronously

        Args:
            function_arn: The ARN of the Lambda function to execute
            payload: The payload to send to the Lambda function

        Returns:
            A dictionary with the execution ID
        """
        logger.info(f"Invoking Lambda asynchronously: {function_arn}")

        # Generate a unique execution ID
        execution_id = str(uuid.uuid4())

        # Add execution ID to payload
        payload_with_id = {**payload, "execution_id": execution_id}

        # Invoke Lambda function asynchronously
        response = self._lambda_client.invoke(
            FunctionName=function_arn,
            InvocationType='Event',  # Asynchronous execution
            Payload=json.dumps(payload_with_id)
        )

        # Return execution ID
        if response['StatusCode'] >= 200 and response['StatusCode'] < 300:
            return {
                "status": "ACCEPTED",
                "execution_id": execution_id,
                "message": "Function execution started asynchronously"
            }
        else:
            return {
                "status": "ERROR",
                "error": f"Lambda execution failed with status code {response['StatusCode']}"
            }

    def invoke_sync(self, function_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an AWS Lambda function with the given payload synchronously

        Args:
            function_arn: The ARN of the Lambda function to execute
            payload: The payload to send to the Lambda function

        Returns:
            The response from the Lambda function
        """
        logger.info(f"Invoking Lambda synchronously: {function_arn}")

        # Invoke Lambda function
        response = self._lambda_client.invoke(
            FunctionName=function_arn,
            InvocationType='RequestResponse',  # Synchronous execution
            Payload=json.dumps(payload)
        )

        # Parse and return response
        if response['StatusCode'] >= 200 and response['StatusCode'] < 300:
            return {
                "status": "SUCCESS",
                "response": json.loads(response['Payload'].read().decode('utf-8'))
            }
        else:
            return {
                "status": "ERROR",
                "error": f"Lambda execution failed with status code {response['StatusCode']}"
            }


# Singleton accessor
_lambda_adapter: LambdaAdapter | None = None


def get_lambda_adapter() -> LambdaAdapter:
    """Get the Lambda adapter instance."""
    global _lambda_adapter
    if _lambda_adapter is None:
        _lambda_adapter = LambdaAdapter()
    return _lambda_adapter
