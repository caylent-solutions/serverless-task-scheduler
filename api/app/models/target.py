from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from app.validation import validate_url_safe_identifier

ECS_CONFIG_REQUIRED_KEYS = {'cluster', 'task_definition', 'launch_type', 'container_name', 'network_configuration'}


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
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="ECS target configuration (cluster, task_definition, launch_type, container_name, network_configuration)"
    )

    @model_validator(mode='after')
    def validate_ecs_config(self) -> 'Target':
        if ':ecs:' not in self.target_arn:
            return self
        if not self.config:
            raise ValueError("config is required for ECS targets")
        missing = ECS_CONFIG_REQUIRED_KEYS - self.config.keys()
        if missing:
            raise ValueError(f"ECS config missing required keys: {sorted(missing)}")
        return self


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
