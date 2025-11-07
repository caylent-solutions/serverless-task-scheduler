from fastapi import APIRouter, Depends
from typing import Dict, Any, Optional, List, Union, Type
from pydantic import BaseModel, create_model, Field
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from ..models.target import Target, TargetList, TargetExecution, RouteChangedEvent
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
        """OpenAPI JSON endpoint"""
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
            response_model=Target
        )
        addrouter.add_api_route(
            f"/targets/{event.name}/_execute",
            create_execute_target(event.name, request_model),
            methods=["POST"],
            summary=f"Execute {event.name}",
            description=f"{event.description}",
            response_model=TargetExecution
        )
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