from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any
from datetime import datetime
from app.validation import validate_url_safe_identifier


class TenantMapping(BaseModel):
    tenant_id: str                           # Unique identifier for the tenant
    target_alias: str                        # Tenant's alias for the target (compound key)
    target_id: str                           # Unique identifier for the target
    description: str                         # Tenant Description of the target / Business Logic
    authorized_groups: list[str] = []        # List of groups authorized to access the target
    environment_variables: Optional[Dict[str, str]] = None  # Environment variables for execution
    default_payload: Optional[Dict[str, Any]] = None        # Default payload for target execution
    last_update_user: Optional[str] = None   # User who last updated the mapping
    last_update_date: Optional[str] = None   # Timestamp of last update

    @field_validator('tenant_id')
    @classmethod
    def validate_tenant_id_format(cls, v):
        """Ensure tenant_id is URL-safe (lowercase alphanumeric, underscores, hyphens)."""
        return validate_url_safe_identifier(v, "tenant_id")

    @field_validator('target_alias')
    @classmethod
    def validate_target_alias_format(cls, v):
        """Ensure target_alias is URL-safe (lowercase alphanumeric, underscores, hyphens)."""
        return validate_url_safe_identifier(v, "target_alias")

    @field_validator('target_id')
    @classmethod
    def validate_target_id_format(cls, v):
        """Ensure target_id is URL-safe (lowercase alphanumeric, underscores, hyphens)."""
        return validate_url_safe_identifier(v, "target_id")