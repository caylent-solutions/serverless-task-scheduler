from typing import List, Optional
from pydantic import BaseModel, field_validator
from app.validation import validate_url_safe_identifier


class TenantBase(BaseModel):
    tenant_id: str
    tenant_name: str
    description: Optional[str] = None

    @field_validator('tenant_id')
    @classmethod
    def validate_tenant_id_format(cls, v):
        """Ensure tenant_id is URL-safe (lowercase alphanumeric, underscores, hyphens)."""
        return validate_url_safe_identifier(v, "tenant_id")


class Tenant(TenantBase):
    pass


class TenantList(BaseModel):
    tenants: List[Tenant]
