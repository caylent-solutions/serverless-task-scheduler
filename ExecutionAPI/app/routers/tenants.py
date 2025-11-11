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
from ..awssdk.lambdas import get_lambda_runner  # Still used for _execute endpoints
from ..awssdk.schedules import get_scheduler_client
from ..awssdk.usermappings import UserMappingsDB
from ..models.schedule import Schedule
from ..models.tenant import Tenant, TenantList
from ..models.tenantmapping import TenantMapping
from ..models.usermapping import UserMapping, UserMappingList
from .user import get_current_user
from ..authorization import require_admin, require_tenant_access

router = APIRouter()
logger = logging.getLogger("app.routers.tenants")

# Get the database client, scheduler client, and lambda runner
db_client = get_database_client()
scheduler = get_scheduler_client()
lambda_runner = get_lambda_runner()  # Still used for _execute endpoints

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
    async_execution: bool = Query(False, alias="async"),
    _: dict = Depends(require_tenant_access)
):
    """Execute a tenant target mapping with the given parameters (requires tenant access)"""
    # Check if mapping exists
    mapping = db_client.get_tenant_target_mapping(tenant_id, target_alias)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Mapping for tenant '{tenant_id}' and target alias '{target_alias}' not found")

    # Get the target details to validate execution parameters
    target = db_client.get_target(mapping.target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{mapping.target_id}' not found")

    # Add tenant context to execution data
    execution_data_with_context = {
        **execution_data,
        "tenant_context": {
            "tenant_id": tenant_id,
            "target_alias": target_alias
        }
    }

    result = db_client.execute_target(
            mapping.target_id,
            execution_data_with_context,
            is_async=async_execution)

    # Execute the target
    if async_execution:
        # For async execution, use the async Lambda invocation
        lambda_runner.execute_lambda_async(target["target_arn"], execution_data_with_context)

        return result
    else:
        # For sync execution, directly call the execute_target method
        target_result = lambda_runner.execute_lambda_sync(target["target_arn"], execution_data_with_context)
        result["target_result"] = target_result
        return result

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

    # Create in EventBridge Scheduler first
    target_input = {
        "version": "2.0",
        "routeKey": "POST /tenants/{tenant_id}/mappings/{target_alias}/_execute",
        "rawPath": f"/tenants/{tenant_id}/mappings/{target_alias}/_execute",
        "rawQueryString": "",
        "headers": {
            "content-type": "application/json",
            "x-forwarded-for": "127.0.0.1",
            "x-forwarded-port": "443",
            "x-forwarded-proto": "https",
            "accept": "*/*",
            "accept-encoding": "gzip, deflate",
            "host": "api.example.com"
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "api-id",
            "domainName": "api.example.com",
            "domainPrefix": "api",
            "http": {
                "method": "POST",
                "path": f"/tenants/{tenant_id}/mappings/{target_alias}/_execute",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "Custom/1.0"
            },
            "requestId": str(uuid.uuid4()),
            "routeKey": "POST /tenants/{tenant_id}/mappings/{target_alias}/_execute",
            "stage": "$default",
            "time": datetime.datetime.now().strftime("%d/%b/%Y:%H:%M:%S +0000"),
            "timeEpoch": int(datetime.datetime.now().timestamp() * 1000)
        },
        "isBase64Encoded": False,
        "body": json.dumps(schedule.get("target_input", {}))
    }

    result = scheduler.create_schedule(
        schedule_name=schedule_model.schedule_id,
        schedule_expression=schedule_model.schedule_expression,
        target_arn=os.environ.get("EXECUTION_API_LAMBDA_ARN"),
        target_input=target_input,
        description=schedule_model.description,
        timezone=schedule_model.timezone,
        start_date=schedule_model.start_date,
        end_date=schedule_model.end_date,
        state=schedule_model.state
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

    # Update in EventBridge Scheduler first
    target_input = {
        "version": "2.0",
        "routeKey": "POST /tenants/{tenant_id}/mappings/{target_alias}/_execute",
        "rawPath": f"/tenants/{tenant_id}/mappings/{target_alias}/_execute",
        "rawQueryString": "",
        "headers": {
            "content-type": "application/json",
            "x-forwarded-for": "127.0.0.1",
            "x-forwarded-port": "443",
            "x-forwarded-proto": "https",
            "accept": "*/*",
            "accept-encoding": "gzip, deflate",
            "host": "api.example.com"
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "api-id",
            "domainName": "api.example.com",
            "domainPrefix": "api",
            "http": {
                "method": "POST",
                "path": f"/tenants/{tenant_id}/mappings/{target_alias}/_execute",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "Custom/1.0"
            },
            "requestId": str(uuid.uuid4()),
            "routeKey": "POST /tenants/{tenant_id}/mappings/{target_alias}/_execute",
            "stage": "$default",
            "time": datetime.datetime.now().strftime("%d/%b/%Y:%H:%M:%S +0000"),
            "timeEpoch": int(datetime.datetime.now().timestamp() * 1000)
        },
        "isBase64Encoded": False,
        "body": json.dumps(schedule.get("target_input", {}))
    }

    result = scheduler.update_schedule(
        schedule_name=schedule_model.schedule_id,
        schedule_expression=schedule_model.schedule_expression,
        target_arn=os.environ.get("EXECUTION_API_LAMBDA_ARN"),
        target_input=target_input,
        description=schedule_model.description,
        timezone=schedule_model.timezone,
        start_date=schedule_model.start_date,
        end_date=schedule_model.end_date,
        state=schedule_model.state
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
    # Delete from EventBridge first
    result = scheduler.delete_schedule(schedule_name=schedule_id)

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