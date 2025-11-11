"""
AWS ECS adapter for running ECS tasks.

This module provides a client/adapter for running AWS ECS tasks
both synchronously and asynchronously.
"""

import logging
from typing import Any, Dict, List

from . import get_session


logger = logging.getLogger("app.awssdk.ecs_adapter")


class ECSAdapter:
    """Adapter for running AWS ECS tasks."""
    
    def __init__(self):
        """Initialize the ECS adapter."""
        session = get_session()
        self._ecs_client = session.client("ecs")
    
    def invoke_async(self, ecs_resource_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run an ECS task asynchronously (start and return immediately).
        
        Args:
            ecs_resource_arn: The ARN of the task definition (task-definition/NAME:REV)
            payload: The payload containing task configuration and cluster information
            
        Returns:
            Dictionary with task execution details
        """
        logger.info(f"Running ECS task for resource: {ecs_resource_arn}")
        
        # The ARN is typically a task definition (task-definition/NAME:REV). We pass it as taskDefinition.
        task_definition = ecs_resource_arn
        
        # Cluster can be provided as 'clusterArn' or 'cluster' inside payload
        cluster_value = payload.get("clusterArn") or payload.get("cluster")
        if not cluster_value:
            raise ValueError("ECS run_task requires 'clusterArn' (or 'cluster') in payload")
        
        params = self._build_run_task_params(task_definition, cluster_value, payload)
        
        response = self._ecs_client.run_task(**params)
        task_arns = [t.get("taskArn") for t in response.get("tasks", []) if t.get("taskArn")]
        
        failures = response.get("failures") or []
        if failures:
            return {
                "status": "ERROR",
                "message": "One or more tasks failed to start",
                "failures": failures,
                "taskArns": task_arns,
            }
        
        return {
            "status": "ACCEPTED",
            "taskArns": task_arns,
        }
    
    def invoke_sync(self, ecs_resource_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run an ECS task and wait for completion.
        
        Note: This waits for the task to reach STOPPED state, which may take time.
        
        Args:
            ecs_resource_arn: The ARN of the task definition (task-definition/NAME:REV)
            payload: The payload containing task configuration and cluster information
            
        Returns:
            Dictionary with task execution result
        """
        logger.info(f"Running ECS task synchronously for resource: {ecs_resource_arn}")
        
        # The ARN is typically a task definition (task-definition/NAME:REV). We pass it as taskDefinition.
        task_definition = ecs_resource_arn
        
        # Cluster can be provided as 'clusterArn' or 'cluster' inside payload
        cluster_value = payload.get("clusterArn") or payload.get("cluster")
        if not cluster_value:
            raise ValueError("ECS run_task requires 'clusterArn' (or 'cluster') in payload")
        
        params = self._build_run_task_params(task_definition, cluster_value, payload)
        
        response = self._ecs_client.run_task(**params)
        tasks = response.get("tasks", [])
        task_arns = [t.get("taskArn") for t in tasks if t.get("taskArn")]
        
        failures = response.get("failures") or []
        if failures:
            return {
                "status": "ERROR",
                "message": "One or more tasks failed to start",
                "failures": failures,
                "taskArns": task_arns,
            }
        
        if not task_arns:
            return {
                "status": "ERROR",
                "message": "No tasks were started",
            }
        
        # Wait for tasks to complete (wait for STOPPED state)
        waiter = self._ecs_client.get_waiter('tasks_stopped')
        try:
            waiter.wait(
                cluster=cluster_value,
                tasks=task_arns,
                WaiterConfig={
                    'Delay': 6,  # Wait 6 seconds between checks
                    'MaxAttempts': 100  # Max 10 minutes (100 * 6s)
                }
            )
            
            # Describe the tasks to get their final status
            task_details = self._ecs_client.describe_tasks(
                cluster=cluster_value,
                tasks=task_arns
            )
            
            tasks_info = task_details.get('tasks', [])
            exit_codes = [t.get('containers', [{}])[0].get('exitCode') for t in tasks_info]
            
            # Check if any task failed (non-zero exit code)
            if any(code and code != 0 for code in exit_codes):
                return {
                    "status": "ERROR",
                    "taskArns": task_arns,
                    "exitCodes": exit_codes,
                    "message": "One or more tasks completed with non-zero exit code"
                }
            
            return {
                "status": "SUCCESS",
                "taskArns": task_arns,
                "exitCodes": exit_codes,
                "message": "All tasks completed successfully"
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "taskArns": task_arns,
                "error": f"Error waiting for tasks to complete: {str(e)}"
            }
    
    def _build_run_task_params(self, task_definition: str, cluster: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build parameters for run_task API call.
        
        Args:
            task_definition: The task definition ARN or name:revision
            cluster: The cluster name or ARN
            payload: The payload containing additional parameters
            
        Returns:
            Dictionary of parameters for run_task
        """
        params: Dict[str, Any] = {
            "taskDefinition": task_definition,
            "cluster": cluster,
            "count": int(payload.get("count", 1)),
        }
        
        # Pass-through of common optional parameters if provided by caller
        passthrough_keys: List[str] = [
            "launchType",
            "capacityProviderStrategy",
            "platformVersion",
            "networkConfiguration",
            "overrides",
            "enableECSManagedTags",
            "enableExecuteCommand",
            "propagateTags",
            "tags",
            "placementConstraints",
            "placementStrategy",
            "group",
        ]
        
        for key in passthrough_keys:
            if key in payload and payload[key] is not None:
                params[key] = payload[key]
        
        return params


# Singleton accessor
_ecs_adapter: ECSAdapter | None = None


def get_ecs_adapter() -> ECSAdapter:
    """Get the ECS adapter instance."""
    global _ecs_adapter
    if _ecs_adapter is None:
        _ecs_adapter = ECSAdapter()
    return _ecs_adapter

