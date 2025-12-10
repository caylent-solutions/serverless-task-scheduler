"""
Cognito User Pool management client
"""
import os
import logging
from typing import List, Dict, Optional
from botocore.exceptions import ClientError
from . import get_session

logger = logging.getLogger("app.awssdk.cognito")

# Singleton client instance
_cognito_client = None


class CognitoClient:
    """Client for interacting with AWS Cognito User Pools"""

    def __init__(self):
        self.user_pool_id = os.environ.get('COGNITO_USER_POOL_ID', '')
        self.client_id = os.environ.get('COGNITO_CLIENT_ID', '')

        if not self.user_pool_id:
            raise ValueError("COGNITO_USER_POOL_ID environment variable not set")
        if not self.client_id:
            raise ValueError("COGNITO_CLIENT_ID environment variable not set")

        self.client = get_session().client('cognito-idp')

    def list_users(self, filter_expression: Optional[str] = None, limit: int = 60) -> List[Dict]:
        """
        List all users in the Cognito User Pool

        Args:
            filter_expression: Optional filter expression (e.g., 'email = "user@example.com"')
            limit: Maximum number of users to return (default 60, max 60 per API call)

        Returns:
            List of user dictionaries with email, username, and attributes
        """
        try:
            users = []
            pagination_token = None

            while True:
                params = {
                    'UserPoolId': self.user_pool_id,
                    'Limit': min(limit, 60)  # Cognito max is 60
                }

                if filter_expression:
                    params['Filter'] = filter_expression

                if pagination_token:
                    params['PaginationToken'] = pagination_token

                response = self.client.list_users(**params)

                # Process users
                for user in response.get('Users', []):
                    user_dict = {
                        'user_id': user.get('Username'),
                        'username': user.get('Username'),
                        'enabled': user.get('Enabled', True),
                        'user_status': user.get('UserStatus'),
                        'created_at': user.get('UserCreateDate').isoformat() if user.get('UserCreateDate') else None,
                        'updated_at': user.get('UserLastModifiedDate').isoformat() if user.get('UserLastModifiedDate') else None,
                    }

                    # Extract attributes
                    attributes = {}
                    for attr in user.get('Attributes', []):
                        attributes[attr['Name']] = attr['Value']

                    user_dict['email'] = attributes.get('email', '')
                    user_dict['full_name'] = attributes.get('name', attributes.get('given_name', ''))
                    user_dict['attributes'] = attributes

                    users.append(user_dict)

                # Check if we've retrieved enough users or if there are more pages
                if len(users) >= limit or 'PaginationToken' not in response:
                    break

                pagination_token = response['PaginationToken']

            return users[:limit]

        except ClientError as e:
            logger.error(f"Error listing Cognito users: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing Cognito users: {e}")
            return []

    def get_user(self, username: str) -> Optional[Dict]:
        """
        Get detailed information about a specific user

        Args:
            username: The username (or email) of the user

        Returns:
            User dictionary or None if not found
        """
        try:
            response = self.client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=username
            )

            user_dict = {
                'user_id': response.get('Username'),
                'username': response.get('Username'),
                'enabled': response.get('Enabled', True),
                'user_status': response.get('UserStatus'),
                'created_at': response.get('UserCreateDate').isoformat() if response.get('UserCreateDate') else None,
                'updated_at': response.get('UserLastModifiedDate').isoformat() if response.get('UserLastModifiedDate') else None,
            }

            # Extract attributes
            attributes = {}
            for attr in response.get('UserAttributes', []):
                attributes[attr['Name']] = attr['Value']

            user_dict['email'] = attributes.get('email', '')
            user_dict['full_name'] = attributes.get('name', attributes.get('given_name', ''))
            user_dict['attributes'] = attributes

            return user_dict

        except ClientError as e:
            if e.response['Error']['Code'] == 'UserNotFoundException':
                return None
            logger.error(f"Error getting Cognito user {username}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting Cognito user {username}: {e}")
            return None

    def delete_user(self, username: str) -> bool:
        """
        Delete a user from the Cognito User Pool

        Args:
            username: The username (or email) of the user to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            self.client.admin_delete_user(
                UserPoolId=self.user_pool_id,
                Username=username
            )
            logger.info(f"Successfully deleted user from Cognito: {username}")
            return True

        except ClientError as e:
            if e.response['Error']['Code'] == 'UserNotFoundException':
                logger.warning(f"User not found in Cognito: {username}")
                return True  # Consider it successful if user doesn't exist
            logger.error(f"Error deleting Cognito user {username}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting Cognito user {username}: {e}")
            return False

    def forgot_password(self, username: str) -> Dict[str, str]:
        """
        Initiate a forgot password flow for a user

        This sends a verification code to the user's email.

        Args:
            username: The username (or email) of the user

        Returns:
            Dict with 'status' and 'message' or 'error'
        """
        try:
            response = self.client.forgot_password(
                ClientId=self.client_id,
                Username=username
            )

            logger.info(f"Password reset initiated for user: {username}")

            # Get delivery details if available
            delivery = response.get('CodeDeliveryDetails', {})
            destination = delivery.get('Destination', 'your email')

            return {
                'status': 'SUCCESS',
                'message': f'Password reset code sent to {destination}',
                'destination': destination
            }

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            logger.error(f"Error initiating password reset for {username}: {error_code} - {error_message}")

            # Provide user-friendly error messages
            if error_code == 'UserNotFoundException':
                return {
                    'status': 'ERROR',
                    'error': 'User not found'
                }
            elif error_code == 'InvalidParameterException':
                return {
                    'status': 'ERROR',
                    'error': 'Invalid username format'
                }
            elif error_code == 'LimitExceededException':
                return {
                    'status': 'ERROR',
                    'error': 'Too many requests. Please try again later.'
                }
            else:
                return {
                    'status': 'ERROR',
                    'error': error_message
                }

        except Exception as e:
            logger.error(f"Unexpected error initiating password reset: {e}")
            return {
                'status': 'ERROR',
                'error': 'An unexpected error occurred'
            }

    def confirm_forgot_password(self, username: str, confirmation_code: str, new_password: str) -> Dict[str, str]:
        """
        Confirm forgot password with verification code and set new password

        Args:
            username: The username (or email) of the user
            confirmation_code: The verification code sent to user's email
            new_password: The new password to set

        Returns:
            Dict with 'status' and 'message' or 'error'
        """
        try:
            self.client.confirm_forgot_password(
                ClientId=self.client_id,
                Username=username,
                ConfirmationCode=confirmation_code,
                Password=new_password
            )

            logger.info(f"Password reset confirmed for user: {username}")

            return {
                'status': 'SUCCESS',
                'message': 'Password has been reset successfully'
            }

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            logger.error(f"Error confirming password reset for {username}: {error_code} - {error_message}")

            # Provide user-friendly error messages
            if error_code == 'CodeMismatchException':
                return {
                    'status': 'ERROR',
                    'error': 'Invalid verification code'
                }
            elif error_code == 'ExpiredCodeException':
                return {
                    'status': 'ERROR',
                    'error': 'Verification code has expired. Please request a new one.'
                }
            elif error_code == 'InvalidPasswordException':
                return {
                    'status': 'ERROR',
                    'error': 'Password does not meet requirements'
                }
            elif error_code == 'UserNotFoundException':
                return {
                    'status': 'ERROR',
                    'error': 'User not found'
                }
            else:
                return {
                    'status': 'ERROR',
                    'error': error_message
                }

        except Exception as e:
            logger.error(f"Unexpected error confirming password reset: {e}")
            return {
                'status': 'ERROR',
                'error': 'An unexpected error occurred'
            }

    def create_user(self, email: str, temporary_password: str = None, send_invite: bool = True) -> Dict[str, str]:
        """
        Create a new user in the Cognito User Pool (Admin only)

        This creates a user with FORCE_CHANGE_PASSWORD status and optionally
        triggers a password reset email using admin_reset_user_password.

        Args:
            email: The email address for the new user
            temporary_password: Optional temporary password (will be auto-generated if not provided)
            send_invite: If True, use admin_reset_user_password to send reset email

        Returns:
            Dict with 'status', 'message', and optionally 'temporary_password'
        """
        try:
            # Build the parameters for admin_create_user
            create_user_params = {
                'UserPoolId': self.user_pool_id,
                'Username': email,
                'UserAttributes': [
                    {
                        'Name': 'email',
                        'Value': email
                    },
                    {
                        'Name': 'email_verified',
                        'Value': 'true'  # Mark email as verified since admin is creating
                    }
                ],
                'DesiredDeliveryMediums': ['EMAIL'],
                'MessageAction': 'SUPPRESS'  # Always suppress the welcome email
            }

            # Only include TemporaryPassword if one was explicitly provided
            # Otherwise, let Cognito generate a compliant password automatically
            if temporary_password:
                create_user_params['TemporaryPassword'] = temporary_password

            # Create the user with admin_create_user
            # If no TemporaryPassword is provided, Cognito generates one automatically
            response = self.client.admin_create_user(**create_user_params)

            logger.info(f"Successfully created user: {email}")

            result = {
                'status': 'SUCCESS',
                'message': f'User {email} created successfully',
                'user_id': response['User']['Username']
            }

            # Update message with instructions for the invited user
            if send_invite:
                import secrets
                import string

                # Generate a secure random password and set user to CONFIRMED state
                # User doesn't know this password, so they must use "Forgot Password"
                alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits + '!@#$%^&*'
                random_pass = (
                    secrets.choice(string.ascii_uppercase) +
                    secrets.choice(string.ascii_lowercase) +
                    secrets.choice(string.digits) +
                    secrets.choice('!@#$%^&*') +
                    ''.join(secrets.choice(alphabet) for _ in range(12))
                )

                # Set a permanent password to move user to CONFIRMED state
                # This allows forgot_password to work
                self.client.admin_set_user_password(
                    UserPoolId=self.user_pool_id,
                    Username=email,
                    Password=random_pass,
                    Permanent=True
                )
                logger.info(f"User set to CONFIRMED state: {email}")
                result['message'] = f'User {email} created successfully. The user should visit the login page and click "Forgot Password" to receive a password reset email.'
            else:
                if temporary_password:
                    result['temporary_password'] = temporary_password

            return result

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            logger.error(f"Error creating user {email}: {error_code} - {error_message}")

            # Provide user-friendly error messages
            if error_code == 'UsernameExistsException':
                return {
                    'status': 'ERROR',
                    'error': 'A user with this email already exists'
                }
            elif error_code == 'InvalidParameterException':
                return {
                    'status': 'ERROR',
                    'error': 'Invalid email format'
                }
            elif error_code == 'InvalidPasswordException':
                return {
                    'status': 'ERROR',
                    'error': 'Password does not meet requirements'
                }
            else:
                return {
                    'status': 'ERROR',
                    'error': error_message
                }

        except Exception as e:
            logger.error(f"Unexpected error creating user: {e}")
            return {
                'status': 'ERROR',
                'error': 'An unexpected error occurred'
            }


def get_cognito_client() -> CognitoClient:
    """
    Get the singleton Cognito client instance

    Returns:
        CognitoClient instance
    """
    global _cognito_client

    if _cognito_client is None:
        try:
            _cognito_client = CognitoClient()
            logger.info("Successfully initialized Cognito client")
        except Exception as e:
            logger.warning(f"Failed to initialize Cognito client: {e}")
            # Return None if Cognito is not configured
            return None

    return _cognito_client
