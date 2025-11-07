from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime


class Schedule(BaseModel):
    """Represents a scheduled target execution for a tenant."""
    
    # Core identifiers
    tenant_id: str = Field(..., description="Tenant identifier")
    schedule_id: str = Field(..., description="Unique schedule identifier within tenant")
    target_alias: str = Field(..., description="Tenant's alias for the target to execute")
    
    # Schedule configuration
    schedule_expression: str = Field(..., description="Cron or rate expression for the schedule")
    # Optional configuration
    description: Optional[str] = Field(None, description="Description of the schedule")
    timezone: Optional[str] = Field(None, description="Timezone for the schedule (defaults to UTC)")
    start_date: Optional[datetime] = Field(None, description="Start date for the schedule")
    end_date: Optional[datetime] = Field(None, description="End date for the schedule")
    state: str = Field("ENABLED", description="Schedule state (ENABLED, DISABLED)")
    
    @validator("schedule_expression")
    def validate_schedule_expression(cls, v):
        """Validate that the schedule expression is properly formatted."""
        if not v.startswith(('rate(', 'cron(', 'at(')):
            raise ValueError("Schedule expression must start with 'rate(' or 'cron(' or 'at('")
        return v
    
    @validator("state")
    def validate_state(cls, v):
        """Validate the state value."""
        if v not in ("ENABLED", "DISABLED"):
            raise ValueError("State must be either 'ENABLED' or 'DISABLED'")
        return v
    
    def to_eventbridge_config(self) -> Dict[str, Any]:
        """Convert to EventBridge Scheduler configuration."""
        config = {
            'Name': self.eventbridge_name or f"{self.tenant_id}-{self.schedule_id}",
            'ScheduleExpression': self.schedule_expression,
            'Target': {
                'Input': self.target_input
            },
            'State': self.state,
            'FlexibleTimeWindow': {
                'Mode': 'OFF'
            },
            'GroupName': 'default'  # Could be made configurable
        }
        
        if self.description:
            config['Description'] = self.description
            
        if self.timezone:
            config['ScheduleExpressionTimezone'] = self.timezone
            
        if self.target_input:
            config['Target']['Input'] = self.target_input
            
        if self.start_date:
            config['StartDate'] = self.start_date.isoformat()
            
        if self.end_date:
            config['EndDate'] = self.end_date.isoformat()
            
        return config
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format with proper datetime serialization."""
        item = {
            'tenant_id': self.tenant_id,
            'schedule_id': self.schedule_id,
            'target_alias': self.target_alias,
            'schedule_expression': self.schedule_expression,
            'description': self.description,
            'timezone': self.timezone,
            'state': self.state
        }
        
        # Convert datetime objects to ISO strings for DynamoDB
        if self.start_date:
            item['start_date'] = self.start_date.isoformat()
        
        if self.end_date:
            item['end_date'] = self.end_date.isoformat()
            
        return item
    
