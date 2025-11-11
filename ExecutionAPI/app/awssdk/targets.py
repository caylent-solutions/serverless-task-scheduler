import logging
import uuid
from typing import Any, Dict
from datetime import datetime, timezone, timedelta

from .schedules import get_scheduler_client
from .lambda_adapter import get_lambda_adapter
from .stepfunctions_adapter import get_stepfunctions_adapter
from .ecs_adapter import get_ecs_adapter


logger = logging.getLogger("app.awssdk.targets")


class TargetInvoker:
    def __init__(self) -> None:
        self._lambda_adapter = get_lambda_adapter()
        self._stepfunctions_adapter = get_stepfunctions_adapter()
        self._ecs_adapter = get_ecs_adapter()
        self._scheduler = get_scheduler_client()

    def _parse_arn(self, arn: str) -> Dict[str, str]:
        parts = arn.split(":", 5)
        # arn:partition:service:region:account-id:resource
        if len(parts) < 6 or not arn.startswith("arn:"):
            raise ValueError(f"Invalid ARN: {arn}")
        return {
            "partition": parts[1],
            "service": parts[2],
            "region": parts[3],
            "account": parts[4],
            "resource": parts[5],
        }

    def invoke_async(self, target_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke target asynchronously"""
        meta = self._parse_arn(target_arn)
        service = meta["service"]

        if service == "lambda":
            return self._lambda_adapter.invoke_async(target_arn, payload)
        if service == "states":
            return self._stepfunctions_adapter.invoke_async(target_arn, payload)
        if service == "ecs":
            return self._ecs_adapter.invoke_async(target_arn, payload)

        raise ValueError(f"Unsupported target ARN service: {service}")

    def invoke_sync(self, target_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke target synchronously and wait for response"""
        meta = self._parse_arn(target_arn)
        service = meta["service"]

        if service == "lambda":
            return self._lambda_adapter.invoke_sync(target_arn, payload)
        if service == "states":
            return self._stepfunctions_adapter.invoke_sync(target_arn, payload)
        if service == "ecs":
            return self._ecs_adapter.invoke_sync(target_arn, payload)

        raise ValueError(f"Unsupported target ARN service: {service}")

    def create_scheduled_invocation(self, target_arn: str, payload: Dict[str, Any], delay_seconds: int = 10) -> Dict[str, Any]:
        """
        Create a one-time EventBridge schedule to invoke the target after delay_seconds.
        
        Args:
            target_arn: ARN of the target to invoke
            payload: Payload to pass to the target
            delay_seconds: Number of seconds to delay execution (default: 10)
            
        Returns:
            Dictionary with schedule creation result
        """
        # Calculate execution time (~10 seconds from now)
        execution_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        
        # Create unique schedule name
        schedule_name = f"target-invocation-{uuid.uuid4()}"
        
        # Format time for EventBridge at() expression: at(YYYY-MM-DDTHH:MM:SS)
        at_expression = f"at({execution_time.strftime('%Y-%m-%dT%H:%M:%S')})"
        
        # Set end_date to same as execution time + 1 second to make it a one-time schedule
        end_date = execution_time + timedelta(seconds=1)
        
        logger.info(f"Creating one-time EventBridge schedule '{schedule_name}' to execute target at {execution_time}")
        
        result = self._scheduler.create_schedule(
            schedule_name=schedule_name,
            schedule_expression=at_expression,
            target_arn=target_arn,
            target_input=payload,
            description=f"One-time target invocation for {target_arn}",
            end_date=end_date,
            state='ENABLED'
        )
        
        if result.get('status') == 'SUCCESS':
            return {
                "status": "ACCEPTED",
                "schedule_name": schedule_name,
                "schedule_arn": result.get('schedule_arn'),
                "scheduled_execution_time": execution_time.isoformat(),
                "message": f"Target scheduled for execution in {delay_seconds} seconds"
            }
        else:
            raise Exception(f"Failed to create EventBridge schedule: {result.get('error_message', 'Unknown error')}")



# Singleton accessor
_target_invoker: TargetInvoker | None = None


def get_target_invoker() -> TargetInvoker:
    global _target_invoker
    if _target_invoker is None:
        _target_invoker = TargetInvoker()
    return _target_invoker


