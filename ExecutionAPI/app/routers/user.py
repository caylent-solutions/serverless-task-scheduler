"""
User info router - provides authenticated user information and user-tenant access management
"""
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import logging
import os
from ..awssdk.dynamodb import get_database_client
from ..awssdk.cognito import get_cognito_client
from ..models.usermapping import UserMapping, UserMappingCreate, UserMappingList

logger = logging.getLogger("app")

router = APIRouter(
    prefix="/user",
    tags=["user"]
)


class UserInfo(BaseModel):
    email: str
    username: str
    isAdmin: bool
    tenants: List[str]


class UserDetail(BaseModel):
    """Detailed user information combining Cognito and DynamoDB data"""
    user_id: str
    email: str
    full_name: Optional[str] = None
    tenants: List[str] = []
    user_status: Optional[str] = None
    enabled: bool = True
    created_at: Optional[str] = None
    in_cognito: bool = True
    in_database: bool = False


class UserDetailList(BaseModel):
    """Response model for listing users"""
    users: List[UserDetail]
    count: int


class InviteUserRequest(BaseModel):
    """Request model for inviting a new user"""
    email: str
    tenants: List[str] = []


class InviteUserResponse(BaseModel):
    """Response model for user invitation"""
    message: str
    user_id: str
    email: str
    tenants: List[str]


class SyncIdPResponse(BaseModel):
    """Response model for IdP sync operation"""
    message: str
    removed_users: List[str]
    removed_count: int


def get_admin_user_email() -> str:
    """Get the admin user email from environment variable"""
    return os.environ.get('ADMIN_USER_EMAIL', 'jeremy.yelle@caylent.com')


def is_admin(user_email: str) -> bool:
    """Check if a user is an admin by checking their membership in the 'admin' tenant"""
    try:
        db = get_database_client()
        tenants = db.get_user_tenants(user_email)
        return 'admin' in tenants
    except Exception as e:
        logger.error(f"Error checking admin status for {user_email}: {e}")
        # Fallback to environment variable check
        admin_email = get_admin_user_email()
        return user_email == admin_email


