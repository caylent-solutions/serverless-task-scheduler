import datetime
import json
import os
import uuid
from uuid_v7.base import uuid7
from fastapi import APIRouter, HTTPException, Query, Depends, Request
import logging
from typing import Dict, Any, List, Optional
from fastapi_events.dispatcher import dispatch
from ..awssdk.dynamodb import get_database_client
from ..awssdk.targets import get_target_invoker
from ..awssdk.schedules import get_scheduler_client
from ..awssdk.usermappings import UserMappingsDB
from ..models.schedule import Schedule
from ..models.tenant import Tenant, TenantList
from ..models.tenantmapping import TenantMapping
from ..models.usermapping import UserMapping, UserMappingList
from ..authorization import require_admin, require_tenant_access

router = APIRouter()
logger = logging.getLogger("app.routers.tenants")

# Get the database client, scheduler client, and target invoker
db_client = get_database_client()
scheduler = get_scheduler_client()
target_invoker = get_target_invoker()

# =============================================================================
# Tenant CRUD Endpoints
# =============================================================================

@router.get("/tenants", response_model=TenantList)
async def get_all_tenants(_: dict = Depends(require_admin)):
    """Get all tenants (admin only)"""
    tenants = db_client.get_all_tenants()
    return TenantList(tenants=tenants)


@router.get("/tenants/{tenant_id}", response_model=Tenant)
async def get_tenant(tenant_id: str, _: dict = Depends(require_admin)):
    """Get a specific tenant by id (admin only)"""
    tenant = db_client.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    return tenant


@router.post("/tenants", response_model=Tenant)
async def create_tenant(tenant: Tenant, _: dict = Depends(require_admin)):
    """Create a new tenant (admin only)"""
    # Check if tenant already exists
    existing = db_client.get_tenant(tenant.tenant_id)
    if existing:
        raise HTTPException(status_code=400, detail="Tenant already exists")

    # Create tenant in storage
    success = db_client.create_tenant(tenant.dict())
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create tenant")

    return tenant


