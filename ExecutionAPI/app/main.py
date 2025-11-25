from fastapi import FastAPI, Request
import pydantic
from .routers.targets import router as targets_router
from .routers.openapi import router as openapi_router
from .routers.tenants import router as tenants_router
from .routers.user import router as user_router
from .routers.auth import router as auth_router
from .models.target import RouteChangedEvent
from .awssdk.dynamodb import get_database_client
import logging
import time
import os
from fastapi_events.middleware import EventHandlerASGIMiddleware
from fastapi_events.handlers.local import local_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response, FileResponse, HTMLResponse
import mimetypes

# Configure logging - use the custom handler from __init__.py
logger = logging.getLogger("app")
logger.setLevel(logging.DEBUG)

# Set database target environment variable
# Options: 'memory', 'local' (default), or 'aws'
# os.environ['DB_TARGET'] = 'local'

# Get base path from environment (for API Gateway stage routing)
base_path = os.environ.get('API_BASE_PATH', '')

# Create FastAPI app with base path
app = FastAPI(
    title="Target Execution Service",
    description="API for managing and executing targets",
    version="1.0.0",
    servers=[{"url": "/"}],
    # docs_url=None,  # We'll create a custom docs endpoint
    #openapi_url="openapi.json",  # Disable FastAPI's built-in OpenAPI endpoint
    root_path=f"/{base_path}" if base_path else ""
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add middleware for request tracking
@app.middleware("http")
async def log_and_time_requests(request: Request, call_next):
    request_id = id(request)
    logger.info(f"Request started: {request.method} {request.url.path} (ID: {request_id})")
    start_time = time.time()
    
    try:
        # Optional authentication check for API routes only (not /app/ since React handles login page)
        # Check specific paths that need authentication:
        # - /user/* (user info, user management)
        # - /tenants/* (tenant management, includes all execution endpoints)
        # - POST/PUT/DELETE /targets/* (modifying targets - admin only)
        # But NOT:
        # - GET /targets/{id} (reading target specs should be public)
        # - /auth/* (login, signup, etc.)

        # Note: FastAPI's root_path already strips the base path from request.url.path,
        # so we should check paths without the base_path prefix
        # All /targets operations now require authentication (GET requires admin, POST/PUT/DELETE are mutating)
        path_needs_auth = (
            request.url.path.startswith("/user") or
            request.url.path.startswith("/tenants") or
            request.url.path.startswith("/targets")
        )

        if path_needs_auth:
            # Check for authentication in cookies or Authorization header
            auth_token = None
            
            # Check Authorization header
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                auth_token = auth_header[7:]
            
            # Check cookies
            if not auth_token:
                auth_token = request.cookies.get('idToken') or request.cookies.get('accessToken')

            # If authentication is configured, require valid token
            if os.environ.get('COGNITO_USER_POOL_ID'):
                if not auth_token:
                    # No token found - redirect to login
                    logger.warning(f"No authentication token found for {request.url.path}")
                    if request.url.path.startswith("/app"):
                        return RedirectResponse(url="/")
                    else:
                        from fastapi.responses import JSONResponse
                        return JSONResponse(
                            status_code=401,
                            content={"detail": "Authentication required"}
                        )
                
                # Verify the token
                try:
                    from .cognito_auth import get_token_verifier
                    verifier = get_token_verifier()
                    claims = verifier.verify_token(auth_token)
                    if not claims:
                        # Token verification failed - redirect to login for /app, return 401 for API
                        logger.warning(f"Invalid token for {request.url.path}")
                        if request.url.path.startswith("/app"):
                            return RedirectResponse(url="/")
                        else:
                            from fastapi.responses import JSONResponse
                            return JSONResponse(
                                status_code=401,
                                content={"detail": "Invalid or expired token"}
                            )
                    # Token is valid, attach user info to request
                    request.state.user = claims
                except ImportError:
                    # Cognito auth not available, proceed without authentication
                    logger.warning("Cognito auth module not available")
                    pass
                except Exception as e:
                    logger.error(f"Token verification error: {e}")
                    # Redirect to login on error
                    if request.url.path.startswith("/app"):
                        return RedirectResponse(url="/")
                    else:
                        from fastapi.responses import JSONResponse
                        return JSONResponse(
                            status_code=401,
                            content={"detail": "Authentication error"}
                        )
        
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"Request completed: {request.method} {request.url.path} (ID: {request_id}) - Status: {response.status_code} - Took: {process_time:.4f}s")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request failed: {request.method} {request.url.path} (ID: {request_id}) - Error: {str(e)} - Took: {process_time:.4f}s")
        raise

app.add_middleware(EventHandlerASGIMiddleware, handlers=[local_handler])


# Include routers
app.include_router(auth_router)
app.include_router(openapi_router)
app.include_router(targets_router)
app.include_router(tenants_router)
app.include_router(user_router)

