"""
DynamoDB operations for UserMappings table
"""
import boto3
import os
import logging
from typing import List, Optional
from ..models.usermapping import UserMapping

logger = logging.getLogger("app")


class UserMappingsDB:
    """DynamoDB operations for user-tenant mappings"""
    
    def __init__(self):
        self.table_name = os.environ.get('DYNAMODB_USER_MAPPINGS_TABLE', 'sts-dev-user-mappings')
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(self.table_name)
        logger.info(f"UserMappingsDB initialized with table: {self.table_name}")
    
    def create_mapping(self, user_id: str, tenant_id: str, create_user: str) -> UserMapping:
        """
        Create a new user-tenant mapping
        
        Args:
            user_id: Cognito user ID or email
            tenant_id: Tenant identifier
            create_user: User who is creating this mapping
            
        Returns:
            Created UserMapping
        """
        mapping = UserMapping(
            user_id=user_id,
            tenant_id=tenant_id,
            create_user=create_user
        )

        self.table.put_item(Item=mapping.dict())
        logger.info(f"Created user mapping: {user_id} -> {tenant_id}")
        return mapping
    
    def delete_mapping(self, user_id: str, tenant_id: str) -> bool:
        """
        Delete a user-tenant mapping
        
        Args:
            user_id: Cognito user ID or email
            tenant_id: Tenant identifier
            
        Returns:
            True if deleted successfully
        """
        try:
            self.table.delete_item(
                Key={
                    'user_id': user_id,
                    'tenant_id': tenant_id
                }
            )
            logger.info(f"Deleted user mapping: {user_id} -> {tenant_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting user mapping: {e}")
            return False
    
    def get_user_tenants(self, user_id: str) -> List[str]:
        """
        Get all tenants a user has access to
        
        Args:
            user_id: Cognito user ID or email
            
        Returns:
            List of tenant IDs
        """
        try:
            response = self.table.query(
                KeyConditionExpression='user_id = :uid',
                ExpressionAttributeValues={
                    ':uid': user_id
                }
            )
            
            tenants = [item['tenant_id'] for item in response.get('Items', [])]
            logger.info(f"User {user_id} has access to tenants: {tenants}")
            return tenants
        except Exception as e:
            logger.error(f"Error getting user tenants: {e}")
            return []
    
    def get_tenant_users(self, tenant_id: str) -> List[UserMapping]:
        """
        Get all users that have access to a tenant
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of UserMapping objects
        """
        try:
            response = self.table.query(
                IndexName='tenant-index',
                KeyConditionExpression='tenant_id = :tid',
                ExpressionAttributeValues={
                    ':tid': tenant_id
                }
            )
            
            mappings = [UserMapping(**item) for item in response.get('Items', [])]
            logger.info(f"Tenant {tenant_id} has {len(mappings)} user(s)")
            return mappings
        except Exception as e:
            logger.error(f"Error getting tenant users: {e}")
            return []
    
    def get_mapping(self, user_id: str, tenant_id: str) -> Optional[UserMapping]:
        """
        Get a specific user-tenant mapping
        
        Args:
            user_id: Cognito user ID or email
            tenant_id: Tenant identifier
            
        Returns:
            UserMapping if exists, None otherwise
        """
        try:
            response = self.table.get_item(
                Key={
                    'user_id': user_id,
                    'tenant_id': tenant_id
                }
            )
            
            if 'Item' in response:
                return UserMapping(**response['Item'])
            return None
        except Exception as e:
            logger.error(f"Error getting user mapping: {e}")
            return None
    
    def get_all_mappings(self) -> List[UserMapping]:
        """
        Get all user-tenant mappings
        
        Returns:
            List of all UserMapping objects
        """
        try:
            response = self.table.scan()
            mappings = [UserMapping(**item) for item in response.get('Items', [])]
            logger.info(f"Retrieved {len(mappings)} user mapping(s)")
            return mappings
        except Exception as e:
            logger.error(f"Error getting all mappings: {e}")
            return []