async def get_current_user(request: Request) -> dict:
    """
    Dependency to get the current authenticated user
    
    Returns:
        dict: User claims from Cognito token
    """
    user = getattr(request.state, 'user', None)
    
    if not user:
        # For development/testing, return a default admin user
        logger.warning("No user found in request state, returning default admin user")
        return {
            'email': get_admin_user_email(),
            'cognito:username': 'admin'
        }
    
    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency to require admin access
    
    Raises:
        HTTPException: If user is not admin
    """
    email = current_user.get('email', '')
    if not is_admin(email):
        logger.warning(f"Access denied for non-admin user: {email}")
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/info", response_model=UserInfo)
async def get_user_info(current_user: dict = Depends(get_current_user)):
    """
    Get authenticated user information
    
    Returns user details including admin status and accessible tenants
    """
    try:
        # Extract email and username from Cognito claims
        email = current_user.get('email', current_user.get('cognito:username', 'unknown'))
        username = current_user.get('cognito:username', email)

        # Get user's accessible tenants from database
        db = get_database_client()
        tenants = db.get_user_tenants(email)

        # Check if user is admin (member of 'admin' tenant)
        user_is_admin = 'admin' in tenants

        return UserInfo(
            email=email,
            username=username,
            isAdmin=user_is_admin,
            tenants=tenants if tenants else []
        )
        
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving user information")


@router.get("s/{user_id}/tenants", response_model=UserMappingList)
async def list_user_tenants(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """
    List all tenants accessible to a specific user (Admin only)

    Args:
        user_id: User ID or email
        current_user: Current authenticated user (must be admin)

    Returns:
        List of tenant mappings for the user
    """
    try:
        db = get_database_client()
        tenants = db.get_user_tenants(user_id)

        # Convert tenant list to UserMapping objects
        mappings = [
            UserMapping(user_id=user_id, tenant_id=tenant_id)
            for tenant_id in tenants
        ]

        return UserMappingList(
            mappings=mappings,
            count=len(mappings)
        )

    except Exception as e:
        logger.error(f"Error listing user tenants: {e}")
        raise HTTPException(status_code=500, detail="Error listing user tenants")


@router.post("s/{user_id}/tenants/{tenant_id}", response_model=UserMapping, status_code=201)
async def grant_user_tenant_access(
    user_id: str,
    tenant_id: str,
    current_user: dict = Depends(require_admin)
):
    """
    Grant a user access to a tenant (Admin only)

    Args:
        user_id: User ID or email
        tenant_id: Tenant ID
        current_user: Current authenticated user (must be admin)

    Returns:
        Created UserMapping
    """
    try:
        db = get_database_client()
        admin_email = current_user.get('email', get_admin_user_email())

        new_mapping = db.create_user_mapping(
            user_id=user_id,
            tenant_id=tenant_id,
            create_user=admin_email
        )

        return new_mapping

    except Exception as e:
        logger.error(f"Error granting user tenant access: {e}")
        raise HTTPException(status_code=500, detail="Error granting user tenant access")


@router.delete("s/{user_id}/tenants/{tenant_id}", status_code=204)
async def revoke_user_tenant_access(
    user_id: str,
    tenant_id: str,
    current_user: dict = Depends(require_admin)
):
    """
    Revoke a user's access to a tenant (Admin only)

    Args:
        user_id: User ID or email
        tenant_id: Tenant ID
        current_user: Current authenticated user (must be admin)
    """
    try:
        db = get_database_client()
        success = db.delete_user_mapping(user_id, tenant_id)

        if not success:
            raise HTTPException(status_code=404, detail="User tenant access not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking user tenant access: {e}")
        raise HTTPException(status_code=500, detail="Error revoking user tenant access")


@router.get("s", response_model=UserMappingList)
async def list_all_user_tenant_access(current_user: dict = Depends(require_admin)):
    """
    List all user-tenant access relationships (Admin only)

    Args:
        current_user: Current authenticated user (must be admin)

    Returns:
        List of all user-tenant access relationships
    """
    try:
        db = get_database_client()
        mappings = db.get_all_user_mappings()

        return UserMappingList(
            mappings=mappings,
            count=len(mappings)
        )

    except Exception as e:
        logger.error(f"Error listing user-tenant access: {e}")
        raise HTTPException(status_code=500, detail="Error listing user-tenant access")


@router.get("/management", response_model=UserDetailList)
async def list_all_users(current_user: dict = Depends(require_admin)):
    """
    List all users merged from Cognito and DynamoDB (Admin only)

    This endpoint combines users from:
    - Cognito User Pool (all registered users)
    - DynamoDB UserMappings table (users with tenant assignments)

    Users with tenant assignments are listed first, followed by Cognito-only users.

    Args:
        current_user: Current authenticated user (must be admin)

    Returns:
        Combined list of all users with their tenant assignments
    """
    try:
        db = get_database_client()
        cognito = get_cognito_client()

        # Get all user-tenant mappings from DynamoDB
        all_mappings = db.get_all_user_mappings()

        # Group mappings by user_id
        user_tenants_map = {}
        for mapping in all_mappings:
            user_id = mapping.user_id
            if user_id not in user_tenants_map:
                user_tenants_map[user_id] = []
            user_tenants_map[user_id].append(mapping.tenant_id)

        # Get all users from Cognito
        cognito_users = []
        if cognito:
            cognito_users = cognito.list_users(limit=1000)

        # Create a set of user IDs we've seen
        seen_users = set()
        result_users = []

        # First, add users that have tenant mappings (from DynamoDB)
        for user_id, tenants in user_tenants_map.items():
            seen_users.add(user_id)

            # Try to find this user in Cognito for additional details
            cognito_user = None
            for cu in cognito_users:
                if cu['user_id'] == user_id or cu['email'] == user_id:
                    cognito_user = cu
                    break

            if cognito_user:
                result_users.append(UserDetail(
                    user_id=user_id,
                    email=cognito_user.get('email', user_id),
                    full_name=cognito_user.get('full_name', ''),
                    tenants=sorted(tenants),
                    user_status=cognito_user.get('user_status'),
                    enabled=cognito_user.get('enabled', True),
                    created_at=cognito_user.get('created_at'),
                    in_cognito=True,
                    in_database=True
                ))
            else:
                # User is in database but not in Cognito (shouldn't happen often)
                result_users.append(UserDetail(
                    user_id=user_id,
                    email=user_id,
                    full_name='',
                    tenants=sorted(tenants),
                    in_cognito=False,
                    in_database=True
                ))

        # Then, add users from Cognito that don't have tenant mappings yet
        for cognito_user in cognito_users:
            user_id = cognito_user['user_id']
            email = cognito_user.get('email', user_id)

            # Check both user_id and email as they might be used interchangeably
            if user_id not in seen_users and email not in seen_users:
                result_users.append(UserDetail(
                    user_id=email,  # Use email as primary identifier
                    email=email,
                    full_name=cognito_user.get('full_name', ''),
                    tenants=[],
                    user_status=cognito_user.get('user_status'),
                    enabled=cognito_user.get('enabled', True),
                    created_at=cognito_user.get('created_at'),
                    in_cognito=True,
                    in_database=False
                ))

        return UserDetailList(
            users=result_users,
            count=len(result_users)
        )

    except Exception as e:
        logger.error(f"Error listing all users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing all users: {str(e)}")


@router.put("/management/{user_id}", response_model=UserDetail)
async def update_user_tenants(
    user_id: str,
    tenants: List[str],
    current_user: dict = Depends(require_admin)
):
    """
    Update a user's tenant assignments (Admin only)

    This will replace all existing tenant assignments for the user.

    Args:
        user_id: User ID or email
        tenants: List of tenant IDs to assign to the user
        current_user: Current authenticated user (must be admin)

    Returns:
        Updated user details
    """
    try:
        db = get_database_client()
        admin_email = current_user.get('email', get_admin_user_email())

        # Get existing tenant mappings for this user
        existing_tenants = db.get_user_tenants(user_id)

        # Calculate tenants to add and remove
        tenants_to_add = set(tenants) - set(existing_tenants)
        tenants_to_remove = set(existing_tenants) - set(tenants)

        # Remove old mappings
        for tenant_id in tenants_to_remove:
            db.delete_user_mapping(user_id, tenant_id)

        # Add new mappings
        for tenant_id in tenants_to_add:
            db.create_user_mapping(
                user_id=user_id,
                tenant_id=tenant_id,
                create_user=admin_email
            )

        # Get updated user details
        cognito = get_cognito_client()
        cognito_user = None
        if cognito:
            cognito_user = cognito.get_user(user_id)

        if cognito_user:
            return UserDetail(
                user_id=user_id,
                email=cognito_user.get('email', user_id),
                full_name=cognito_user.get('full_name', ''),
                tenants=sorted(tenants),
                user_status=cognito_user.get('user_status'),
                enabled=cognito_user.get('enabled', True),
                created_at=cognito_user.get('created_at'),
                in_cognito=True,
                in_database=len(tenants) > 0
            )
        else:
            return UserDetail(
                user_id=user_id,
                email=user_id,
                full_name='',
                tenants=sorted(tenants),
                in_cognito=False,
                in_database=len(tenants) > 0
            )

    except Exception as e:
        logger.error(f"Error updating user tenants: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating user tenants: {str(e)}")


@router.delete("/management/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    delete_from_cognito: bool = False,
    current_user: dict = Depends(require_admin)
):
    """
    Delete a user and all their tenant assignments (Admin only)

    This will:
    - Remove all tenant mappings from DynamoDB
    - Optionally delete the user from Cognito (if delete_from_cognito=true)

    Args:
        user_id: User ID or email
        delete_from_cognito: Whether to also delete from Cognito User Pool
        current_user: Current authenticated user (must be admin)
    """
    try:
        db = get_database_client()
        cognito = get_cognito_client()

        # Get all tenant mappings for this user
        existing_tenants = db.get_user_tenants(user_id)

        # Delete all tenant mappings from DynamoDB
        for tenant_id in existing_tenants:
            success = db.delete_user_mapping(user_id, tenant_id)
            if not success:
                logger.warning(f"Failed to delete mapping {user_id}:{tenant_id}")

        # Delete from Cognito if requested
        if delete_from_cognito:
            if cognito:
                success = cognito.delete_user(user_id)
                if not success:
                    logger.error(f"Failed to delete user from Cognito: {user_id}")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to delete user from Cognito"
                    )
            else:
                logger.warning("Cognito client not available, cannot delete user from Cognito")

        logger.info(f"Successfully deleted user {user_id} (Cognito: {delete_from_cognito})")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")


@router.post("/management/invite", response_model=InviteUserResponse, status_code=201)
async def invite_user(
    invite_request: InviteUserRequest,
    current_user: dict = Depends(require_admin)
):
    """
    Invite a new user by creating their Cognito account and assigning tenants (Admin only)

    This will:
    1. Create a new user in Cognito with a temporary password
    2. Trigger a password reset email (user receives verification code)
    3. Assign the user to the specified tenants in DynamoDB
    4. User should visit the login page, click "Forgot Password", and use the code from their email

    Args:
        invite_request: Email and list of tenant IDs to assign
        current_user: Current authenticated user (must be admin)

    Returns:
        Details about the invited user and instructions
    """
    try:
        db = get_database_client()
        cognito = get_cognito_client()
        admin_email = current_user.get('email', get_admin_user_email())

        if not cognito:
            raise HTTPException(status_code=500, detail="Cognito not configured")

        # Create user in Cognito and trigger password reset email
        result = cognito.create_user(
            email=invite_request.email,
            send_invite=True  # This triggers the forgot_password flow
        )

        if result['status'] != 'SUCCESS':
            raise HTTPException(
                status_code=400,
                detail=result.get('error', 'Failed to create user')
            )

        user_id = result['user_id']
        message = result['message']

        # Assign tenants to the user in DynamoDB
        for tenant_id in invite_request.tenants:
            try:
                db.create_user_mapping(
                    user_id=invite_request.email,
                    tenant_id=tenant_id,
                    create_user=admin_email
                )
            except Exception as e:
                logger.warning(f"Failed to assign tenant {tenant_id} to user {invite_request.email}: {e}")

        logger.info(f"User {invite_request.email} invited with {len(invite_request.tenants)} tenant(s)")

        return InviteUserResponse(
            message=message,
            user_id=user_id,
            email=invite_request.email,
            tenants=invite_request.tenants
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inviting user: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error inviting user: {str(e)}")


@router.post("/management/sync", response_model=SyncIdPResponse)
async def sync_idp_users(current_user: dict = Depends(require_admin)):
    """
    Sync user mappings with Cognito IdP by removing orphaned users (Admin only)

    This will:
    1. Get all user mappings from DynamoDB
    2. Get all users from Cognito User Pool
    3. Remove any user mappings where the user doesn't exist in Cognito

    This helps clean up orphaned user-tenant mappings when users are deleted
    from Cognito but their mappings remain in the database.

    Args:
        current_user: Current authenticated user (must be admin)

    Returns:
        Details about the sync operation including removed users
    """
    try:
        db = get_database_client()
        cognito = get_cognito_client()

        if not cognito:
            raise HTTPException(status_code=500, detail="Cognito not configured")

        # Get all user mappings from DynamoDB
        all_mappings = db.get_all_user_mappings()

        # Get unique user IDs from mappings
        db_user_ids = set(mapping.user_id for mapping in all_mappings)

        logger.info(f"Found {len(db_user_ids)} unique users in DynamoDB")

        # Get all users from Cognito
        cognito_users = cognito.list_users(limit=1000)
        cognito_user_ids = set()

        for user in cognito_users:
            # Add both the username and email to the set
            # since user_id could be either
            cognito_user_ids.add(user['user_id'])
            if user.get('email'):
                cognito_user_ids.add(user['email'])

        logger.info(f"Found {len(cognito_users)} users in Cognito")

        # Find users in DB but not in Cognito (orphaned users)
        orphaned_users = db_user_ids - cognito_user_ids

        logger.info(f"Found {len(orphaned_users)} orphaned users to remove")

        # Remove all mappings for orphaned users
        removed_users = []
        for user_id in orphaned_users:
            # Get all tenants for this user
            user_tenants = db.get_user_tenants(user_id)

            # Delete all mappings for this user
            for tenant_id in user_tenants:
                success = db.delete_user_mapping(user_id, tenant_id)
                if success:
                    logger.info(f"Removed mapping: {user_id} -> {tenant_id}")

            if user_tenants:
                removed_users.append(user_id)

        message = f"Sync completed. Removed {len(removed_users)} orphaned user(s) from user-tenant mappings."
        if len(removed_users) == 0:
            message = "Sync completed. No orphaned users found - all user mappings are in sync with Cognito."

        logger.info(f"Sync completed: removed {len(removed_users)} orphaned users")

        return SyncIdPResponse(
            message=message,
            removed_users=sorted(removed_users),
            removed_count=len(removed_users)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing IdP users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error syncing IdP users: {str(e)}")
