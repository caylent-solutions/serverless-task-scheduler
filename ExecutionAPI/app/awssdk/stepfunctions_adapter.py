"""
AWS Step Functions adapter for executing state machines.

This module provides a client/adapter for invoking AWS Step Functions
state machines both synchronously and asynchronously.
"""

import json
import logging
import uuid
from typing import Any, Dict

from . import get_session


logger = logging.getLogger("app.awssdk.stepfunctions_adapter")


class StepFunctionsAdapter:
    """Adapter for executing AWS Step Functions state machines."""
    
    def __init__(self):
        """Initialize the Step Functions adapter."""
        session = get_session()
        self._sfn_client = session.client("stepfunctions")
    
    def invoke_async(self, state_machine_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a Step Functions execution asynchronously.
        
        Args:
            state_machine_arn: The ARN of the state machine to execute
            payload: The input payload for the state machine
            
        Returns:
            Dictionary with execution details
        """
        logger.info(f"Starting Step Functions execution: {state_machine_arn}")
        execution_id = str(uuid.uuid4())
        input_with_id = {**payload, "execution_id": execution_id}
        
        response = self._sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            name=execution_id,
            input=json.dumps(input_with_id),
        )
        
        return {
            "status": "ACCEPTED",
            "execution_id": execution_id,
            "executionArn": response.get("executionArn"),
            "startDate": response.get("startDate").isoformat() if response.get("startDate") else None,
        }
    
    def invoke_sync(self, state_machine_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a Step Functions execution and wait for completion.
        
        Note: This waits for the execution to complete, which may take time.
        
        Args:
            state_machine_arn: The ARN of the state machine to execute
            payload: The input payload for the state machine
            
        Returns:
            Dictionary with execution result
        """
        logger.info(f"Starting Step Functions execution synchronously: {state_machine_arn}")
        execution_id = str(uuid.uuid4())
        input_with_id = {**payload, "execution_id": execution_id}
        
        # Start execution
        response = self._sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            name=execution_id,
            input=json.dumps(input_with_id),
        )
        execution_arn = response.get("executionArn")
        
        if not execution_arn:
            return {
                "status": "ERROR",
                "error": "Failed to start Step Functions execution"
            }
        
        # Wait for execution to complete
        waiter = self._sfn_client.get_waiter('execution_succeeded')
        try:
            waiter.wait(
                executionArn=execution_arn,
                WaiterConfig={
                    'Delay': 3,  # Wait 3 seconds between checks
                    'MaxAttempts': 200  # Max 10 minutes (200 * 3s)
                }
            )
            
            # Get execution result
            result = self._sfn_client.describe_execution(executionArn=execution_arn)
            output = json.loads(result.get('output', '{}')) if result.get('output') else {}
            
            return {
                "status": "SUCCESS",
                "execution_id": execution_id,
                "executionArn": execution_arn,
                "response": output,
                "stopDate": result.get('stopDate').isoformat() if result.get('stopDate') else None,
            }
        except Exception as e:
            # If execution failed or timed out, get the error details
            try:
                result = self._sfn_client.describe_execution(executionArn=execution_arn)
                if result.get('status') == 'FAILED':
                    error_details = json.loads(result.get('error', '{}')) if result.get('error') else {}
                    return {
                        "status": "ERROR",
                        "execution_id": execution_id,
                        "executionArn": execution_arn,
                        "error": error_details.get('Error', 'Execution failed'),
                        "cause": error_details.get('Cause', 'Unknown cause')
                    }
            except:
                pass
            
            return {
                "status": "ERROR",
                "execution_id": execution_id,
                "executionArn": execution_arn,
                "error": f"Execution failed or timed out: {str(e)}"
            }


# Singleton accessor
_stepfunctions_adapter: StepFunctionsAdapter | None = None


def get_stepfunctions_adapter() -> StepFunctionsAdapter:
    """Get the Step Functions adapter instance."""
    global _stepfunctions_adapter
    if _stepfunctions_adapter is None:
        _stepfunctions_adapter = StepFunctionsAdapter()
    return _stepfunctions_adapter

