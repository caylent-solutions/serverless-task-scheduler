import logging
import boto3
import os
import json
import uuid
from typing import Dict, Any

from . import get_session


class LambdaRunner:
    def __init__(self):
        self.lambda_client = get_session().client('lambda')

    def execute_lambda_sync(self, function_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an AWS Lambda function with the given payload synchronously
        
        Args:
            function_arn: The ARN of the Lambda function to execute
            payload: The payload to send to the Lambda function
            
        Returns:
            The response from the Lambda function
        """
        
        # Invoke Lambda function
        response = self.lambda_client.invoke(
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

    def execute_lambda_async(self, function_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an AWS Lambda function with the given payload asynchronously
        
        Args:
            function_arn: The ARN of the Lambda function to execute
            payload: The payload to send to the Lambda function
            
        Returns:
            A dictionary with the execution ID
        """
        
        # Generate a unique execution ID
        execution_id = str(uuid.uuid4())
        
        # Add execution ID to payload
        payload_with_id = {**payload, "execution_id": execution_id}
        
        # Invoke Lambda function asynchronously
        response = self.lambda_client.invoke(
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

# Configure logging
logger = logging.getLogger("app.awssdk.lambdas")

# Singleton lambda runner instance
_lambda_runner = None

def get_lambda_runner():
    global _lambda_runner
    if _lambda_runner is None:
        _lambda_runner = LambdaRunner()
    return _lambda_runner
