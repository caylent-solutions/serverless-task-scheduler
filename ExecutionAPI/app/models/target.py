from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator
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
    target_parameter_schema: Dict[str, Any] = Field(
        ...,
        description="JSON Schema defining the parameters required for execution",
        example={
            "type": "object",
            "required": ["param1", "param2"],
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "First parameter"
                },
                "param2": {
                    "type": "integer",
                    "description": "Second parameter"
                }
            }
        }
    )
    target_binary_link: Optional[str] = None


class TargetWithExecutionInfo(Target):
    """
    Extended target information including execution details for AI agents.
    This includes the execution endpoint and parameter schema.
    """
    execution_endpoint: str = Field(
        ...,
        description="The URL template to POST to for execution. Replace {tenant_id} with actual tenant ID",
        example="/tenants/my-tenant/targets/my-target/_execute"
    )
    execution_method: str = Field(
        default="POST",
        description="HTTP method for execution"
    )
    execution_requires_tenant_context: bool = Field(
        default=True,
        description="Whether tenant context is required for execution"
    )


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
