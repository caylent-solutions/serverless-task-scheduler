"""
Authorization middleware and utilities for the application.
Provides flexible authorization checks that can be extended for:
- Admin user checks (current implementation)
- DynamoDB group lookups (future)
- Cognito attribute-based access (future)
"""
import os
import logging
from fastapi import HTTPException, Depends
from .routers.user import get_current_user

logger = logging.getLogger("app.authorization")

# Constants
COGNITO_USERNAME_KEY = 'cognito:username'


class AuthorizationError(HTTPException):
    """Custom exception for authorization failures"""
    def __init__(self, detail: str = "Access denied"):
        super().__init__(status_code=403, detail=detail)


def get_admin_email() -> str:
    """Get the admin email from environment configuration"""
    return os.environ.get('ADMIN_USER_EMAIL', '')


def is_admin(user: dict) -> bool:
    """
    Check if a user is an admin by checking their membership in the 'admin' tenant.

    Args:
        user: User dict from get_current_user

    Returns:
        True if user is admin (member of 'admin' tenant), False otherwise
    """
    try:
        from .awssdk.dynamodb import get_database_client
        user_email = user.get('email', user.get(COGNITO_USERNAME_KEY, ''))

        db = get_database_client()
        tenants = db.get_user_tenants(user_email)
        is_admin_user = 'admin' in tenants

        if is_admin_user:
            logger.debug(f"User {user_email} identified as admin (member of admin tenant)")

        return is_admin_user
    except Exception as e:
        logger.error(f"Error checking admin status for user: {e}")
        # Fallback to environment variable check in case of database error
        admin_email = get_admin_email()
        user_email = user.get('email', user.get(COGNITO_USERNAME_KEY, ''))
        return user_email == admin_email


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency that requires the user to be an admin.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: dict = Depends(require_admin)):
            # This code only runs if user is admin
            pass

    Args:
        current_user: Current authenticated user from get_current_user

    Returns:
        The user dict if they are admin

    Raises:
        AuthorizationError: If user is not an admin
    """
    if not is_admin(current_user):
        user_email = current_user.get('email', current_user.get(COGNITO_USERNAME_KEY, 'unknown'))
        logger.warning(f"Access denied for non-admin user: {user_email}")
        raise AuthorizationError("Admin access required")

    return current_user


def require_group(group_name: str):
    """
    Dependency factory that requires the user to be in a specific group.

    Future implementation for DynamoDB group lookups.

    Usage:
        @router.get("/managers-only")
        async def manager_endpoint(user: dict = Depends(require_group("managers"))):
            pass

    Args:
        group_name: Name of the required group

    Returns:
        A dependency function that checks group membership
    """
    async def check_group(current_user: dict = Depends(get_current_user)) -> dict:
        # TODO: Implement DynamoDB group lookup
        # groups = db_client.get_user_groups(current_user['sub'])
        # if group_name not in groups:
        #     raise AuthorizationError(f"Group '{group_name}' required")
        raise NotImplementedError("Group-based authorization not yet implemented")

    return check_group


async def require_tenant_access(
    tenant_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Dependency that requires the user to have access to a specific tenant.

    Usage:
        @router.get("/tenants/{tenant_id}/data")
        async def get_tenant_data(
            tenant_id: str,
            user: dict = Depends(require_tenant_access)
        ):
            pass

    Args:
        tenant_id: The tenant ID from the path parameter
        current_user: Current authenticated user from get_current_user

    Returns:
        The user dict if they have access to the tenant

    Raises:
        AuthorizationError: If user doesn't have access to the tenant
    """
    # Admins have access to all tenants
    if is_admin(current_user):
        return current_user

    # Check if user has access to the specific tenant
    try:
        from .awssdk.dynamodb import get_database_client
        user_email = current_user.get('email', current_user.get(COGNITO_USERNAME_KEY, ''))

        db = get_database_client()
        user_tenants = db.get_user_tenants(user_email)

        if tenant_id not in user_tenants:
            logger.warning(f"Access denied: User {user_email} attempted to access tenant {tenant_id}")
            raise AuthorizationError(f"Access to tenant '{tenant_id}' denied")

        logger.debug(f"User {user_email} granted access to tenant {tenant_id}")
        return current_user

    except AuthorizationError:
        # Re-raise authorization errors
        raise
    except Exception as e:
        logger.error(f"Error checking tenant access for user: {e}")
        raise AuthorizationError(f"Unable to verify access to tenant '{tenant_id}'")
