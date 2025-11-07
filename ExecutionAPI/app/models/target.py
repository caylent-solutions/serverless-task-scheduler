from typing import Dict, List, Optional, Any
from pydantic import BaseModel


class TargetBase(BaseModel):
    target_id: str
    target_description: str


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
