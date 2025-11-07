from typing import List, Optional
from pydantic import BaseModel


class TenantBase(BaseModel):
    tenant_id: str
    tenant_name: str
    description: Optional[str] = None


class Tenant(TenantBase):
    pass


class TenantList(BaseModel):
    tenants: List[Tenant]
