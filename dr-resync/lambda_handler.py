"""
DR Resync Lambda Handler

Resyncs EventBridge Scheduler schedules from DynamoDB Global Tables during
disaster recovery failover. Reads all schedules from DynamoDB and recreates
them in the current region's EventBridge Scheduler.

Input Event:
{
    "mode": "enable|disable|validate",
    "dry_run": false,
    "tenant_id": null  # Optional: filter to specific tenant
}

Output:
{
    "status": "success|partial|failure",
    "mode": "enable|disable|validate",
    "region": "us-east-1",
    "summary": {...},
    "errors": [...]
}
"""

import json
import logging
import os
import sys
from datetime import datetime

# Ensure the dr-resync directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from resync_logic import ResyncManager

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Main Lambda handler for DR resync operations.
    
    Args:
        event: Lambda event with mode, dry_run, tenant_id
        context: Lambda context
        
    Returns:
        Dict with status, summary, and errors
    """
    try:
        # Parse input
        mode = event.get('mode', 'validate')
        dry_run = event.get('dry_run', False)
        tenant_id_filter = event.get('tenant_id')
        
        # Validate mode
        if mode not in ['enable', 'disable', 'validate']:
            return {
                'status': 'failure',
                'error': f'Invalid mode: {mode}. Must be enable, disable, or validate.'
            }
        
        logger.info(f"Starting DR resync: mode={mode}, dry_run={dry_run}, tenant_filter={tenant_id_filter}")
        
        # Initialize resync manager
        resync = ResyncManager(tenant_id_filter=tenant_id_filter)
        
        # Execute resync based on mode
        if mode == 'enable':
            result = resync.enable_region(dry_run=dry_run)
        elif mode == 'disable':
            result = resync.disable_region(dry_run=dry_run)
        else:  # validate
            result = resync.validate_region()
        
        # Build response
        response = {
            'status': result['status'],
            'mode': mode,
            'region': os.environ.get('AWS_REGION', 'unknown'),
            'execution_time': datetime.utcnow().isoformat() + 'Z',
            'duration_seconds': result.get('duration_seconds', 0),
            'summary': result.get('summary', {}),
            'errors': result.get('errors', []),
            'warnings': result.get('warnings', [])
        }
        
        logger.info(f"DR resync completed: {json.dumps(response['summary'])}")
        return response
        
    except Exception as e:
        logger.exception(f"Unexpected error in DR resync: {str(e)}")
        return {
            'status': 'failure',
            'error': str(e),
            'mode': event.get('mode', 'unknown'),
            'region': os.environ.get('AWS_REGION', 'unknown')
        }
