from typing import Dict, List, Optional, Any
from pydantic import BaseModel, field_validator
from app.validation import validate_url_safe_identifier


class TargetBase(BaseModel):
    target_id: str
    target_description: str

    @field_validator('target_id')
    @classmethod
    def validate_target_id_format(cls, v):
        """Ensure target_id is URL-safe (lowercase alphanumeric, underscores, hyphens)."""
        return validate_url_safe_identifier(v, "target_id")


class Target(TargetBase):
    target_arn: str
    target_parameter_schema: Dict[str, Any]
    target_binary_link: Optional[str] = None


class TargetList(BaseModel):
    targets: List[Target]


class TargetExecution(BaseModel):
    target_parameter_values: Dict[str, Any]
    synchronous_execution: bool = True
    execution_id: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None

class RouteChangedEvent(BaseModel):
    name: str
    description: str
    path: str
    parameters: Dict[str, Any]
