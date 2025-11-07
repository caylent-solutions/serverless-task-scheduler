from pydantic import BaseModel
from typing import Optional, Dict, Any


class Execution(BaseModel):
    tenant_id: str
    target_id: str
    schedule_id: Optional[str] = None
    execution_id: str
    timestamp: str
    status: str
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None