# Cognito configuration endpoint
@app.get("/config/cognito", include_in_schema=False)
async def get_cognito_config():
    """Return Cognito configuration for the frontend"""
    return {
        "UserPoolId": os.environ.get('COGNITO_USER_POOL_ID', ''),
        "ClientId": os.environ.get('COGNITO_CLIENT_ID', ''),
        "Region": os.environ.get('COGNITO_REGION', 'us-east-1')
    }

# Root endpoint - redirect to app (React will handle showing login page if not authenticated)
@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Redirect to app"""
    base_url = str(request.base_url).rstrip('/')
    return RedirectResponse(url=f"{base_url}/app/", status_code=302)

# Old logout endpoint kept for backwards compatibility - just clears cookies now
@app.get("/logout", include_in_schema=False)
async def logout_legacy(response: Response):
    """Clear authentication cookies (legacy endpoint)"""
    response.delete_cookie("idToken")
    response.delete_cookie("accessToken")
    response.delete_cookie("refreshToken")
    return RedirectResponse(url="/app/")

# Custom static file serving for React app (StaticFiles doesn't work well with Mangum/Lambda)
wwwroot_path = os.path.join(os.path.dirname(__file__), "wwwroot")
logger.info(f"Setting up custom static file serving at /app with directory: {wwwroot_path}")
logger.info(f"Directory exists: {os.path.exists(wwwroot_path)}")
if os.path.exists(wwwroot_path):
    logger.info(f"Directory contents: {os.listdir(wwwroot_path)}")

@app.get("/app/{file_path:path}")
async def serve_react_app(file_path: str):
    """
    Serve React app static files.
    For directory requests or unknown files, serve index.html (SPA routing).
    """
    # Security: Validate and sanitize file path to prevent directory traversal
    # Strip leading/trailing slashes and whitespace
    file_path = file_path.strip().strip("/")

    # If no file path or ends with /, serve index.html
    if not file_path or file_path.endswith("/"):
        file_path = "index.html"
        logger.info(f"Serving index.html for empty or directory path")

    # Reject any path containing directory traversal patterns
    # This includes ., .., encoded variants, and backslashes
    dangerous_patterns = ['..', '/./', '/../', '\\', '%2e', '%2f', '%5c']
    if any(pattern in file_path.lower() for pattern in dangerous_patterns):
        logger.warning(f"Path traversal attempt blocked: {file_path}")
        return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

    # Additional check: ensure path doesn't start with dangerous characters
    if file_path.startswith(('.', '/')):
        logger.warning(f"Invalid path rejected: {file_path}")
        return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

    try:
        # Build the full path using os.path.join
        full_path = os.path.normpath(os.path.join(wwwroot_path, file_path))

        # Security check: Ensure the resolved path is within wwwroot directory
        # Use os.path.commonpath to verify the file is in the allowed directory
        wwwroot_realpath = os.path.realpath(wwwroot_path)
        full_realpath = os.path.realpath(full_path)

        # Ensure common path is exactly the wwwroot (prevents traversal)
        if os.path.commonpath([wwwroot_realpath, full_realpath]) != wwwroot_realpath:
            logger.warning(f"Path outside wwwroot blocked: {file_path}")
            return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

        # Additional security: Ensure full_realpath actually starts with wwwroot_realpath
        if not full_realpath.startswith(wwwroot_realpath + os.sep) and full_realpath != wwwroot_realpath:
            logger.warning(f"Path traversal attempt blocked after resolution: {file_path}")
            return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

    except (ValueError, OSError) as e:
        logger.error(f"Error resolving path: {e}")
        return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

    # If file exists, serve it
    if os.path.isfile(full_path):
        # Determine media type
        media_type, _ = mimetypes.guess_type(full_path)
        logger.info(f"Serving file: {os.path.basename(full_path)} with media_type: {media_type}")
        return FileResponse(full_path, media_type=media_type)

    # If file doesn't exist, serve index.html (for SPA client-side routing)
    index_path = os.path.join(wwwroot_path, "index.html")
    if os.path.isfile(index_path):
        logger.info(f"File not found, serving index.html for SPA routing: {file_path}")
        return FileResponse(index_path, media_type="text/html")

    # If even index.html doesn't exist, return 404
    logger.error(f"File not found and no index.html: {file_path}")
    return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

# Override FastAPI's openapi() method to inject dynamic target schemas
def custom_openapi():
    """Custom OpenAPI schema generator that injects dynamic target schemas"""
    if app.openapi_schema:
        return app.openapi_schema

    from .routers.openapi import helpers
    try:
        # Generate the OpenAPI schema with all routes
        db_client = get_database_client()
        openapi_schema = helpers.get_open_api_endpoint(app_routes=app.routes, db=db_client)

        # Cache it
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    except Exception as e:
        logger.error(f"Error generating OpenAPI schema: {e}")
        # Return a minimal schema if generation fails
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "Target Execution Service - API Documentation",
                "version": "1.0.0",
                "description": "API for managing and executing targets"
            },
            "paths": {},
            "components": {}
        }

# Replace FastAPI's openapi method with our custom one
app.openapi = custom_openapi


@local_handler.register(event_name="route-added")
def handle_route_added_event(event: RouteChangedEvent):
    from .routers.openapi import OpenAPIHelpers
    logger.warning(f"Handling route added event: {event[1].name} - {event[1].description} at {event[1].path}")
    app.openapi_schema = None
    helpers = OpenAPIHelpers(app.router)

    app.include_router(helpers.add_dynamic_route(event[1]))
    for route in app.routes:
        print(f"path: {route.path}, name: {route.name}, methods: {list(route.methods)}")    
        
    helpers.get_open_api_endpoint()  # Ensure OpenAPI is updated

@local_handler.register(event_name="route-deleted")
def handle_route_deleted_event(event: RouteChangedEvent):
    from .routers.openapi import OpenAPIHelpers
    logger.warning(f"Handling route deleted event: {event[1].name} - {event[1].description} at {event[1].path}")

    app.routes[:] = [route for route in app.routes if route.path != event[1].path]
    app.routes[:] = [route for route in app.routes if route.path != (event[1].path + "/_execute")]

    app.openapi_schema = None
    helpers = OpenAPIHelpers(app.router)

    for route in app.routes:
        print(f"path: {route.path}, name: {route.name}, methods: {list(route.methods)}")    
        
    helpers.get_open_api_endpoint()  # Ensure OpenAPI is updated


_init_done = False

def initialize_admin_tenant():
    """Initialize the admin tenant, create owner in Cognito, and assign the owner to it"""
    try:
        db_client = get_database_client()

        # Get the admin/owner email from environment
        admin_email = os.environ.get('ADMIN_USER_EMAIL', '')
        if not admin_email:
            logger.warning("No ADMIN_USER_EMAIL configured - skipping admin tenant initialization")
            return

        # Check if admin tenant exists
        admin_tenant = db_client.get_tenant('admin')
        if not admin_tenant:
            logger.info("Creating 'admin' tenant...")
            from .models.tenant import Tenant
            db_client.create_tenant({
                'tenant_id': 'admin',
                'tenant_name': 'admin',
                'tenant_description': 'Administrative tenant for system administrators',
                'create_user': 'system',
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            })
            logger.info("Admin tenant created successfully")
        else:
            logger.info("Admin tenant already exists")

        # Create owner in Cognito if they don't exist
        try:
            from .awssdk.cognito import get_cognito_client
            cognito = get_cognito_client()

            if cognito:
                # Check if user exists in Cognito
                existing_user = cognito.get_user(admin_email)

                if not existing_user:
                    logger.info(f"Creating Cognito user for owner: {admin_email}")
                    result = cognito.create_user(
                        email=admin_email,
                        send_invite=True  # Triggers password reset flow
                    )

                    if result['status'] == 'SUCCESS':
                        logger.info(f"Owner {admin_email} created in Cognito successfully")
                        logger.info(f"Password reset email sent to {admin_email}")
                    else:
                        logger.warning(f"Failed to create owner in Cognito: {result.get('error', 'Unknown error')}")
                else:
                    logger.info(f"Owner {admin_email} already exists in Cognito")
            else:
                logger.warning("Cognito client not available - skipping Cognito user creation")

        except Exception as e:
            logger.warning(f"Error creating owner in Cognito: {e}")
            # Don't fail if Cognito setup fails - user can be invited manually

        # Check if owner is mapped to admin tenant
        user_tenants = db_client.get_user_tenants(admin_email)
        if 'admin' not in user_tenants:
            logger.info(f"Mapping {admin_email} to admin tenant...")
            db_client.create_user_mapping(
                user_id=admin_email,
                tenant_id='admin',
                create_user='system'
            )
            logger.info(f"Owner {admin_email} mapped to admin tenant successfully")
        else:
            logger.info(f"Owner {admin_email} already mapped to admin tenant")

    except Exception as e:
        logger.error(f"Error initializing admin tenant: {e}")
        # Don't fail startup if admin initialization fails
        pass


@app.on_event("startup")
def load_targets_on_startup():
    from .routers.openapi import OpenAPIHelpers
    """Load all targets from the database and register them on startup"""

    global _init_done
    if _init_done:
        logger.info("Targets already loaded on startup")
        return
    # build models & routes exactly once
    _init_done = True

    logger.info("Loading targets on startup")

    # Initialize admin tenant before loading targets
    initialize_admin_tenant()

    db_client = get_database_client()
    targets = db_client.get_all_targets()
    helpers = OpenAPIHelpers(app.router)
    for target in targets:
        logger.info(f"Registering target: {target['target_id']}")
        # Dispatch route-added event for each target
        event = RouteChangedEvent(
            name=target['target_id'],
            description=target['target_description'],
            path=f"/targets/{target['target_id']}",
            parameters=target['target_parameter_schema']
        )
        app.include_router(helpers.add_dynamic_route(event))
    logger.info(f"Loaded {len(targets)} targets on startup")
    app.openapi_schema = None  # Reset OpenAPI schema

    # helpers.get_open_api_endpoint()  # Ensure OpenAPI is updated