from abc import ABC, abstractmethod
import logging
import boto3
import os
from typing import Dict, List, Any, Optional
from botocore.exceptions import ClientError

from ..models.schedule import Schedule
from ..models.target import Target
from ..models.tenant import Tenant
from ..models.tenantmapping import TenantMapping
from . import get_session

# Configure logging
logger = logging.getLogger("app.awssdk.dynamodb")

# Singleton database client instance
_db_client = None

class DatabaseClient(ABC):
    @abstractmethod
    def get_all_targets(self) -> List[Target]:
        """Get all targets from storage"""
        pass

    @abstractmethod
    def get_target(self, target_id: str) -> Optional[Target]:
        """Get a specific target by id"""
        pass

    @abstractmethod
    def create_target(self, target: Target) -> bool:
        """Create a new target"""
        pass

    @abstractmethod
    def update_target(self, target_id: str, target: Target) -> bool:
        """Update an existing target"""
        pass
            
    @abstractmethod
    def delete_target(self, target_id: str) -> bool:
        """Delete a target"""
        pass

    @abstractmethod
    def get_all_tenants(self) -> List[Tenant]:
        """Get all tenants from storage"""
        pass

    @abstractmethod
    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get a specific tenant by id"""
        pass

    @abstractmethod
    def create_tenant(self, tenant: Tenant) -> bool:
        """Create a new tenant"""
        pass

    @abstractmethod
    def update_tenant(self, tenant_id: str, tenant: Tenant) -> bool:
        """Update an existing tenant"""
        pass

    @abstractmethod
    def delete_tenant_record(self, tenant_id: str) -> bool:
        """Delete a tenant record"""
        pass

    @abstractmethod
    def execute_target(self, target_id: str, execution_params: Dict[str, Any], is_async: bool = False) -> Dict[str, Any]:
        """Execute a target with the given parameters
        
        Args:
            target_id: The ID of the target to execute
            execution_params: The parameters to pass to the target
            is_async: Whether to execute the target asynchronously
            
        Returns:
            The response from the target execution
        """
        pass
        
    @abstractmethod
    def get_all_tenant_mappings(self) -> List[TenantMapping]:
        """Get all tenant mappings from storage"""
        pass
        
    @abstractmethod
    def get_tenant_mappings(self, tenant_id: str) -> List[TenantMapping]:
        """Get all mappings for a specific tenant"""
        pass
        
    @abstractmethod
    def get_tenant_target_mapping(self, tenant_id: str, target_alias: str) -> Optional[TenantMapping]:
        """Get a specific tenant target mapping"""
        pass
        
    @abstractmethod
    def create_tenant_mapping(self, mapping: TenantMapping) -> bool:
        """Create a new tenant target mapping"""
        pass
        
    @abstractmethod
    def update_tenant_mapping(self, tenant_id: str, target_alias: str, mapping: TenantMapping) -> bool:
        """Update an existing tenant target mapping"""
        pass
        
    @abstractmethod
    def delete_tenant_mapping(self, tenant_id: str, target_alias: str) -> bool:
        """Delete a tenant target mapping"""
        pass
        
    @abstractmethod
    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete all mappings for a tenant"""
        pass

    @abstractmethod
    def create_schedule(self, schedule: Schedule) -> bool:
        """Create a new target schedule in DynamoDB"""
        pass

    @abstractmethod
    def update_schedule(self, schedule: Schedule) -> bool:
        """Update an existing target schedule in DynamoDB"""
        pass

    @abstractmethod
    def delete_schedule(self, tenant_id: str, schedule_id: str) -> bool:
        """Delete a target schedule from DynamoDB"""
        pass

    @abstractmethod
    def get_schedule(self, tenant_id: str, schedule_id: str) -> Optional[Schedule]:
        """Get a target schedule"""
        pass

    @abstractmethod
    @abstractmethod
    def get_all_schedules(self, tenant_id: str) -> List[Schedule]:
        """Get all target schedules for a tenant"""
        pass

    @abstractmethod
    def get_all_target_schedules(self, tenant_id: str, target_alias: str) -> List[Schedule]:
        """Get all schedules for a specific target"""
        pass

    @abstractmethod
    def get_user_tenants(self, user_id: str) -> List[str]:
        """Get all tenants a user has access to"""
        pass

    @abstractmethod
    def create_user_mapping(self, user_id: str, tenant_id: str, create_user: str):
        """Create a new user-tenant mapping"""
        pass

    @abstractmethod
    def delete_user_mapping(self, user_id: str, tenant_id: str) -> bool:
        """Delete a user-tenant mapping"""
        pass

    @abstractmethod
    def get_user_mapping(self, user_id: str, tenant_id: str):
        """Get a specific user-tenant mapping"""
        pass

    @abstractmethod
    def get_tenant_users(self, tenant_id: str) -> List:
        """Get all users that have access to a tenant"""
        pass

    @abstractmethod
    def get_all_user_mappings(self) -> List:
        """Get all user-tenant mappings"""
        pass

    @abstractmethod
    def get_execution_by_schedule_id(self, tenant_id: str, schedule_id: str, execution_id: str = None) -> Optional[Dict[str, Any]]:
        """Get execution record by tenant_id + schedule_id and optionally execution_id"""
        pass

    @abstractmethod
    def list_target_executions(self, tenant_id: str, target_alias: str, limit: int = 20) -> List[Dict[str, Any]]:
        """List executions for a specific tenant target"""
        pass
    
    
