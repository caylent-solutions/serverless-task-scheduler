"""
EventBridge Scheduler client for managing AWS schedules.

This module provides functionality to create, update, and delete schedules
on AWS EventBridge Scheduler. It follows the same patterns as other AWS SDK
modules in this project.

Usage Examples:

1. Basic schedule creation:
    ```python
    from app.awssdk.schedules import get_scheduler_client
    
    scheduler = get_scheduler_client()
    
    result = scheduler.create_schedule(
        schedule_name="my-daily-task",
        schedule_expression="rate(1 day)",
        target_arn="arn:aws:lambda:us-east-1:123456789012:function:my-function",
        description="Daily task execution"
    )
    ```

2. Using Schedule model:
    ```python
    from app.models.schedule import Schedule
    from app.awssdk.schedules import get_scheduler_client
    
    schedule = Schedule(
        tenant_id="tenant-123",
        schedule_id="daily-cleanup",
        function_name="cleanup-function",
        schedule_expression="cron(0 2 * * ? *)",  # Daily at 2 AM
        target_arn="arn:aws:lambda:us-east-1:123456789012:function:cleanup",
        role_arn="arn:aws:iam::123456789012:role/SchedulerRole"
    )
    
    scheduler = get_scheduler_client()
    result = scheduler.create_schedule_from_model(schedule)
    ```

3. Schedule management:
    ```python
    # Update a schedule
    result = scheduler.update_schedule(
        schedule_name="my-daily-task",
        schedule_expression="rate(2 days)",
        state="DISABLED"
    )
    
    # Enable/disable schedules
    scheduler.enable_schedule("my-daily-task")
    scheduler.disable_schedule("my-daily-task")
    
    # Get schedule details
    schedule_info = scheduler.get_schedule("my-daily-task")
    schedule_status = scheduler.get_schedule_status("my-daily-task")
    
    # Delete a schedule
    result = scheduler.delete_schedule("my-daily-task")
    ```

4. Batch operations:
    ```python
    # Create multiple schedules
    schedules = [
        {
            "schedule_name": "task-1",
            "schedule_expression": "rate(1 hour)",
            "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:task1"
        },
        {
            "schedule_name": "task-2", 
            "schedule_expression": "cron(0 9 * * ? *)",
            "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:task2"
        }
    ]
    
    result = scheduler.bulk_create_schedules(schedules)
    
    # Delete multiple schedules
    schedule_names = ["task-1", "task-2"]
    result = scheduler.bulk_delete_schedules(schedule_names)
    ```

Environment Variables:
    - SCHEDULER_ROLE_ARN: IAM role ARN for EventBridge Scheduler (required)
    - SCHEDULER_GROUP_NAME: EventBridge Scheduler group name (default: 'default')

Required AWS Permissions:
    - scheduler:CreateSchedule
    - scheduler:UpdateSchedule  
    - scheduler:DeleteSchedule
    - scheduler:GetSchedule
    - scheduler:ListSchedules
    - iam:PassRole (for the scheduler role)
"""

import logging
import boto3
import os
import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from botocore.exceptions import ClientError

from . import get_session

# Configure logging
logger = logging.getLogger("app.awssdk.schedules")

# Singleton scheduler client instance
_scheduler_client = None


