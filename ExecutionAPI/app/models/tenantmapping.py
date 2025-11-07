from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


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