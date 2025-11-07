import boto3
import os

def get_aws_credentials():
    """Get AWS credentials from SSO or environment variables"""
    try:
        # Try to use default SSO profile first
        session = boto3.Session(profile_name='default')
        credentials = session.get_credentials()
        if credentials:
            frozen_credentials = credentials.get_frozen_credentials()
            return {
                'aws_access_key_id': frozen_credentials.access_key,
                'aws_secret_access_key': frozen_credentials.secret_key,
                'aws_session_token': frozen_credentials.token
            }
    except Exception:
        pass

    # Fall back to access keys
    return {
        'aws_access_key_id': os.environ.get('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': os.environ.get('AWS_SECRET_ACCESS_KEY')
    }