@router.put("/tenants/{tenant_id}", response_model=Tenant)
async def update_tenant(
    tenant_id: str,
    tenant: Tenant,
    _: dict = Depends(require_admin)
):
    """Update an existing tenant (admin only)"""
    # Ensure tenant_id in path matches the one in the tenant object
    if tenant.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID in path must match tenant ID in body")

    # Check if tenant exists
    existing = db_client.get_tenant(tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")

    # Update tenant in storage
    success = db_client.update_tenant(tenant_id, tenant)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update tenant")

    return tenant


@router.delete("/tenants/{tenant_id}", response_model=Tenant)
async def delete_tenant(tenant_id: str, _: dict = Depends(require_admin)):
    """Delete a tenant (admin only)"""
    # Check if tenant exists
    tenant = db_client.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")

    # Delete tenant from storage
    success = db_client.delete_tenant_record(tenant_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete tenant")

    return tenant


@router.get("/tenants/{tenant_id}/users", response_model=UserMappingList)
async def list_tenant_users(
    tenant_id: str,
    _: dict = Depends(require_admin)
):
    """
    List all users with access to a specific tenant (Admin only)

    Args:
        tenant_id: Tenant ID

    Returns:
        List of users with access to the tenant
    """
    try:
        user_db = UserMappingsDB()
        mappings = user_db.get_tenant_users(tenant_id)

        return UserMappingList(
            mappings=mappings,
            count=len(mappings)
        )

    except Exception as e:
        logger.error(f"Error listing tenant users: {e}")
        raise HTTPException(status_code=500, detail="Error listing tenant users")


# =============================================================================
# Tenant Target Mapping Endpoints
# =============================================================================

@router.post("/tenants/{tenant_id}/mappings/{target_alias}/_execute")
async def execute_tenant_mapping(
    tenant_id: str,
    target_alias: str,
    execution_data: Dict[str, Any],
    _: dict = Depends(require_tenant_access)
):
    """
    Execute a tenant target mapping asynchronously via a one-time EventBridge schedule.
    This creates a schedule that runs immediately and then auto-deletes itself.
    All execution goes through the ExecutorStepFunction for security.
    """
    # Check if mapping exists
    mapping = db_client.get_tenant_target_mapping(tenant_id, target_alias)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Mapping for tenant '{tenant_id}' and target alias '{target_alias}' not found")

    # Get the target details to validate
    target = db_client.get_target(mapping.target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{mapping.target_id}' not found")

    # Generate unique one-time schedule ID
    from uuid_v7.base import uuid7
    schedule_id = f"adhoc-{uuid7()}"

    # Build tenant-specific schedule group name
    base_group_name = os.environ.get("SCHEDULER_GROUP_NAME", "default")
    tenant_group_name = f"{base_group_name}-{tenant_id}"

    # Get executor Step Functions ARN from environment
    executor_arn = os.environ.get("STEP_FUNCTIONS_EXECUTOR_ARN")
    if not executor_arn:
        raise HTTPException(
            status_code=500,
            detail="STEP_FUNCTIONS_EXECUTOR_ARN not configured"
        )

    # Build the target input payload for the executor Step Functions
    target_input = {
        "tenant_id": tenant_id,
        "target_alias": target_alias,
        "schedule_id": schedule_id,
        "payload": execution_data
    }

    # Create a one-time schedule that runs immediately (at: now + 1 minute)
    import datetime
    start_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)

    # Use 'at' expression for one-time execution
    schedule_expression = f"at({start_time.strftime('%Y-%m-%dT%H:%M:%S')})"

    result = scheduler.create_schedule(
        schedule_name=schedule_id,
        schedule_expression=schedule_expression,
        target_arn=executor_arn,
        target_input=target_input,
        description=f"Ad-hoc execution for {target_alias} (auto-delete after execution)",
        state='ENABLED',
        group_name=tenant_group_name
    )

    if result["status"] != "SUCCESS":
        logger.error(f"Failed to create one-time schedule: {result}")
        raise HTTPException(status_code=500, detail=f"Failed to schedule execution: {result.get('error_message', 'Unknown error')}")

    # Construct the URL to query execution status
    # Uses the same endpoint structure as recurring schedules
    execution_query_url = f"/tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}/executions"

    return {
        "status": "SCHEDULED",
        "schedule_id": schedule_id,
        "message": f"Ad-hoc execution scheduled for {start_time.isoformat()}",
        "execution_time": start_time.isoformat(),
        "execution_query_url": execution_query_url,
        "note": "This one-time schedule will be automatically deleted by EventBridge after execution. Use the execution_query_url to poll for results and CloudWatch Logs URL."
    }

@router.post("/tenants/{tenant_id}/mappings/{target_alias}/schedules")
async def create_target_schedule(
    tenant_id: str,
    target_alias: str,
    schedule: Dict[str, Any],
    _: dict = Depends(require_tenant_access)
):
    """Create a new schedule for a target mapping (requires tenant access)"""
    # Generate unique schedule ID (using uuid7 for time-based sorting)
    schedule_name = f"{uuid7()}"

    # Convert datetime strings to datetime objects
    start_date_obj = None
    end_date_obj = None

    if schedule.get("start_date"):
        start_date_obj = datetime.datetime.fromisoformat(schedule["start_date"])

    if schedule.get("end_date"):
        end_date_obj = datetime.datetime.fromisoformat(schedule["end_date"])

    # Create Schedule model
    schedule_model = Schedule(
        tenant_id=tenant_id,
        schedule_id=schedule_name,
        target_alias=target_alias,
        schedule_expression=schedule["schedule_expression"],
        description=schedule.get("description", f"Schedule for {target_alias} and tenant {tenant_id}"),
        timezone=schedule.get("timezone", None),
        start_date=start_date_obj,
        end_date=end_date_obj,
        state=schedule.get("state", "ENABLED")
    )

    # Build tenant-specific schedule group name
    # Format: {base_group_name}-{tenant_id}
    # Example: jyelle-sts-dev-schedules-jer
    base_group_name = os.environ.get("SCHEDULER_GROUP_NAME", "default")
    tenant_group_name = f"{base_group_name}-{tenant_id}"

    # Get executor Step Functions ARN from environment
    executor_arn = os.environ.get("STEP_FUNCTIONS_EXECUTOR_ARN")
    if not executor_arn:
        raise HTTPException(
            status_code=500,
            detail="STEP_FUNCTIONS_EXECUTOR_ARN not configured"
        )

    # Create in EventBridge Scheduler first
    # Build the target input payload for the executor Step Functions
    target_input = {
        "tenant_id": tenant_id,
        "target_alias": target_alias,
        "schedule_id": schedule_model.schedule_id,
        "payload": schedule.get("target_input", {})
    }

    result = scheduler.create_schedule(
        schedule_name=schedule_model.schedule_id,
        schedule_expression=schedule_model.schedule_expression,
        target_arn=executor_arn,
        target_input=target_input,
        description=schedule_model.description,
        timezone=schedule_model.timezone,
        start_date=schedule_model.start_date,
        end_date=schedule_model.end_date,
        state=schedule_model.state,
        group_name=tenant_group_name
    )

    if result["status"] != "SUCCESS":
        logger.error(f"Failed to create EventBridge schedule: {result}")
        raise HTTPException(status_code=500, detail=f"Failed to create EventBridge schedule: {result.get('error_message', 'Unknown error')}")

    # If EventBridge creation succeeded, save to DynamoDB
    success = db_client.create_schedule(schedule_model)
    if not success:
        logger.error(f"Failed to save schedule to DynamoDB after EventBridge creation")
        # Attempt to clean up EventBridge schedule
        scheduler.delete_schedule(schedule_name=schedule_model.schedule_id)
        raise HTTPException(status_code=500, detail="Failed to save schedule to database")

    return result

@router.put("/tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}")
async def update_target_schedule(
    tenant_id: str,
    target_alias: str,
    schedule_id: str,
    schedule: Dict[str, Any],
    _: dict = Depends(require_tenant_access)
):
    """Update a schedule for a target mapping (requires tenant access)"""
    # Convert datetime strings to datetime objects if they exist
    start_date_obj = None
    end_date_obj = None

    if schedule.get("start_date"):
        if isinstance(schedule["start_date"], str):
            start_date_obj = datetime.datetime.fromisoformat(schedule["start_date"])
        else:
            start_date_obj = schedule["start_date"]

    if schedule.get("end_date"):
        if isinstance(schedule["end_date"], str):
            end_date_obj = datetime.datetime.fromisoformat(schedule["end_date"])
        else:
            end_date_obj = schedule["end_date"]

    # Create Schedule model
    schedule_model = Schedule(
        tenant_id=tenant_id,
        schedule_id=schedule_id,
        target_alias=target_alias,
        schedule_expression=schedule["schedule_expression"],
        description=schedule.get("description", f"Schedule for {target_alias} and tenant {tenant_id}"),
        timezone=schedule.get("timezone", None),
        start_date=start_date_obj,
        end_date=end_date_obj,
        state=schedule.get("state", "ENABLED")
    )

    # Build tenant-specific schedule group name
    base_group_name = os.environ.get("SCHEDULER_GROUP_NAME", "default")
    tenant_group_name = f"{base_group_name}-{tenant_id}"

    # Get executor Step Functions ARN from environment
    executor_arn = os.environ.get("STEP_FUNCTIONS_EXECUTOR_ARN")
    if not executor_arn:
        raise HTTPException(
            status_code=500,
            detail="STEP_FUNCTIONS_EXECUTOR_ARN not configured"
        )

    # Update in EventBridge Scheduler first
    # Build the target input payload for the executor Step Functions
    target_input = {
        "tenant_id": tenant_id,
        "target_alias": target_alias,
        "schedule_id": schedule_model.schedule_id,
        "payload": schedule.get("target_input", {})
    }

    result = scheduler.update_schedule(
        schedule_name=schedule_model.schedule_id,
        schedule_expression=schedule_model.schedule_expression,
        target_arn=executor_arn,
        target_input=target_input,
        description=schedule_model.description,
        timezone=schedule_model.timezone,
        start_date=schedule_model.start_date,
        end_date=schedule_model.end_date,
        state=schedule_model.state,
        group_name=tenant_group_name
    )

    if result["status"] != "SUCCESS":
        raise HTTPException(status_code=500, detail=f"Failed to update EventBridge schedule: {result.get('error_message', 'Unknown error')}")

    # If EventBridge update succeeded, update in DynamoDB
    success = db_client.update_schedule(schedule_model)
    if not success:
        logger.error(f"Failed to update schedule in DynamoDB after EventBridge update")
        raise HTTPException(status_code=500, detail="Failed to update schedule in database")

    return result

@router.delete("/tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}")
async def delete_target_schedule(
    tenant_id: str,
    target_alias: str,
    schedule_id: str,
    _: dict = Depends(require_tenant_access)
):
    """Delete a schedule for a target mapping (requires tenant access)"""
    # Build tenant-specific schedule group name
    base_group_name = os.environ.get("SCHEDULER_GROUP_NAME", "default")
    tenant_group_name = f"{base_group_name}-{tenant_id}"

    # Delete from EventBridge first
    result = scheduler.delete_schedule(schedule_name=schedule_id, group_name=tenant_group_name)

    if result["status"] != "SUCCESS" and result.get("error_code") != "ResourceNotFoundException":
        raise HTTPException(status_code=500, detail=f"Failed to delete EventBridge schedule: {result.get('error_message', 'Unknown error')}")

    # If EventBridge deletion succeeded (or resource not found), delete from DynamoDB
    success = db_client.delete_schedule(tenant_id, schedule_id)
    if not success and result.get("error_code") != "ResourceNotFoundException":
        logger.warning(f"EventBridge schedule deleted but DynamoDB deletion failed for {schedule_id}")

    return result

@router.get("/tenants/{tenant_id}/mappings/{target_alias}/schedules")
async def get_target_schedules(
    tenant_id: str,
    target_alias: str,
    _: dict = Depends(require_tenant_access)
):
    """Get all schedules for a target mapping (requires tenant access)"""
    schedules = db_client.get_all_target_schedules(tenant_id, target_alias)
    return schedules

@router.get("/tenants/{tenant_id}/schedules")
async def get_tenant_schedules(
    tenant_id: str,
    _: dict = Depends(require_tenant_access)
):
    """Get all schedules for a tenant (requires tenant access)"""
    schedules = db_client.get_all_schedules(tenant_id)
    return schedules

@router.get("/tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}/executions")
async def get_schedule_executions(
    tenant_id: str,
    target_alias: str,
    schedule_id: str,
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of executions to return"),
    start_time_lower: Optional[str] = Query(default=None, description="ISO 8601 timestamp - only return executions after this time"),
    start_time_upper: Optional[str] = Query(default=None, description="ISO 8601 timestamp - only return executions before this time"),
    status: Optional[str] = Query(default=None, description="Filter by execution status (SUCCESS or FAILED)"),
    _: dict = Depends(require_tenant_access)
):
    """
    Get all executions for a specific schedule (requires tenant access).
    Works for both ad-hoc and recurring schedules.
    Supports filtering by time range and status.
    """
    try:
        # Query executions for this schedule with filters
        executions = db_client.get_schedule_executions(
            tenant_id=tenant_id,
            schedule_id=schedule_id,
            target_alias=target_alias,
            limit=limit,
            start_time_lower=start_time_lower,
            start_time_upper=start_time_upper,
            status=status
        )

        return {
            "tenant_id": tenant_id,
            "target_alias": target_alias,
            "schedule_id": schedule_id,
            "count": len(executions),
            "executions": executions
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving schedule executions: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving schedule executions")


# Tenant Target Mappings Management Endpoints (RESTful structure)
@router.get("/tenants/{tenant_id}/mappings", response_model=List[TenantMapping])
async def get_tenant_mappings_rest(
    tenant_id: str,
    _: dict = Depends(require_tenant_access)
):
    """Get all target mappings for a specific tenant (requires tenant access)"""
    mappings = db_client.get_tenant_mappings(tenant_id)
    return mappings


@router.post("/tenants/{tenant_id}/mappings", response_model=TenantMapping)
async def create_tenant_mapping(
    tenant_id: str,
    mapping: TenantMapping,
    current_user: dict = Depends(require_tenant_access)
):
    """Create a new tenant target mapping (requires tenant access)"""
    # Ensure tenant_id in path matches the one in the mapping
    if mapping.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID in path must match tenant ID in mapping")
    
    # Add audit fields
    mapping.last_update_user = current_user.get('email', current_user.get('cognito:username', 'unknown'))
    mapping.last_update_date = datetime.datetime.utcnow().isoformat()
    
    # Check if mapping already exists
    existing = db_client.get_tenant_target_mapping(mapping.tenant_id, mapping.target_alias)
    if existing:
        raise HTTPException(status_code=400, detail="Tenant target mapping already exists")
    
    # Check if the target_id exists
    target = db_client.get_target(mapping.target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{mapping.target_id}' not found")
    
    # Create mapping in storage
    success = db_client.create_tenant_mapping(mapping)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create tenant mapping")
    
    return mapping


@router.get("/tenants/{tenant_id}/mappings/{target_alias}", response_model=TenantMapping)
async def get_tenant_mapping(
    tenant_id: str,
    target_alias: str,
    _: dict = Depends(require_tenant_access)
):
    """Get a specific tenant target mapping (requires tenant access)"""
    mapping = db_client.get_tenant_target_mapping(tenant_id, target_alias)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Mapping for tenant '{tenant_id}' and target '{target_alias}' not found")
    return mapping


@router.put("/tenants/{tenant_id}/mappings/{target_alias}", response_model=TenantMapping)
async def update_tenant_mapping(
    tenant_id: str,
    target_alias: str,
    mapping: TenantMapping,
    current_user: dict = Depends(require_tenant_access)
):
    """Update a tenant target mapping (requires tenant access)"""
    # Add audit fields
    mapping.last_update_user = current_user.get('email', current_user.get('cognito:username', 'unknown'))
    mapping.last_update_date = datetime.datetime.utcnow().isoformat()
    
    # Ensure tenant_id and target_alias in path match the ones in the mapping
    if mapping.tenant_id != tenant_id or mapping.target_alias != target_alias:
        raise HTTPException(status_code=400, detail="Tenant ID and target alias in path must match those in mapping")
    
    # Check if mapping exists
    existing = db_client.get_tenant_target_mapping(tenant_id, target_alias)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mapping for tenant '{tenant_id}' and target '{target_alias}' not found")
    
    # Check if the target_id exists
    target = db_client.get_target(mapping.target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{mapping.target_id}' not found")
    
    # Update mapping in storage
    success = db_client.update_tenant_mapping(tenant_id, target_alias, mapping)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update tenant mapping")
    
    return mapping


@router.delete("/tenants/{tenant_id}/mappings/{target_alias}", response_model=TenantMapping)
async def delete_tenant_mapping(
    tenant_id: str,
    target_alias: str,
    _: dict = Depends(require_tenant_access)
):
    """Delete a tenant target mapping (requires tenant access)"""
    # Check if mapping exists
    mapping = db_client.get_tenant_target_mapping(tenant_id, target_alias)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Mapping for tenant '{tenant_id}' and target '{target_alias}' not found")

    # Delete mapping from storage
    success = db_client.delete_tenant_mapping(tenant_id, target_alias)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete tenant mapping")

    return mapping


# =============================================================================
# Execution Query Endpoints
# =============================================================================

@router.get("/tenants/{tenant_id}/mappings/{target_alias}/executions/{execution_id}")
async def get_execution_by_id(
    tenant_id: str,
    target_alias: str,
    execution_id: str,
    _: dict = Depends(require_tenant_access)
):
    """
    Get execution record by execution_id (for ad-hoc executions) or schedule_id (for scheduled executions).
    Returns execution details including CloudWatch Logs URL for testing.
    Requires tenant access to the tenant_id.
    """
    try:
        # Query execution record by tenant_id + schedule_id (which is execution_id for ad-hoc executions)
        execution = db_client.get_execution_by_schedule_id(tenant_id, execution_id)

        if not execution:
            raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found or not yet completed")

        # Verify the execution matches the tenant and target from the path
        tenant_target = execution.get('tenant_target', '')
        expected_tenant_target = f"{tenant_id}#{target_alias}"

        if tenant_target != expected_tenant_target:
            raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' does not match tenant '{tenant_id}' and target '{target_alias}'")

        return execution

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving execution: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving execution record")


@router.get("/tenants/{tenant_id}/mappings/{target_alias}/executions")
async def list_executions(
    tenant_id: str,
    target_alias: str,
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of executions to return"),
    start_time_lower: Optional[str] = Query(default=None, description="ISO 8601 timestamp - only return executions after this time"),
    start_time_upper: Optional[str] = Query(default=None, description="ISO 8601 timestamp - only return executions before this time"),
    status: Optional[str] = Query(default=None, description="Filter by execution status (SUCCESS or FAILED)"),
    _: dict = Depends(require_tenant_access)
):
    """
    List recent executions for a specific tenant target mapping (requires tenant access).
    Returns up to 'limit' most recent executions sorted by timestamp descending.
    Supports filtering by time range and status.
    """
    try:
        executions = db_client.list_target_executions(
            tenant_id=tenant_id,
            target_alias=target_alias,
            limit=limit,
            start_time_lower=start_time_lower,
            start_time_upper=start_time_upper,
            status=status
        )
        return {
            "tenant_id": tenant_id,
            "target_alias": target_alias,
            "count": len(executions),
            "executions": executions
        }
    except Exception as e:
        logger.error(f"Error listing executions: {e}")
        raise HTTPException(status_code=500, detail="Error listing executions")


@router.post("/tenants/{tenant_id}/mappings/{target_alias}/executions/{execution_id}/redrive")
async def redrive_execution(
    tenant_id: str,
    target_alias: str,
    execution_id: str,
    _: dict = Depends(require_tenant_access)
):
    """
    Re-drive a failed Step Functions execution using AWS Step Functions redrive capability.
    This allows retrying a failed execution from the point of failure.

    Args:
        tenant_id: Tenant identifier
        target_alias: Target alias for the execution
        execution_id: Execution ID (UUIDv7 of the Step Functions execution)

    Returns:
        Information about the re-driven execution

    Raises:
        404: If execution not found or cannot be redriven
        400: If execution is not in FAILED status
        500: If redrive operation fails
    """
    import boto3
    from botocore.exceptions import ClientError

    try:
        # Query DynamoDB using the tenant-target-index GSI to find the execution
        tenant_target = f"{tenant_id}#{target_alias}"

        dynamodb = boto3.resource('dynamodb')
        executions_table_name = os.environ.get('DYNAMODB_EXECUTIONS_TABLE')
        table = dynamodb.Table(executions_table_name)

        # Query the GSI with tenant_target and filter by execution_id (UUIDv7)
        # Note: Don't use Limit here as it applies before FilterExpression
        response = table.query(
            IndexName='tenant-target-index',
            KeyConditionExpression='tenant_target = :tt',
            FilterExpression='execution_id = :eid',
            ExpressionAttributeValues={':tt': tenant_target, ':eid': execution_id}
        )

        items = response.get('Items', [])
        if not items:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found for tenant '{tenant_id}' and target '{target_alias}'"
            )

        execution_record = items[0]

        # Check if execution is in FAILED status
        if execution_record.get('status') != 'FAILED':
            raise HTTPException(
                status_code=400,
                detail=f"Only FAILED executions can be redriven. Current status: {execution_record.get('status')}"
            )

        # Check if execution can be redriven
        if not execution_record.get('can_redrive', False):
            raise HTTPException(
                status_code=400,
                detail="This execution cannot be redriven"
            )

        # Get the state machine ARN from environment and construct the full execution ARN
        state_machine_arn = os.environ.get('STEP_FUNCTIONS_EXECUTOR_ARN')
        if not state_machine_arn:
            raise HTTPException(
                status_code=500,
                detail="State machine ARN not configured"
            )

        # Construct the full execution ARN using the execution_id (UUID)
        # Format: arn:aws:states:region:account:execution:stateMachineName:executionName
        sfn_execution_arn = f"{state_machine_arn.replace(':stateMachine:', ':execution:')}:{execution_id}"

        # Initialize Step Functions client
        sfn_client = boto3.client('stepfunctions')

        # Record initial IN_PROGRESS status before redriving
        try:
            from datetime import datetime, timezone, timedelta

            timestamp = datetime.now(timezone.utc).isoformat()
            tenant_schedule = execution_record.get('tenant_schedule')

            # Calculate TTL: 45 days from now (in seconds since epoch)
            ttl_date = datetime.now(timezone.utc) + timedelta(days=45)
            ttl = int(ttl_date.timestamp())

            # Update the execution record to IN_PROGRESS status
            table.put_item(Item={
                'tenant_schedule': tenant_schedule,
                'execution_id': execution_id,
                'tenant_target': tenant_target,
                'timestamp': timestamp,
                'status': 'IN_PROGRESS',
                'result': {},
                'executed_at': timestamp,
                'state_machine_execution_arn': execution_id,
                'execution_start_time': timestamp,
                'ttl': ttl
            })
            logger.info(f"Updated execution to IN_PROGRESS before redrive: {execution_id}")
        except Exception as e:
            logger.warning(f"Failed to update execution status to IN_PROGRESS: {e}")
            # Continue with redrive even if status update fails

        # Call Step Functions redrive API
        # Note: Using RedriveExecution API (boto3 >= 1.34.0)
        try:
            redrive_response = sfn_client.redrive_execution(
                executionArn=sfn_execution_arn
            )

            logger.info(f"Successfully redriven execution: {sfn_execution_arn}")

            return {
                "status": "REDRIVEN",
                "execution_id": execution_id,
                "original_execution_arn": sfn_execution_arn,
                "redrive_date": redrive_response.get('redriveDate'),
                "redrive_count": redrive_response.get('redriveCount'),
                "message": "Execution has been redriven successfully",
                "note": "The execution will restart from the failed state. Check the executions list for updated status."
            }

        except AttributeError:
            # Fallback for older boto3 versions without redrive_execution
            logger.error("boto3 version does not support redrive_execution")
            raise HTTPException(
                status_code=500,
                detail="Step Functions redrive feature requires boto3 >= 1.34.0. Please update the Lambda runtime dependencies."
            )

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            if error_code == 'ExecutionNotRedrivable':
                raise HTTPException(
                    status_code=400,
                    detail=f"Execution cannot be redriven: {error_message}"
                )
            elif error_code == 'ExecutionDoesNotExist':
                raise HTTPException(
                    status_code=404,
                    detail="Step Functions execution not found or has been deleted"
                )
            else:
                logger.error(f"Step Functions redrive failed: {error_code} - {error_message}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to redrive execution: {error_message}"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during redrive: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during redrive: {str(e)}"
        )