class EventBridgeScheduler:
    """Client for managing AWS EventBridge Scheduler schedules."""
    
    def __init__(self):
        """Initialize the EventBridge Scheduler client."""
        self.scheduler_client = get_session().client('scheduler')
        self.lambda_client = get_session().client('lambda')
        
        # Get configuration from environment
        self.role_arn = os.environ.get('SCHEDULER_ROLE_ARN')
        self.group_name = os.environ.get('SCHEDULER_GROUP_NAME', 'default')
        
        if not self.role_arn:
            logger.warning("SCHEDULER_ROLE_ARN not set. Schedule operations may fail.")
    
    def ensure_schedule_group_exists(self, group_name: Optional[str] = None) -> bool:
        """
        Ensure a schedule group exists, creating it if necessary.

        Args:
            group_name: Name of the group to check/create (defaults to configured group)

        Returns:
            True if group exists or was created successfully, False otherwise
        """
        target_group = group_name or self.group_name

        try:
            # Try to get the schedule group
            self.scheduler_client.get_schedule_group(Name=target_group)
            logger.info(f"Schedule group already exists: {target_group}")
            return True

        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                # Group doesn't exist, create it
                try:
                    logger.info(f"Creating schedule group: {target_group}")
                    self.scheduler_client.create_schedule_group(Name=target_group)
                    logger.info(f"Successfully created schedule group: {target_group}")
                    return True
                except ClientError as create_error:
                    logger.error(f"Failed to create schedule group {target_group}: {create_error}")
                    return False
            else:
                logger.error(f"Error checking schedule group {target_group}: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error checking schedule group {target_group}: {e}")
            return False

    def create_schedule(self,
                       schedule_name: str,
                       schedule_expression: str,
                       target_arn: str,
                       target_input: Optional[Dict[str, Any]] = None,
                       description: Optional[str] = None,
                       timezone: Optional[str] = None,
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None,
                       state: str = 'ENABLED',
                       tags: Optional[Dict[str, str]] = None,
                       group_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new schedule on AWS EventBridge Scheduler.

        Args:
            schedule_name: Unique name for the schedule
            schedule_expression: Cron or rate expression for the schedule
            target_arn: ARN of the target (Lambda function, SQS queue, etc.)
            target_input: Optional input payload for the target
            description: Optional description of the schedule
            timezone: Optional timezone for the schedule (defaults to UTC)
            start_date: Optional start date for the schedule
            end_date: Optional end date for the schedule
            state: Schedule state (ENABLED, DISABLED)
            tags: Optional tags for the schedule
            group_name: Optional custom group name (defaults to configured group)

        Returns:
            Dictionary with schedule creation result
        """
        try:
            # Use custom group name or default
            target_group = group_name or self.group_name
            logger.info(f"Creating schedule: {schedule_name} in group: {target_group}")

            # Ensure the schedule group exists before creating the schedule
            if not self.ensure_schedule_group_exists(target_group):
                return {
                    'status': 'ERROR',
                    'schedule_name': schedule_name,
                    'error_message': f'Failed to ensure schedule group {target_group} exists'
                }

            # Build the schedule configuration
            schedule_config = {
                'Name': schedule_name,
                'ScheduleExpression': schedule_expression,
                'FlexibleTimeWindow': {
                    'Mode': 'OFF'
                },
                'Target': {
                    'Arn': target_arn,
                    'RoleArn': self.role_arn
                },
                'State': state,
                'GroupName': target_group
            }
            
            # Add optional fields
            if description:
                schedule_config['Description'] = description
                
            if timezone:
                schedule_config['ScheduleExpressionTimezone'] = timezone
                
            if target_input:
                schedule_config['Target']['Input'] = json.dumps(target_input)
                
            if start_date:
                schedule_config['StartDate'] = start_date.isoformat()
                
            if end_date:
                schedule_config['EndDate'] = end_date.isoformat()
                
            if tags:
                schedule_config['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]
            
            # Create the schedule
            response = self.scheduler_client.create_schedule(**schedule_config)
            
            logger.info(f"Successfully created schedule: {schedule_name}")
            return {
                'status': 'SUCCESS',
                'schedule_name': schedule_name,
                'schedule_arn': response.get('ScheduleArn'),
                'message': 'Schedule created successfully'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to create schedule {schedule_name}: {error_message}")
            
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error creating schedule {schedule_name}: {str(e)}")
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_message': str(e)
            }
    
    def update_schedule(self,
                       schedule_name: str,
                       schedule_expression: Optional[str] = None,
                       target_arn: Optional[str] = None,
                       target_input: Optional[Dict[str, Any]] = None,
                       description: Optional[str] = None,
                       timezone: Optional[str] = None,
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None,
                       state: Optional[str] = None,
                       tags: Optional[Dict[str, str]] = None,
                       group_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Update an existing schedule on AWS EventBridge Scheduler.

        Args:
            schedule_name: Name of the schedule to update
            schedule_expression: New cron or rate expression (optional)
            target_arn: New target ARN (optional)
            target_input: New target input (optional)
            description: New description (optional)
            timezone: New timezone (optional)
            start_date: New start date (optional)
            end_date: New end date (optional)
            state: New state (optional)
            tags: New tags (optional)
            group_name: Optional custom group name (defaults to configured group)

        Returns:
            Dictionary with schedule update result
        """
        try:
            # Use custom group name or default
            target_group = group_name or self.group_name
            logger.info(f"Updating schedule: {schedule_name} in group: {target_group}")

            # Build the update configuration
            update_config = {
                'Name': schedule_name,
                'GroupName': target_group
            }
            
            # Add fields that are being updated
            if schedule_expression is not None:
                update_config['ScheduleExpression'] = schedule_expression
                
            if target_arn is not None:
                update_config['Target'] = {'Arn': target_arn, 'RoleArn': self.role_arn}
                if target_input is not None:
                    update_config['Target']['Input'] = json.dumps(target_input)
                    
            if description is not None:
                update_config['Description'] = description
                
            if timezone is not None:
                update_config['ScheduleExpressionTimezone'] = timezone
                
            if start_date is not None:
                update_config['StartDate'] = start_date.isoformat()
                
            if end_date is not None:
                update_config['EndDate'] = end_date.isoformat()
                
            if state is not None:
                update_config['State'] = state
                
            if tags is not None:
                update_config['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]
            
            # Update the schedule
            response = self.scheduler_client.update_schedule(**update_config)
            
            logger.info(f"Successfully updated schedule: {schedule_name}")
            return {
                'status': 'SUCCESS',
                'schedule_name': schedule_name,
                'schedule_arn': response.get('ScheduleArn'),
                'message': 'Schedule updated successfully'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to update schedule {schedule_name}: {error_message}")
            
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error updating schedule {schedule_name}: {str(e)}")
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_message': str(e)
            }
    
    def delete_schedule(self, schedule_name: str, group_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Delete a schedule from AWS EventBridge Scheduler.

        Args:
            schedule_name: Name of the schedule to delete
            group_name: Optional custom group name (defaults to configured group)

        Returns:
            Dictionary with schedule deletion result
        """
        try:
            # Use custom group name or default
            target_group = group_name or self.group_name
            logger.info(f"Deleting schedule: {schedule_name} from group: {target_group}")

            response = self.scheduler_client.delete_schedule(
                Name=schedule_name,
                GroupName=target_group
            )
            
            logger.info(f"Successfully deleted schedule: {schedule_name}")
            return {
                'status': 'SUCCESS',
                'schedule_name': schedule_name,
                'message': 'Schedule deleted successfully'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to delete schedule {schedule_name}: {error_message}")
            
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error deleting schedule {schedule_name}: {str(e)}")
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_message': str(e)
            }
    
    def get_schedule(self, schedule_name: str) -> Dict[str, Any]:
        """
        Get details of a specific schedule.
        
        Args:
            schedule_name: Name of the schedule to retrieve
            
        Returns:
            Dictionary with schedule details or error information
        """
        try:
            logger.info(f"Getting schedule: {schedule_name}")
            
            response = self.scheduler_client.get_schedule(
                Name=schedule_name,
                GroupName=self.group_name
            )
            
            logger.info(f"Successfully retrieved schedule: {schedule_name}")
            return {
                'status': 'SUCCESS',
                'schedule': response,
                'message': 'Schedule retrieved successfully'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to get schedule {schedule_name}: {error_message}")
            
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error getting schedule {schedule_name}: {str(e)}")
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_message': str(e)
            }
    
    def list_schedules(self, group_name: Optional[str] = None) -> Dict[str, Any]:
        """
        List all schedules in a group.
        
        Args:
            group_name: Name of the group to list schedules from (defaults to configured group)
            
        Returns:
            Dictionary with list of schedules or error information
        """
        try:
            target_group = group_name or self.group_name
            logger.info(f"Listing schedules in group: {target_group}")
            
            response = self.scheduler_client.list_schedules(
                GroupName=target_group
            )
            
            logger.info(f"Successfully listed schedules in group: {target_group}")
            return {
                'status': 'SUCCESS',
                'schedules': response.get('Schedules', []),
                'message': f'Found {len(response.get("Schedules", []))} schedules'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to list schedules: {error_message}")
            
            return {
                'status': 'ERROR',
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error listing schedules: {str(e)}")
            return {
                'status': 'ERROR',
                'error_message': str(e)
            }
    
    def enable_schedule(self, schedule_name: str) -> Dict[str, Any]:
        """
        Enable a schedule (set state to ENABLED).
        
        Args:
            schedule_name: Name of the schedule to enable
            
        Returns:
            Dictionary with enable result
        """
        return self.update_schedule(schedule_name, state='ENABLED')
    
    def disable_schedule(self, schedule_name: str) -> Dict[str, Any]:
        """
        Disable a schedule (set state to DISABLED).
        
        Args:
            schedule_name: Name of the schedule to disable
            
        Returns:
            Dictionary with disable result
        """
        return self.update_schedule(schedule_name, state='DISABLED')
    
    def validate_schedule_expression(self, expression: str) -> Dict[str, Any]:
        """
        Validate a schedule expression (cron or rate).
        
        Args:
            expression: The schedule expression to validate
            
        Returns:
            Dictionary with validation result
        """
        try:
            # Basic validation for cron expressions
            if expression.startswith('rate(') or expression.startswith('cron('):
                # These are valid EventBridge expressions
                return {
                    'status': 'SUCCESS',
                    'valid': True,
                    'message': 'Valid schedule expression'
                }
            else:
                return {
                    'status': 'ERROR',
                    'valid': False,
                    'message': 'Invalid schedule expression format. Must start with rate( or cron('
                }
        except Exception as e:
            return {
                'status': 'ERROR',
                'valid': False,
                'message': f'Error validating expression: {str(e)}'
            }
    
    def create_schedule_from_model(self, schedule_model) -> Dict[str, Any]:
        """
        Create a schedule from a Schedule model object.
        
        Args:
            schedule_model: A Schedule model instance
            
        Returns:
            Dictionary with schedule creation result
        """
        try:
            # Convert model to EventBridge config
            config = schedule_model.to_eventbridge_config()
            
            # Create the schedule using the config
            response = self.scheduler_client.create_schedule(**config)
            
            # Update the model with the EventBridge ARN
            schedule_model.eventbridge_arn = response.get('ScheduleArn')
            schedule_model.eventbridge_name = config['Name']
            
            logger.info(f"Successfully created schedule from model: {config['Name']}")
            return {
                'status': 'SUCCESS',
                'schedule_name': config['Name'],
                'schedule_arn': response.get('ScheduleArn'),
                'message': 'Schedule created successfully from model'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to create schedule from model: {error_message}")
            
            return {
                'status': 'ERROR',
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error creating schedule from model: {str(e)}")
            return {
                'status': 'ERROR',
                'error_message': str(e)
            }
    
    def update_schedule_from_model(self, schedule_model) -> Dict[str, Any]:
        """
        Update a schedule from a Schedule model object.
        
        Args:
            schedule_model: A Schedule model instance with updated values
            
        Returns:
            Dictionary with schedule update result
        """
        try:
            # Convert model to EventBridge config
            config = schedule_model.to_eventbridge_config()
            
            # Update the schedule using the config
            response = self.scheduler_client.update_schedule(**config)
            
            logger.info(f"Successfully updated schedule from model: {config['Name']}")
            return {
                'status': 'SUCCESS',
                'schedule_name': config['Name'],
                'schedule_arn': response.get('ScheduleArn'),
                'message': 'Schedule updated successfully from model'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to update schedule from model: {error_message}")
            
            return {
                'status': 'ERROR',
                'error_code': error_code,
                'error_message': error_message
            }
        except Exception as e:
            logger.error(f"Unexpected error updating schedule from model: {str(e)}")
            return {
                'status': 'ERROR',
                'error_message': str(e)
            }
    
    def get_schedule_status(self, schedule_name: str) -> Dict[str, Any]:
        """
        Get the current status of a schedule.
        
        Args:
            schedule_name: Name of the schedule to check
            
        Returns:
            Dictionary with schedule status information
        """
        try:
            response = self.get_schedule(schedule_name)
            
            if response['status'] == 'SUCCESS':
                schedule_data = response['schedule']
                return {
                    'status': 'SUCCESS',
                    'schedule_name': schedule_name,
                    'state': schedule_data.get('State'),
                    'last_modified': schedule_data.get('LastModifiedDate'),
                    'creation_date': schedule_data.get('CreationDate'),
                    'message': 'Schedule status retrieved successfully'
                }
            else:
                return response
                
        except Exception as e:
            logger.error(f"Unexpected error getting schedule status: {str(e)}")
            return {
                'status': 'ERROR',
                'schedule_name': schedule_name,
                'error_message': str(e)
            }
    
    def bulk_create_schedules(self, schedules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create multiple schedules in batch.
        
        Args:
            schedules: List of schedule configurations
            
        Returns:
            Dictionary with batch creation results
        """
        results = {
            'status': 'SUCCESS',
            'total_schedules': len(schedules),
            'successful': 0,
            'failed': 0,
            'results': []
        }
        
        for schedule_config in schedules:
            try:
                result = self.create_schedule(**schedule_config)
                results['results'].append(result)
                
                if result['status'] == 'SUCCESS':
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                    
            except Exception as e:
                error_result = {
                    'status': 'ERROR',
                    'schedule_name': schedule_config.get('schedule_name', 'unknown'),
                    'error_message': str(e)
                }
                results['results'].append(error_result)
                results['failed'] += 1
        
        if results['failed'] > 0:
            results['status'] = 'PARTIAL_SUCCESS'
            
        return results
    
    def bulk_delete_schedules(self, schedule_names: List[str]) -> Dict[str, Any]:
        """
        Delete multiple schedules in batch.
        
        Args:
            schedule_names: List of schedule names to delete
            
        Returns:
            Dictionary with batch deletion results
        """
        results = {
            'status': 'SUCCESS',
            'total_schedules': len(schedule_names),
            'successful': 0,
            'failed': 0,
            'results': []
        }
        
        for schedule_name in schedule_names:
            try:
                result = self.delete_schedule(schedule_name)
                results['results'].append(result)
                
                if result['status'] == 'SUCCESS':
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                    
            except Exception as e:
                error_result = {
                    'status': 'ERROR',
                    'schedule_name': schedule_name,
                    'error_message': str(e)
                }
                results['results'].append(error_result)
                results['failed'] += 1
        
        if results['failed'] > 0:
            results['status'] = 'PARTIAL_SUCCESS'
            
        return results


def get_scheduler_client() -> EventBridgeScheduler:
    """
    Get the EventBridge Scheduler client instance.
    Returns a singleton instance of the scheduler client.
    """
    global _scheduler_client
    
    if _scheduler_client is None:
        _scheduler_client = EventBridgeScheduler()
    
    return _scheduler_client