class DynamoDBClient(DatabaseClient):
    def __init__(self, db_target='local'):

        endpoint_url = os.environ.get('DYNAMODB_ENDPOINT_URL', 'http://localhost:8000')
        if (db_target == 'aws'):
            endpoint_url = None

        self.db = get_session().resource('dynamodb', endpoint_url=endpoint_url)

        self.targets_table_name = os.environ.get('DYNAMODB_TABLE', 'Targets')
        self.tenants_table_name = os.environ.get('DYNAMODB_TENANTS_TABLE', 'Tenants')
        self.tenant_mappings_table_name = os.environ.get('DYNAMODB_TENANT_TABLE', 'TenantMappings')
        self.schedules_table_name = os.environ.get('DYNAMODB_SCHEDULES_TABLE', 'Schedules')
        self.user_mappings_table_name = os.environ.get('DYNAMODB_USER_MAPPINGS_TABLE', 'sts-dev-user-mappings')
        self.executions_table_name = os.environ.get('DYNAMODB_EXECUTIONS_TABLE', 'Executions')

        # This line will raise an exception if DynamoDB is not accessible
        self.targets = self.db.Table(self.targets_table_name)
        self.tenants = self.db.Table(self.tenants_table_name)
        self.tenant_mappings = self.db.Table(self.tenant_mappings_table_name)
        self.schedules = self.db.Table(self.schedules_table_name)
        self.user_mappings = self.db.Table(self.user_mappings_table_name)
        self.executions = self.db.Table(self.executions_table_name)

        # Test the connection to ensure it's working
        try:
            self.targets.scan(Limit=1)
        except Exception as e:
            raise ConnectionError(f"Could not connect to DynamoDB: {e}")

    def get_all_targets(self) -> List[Target]:
        """Get all targets from storage"""
        try:
            response = self.targets.scan()
            return response.get('Items', [])
        except ClientError as e:
            print(f"Error getting targets: {e}")
            return []

    def get_target(self, target_id: str) -> Optional[Target]:
        """Get a specific target by id"""
        try:
            response = self.targets.get_item(Key={'target_id': target_id})
            return response.get('Item')
        except ClientError as e:
            print(f"Error getting target {target_id}: {e}")
            return None

    def create_target(self, target: Dict[str, Any]) -> bool:
        """Create a new target"""
        try:
            self.targets.put_item(Item=target)
            return True
        except ClientError as e:
            print(f"Error creating target: {e}")
            return False

    def update_target(self, target_id: str, target: Target) -> bool:
        """Update an existing target"""
        target['target_id'] = target_id
        try:
            self.targets.put_item(Item=target)
            return True
        except ClientError as e:
            print(f"Error updating target {target_id}: {e}")
            return False
            
    def delete_target(self, target_id: str) -> bool:
        """Delete a target"""
        try:
            response = self.targets.delete_item(
                Key={'target_id': target_id},
                ReturnValues='ALL_OLD'
            )
            return 'Attributes' in response
        except ClientError as e:
            print(f"Error deleting target {target_id}: {e}")
            return False

    def get_all_tenants(self) -> List[Tenant]:
        """Get all tenants from storage"""
        try:
            response = self.tenants.scan()
            return [Tenant(**item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error getting tenants: {e}")
            return []

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get a specific tenant by id"""
        try:
            response = self.tenants.get_item(Key={'tenant_id': tenant_id})
            item = response.get('Item')
            return Tenant(**item) if item else None
        except ClientError as e:
            print(f"Error getting tenant {tenant_id}: {e}")
            return None

    def create_tenant(self, tenant: Dict[str, Any]) -> bool:
        """Create a new tenant"""
        try:
            self.tenants.put_item(Item=tenant)
            return True
        except ClientError as e:
            print(f"Error creating tenant: {e}")
            return False

    def update_tenant(self, tenant_id: str, tenant: Tenant) -> bool:
        """Update an existing tenant"""
        tenant_dict = tenant.dict() if hasattr(tenant, 'dict') else tenant
        tenant_dict['tenant_id'] = tenant_id
        try:
            self.tenants.put_item(Item=tenant_dict)
            return True
        except ClientError as e:
            print(f"Error updating tenant {tenant_id}: {e}")
            return False

    def delete_tenant_record(self, tenant_id: str) -> bool:
        """Delete a tenant record"""
        try:
            response = self.tenants.delete_item(
                Key={'tenant_id': tenant_id},
                ReturnValues='ALL_OLD'
            )
            return 'Attributes' in response
        except ClientError as e:
            print(f"Error deleting tenant {tenant_id}: {e}")
            return False

    def execute_target(self, target_id: str, execution_params: Dict[str, Any], is_async: bool = False) -> Dict[str, Any]:
        """Execute a target with the given parameters"""
        # Get the target to get its ARN
        target = self.get_target(target_id)
        if not target:
            return {
                "status": "ERROR",
                "error": f"Target {target_id} not found"
            }
            
        # In a real implementation, this would use the target ARN
        # For now, we'll just return a mock response
        if is_async:
            return {
                "execution_id": f"exec-async-{target_id}",
                "target_id": target_id,
                "status": "ACCEPTED",
                "message": "Target execution started asynchronously"
            }
        else:
            return {
                "execution_id": f"exec-{target_id}",
                "target_id": target_id,
                "status": "STARTED",
                "parameters": execution_params
            }
            
    def get_all_tenant_mappings(self) -> List[TenantMapping]:
        """Get all tenant mappings from storage"""
        try:
            response = self.tenant_mappings.scan()
            return [TenantMapping(**item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error getting tenant mappings: {e}")
            return []
        
    def get_tenant_mappings(self, tenant_id: str) -> List[TenantMapping]:
        """Get all mappings for a specific tenant"""
        try:
            response = self.tenant_mappings.query(
                KeyConditionExpression='tenant_id = :tid',
                ExpressionAttributeValues={':tid': tenant_id}
            )
            return [TenantMapping(**item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error getting tenant mappings for {tenant_id}: {e}")
            return []
        
    def get_tenant_target_mapping(self, tenant_id: str, target_alias: str) -> Optional[TenantMapping]:
        """Get a specific tenant target mapping"""
        try:
            response = self.tenant_mappings.get_item(
                Key={
                    'tenant_id': tenant_id,
                    'target_alias': target_alias
                }
            )
            item = response.get('Item')
            return TenantMapping(**item) if item else None
        except ClientError as e:
            print(f"Error getting tenant mapping {tenant_id}:{target_alias}: {e}")
            return None
        
    def create_tenant_mapping(self, mapping: TenantMapping) -> bool:
        """Create a new tenant target mapping"""
        try:
            self.tenant_mappings.put_item(Item=mapping.dict())
            return True
        except ClientError as e:
            print(f"Error creating tenant mapping: {e}")
            return False
        
    def update_tenant_mapping(self, tenant_id: str, target_alias: str, mapping: TenantMapping) -> bool:
        """Update an existing tenant target mapping"""
        try:
            self.tenant_mappings.put_item(Item=mapping.dict())
            return True
        except ClientError as e:
            print(f"Error updating tenant mapping {tenant_id}:{target_alias}: {e}")
            return False
        
    def delete_tenant_mapping(self, tenant_id: str, target_alias: str) -> bool:
        """Delete a tenant target mapping"""
        try:
            response = self.tenant_mappings.delete_item(
                Key={
                    'tenant_id': tenant_id,
                    'target_alias': target_alias
                },
                ReturnValues='ALL_OLD'
            )
            return 'Attributes' in response
        except ClientError as e:
            print(f"Error deleting tenant mapping {tenant_id}:{target_alias}: {e}")
            return False
            
    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete all mappings for a tenant"""
        try:
            # First get all mappings for this tenant
            mappings = self.get_tenant_mappings(tenant_id)
            
            if not mappings:
                return False
                
            # Delete each mapping
            success = True
            for mapping in mappings:
                result = self.delete_tenant_mapping(tenant_id, mapping.target_alias)
                success = success and result
                
            return success
        except ClientError as e:
            print(f"Error deleting tenant {tenant_id}: {e}")
            return False

    def create_schedule(self, schedule: Schedule) -> bool:
        """Create a new target schedule"""
        try:
            self.schedules.put_item(Item=schedule.to_dynamodb_item())
            return True
        except ClientError as e:
            print(f"Error creating target schedule: {e}")
            return False

    def update_schedule(self, schedule: Schedule) -> bool:
        """Update an existing target schedule"""
        try:
            self.schedules.put_item(Item=schedule.to_dynamodb_item())
            return True
        except ClientError as e:
            print(f"Error updating target schedule: {e}")
            return False

    def delete_schedule(self, tenant_id: str, schedule_id: str) -> bool:
        """Delete a target schedule"""
        try:
            self.schedules.delete_item(Key={'tenant_id': tenant_id, 'schedule_id': schedule_id})
            return True
        except ClientError as e:
            print(f"Error deleting target schedule: {e}")
            return False
        
    def get_schedule(self, tenant_id: str, schedule_id: str) -> Optional[Schedule]:
        """Get a target schedule"""
        try:
            response = self.schedules.get_item(Key={'tenant_id': tenant_id, 'schedule_id': schedule_id})
            return Schedule(**response.get('Item'))
        except ClientError as e:
            print(f"Error getting target schedule: {e}")
            return None
        
    def get_all_schedules(self, tenant_id: str) -> List[Schedule]:
        """Get all target schedules for a tenant"""
        try:
            response = self.schedules.query(KeyConditionExpression='tenant_id = :tid', ExpressionAttributeValues={':tid': tenant_id})
            return [Schedule(**item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error getting target schedules for {tenant_id}: {e}")
            return []
        
    def get_all_target_schedules(self, tenant_id: str, target_alias: str) -> List[Schedule]:
        """Get all schedules for a specific target"""
        try:
            response = self.schedules.query(
                IndexName='tenant-target-index',
                KeyConditionExpression='tenant_id = :tid AND target_alias = :ta',
                ExpressionAttributeValues={':tid': tenant_id, ':ta': target_alias}
            )
            return [Schedule(**item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error getting target schedules for {tenant_id}:{target_alias}: {e}")
            return []

    def get_user_tenants(self, user_id: str) -> List[str]:
        """Get all tenants a user has access to"""
        try:
            response = self.user_mappings.query(
                KeyConditionExpression='user_id = :uid',
                ExpressionAttributeValues={':uid': user_id}
            )
            return [item['tenant_id'] for item in response.get('Items', [])]
        except ClientError as e:
            logger.error(f"Error getting user tenants for {user_id}: {e}")
            return []

    def create_user_mapping(self, user_id: str, tenant_id: str, create_user: str):
        """Create a new user-tenant mapping"""
        from ..models.usermapping import UserMapping
        try:
            mapping = UserMapping(
                user_id=user_id,
                tenant_id=tenant_id,
                create_user=create_user
            )
            self.user_mappings.put_item(Item=mapping.dict())
            logger.info(f"Created user mapping: {user_id} -> {tenant_id}")
            return mapping
        except ClientError as e:
            logger.error(f"Error creating user mapping: {e}")
            return None

    def delete_user_mapping(self, user_id: str, tenant_id: str) -> bool:
        """Delete a user-tenant mapping"""
        try:
            self.user_mappings.delete_item(
                Key={'user_id': user_id, 'tenant_id': tenant_id}
            )
            logger.info(f"Deleted user mapping: {user_id} -> {tenant_id}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting user mapping: {e}")
            return False

    def get_user_mapping(self, user_id: str, tenant_id: str):
        """Get a specific user-tenant mapping"""
        from ..models.usermapping import UserMapping
        try:
            response = self.user_mappings.get_item(
                Key={'user_id': user_id, 'tenant_id': tenant_id}
            )
            if 'Item' in response:
                return UserMapping(**response['Item'])
            return None
        except ClientError as e:
            logger.error(f"Error getting user mapping: {e}")
            return None

    def get_tenant_users(self, tenant_id: str) -> List:
        """Get all users that have access to a tenant"""
        from ..models.usermapping import UserMapping
        try:
            response = self.user_mappings.query(
                IndexName='tenant-index',
                KeyConditionExpression='tenant_id = :tid',
                ExpressionAttributeValues={':tid': tenant_id}
            )
            return [UserMapping(**item) for item in response.get('Items', [])]
        except ClientError as e:
            logger.error(f"Error getting tenant users for {tenant_id}: {e}")
            return []

    def get_all_user_mappings(self) -> List:
        """Get all user-tenant mappings"""
        from ..models.usermapping import UserMapping
        try:
            response = self.user_mappings.scan()
            return [UserMapping(**item) for item in response.get('Items', [])]
        except ClientError as e:
            logger.error(f"Error getting all user mappings: {e}")
            return []

    def get_execution_by_schedule_id(self, tenant_id: str, schedule_id: str, execution_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Get execution record by tenant_id + schedule_id and optionally execution_id.

        For ad-hoc executions: schedule_id is unique per tenant, so we query and get the first result
        For recurring schedules: execution_id should be provided for a specific execution

        Args:
            tenant_id: The tenant identifier
            schedule_id: The schedule identifier
            execution_id: Optional execution identifier (Lambda RequestId)

        Returns:
            Execution record or None
        """
        try:
            tenant_schedule = f"{tenant_id}#{schedule_id}"

            if execution_id:
                # Direct get_item with both keys
                response = self.executions.get_item(
                    Key={
                        'tenant_schedule': tenant_schedule,
                        'execution_id': execution_id
                    }
                )
                return response.get('Item')
            else:
                # Query by tenant_schedule only, get most recent execution
                response = self.executions.query(
                    KeyConditionExpression='tenant_schedule = :ts',
                    ExpressionAttributeValues={':ts': tenant_schedule},
                    Limit=1,
                    ScanIndexForward=False  # Most recent first (by execution_id sort key)
                )
                items = response.get('Items', [])
                return items[0] if items else None
        except ClientError as e:
            logger.error(f"Error getting execution for schedule {tenant_id}#{schedule_id}: {e}")
            return None

    def get_schedule_executions(
        self,
        tenant_id: str,
        schedule_id: str,
        target_alias: str = None,
        limit: int = 50,
        start_time_lower: str = None,
        start_time_upper: str = None,
        status: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get all executions for a specific schedule with optional filtering.

        Args:
            tenant_id: The tenant identifier
            schedule_id: The schedule identifier
            target_alias: Optional target alias for validation
            limit: Maximum number of executions to return
            start_time_lower: ISO 8601 timestamp - only return executions after this time
            start_time_upper: ISO 8601 timestamp - only return executions before this time
            status: Filter by execution status (SUCCESS or FAILED)

        Returns:
            List of execution records
        """
        try:
            tenant_schedule = f"{tenant_id}#{schedule_id}"

            # Build the query
            query_params = {
                'KeyConditionExpression': 'tenant_schedule = :ts',
                'ExpressionAttributeValues': {':ts': tenant_schedule},
                'Limit': limit,
                'ScanIndexForward': False  # Most recent first (by execution_id sort key)
            }

            # Build filter expression for optional filters
            filter_expressions = []

            if start_time_lower:
                filter_expressions.append('#ts >= :start_lower')
                query_params['ExpressionAttributeValues'][':start_lower'] = start_time_lower
                if 'ExpressionAttributeNames' not in query_params:
                    query_params['ExpressionAttributeNames'] = {}
                query_params['ExpressionAttributeNames']['#ts'] = 'timestamp'

            if start_time_upper:
                filter_expressions.append('#ts <= :start_upper')
                query_params['ExpressionAttributeValues'][':start_upper'] = start_time_upper
                if 'ExpressionAttributeNames' not in query_params:
                    query_params['ExpressionAttributeNames'] = {}
                query_params['ExpressionAttributeNames']['#ts'] = 'timestamp'

            if status:
                filter_expressions.append('#st = :status')
                query_params['ExpressionAttributeValues'][':status'] = status
                if 'ExpressionAttributeNames' not in query_params:
                    query_params['ExpressionAttributeNames'] = {}
                query_params['ExpressionAttributeNames']['#st'] = 'status'

            # If target_alias is provided, validate it matches
            if target_alias:
                expected_tenant_target = f"{tenant_id}#{target_alias}"
                filter_expressions.append('tenant_target = :tt')
                query_params['ExpressionAttributeValues'][':tt'] = expected_tenant_target

            # Add filter expression if we have any filters
            if filter_expressions:
                query_params['FilterExpression'] = ' AND '.join(filter_expressions)

            response = self.executions.query(**query_params)
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Error getting schedule executions for {tenant_id}#{schedule_id}: {e}")
            return []

    def list_target_executions(
        self,
        tenant_id: str,
        target_alias: str,
        limit: int = 50,
        start_time_lower: str = None,
        start_time_upper: str = None,
        status: str = None
    ) -> List[Dict[str, Any]]:
        """
        List executions for a specific tenant target with optional filtering.
        Queries the tenant-target-index GSI by tenant_target (formatted as 'tenant_id#target_alias').

        Args:
            tenant_id: The tenant identifier
            target_alias: The target alias
            limit: Maximum number of executions to return
            start_time_lower: ISO 8601 timestamp - only return executions after this time
            start_time_upper: ISO 8601 timestamp - only return executions before this time
            status: Filter by execution status (SUCCESS or FAILED)

        Returns:
            List of execution records
        """
        try:
            tenant_target = f"{tenant_id}#{target_alias}"

            # Build the query
            query_params = {
                'IndexName': 'tenant-target-index',
                'KeyConditionExpression': 'tenant_target = :tt',
                'ExpressionAttributeValues': {':tt': tenant_target},
                'Limit': limit,
                'ScanIndexForward': False  # Get most recent first (by timestamp)
            }

            # Build filter expression for optional filters
            filter_expressions = []

            if start_time_lower:
                filter_expressions.append('#ts >= :start_lower')
                query_params['ExpressionAttributeValues'][':start_lower'] = start_time_lower
                if 'ExpressionAttributeNames' not in query_params:
                    query_params['ExpressionAttributeNames'] = {}
                query_params['ExpressionAttributeNames']['#ts'] = 'timestamp'

            if start_time_upper:
                filter_expressions.append('#ts <= :start_upper')
                query_params['ExpressionAttributeValues'][':start_upper'] = start_time_upper
                if 'ExpressionAttributeNames' not in query_params:
                    query_params['ExpressionAttributeNames'] = {}
                query_params['ExpressionAttributeNames']['#ts'] = 'timestamp'

            if status:
                filter_expressions.append('#st = :status')
                query_params['ExpressionAttributeValues'][':status'] = status
                if 'ExpressionAttributeNames' not in query_params:
                    query_params['ExpressionAttributeNames'] = {}
                query_params['ExpressionAttributeNames']['#st'] = 'status'

            # Add filter expression if we have any filters
            if filter_expressions:
                query_params['FilterExpression'] = ' AND '.join(filter_expressions)

            response = self.executions.query(**query_params)
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Error listing executions for {tenant_id}/{target_alias}: {e}")
            return []

def get_database_client() -> DatabaseClient:
    """
    Get the appropriate database client based on availability and configuration.
    Returns a singleton instance of the database client.
    """
    global _db_client
    
    # If we already have a client instance, return it
    if _db_client is not None:
        return _db_client
    
    # Check DB_TARGET environment variable
    db_target = os.environ.get('DB_TARGET', 'local').lower()
    
    # Use in-memory database
    if db_target == 'memory':
        logger.info("Using in-memory database")
        _db_client = LocalClient()
        return _db_client
    
    # Use DynamoDB (local or AWS)
    logger.info(f"Attempting to connect to DynamoDB ({db_target})")
    _db_client = DynamoDBClient(db_target)
    _db_client.get_all_targets()  # Test connection
    logger.info(f"Successfully connected to DynamoDB ({db_target})")
    return _db_client

class LocalClient(DatabaseClient):
    def __init__(self):
        self.local_storage: Dict[str, Target] = {}
        self.tenants_storage: Dict[str, Tenant] = {}
        self.tenant_mappings: Dict[str, TenantMapping] = {}
        self.user_mappings: Dict[str, Any] = {}  # Key: "user_id:tenant_id"
        
    def get_all_targets(self) -> List[Dict[str, Target]]:
        """Get all targets from storage"""
        return list(self.local_storage.values())

    def get_target(self, target_id: str) -> Optional[Target]:
        """Get a specific target by name"""
        return self.local_storage.get(target_id)

    def create_target(self, target: Target) -> bool:
        """Create a new target"""
        self.local_storage[target['target_id']] = target
        return True

    def update_target(self, target_id: str, target: Dict[str, Target]) -> bool:
        """Update an existing target"""
        target['target_id'] = target_id
        self.local_storage[target_id] = target
        return True
            
    def delete_target(self, target_id: str) -> bool:
        """Delete a target"""
        if target_id in self.local_storage:
            del self.local_storage[target_id]
            return True
        return False

    def get_all_tenants(self) -> List[Tenant]:
        """Get all tenants from storage"""
        return list(self.tenants_storage.values())

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get a specific tenant by id"""
        return self.tenants_storage.get(tenant_id)

    def create_tenant(self, tenant: Tenant) -> bool:
        """Create a new tenant"""
        self.tenants_storage[tenant['tenant_id']] = tenant
        return True

    def update_tenant(self, tenant_id: str, tenant: Dict[str, Tenant]) -> bool:
        """Update an existing tenant"""
        tenant['tenant_id'] = tenant_id
        self.tenants_storage[tenant_id] = tenant
        return True

    def delete_tenant_record(self, tenant_id: str) -> bool:
        """Delete a tenant record"""
        if tenant_id in self.tenants_storage:
            del self.tenants_storage[tenant_id]
            return True
        return False

    def execute_target(self, target_id: str, execution_params: Dict[str, Any], is_async: bool = False) -> Dict[str, Any]:
        """Execute a target with the given parameters"""
        # Just return a mock response
        if is_async:
            return {
                "execution_id": "exec-async-12345",
                "target_id": target_id,
                "status": "ACCEPTED",
                "message": "Target execution started asynchronously"
            }
        return {
            "execution_id": "exec-12345",
            "target_id": target_id,
            "status": "STARTED",
            "parameters": execution_params
        }
        
    def get_all_tenant_mappings(self) -> List[TenantMapping]:
        """Get all tenant mappings from storage"""
        return list(self.tenant_mappings.values())
        
    def get_tenant_mappings(self, tenant_id: str) -> List[TenantMapping]:
        """Get all mappings for a specific tenant"""
        return [m for m in self.tenant_mappings.values() if m.tenant_id == tenant_id]
        
    def get_tenant_target_mapping(self, tenant_id: str, target_alias: str) -> Optional[TenantMapping]:
        """Get a specific tenant target mapping"""
        key = f"{tenant_id}:{target_alias}"
        return self.tenant_mappings.get(key)
        
    def create_tenant_mapping(self, mapping: TenantMapping) -> bool:
        """Create a new tenant target mapping"""
        key = f"{mapping.tenant_id}:{mapping.target_alias}"
        self.tenant_mappings[key] = mapping
        return True
        
    def update_tenant_mapping(self, tenant_id: str, target_alias: str, mapping: TenantMapping) -> bool:
        """Update an existing tenant target mapping"""
        key = f"{tenant_id}:{target_alias}"
        self.tenant_mappings[key] = mapping
        return True
        
    def delete_tenant_mapping(self, tenant_id: str, target_alias: str) -> bool:
        """Delete a tenant target mapping"""
        key = f"{tenant_id}:{target_alias}"
        if key in self.tenant_mappings:
            del self.tenant_mappings[key]
            return True
        return False
        
    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete all mappings for a tenant"""
        # Find all keys for this tenant
        keys_to_delete = [key for key in self.tenant_mappings.keys()
                         if key.startswith(f"{tenant_id}:")]

        if not keys_to_delete:
            return False

        # Delete all mappings for this tenant
        for key in keys_to_delete:
            del self.tenant_mappings[key]

        return True

    def get_user_tenants(self, user_id: str) -> List[str]:
        """Get all tenants a user has access to"""
        tenants = []
        for key, mapping in self.user_mappings.items():
            if mapping.user_id == user_id:
                tenants.append(mapping.tenant_id)
        return tenants

    def create_user_mapping(self, user_id: str, tenant_id: str, create_user: str):
        """Create a new user-tenant mapping"""
        from ..models.usermapping import UserMapping
        mapping = UserMapping(
            user_id=user_id,
            tenant_id=tenant_id,
            create_user=create_user
        )
        key = f"{user_id}:{tenant_id}"
        self.user_mappings[key] = mapping
        logger.info(f"Created user mapping: {user_id} -> {tenant_id}")
        return mapping

    def delete_user_mapping(self, user_id: str, tenant_id: str) -> bool:
        """Delete a user-tenant mapping"""
        key = f"{user_id}:{tenant_id}"
        if key in self.user_mappings:
            del self.user_mappings[key]
            logger.info(f"Deleted user mapping: {user_id} -> {tenant_id}")
            return True
        return False

    def get_user_mapping(self, user_id: str, tenant_id: str):
        """Get a specific user-tenant mapping"""
        key = f"{user_id}:{tenant_id}"
        return self.user_mappings.get(key)

    def get_tenant_users(self, tenant_id: str) -> List:
        """Get all users that have access to a tenant"""
        users = []
        for key, mapping in self.user_mappings.items():
            if mapping.tenant_id == tenant_id:
                users.append(mapping)
        return users

    def get_all_user_mappings(self) -> List:
        """Get all user-tenant mappings"""
        return list(self.user_mappings.values())

    # Schedule methods (stubs for LocalClient)
    def create_schedule(self, schedule: Schedule) -> bool:
        """Create a new target schedule (stub)"""
        logger.warning("LocalClient: create_schedule not fully implemented")
        return True

    def update_schedule(self, schedule: Schedule) -> bool:
        """Update an existing target schedule (stub)"""
        logger.warning("LocalClient: update_schedule not fully implemented")
        return True

    def delete_schedule(self, tenant_id: str, schedule_id: str) -> bool:
        """Delete a target schedule (stub)"""
        logger.warning("LocalClient: delete_schedule not fully implemented")
        return True

    def get_schedule(self, tenant_id: str, schedule_id: str) -> Optional[Schedule]:
        """Get a target schedule (stub)"""
        logger.warning("LocalClient: get_schedule not fully implemented")
        return None

    def get_all_schedules(self, tenant_id: str) -> List[Schedule]:
        """Get all target schedules for a tenant (stub)"""
        logger.warning("LocalClient: get_all_schedules not fully implemented")
        return []

    def get_all_target_schedules(self, tenant_id: str, target_alias: str) -> List[Schedule]:
        """Get all schedules for a specific target (stub)"""
        logger.warning("LocalClient: get_all_target_schedules not fully implemented")
        return []

    def get_execution_by_schedule_id(self, tenant_id: str, schedule_id: str, execution_id: str = None) -> Optional[Dict[str, Any]]:
        """Get execution record by tenant_id + schedule_id and optionally execution_id (stub)"""
        logger.warning("LocalClient: get_execution_by_schedule_id not fully implemented")
        return None

    def list_target_executions(self, tenant_id: str, target_alias: str, limit: int = 20) -> List[Dict[str, Any]]:
        """List executions for a specific tenant target (stub)"""
        logger.warning("LocalClient: list_target_executions not fully implemented")
        return []