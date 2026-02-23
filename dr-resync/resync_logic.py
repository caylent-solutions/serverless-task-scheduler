"""
DR Resync Manager

Core logic for resyncing EventBridge Scheduler schedules from DynamoDB.
Handles enable, disable, and validate modes with throttling.
"""

import json
import logging
import time
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys

# Add parent directory to path to import from api package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.app.awssdk.dynamodb import get_database_client
from api.app.awssdk.schedules import get_scheduler_client

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Throttling: 10 API calls per second = 100ms between calls
THROTTLE_DELAY = 0.1  # seconds


class ResyncManager:
    """Manages resyncing EventBridge schedules from DynamoDB during DR failover."""
    
    def __init__(self, tenant_id_filter: Optional[str] = None):
        """
        Initialize the resync manager.
        
        Args:
            tenant_id_filter: Optional filter to sync only specific tenant
        """
        self.db = get_database_client()
        self.scheduler = get_scheduler_client()
        self.tenant_id_filter = tenant_id_filter
        self.start_time = datetime.utcnow()
        
        # Get table names from environment
        self.schedules_table = os.environ.get('DYNAMODB_SCHEDULES_TABLE')
        self.tenant_mappings_table = os.environ.get('DYNAMODB_TENANT_TABLE')
        self.targets_table = os.environ.get('DYNAMODB_TABLE')
        
        logger.info(f"ResyncManager initialized: schedules_table={self.schedules_table}, "
                   f"targets_table={self.targets_table}")
    
    def enable_region(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Enable region by recreating EventBridge schedules from DynamoDB.
        
        Args:
            dry_run: If True, report what would be created without creating
            
        Returns:
            Dict with status, summary, errors, warnings
        """
        logger.info(f"Starting enable_region (dry_run={dry_run})")
        
        summary = {
            'total_schedules': 0,
            'processed': 0,
            'created': 0,
            'skipped': 0,
            'failed': 0,
            'missing_targets': 0,
            'missing_mappings': 0
        }
        errors = []
        warnings = []
        
        try:
            # Scan all schedules from DynamoDB
            schedules = self._scan_schedules()
            summary['total_schedules'] = len(schedules)
            logger.info(f"Found {len(schedules)} schedules to process")
            
            # Process each schedule
            for schedule in schedules:
                try:
                    result = self._process_schedule_enable(schedule, dry_run)
                    summary['processed'] += 1
                    
                    if result['action'] == 'created':
                        summary['created'] += 1
                    elif result['action'] == 'skipped':
                        summary['skipped'] += 1
                    elif result['action'] == 'error':
                        summary['failed'] += 1
                        if result['reason'] == 'missing_target':
                            summary['missing_targets'] += 1
                        elif result['reason'] == 'missing_mapping':
                            summary['missing_mappings'] += 1
                    
                    # Track errors and warnings
                    if 'error' in result:
                        errors.append({
                            'tenant_id': schedule.get('tenant_id'),
                            'schedule_id': schedule.get('schedule_id'),
                            'error': result['error']
                        })
                    if 'warning' in result:
                        warnings.append({
                            'tenant_id': schedule.get('tenant_id'),
                            'schedule_id': schedule.get('schedule_id'),
                            'warning': result['warning']
                        })
                    
                    # Throttle API calls
                    time.sleep(THROTTLE_DELAY)
                    
                except Exception as e:
                    logger.error(f"Unexpected error processing schedule {schedule.get('schedule_id')}: {str(e)}")
                    summary['processed'] += 1
                    summary['failed'] += 1
                    errors.append({
                        'tenant_id': schedule.get('tenant_id'),
                        'schedule_id': schedule.get('schedule_id'),
                        'error': str(e)
                    })
            
            # Determine overall status
            status = 'success' if summary['failed'] == 0 else ('partial' if summary['created'] > 0 else 'failure')
            
        except Exception as e:
            logger.exception(f"Fatal error in enable_region: {str(e)}")
            status = 'failure'
            errors.append({'fatal': str(e)})
        
        return {
            'status': status,
            'summary': summary,
            'errors': errors,
            'warnings': warnings,
            'duration_seconds': (datetime.utcnow() - self.start_time).total_seconds()
        }
    
    def disable_region(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Disable region by deleting EventBridge schedules.
        
        Args:
            dry_run: If True, report what would be deleted without deleting
            
        Returns:
            Dict with status, summary, errors, warnings
        """
        logger.info(f"Starting disable_region (dry_run={dry_run})")
        
        summary = {
            'total_schedules': 0,
            'processed': 0,
            'deleted': 0,
            'skipped': 0,
            'failed': 0
        }
        errors = []
        warnings = []
        
        try:
            # Scan all schedules from DynamoDB
            schedules = self._scan_schedules()
            summary['total_schedules'] = len(schedules)
            logger.info(f"Found {len(schedules)} schedules to delete")
            
            # Process each schedule
            for schedule in schedules:
                try:
                    result = self._process_schedule_disable(schedule, dry_run)
                    summary['processed'] += 1
                    
                    if result['action'] == 'deleted':
                        summary['deleted'] += 1
                    elif result['action'] == 'skipped':
                        summary['skipped'] += 1
                    elif result['action'] == 'error':
                        summary['failed'] += 1
                    
                    # Track errors
                    if 'error' in result:
                        errors.append({
                            'tenant_id': schedule.get('tenant_id'),
                            'schedule_id': schedule.get('schedule_id'),
                            'error': result['error']
                        })
                    
                    # Throttle API calls
                    time.sleep(THROTTLE_DELAY)
                    
                except Exception as e:
                    logger.error(f"Unexpected error deleting schedule {schedule.get('schedule_id')}: {str(e)}")
                    summary['processed'] += 1
                    summary['failed'] += 1
                    errors.append({
                        'tenant_id': schedule.get('tenant_id'),
                        'schedule_id': schedule.get('schedule_id'),
                        'error': str(e)
                    })
            
            # Determine overall status
            status = 'success' if summary['failed'] == 0 else ('partial' if summary['deleted'] > 0 else 'failure')
            
        except Exception as e:
            logger.exception(f"Fatal error in disable_region: {str(e)}")
            status = 'failure'
            errors.append({'fatal': str(e)})
        
        return {
            'status': status,
            'summary': summary,
            'errors': errors,
            'warnings': warnings,
            'duration_seconds': (datetime.utcnow() - self.start_time).total_seconds()
        }
    
    def validate_region(self) -> Dict[str, Any]:
        """
        Validate region configuration without making changes.
        Checks if schedules in DynamoDB have corresponding EventBridge schedules.
        
        Returns:
            Dict with status, summary, errors, warnings
        """
        logger.info("Starting validate_region")
        
        summary = {
            'total_schedules': 0,
            'valid': 0,
            'missing_in_eventbridge': 0,
            'invalid_configuration': 0
        }
        errors = []
        warnings = []
        
        try:
            # Scan all schedules from DynamoDB
            schedules = self._scan_schedules()
            summary['total_schedules'] = len(schedules)
            logger.info(f"Validating {len(schedules)} schedules")
            
            # Check each schedule
            for schedule in schedules:
                try:
                    tenant_id = schedule.get('tenant_id')
                    schedule_id = schedule.get('schedule_id')
                    target_alias = schedule.get('target_alias')
                    
                    # Build EventBridge schedule name
                    eb_schedule_name = f"sts-{tenant_id}-{target_alias}-{schedule_id}"
                    
                    # Check if schedule exists in EventBridge
                    try:
                        self.scheduler.get_schedule(eb_schedule_name)
                        summary['valid'] += 1
                        logger.debug(f"Schedule {eb_schedule_name} exists in EventBridge")
                    except self.scheduler.scheduler_client.exceptions.ResourceNotFoundException:
                        summary['missing_in_eventbridge'] += 1
                        warnings.append({
                            'tenant_id': tenant_id,
                            'schedule_id': schedule_id,
                            'warning': f'Schedule exists in DynamoDB but not in EventBridge: {eb_schedule_name}'
                        })
                    
                    # Throttle API calls
                    time.sleep(THROTTLE_DELAY)
                    
                except Exception as e:
                    logger.error(f"Error validating schedule {schedule_id}: {str(e)}")
                    summary['invalid_configuration'] += 1
                    errors.append({
                        'tenant_id': schedule.get('tenant_id'),
                        'schedule_id': schedule_id,
                        'error': str(e)
                    })
            
            # Determine status
            status = 'success' if summary['missing_in_eventbridge'] == 0 else 'partial'
            
        except Exception as e:
            logger.exception(f"Fatal error in validate_region: {str(e)}")
            status = 'failure'
            errors.append({'fatal': str(e)})
        
        return {
            'status': status,
            'summary': summary,
            'errors': errors,
            'warnings': warnings,
            'duration_seconds': (datetime.utcnow() - self.start_time).total_seconds()
        }
    
    def _scan_schedules(self) -> List[Dict[str, Any]]:
        """
        Scan all schedules from DynamoDB Schedules table.
        Optionally filter by tenant_id.
        
        Returns:
            List of schedule items
        """
        schedules = []
        
        # Use scan or query based on whether tenant_id is provided
        if self.tenant_id_filter:
            # Query specific tenant
            logger.info(f"Querying schedules for tenant: {self.tenant_id_filter}")
            response = self.db.query(
                table_name=self.schedules_table,
                key_condition_expression='tenant_id = :tid',
                expression_attribute_values={':tid': self.tenant_id_filter}
            )
            schedules = response.get('Items', [])
        else:
            # Scan all schedules
            logger.info("Scanning all schedules")
            response = self.db.scan(table_name=self.schedules_table)
            schedules = response.get('Items', [])
        
        logger.info(f"Found {len(schedules)} schedules")
        return schedules
    
    def _process_schedule_enable(self, schedule: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
        """
        Process a single schedule for enable mode.
        Creates EventBridge schedule if it doesn't exist and target is valid.
        
        Args:
            schedule: Schedule item from DynamoDB
            dry_run: If True, don't actually create the schedule
            
        Returns:
            Dict with action, reason, error/warning if applicable
        """
        tenant_id = schedule.get('tenant_id')
        schedule_id = schedule.get('schedule_id')
        target_alias = schedule.get('target_alias')
        schedule_expression = schedule.get('schedule_expression')
        state = schedule.get('state', 'ENABLED')
        
        # Lookup tenant mapping to get target_id
        mapping = self._get_tenant_mapping(tenant_id, target_alias)
        if not mapping:
            logger.warning(f"Tenant mapping not found: {tenant_id}/{target_alias}")
            return {'action': 'error', 'reason': 'missing_mapping', 'error': 'Tenant mapping not found'}
        
        target_id = mapping.get('target_id')
        
        # Lookup target to get ARN
        target = self._get_target(target_id)
        if not target:
            logger.warning(f"Target not found: {target_id}")
            return {'action': 'error', 'reason': 'missing_target', 'error': 'Target not found in regional Targets table'}
        
        target_arn = target.get('arn')
        
        # Build EventBridge schedule name
        eb_schedule_name = f"sts-{tenant_id}-{target_alias}-{schedule_id}"
        
        # Build target input (execution parameters)
        target_input = {
            'tenant_id': tenant_id,
            'schedule_id': schedule_id,
            'target_alias': target_alias,
            'payload': schedule.get('payload', {})
        }
        
        logger.info(f"Creating schedule: {eb_schedule_name}")
        
        if dry_run:
            logger.info(f"[DRY RUN] Would create schedule: {eb_schedule_name}")
            return {'action': 'created', 'dry_run': True}
        
        # Create the schedule
        result = self.scheduler.create_schedule(
            schedule_name=eb_schedule_name,
            schedule_expression=schedule_expression,
            target_arn=target_arn,
            target_input=target_input,
            state=state,
            description=schedule.get('description', ''),
            timezone=schedule.get('timezone', 'UTC')
        )
        
        if result.get('status') == 'SUCCESS':
            logger.info(f"Successfully created schedule: {eb_schedule_name}")
            return {'action': 'created'}
        elif result.get('status') == 'ERROR':
            if 'already exists' in result.get('error_message', '').lower():
                logger.info(f"Schedule already exists: {eb_schedule_name}")
                return {'action': 'skipped', 'warning': 'Schedule already exists'}
            else:
                logger.error(f"Failed to create schedule: {result.get('error_message')}")
                return {'action': 'error', 'error': result.get('error_message')}
        else:
            return {'action': 'error', 'error': 'Unknown error creating schedule'}
    
    def _process_schedule_disable(self, schedule: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
        """
        Process a single schedule for disable mode.
        Deletes EventBridge schedule if it exists.
        
        Args:
            schedule: Schedule item from DynamoDB
            dry_run: If True, don't actually delete the schedule
            
        Returns:
            Dict with action, error if applicable
        """
        tenant_id = schedule.get('tenant_id')
        schedule_id = schedule.get('schedule_id')
        target_alias = schedule.get('target_alias')
        
        # Build EventBridge schedule name
        eb_schedule_name = f"sts-{tenant_id}-{target_alias}-{schedule_id}"
        
        logger.info(f"Deleting schedule: {eb_schedule_name}")
        
        if dry_run:
            logger.info(f"[DRY RUN] Would delete schedule: {eb_schedule_name}")
            return {'action': 'deleted', 'dry_run': True}
        
        # Delete the schedule
        result = self.scheduler.delete_schedule(eb_schedule_name)
        
        if result.get('status') == 'SUCCESS':
            logger.info(f"Successfully deleted schedule: {eb_schedule_name}")
            return {'action': 'deleted'}
        elif result.get('status') == 'ERROR':
            if 'not found' in result.get('error_message', '').lower():
                logger.info(f"Schedule doesn't exist: {eb_schedule_name}")
                return {'action': 'skipped', 'warning': 'Schedule not found'}
            else:
                logger.error(f"Failed to delete schedule: {result.get('error_message')}")
                return {'action': 'error', 'error': result.get('error_message')}
        else:
            return {'action': 'error', 'error': 'Unknown error deleting schedule'}
    
    def _get_tenant_mapping(self, tenant_id: str, target_alias: str) -> Optional[Dict[str, Any]]:
        """
        Lookup tenant mapping from DynamoDB.
        
        Args:
            tenant_id: Tenant ID
            target_alias: Target alias
            
        Returns:
            Mapping item or None if not found
        """
        try:
            response = self.db.get_item(
                table_name=self.tenant_mappings_table,
                key={
                    'tenant_id': tenant_id,
                    'target_alias': target_alias
                }
            )
            return response.get('Item')
        except Exception as e:
            logger.error(f"Failed to get tenant mapping ({tenant_id}/{target_alias}): {str(e)}")
            return None
    
    def _get_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        """
        Lookup target from regional Targets table.
        
        Args:
            target_id: Target ID
            
        Returns:
            Target item or None if not found
        """
        try:
            response = self.db.get_item(
                table_name=self.targets_table,
                key={'target_id': target_id}
            )
            return response.get('Item')
        except Exception as e:
            logger.error(f"Failed to get target ({target_id}): {str(e)}")
            return None
