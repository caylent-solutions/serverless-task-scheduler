"""
UserMapping model - maps users to tenants for access control
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, timezone


class UserMapping(BaseModel):
    """
    Represents a mapping between a user and a tenant

    Attributes:
        user_id: Cognito user ID or email (primary key)
        tenant_id: Tenant identifier (sort key)
        create_date: When the mapping was created
        create_user: Who created the mapping
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "jeremy.yelle@caylent.com",
                "tenant_id": "acme-corp",
                "create_date": "2025-11-04T12:00:00Z",
                "create_user": "admin@caylent.com"
            }
        }
    )

    user_id: str = Field(..., description="Cognito user ID or email")
    tenant_id: str = Field(..., description="Tenant identifier")
    create_date: Optional[str] = Field(default_factory=lambda: datetime.now(datetime.timezone.utc).isoformat(), description="Creation timestamp")
    create_user: Optional[str] = Field(None, description="User who created this mapping")


class UserMappingCreate(BaseModel):
    """Request model for creating a user-tenant mapping"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "user@example.com",
                "tenant_id": "acme-corp"
            }
        }
    )

    user_id: str = Field(..., description="Cognito user ID or email")
    tenant_id: str = Field(..., description="Tenant identifier")


class UserMappingList(BaseModel):
    """Response model for listing user mappings"""
    mappings: list[UserMapping]
    count: int
