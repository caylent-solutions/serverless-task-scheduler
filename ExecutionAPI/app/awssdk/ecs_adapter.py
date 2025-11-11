"""
AWS ECS adapter for running ECS tasks.

This module provides a client/adapter for running AWS ECS tasks
both synchronously and asynchronously.
"""

import logging
from typing import Any, Dict, List, Optional

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
    
    def register_task_definition(self, task_definition: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new ECS task definition.
        
        Args:
            task_definition: Dictionary containing task definition parameters:
                - family: Task definition family name (required)
                - containerDefinitions: List of container definitions (required)
                - taskRoleArn: IAM role for the task (optional)
                - executionRoleArn: IAM role for ECS to pull images and manage tasks (optional)
                - networkMode: Network mode (optional)
                - cpu: CPU units (optional)
                - memory: Memory in MB (optional)
                - requiresCompatibilities: List of launch types (optional)
                - volumes: List of volumes (optional)
                - placementConstraints: List of placement constraints (optional)
                - tags: List of tags (optional)
                - etc. (all standard ECS RegisterTaskDefinition parameters)
            
        Returns:
            Dictionary with task definition details
        """
        logger.info(f"Registering ECS task definition: {task_definition.get('family')}")
        
        try:
            response = self._ecs_client.register_task_definition(**task_definition)
            
            task_def = response.get('taskDefinition', {})
            return {
                "status": "SUCCESS",
                "taskDefinitionArn": task_def.get('taskDefinitionArn'),
                "family": task_def.get('family'),
                "revision": task_def.get('revision'),
                "taskDefinition": task_def
            }
        except Exception as e:
            logger.error(f"Failed to register task definition: {str(e)}")
            return {
                "status": "ERROR",
                "error": str(e)
            }
    
    def describe_task_definition(self, task_definition: str) -> Dict[str, Any]:
        """
        Describe an ECS task definition.
        
        Args:
            task_definition: Task definition ARN or family:revision
            
        Returns:
            Dictionary with task definition details
        """
        logger.info(f"Describing ECS task definition: {task_definition}")
        
        try:
            response = self._ecs_client.describe_task_definition(
                taskDefinition=task_definition
            )
            
            task_def = response.get('taskDefinition', {})
            return {
                "status": "SUCCESS",
                "taskDefinition": task_def
            }
        except Exception as e:
            logger.error(f"Failed to describe task definition: {str(e)}")
            return {
                "status": "ERROR",
                "error": str(e)
            }
    
    def list_task_definitions(self, family_prefix: Optional[str] = None, status: str = "ACTIVE") -> Dict[str, Any]:
        """
        List ECS task definitions.
        
        Args:
            family_prefix: Filter by family prefix (optional)
            status: Filter by status (ACTIVE, INACTIVE, or ALL) - default: ACTIVE
            
        Returns:
            Dictionary with list of task definition ARNs
        """
        logger.info(f"Listing ECS task definitions (family_prefix={family_prefix}, status={status})")
        
        try:
            params = {"status": status}
            if family_prefix:
                params["familyPrefix"] = family_prefix
            
            response = self._ecs_client.list_task_definitions(**params)
            
            return {
                "status": "SUCCESS",
                "taskDefinitionArns": response.get('taskDefinitionArns', []),
                "nextToken": response.get('nextToken')
            }
        except Exception as e:
            logger.error(f"Failed to list task definitions: {str(e)}")
            return {
                "status": "ERROR",
                "error": str(e)
            }


# Singleton accessor
_ecs_adapter: ECSAdapter | None = None


def get_ecs_adapter() -> ECSAdapter:
    """Get the ECS adapter instance."""
    global _ecs_adapter
    if _ecs_adapter is None:
        _ecs_adapter = ECSAdapter()
    return _ecs_adapter

