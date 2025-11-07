import boto3
import os

# Singleton session instance
_session = None

def get_session():
    global _session
    if _session is None:
        _session = boto3.Session()
    return _session