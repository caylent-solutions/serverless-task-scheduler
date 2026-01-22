from fastapi import APIRouter, Depends, HTTPException, Query
import logging
from fastapi_events.dispatcher import dispatch
from typing import Optional

from ..awssdk.schedules import get_scheduler_client


from ..awssdk.dynamodb import get_database_client
from ..awssdk.lambdas import get_lambda_runner
from ..awssdk.targets import get_target_invoker
from ..models.target import TargetBase, Target, TargetList, RouteChangedEvent
from ..authorization import require_admin
from ..routers.user import get_current_user

router = APIRouter()
logger = logging.getLogger("app.routers.targets")

# Get the database client
db_client = get_database_client()
lambda_runner = get_lambda_runner()
target_invoker = get_target_invoker()
scheduler = get_scheduler_client()


def create_get_target(target_id):
    async def get_target():
        """Get information about the target including execution endpoint for AI agents"""
        # Check if target still exists
        target = db_client.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")

        # Flatten the parameter schema if it's nested under 'schema' key
        parameter_schema = target.get('target_parameter_schema', {})
        if isinstance(parameter_schema, dict) and 'schema' in parameter_schema:
            parameter_schema = parameter_schema['schema']

        # Enhance with execution information for AI agents
        # Note: Execution must go through tenant context
        target_with_execution = {
            **target,
            "target_parameter_schema": parameter_schema,
            "execution_endpoint": f"/tenants/{{tenant_id}}/targets/{target_id}/_execute",
            "execution_method": "POST",
            "execution_requires_tenant_context": True
        }

        return target_with_execution

    # Set the function name and docstring
    get_target.__name__ = f"Get_info_{target_id}"
    get_target.__doc__ = f"Get information about the {target_id} target including how to execute it"
    return get_target


def create_execute_target(target_id, execution_data_schema):
    async def execute_target(
        execution_data: execution_data_schema,  # type: ignore
        mode: Optional[str] = Query("async", description="Execution mode: 'sync' to wait for response, 'async' to schedule via EventBridge")
    ):
        """
        Execute a target with the given parameters

        Modes:
        - sync: Invoke and wait for the output/response
        - async: Create a one-time EventBridge schedule that will execute the target in ~10 seconds
        """
        # Check if target still exists
        target = db_client.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")

        # Record logical execution in DB (mocked by current implementation)
        db_client.execute_target(target_id, execution_data)
        logger.info(f"executing target with arn: {target['target_arn']} in mode: {mode}")

        try:
            if mode == "sync":
                # Synchronous execution: invoke and wait for response
                invoke_response = target_invoker.invoke_sync(target["target_arn"], execution_data.dict())
                return {
                    "target_parameter_values": execution_data,
                    "execution_result": invoke_response,
                    "synchronous_execution": True
                }
            elif mode == "async":
                # Asynchronous execution: create one-time EventBridge schedule
                invoke_response = target_invoker.create_scheduled_invocation(
                    target["target_arn"],
                    execution_data.dict(),
                    delay_seconds=10
                )
                return {
                    "target_parameter_values": execution_data,
                    "execution_result": invoke_response,
                    "synchronous_execution": False
                }
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid mode '{mode}'. Must be 'sync' or 'async'"
                )
        except Exception as e:
            logger.exception("Target invocation failed")
            raise HTTPException(status_code=500, detail=str(e))

    # Set the function name and docstring
    execute_target.__name__ = f"execute_{target_id}"
    execute_target.__doc__ = f"Execute the {target_id} target"
    return execute_target


@router.get("/targets", response_model=TargetList)
async def get_targets(
    filter: Optional[str] = Query(default=None, description="Filter targets by ID, description, or ARN"),
    _: dict = Depends(get_current_user)
):
    """Get all targets - Authenticated users"""
    targets = db_client.get_all_targets(filter=filter)
    return {"targets": targets}


@router.post("/targets", response_model=TargetBase)
async def create_target(target: Target, _: dict = Depends(require_admin)):
    """Create a new target - Admin only"""
    # Check if target already exists
    existing = db_client.get_target(target.target_id)
    if existing:
        raise HTTPException(status_code=400, detail="target already exists")

    # Create target in storage
    target_dict = target.dict()
    success = db_client.create_target(target_dict)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create target")

    dispatch("route-added", payload=RouteChangedEvent(
        name=target.target_id,
        description=target.target_description,
        path=f"/targets/{target.target_id}",
        parameters=target.target_parameter_schema
    ))

    return target


@router.put("/targets/{target_id}", response_model=TargetBase)
async def update_target(target_id: str, target: Target, _: dict = Depends(require_admin)):
    """Update a target - Admin only"""
    # Ensure target_id in path matches the one in the target object
    if target.target_id != target_id:
        raise HTTPException(status_code=400, detail="Target ID in path must match target ID in body")

    # Check if target exists
    existing = db_client.get_target(target_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")

    # Update target in storage
    target_dict = target.dict()
    success = db_client.update_target(target_id, target_dict)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update target")

    dispatch("route-updated", payload=RouteChangedEvent(
        name=target.target_id,
        description=target.target_description,
        path=f"/targets/{target.target_id}",
        parameters=target.target_parameter_schema
    ))

    return target


@router.delete("/targets/{target_id}", response_model=TargetBase)
async def delete_target(target_id: str, _: dict = Depends(require_admin)):
    """Delete a target by name - Admin only"""
    # Check if target exists
    target = db_client.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")

    # Delete the target
    success = db_client.delete_target(target_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete target")

    dispatch("route-deleted", payload=RouteChangedEvent(
        name=target["target_id"],
        description=target["target_description"],
        path=f"/targets/{target['target_id']}"
    ))

    return TargetBase(**target)
