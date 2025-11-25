import json
import os
from mangum import Mangum
from .main import app

# Create Mangum handler for API Gateway events
# Let FastAPI's root_path handle the base path instead of Mangum
mangum_handler = Mangum(app, lifespan="off")

def handler(event, context):
    """
    Lambda handler that routes events appropriately:
    - API Gateway events -> Mangum (FastAPI)
    - EventBridge Scheduler events -> Already in API Gateway v2 format, pass to Mangum
    """

    # Log the event for debugging
    print(f"Received event: {json.dumps(event, default=str)[:1000]}...")
    print(f"API_BASE_PATH env var: {os.environ.get('API_BASE_PATH', 'NOT SET')}")

    # Check if this is already in API Gateway v2 format
    # API Gateway v2 format has 'version', 'routeKey', and 'requestContext'
    if event.get('version') == '2.0' and 'routeKey' in event and 'requestContext' in event:
        # This is already in API Gateway v2 format (either from API Gateway or EventBridge Scheduler)
        print("Processing as API Gateway v2 event")
        return mangum_handler(event, context)

    # Check if this is an EventBridge Scheduler event with detail
    if event.get('source') == 'aws.scheduler' and 'detail' in event:
        # EventBridge event - extract the detail
        print("Processing EventBridge Scheduler event from detail")
        try:
            if isinstance(event.get('detail'), str):
                api_gateway_event = json.loads(event['detail'])
            else:
                api_gateway_event = event['detail']

            return mangum_handler(api_gateway_event, context)
        except Exception as e:
            print(f"Error processing EventBridge Scheduler event: {e}")
            print(f"Full event: {json.dumps(event, default=str)}")
            raise

    # Otherwise, assume it's a direct API Gateway event
    print("Processing as direct API Gateway event")
    return mangum_handler(event, context)




