from fastapi import APIRouter, Depends
from typing import Dict, Any, Optional, List, Union, Type
from pydantic import BaseModel, create_model, Field
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from ..models.target import Target, TargetList, TargetExecution, RouteChangedEvent, TargetWithExecutionInfo
from .targets import create_get_target, create_execute_target
from ..awssdk.dynamodb import get_database_client
import logging
import json

router = APIRouter()
logger = logging.getLogger("app.routers.openapi")

class OpenAPIHelpers:
    """Helper class for OpenAPI related functionality"""
    def __init__(self, router: APIRouter):
        self.router = router
        self.targets_list = []

    def swagger_ui(self):
        """Root endpoint with Swagger UI"""
        return get_swagger_ui_html(
            # Use a relative URL so it respects API Gateway stage/root_path (e.g., /dev)
            openapi_url="openapi.json",
            title="Target Execution Service - API Documentation",
            swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.5.0/swagger-ui-bundle.js",
            swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.5.0/swagger-ui.css",
        )
    
    def health_check(self):
        """Health check endpoint"""
        return {"status": "healthy"}

    def get_open_api_endpoint(self, app_routes=None, db=get_database_client()):
        """OpenAPI JSON endpoint with dynamically injected target schemas"""
        # Use the main app's routes if provided, otherwise fall back to router routes
        routes_to_use = app_routes if app_routes is not None else self.router.routes

        try:
            # Force FastAPI to regenerate the OpenAPI schema by creating a new schema each time
            openapi_schema = get_openapi(
                title="Target Execution Service - API Documentation",
                version="1.0.0",
                description="API for managing and executing targets",
                routes=routes_to_use,
                servers=[{"url": "/"}],
            )

            # Enhance the schema with dynamic target parameter schemas
            openapi_schema = self._inject_target_schemas(openapi_schema, db)

        except Exception as e:
            logger.error(f"Error generating OpenAPI schema: {e.__str__()}")
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

        return openapi_schema
    
    def get_pydantic_schema(self, schema: Union[Dict[str, Any], str], model_name: str = "DynamicModel") -> Type[BaseModel]:
        """
        Convert a target parameter schema into a Pydantic model.
        
        Args:
            schema: The schema definition (dict or JSON string)
            model_name: Name for the generated model
            
        Returns:
            A Pydantic model class
        """
        try:
            # Parse schema if it's a string
            if isinstance(schema, str):
                try:
                    schema_obj = json.loads(schema)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse schema string: {str(e)}")
                    return create_model(model_name)
            else:
                schema_obj = schema

            # Extract properties and required fields
            properties = {}
            
            try:
                # Handle target_parameter_schema format
                if "parameters" in schema_obj and "properties" in schema_obj["parameters"]:
                    properties = self._handle_parameter_schema(schema_obj["parameters"], properties)
                # Handle targetSchema format
                elif "targets" in schema_obj:
                    for tgt in schema_obj["targets"]:
                        if "parameters" in tgt and "properties" in tgt["parameters"]:
                            properties = self._handle_parameter_schema(tgt["parameters"], properties)
                # Handle direct properties format
                elif "properties" in schema_obj:
                    for param_name, param_details in schema_obj["properties"].items():
                        field_type = str  # Default type
                        field_description = param_details.get("description", "")
                        field_default = ... if param_name in schema_obj.get("required", []) or param_details.get("required", False) else None
                        
                        properties[param_name] = self._get_field_type_and_props(
                            param_details, field_type, field_description, field_default
                        )
                else:
                    logger.warning(f"Schema format not recognized for model {model_name}")
                    return create_model(model_name)

                # Create and return the model
                logger.info(f"creating model with properties: {model_name} {properties}")
                return create_model(model_name, **properties)

            except KeyError as e:
                logger.error(f"Missing required key in schema: {str(e)}")
                return create_model(model_name)
            except TypeError as e:
                logger.error(f"Invalid type in schema: {str(e)}")
                return create_model(model_name)

        except Exception as e:
            logger.error(f"Unexpected error processing schema for model {model_name}: {str(e)}")
            return create_model(model_name)

    def _handle_parameter_schema(self, param_schema: Dict, properties: Dict) -> Dict:
        """Helper method to process parameter schema format"""
        try:
            for param_name, param_details in param_schema["properties"].items():
                field_type = str  # Default type
                field_description = param_details.get("description", "")
                field_default = ... if param_details.get("required", False) else None
                
                properties[param_name] = self._get_field_type_and_props(
                    param_details, field_type, field_description, field_default
                )
            return properties
        except Exception as e:
            logger.error(f"Error processing parameter schema: {str(e)}")
            return properties

    def _get_field_type_and_props(self, details: Dict, default_type: Type, description: str, default_value: Any) -> tuple:
        """Helper method to determine field type and create property tuple"""
        try:
            field_type = default_type
            if details.get("type") == "integer":
                field_type = int
            elif details.get("type") == "number":
                field_type = float
            elif details.get("type") == "boolean":
                field_type = bool

            return (
                Optional[field_type] if default_value is None else field_type,
                Field(default=default_value, description=description)
            )
        except Exception as e:
            logger.error(f"Error determining field type: {str(e)}")
            return (Optional[default_type], Field(default=None, description=description))

    def _inject_target_schemas(self, openapi_schema: Dict[str, Any], db) -> Dict[str, Any]:
        """
        Inject target-specific parameter schemas into the OpenAPI spec for execution endpoints.

        This enhances the generic execution endpoint documentation by replacing the generic
        Dict[str, Any] schema with the actual target_parameter_schema from DynamoDB.

        Args:
            openapi_schema: The base OpenAPI schema from FastAPI
            db: Database client to fetch target schemas

        Returns:
            Enhanced OpenAPI schema with target-specific request body schemas
        """
        try:
            # Get all tenant mappings to know which target_alias -> target_id mappings exist
            # We'll create schema components for each unique target
            targets_cache = {}  # target_id -> target_parameter_schema

            # Fetch all targets from database
            try:
                targets = db.get_all_targets()
                for target in targets:
                    target_id = target.get('target_id')
                    target_schema = target.get('target_parameter_schema', {})
                    if target_id and target_schema:
                        targets_cache[target_id] = target_schema
            except Exception as e:
                logger.error(f"Failed to fetch targets for OpenAPI schema enhancement: {e}")
                return openapi_schema

            # Find and enhance the execution endpoint in the paths
            paths = openapi_schema.get('paths', {})

            # Also enhance GET /targets/{target_id} endpoints with real schemas as examples
            for path, path_item in paths.items():
                if path.startswith('/targets/') and '{' not in path.replace('/targets/', '', 1):
                    # This is a specific target endpoint like /targets/calculator
                    target_id = path.replace('/targets/', '')
                    if target_id in targets_cache:
                        get_operation = path_item.get('get', {})
                        if get_operation:
                            # Replace the $ref with an inline schema that includes the actual target_parameter_schema
                            responses = get_operation.get('responses', {})
                            success_response = responses.get('200', {})
                            content = success_response.get('content', {})
                            app_json = content.get('application/json', {})

                            # Get the actual target description from the target data
                            target_description = None
                            for t in targets:
                                if t.get('target_id') == target_id:
                                    target_description = t.get('target_description', f'Target for {target_id}')
                                    break

                            # Wrap the target_parameter_schema to make it render properly in Swagger
                            target_param_schema = targets_cache[target_id]

                            # Flatten the schema if it's nested under 'schema' key
                            if isinstance(target_param_schema, dict) and 'schema' in target_param_schema:
                                target_param_schema = target_param_schema['schema']

                            # Replace the $ref with an inline schema definition
                            # For target_parameter_schema, we embed the actual schema directly so Swagger renders it properly
                            app_json['schema'] = {
                                'type': 'object',
                                'required': ['target_id', 'target_description', 'target_parameter_schema', 'execution_endpoint', 'execution_method', 'execution_requires_tenant_context'],
                                'properties': {
                                    'target_id': {
                                        'type': 'string',
                                        'example': target_id
                                    },
                                    'target_description': {
                                        'type': 'string',
                                        'example': target_description or f'Target for {target_id}'
                                    },
                                    'target_parameter_schema': target_param_schema,
                                    'execution_endpoint': {
                                        'type': 'string',
                                        'example': '/tenants/{tenant_id}/mappings/{target_alias}/_execute',
                                        'description': f'The URL template to POST to for execution. Replace {{tenant_id}} with actual tenant ID and {{target_alias}} with "{target_id}"'
                                    },
                                    'execution_method': {
                                        'type': 'string',
                                        'example': 'POST',
                                        'description': 'HTTP method for execution'
                                    },
                                    'execution_requires_tenant_context': {
                                        'type': 'boolean',
                                        'example': True,
                                        'description': 'Whether tenant context is required for execution'
                                    }
                                }
                            }

                            content['application/json'] = app_json
                            success_response['content'] = content
                            responses['200'] = success_response
                            get_operation['responses'] = responses
                            path_item['get'] = get_operation
                            paths[path] = path_item

            # Look for the execution endpoint pattern: /tenants/{tenant_id}/mappings/{target_alias}/_execute
            for path, path_item in paths.items():
                if '/mappings/{target_alias}/_execute' in path:
                    # This is an execution endpoint
                    post_operation = path_item.get('post', {})

                    if post_operation:
                        # Update the description to indicate dynamic schema
                        current_description = post_operation.get('description', '')
                        post_operation['description'] = (
                            f"{current_description}\n\n"
                            "**Note**: The request body schema shown here is generic. "
                            "The actual required parameters depend on the target being executed. "
                            "Use GET /targets/{{target_id}} to see the specific parameter schema for each target."
                        )

                        # Add schema information to request body
                        request_body = post_operation.get('requestBody', {})
                        if request_body:
                            content = request_body.get('content', {})
                            app_json = content.get('application/json', {})

                            # Add a note about dynamic schemas
                            app_json['schema'] = {
                                'type': 'object',
                                'description': (
                                    'Execution parameters. The required parameters vary by target. '
                                    'Query the target definition via GET /targets/{target_id} to see '
                                    'the target_parameter_schema field for specific requirements.'
                                ),
                                'additionalProperties': True,
                                'example': {
                                    'param1': 'value1',
                                    'param2': 123,
                                    'note': 'Parameters vary by target - see target_parameter_schema'
                                }
                            }

                            content['application/json'] = app_json
                            request_body['content'] = content
                            post_operation['requestBody'] = request_body

                    path_item['post'] = post_operation
                    paths[path] = path_item

            # Add schema components for common target schemas (if we want to define them)
            if 'components' not in openapi_schema:
                openapi_schema['components'] = {}
            if 'schemas' not in openapi_schema['components']:
                openapi_schema['components']['schemas'] = {}

            # Add a generic example schema component
            openapi_schema['components']['schemas']['TargetExecutionParameters'] = {
                'type': 'object',
                'description': 'Dynamic parameters based on target_parameter_schema',
                'additionalProperties': True,
                'example': {
                    'note': 'Schema varies by target. Query GET /targets/{target_id} for specific schema'
                }
            }

            openapi_schema['paths'] = paths

        except Exception as e:
            logger.error(f"Error injecting target schemas: {e}")
            # Return unmodified schema on error

        return openapi_schema


    def add_dynamic_route(self, event: RouteChangedEvent) -> APIRouter:
        # Create a Pydantic model for the request body (we use event.name here because they need unique names)
        try:
            request_model: Type[BaseModel] = self.get_pydantic_schema(event.parameters, event.name)
        except Exception as e:
            logger.error(f"Failed to create request model for {event.name}: {str(e)}")
            request_model = create_model(event.name)
        addrouter = APIRouter()
        addrouter.add_api_route(
            f"/targets/{event.name}",
            create_get_target(event.name),
            methods=["GET"],
            summary=f"Get info for {event.name}",
            description=f"{event.description}",
            response_model=TargetWithExecutionInfo
        )
        # Note: Direct execution via /targets/{target_id}/_execute has been removed
        # All executions must go through tenant context: /tenants/{tenant_id}/targets/{target_id}/_execute
        return addrouter



helpers = OpenAPIHelpers(router)

@router.get("/swagger", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return helpers.swagger_ui()

@router.get("/health")
async def health_check():
    return helpers.health_check()

# @router.get("/openapi.json", include_in_schema=False)
# def get_open_api_endpoint():
#     db_client = get_database_client()
#     functions = db_client.get_all_functions()
#     for function in functions:
#         logger.info(f"Registering function: {function['function_id']}")
#         # Dispatch route-added event for each function
#         event = RouteChangedEvent(
#             name=function['function_id'],
#             description=function['function_description'],
#             path=f"/functions/{function['function_id']}",
#             parameters=function['function_parameter_schema']
#         )
#         router.include_router(helpers.add_dynamic_route(event))
    
#     return helpers.get_open_api_endpoint()