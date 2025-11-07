"""
Authentication router for Cognito-based login/signup
"""
from fastapi import APIRouter, HTTPException, Response, Depends
from pydantic import BaseModel, EmailStr
import boto3
import os
import logging
from botocore.exceptions import ClientError

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger("app")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class ConfirmSignupRequest(BaseModel):
    email: EmailStr
    confirmation_code: str


class LoginResponse(BaseModel):
    access_token: str
    id_token: str
    refresh_token: str
    token_type: str = "Bearer"


class MessageResponse(BaseModel):
    message: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ConfirmForgotPasswordRequest(BaseModel):
    email: EmailStr
    confirmation_code: str
    new_password: str


def get_cognito_client():
    """Get boto3 Cognito IDP client"""
    return boto3.client('cognito-idp', region_name=os.environ.get('COGNITO_REGION', 'us-east-1'))


@router.post("/login", response_model=LoginResponse)
async def login(credentials: LoginRequest, response: Response):
    """
    Authenticate user with email and password using Cognito
    """
    client_id = os.environ.get('COGNITO_CLIENT_ID')
    
    if not client_id:
        raise HTTPException(status_code=500, detail="Cognito not configured")
    
    client = get_cognito_client()
    
    try:
        # Initiate auth with USER_PASSWORD_AUTH flow
        auth_response = client.initiate_auth(
            ClientId=client_id,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': credentials.email,
                'PASSWORD': credentials.password
            }
        )
        
        # Extract tokens
        tokens = auth_response['AuthenticationResult']
        
        logger.info(f"User {credentials.email} logged in successfully")
        
        # Set tokens as HTTP-only cookies
        response.set_cookie(
            key="idToken",
            value=tokens['IdToken'],
            httponly=True,
            secure=True,
            samesite='lax',
            max_age=3600  # 1 hour
        )
        
        response.set_cookie(
            key="accessToken",
            value=tokens['AccessToken'],
            httponly=True,
            secure=True,
            samesite='lax',
            max_age=3600  # 1 hour
        )
        
        if 'RefreshToken' in tokens:
            response.set_cookie(
                key="refreshToken",
                value=tokens['RefreshToken'],
                httponly=True,
                secure=True,
                samesite='lax',
                max_age=2592000  # 30 days
            )
        
        return LoginResponse(
            access_token=tokens['AccessToken'],
            id_token=tokens['IdToken'],
            refresh_token=tokens.get('RefreshToken', ''),
            token_type="Bearer"
        )
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error'].get('Message', '')
        logger.error(f"Login failed for {credentials.email}: {error_code} - {error_message}")
        
        if error_code == 'NotAuthorizedException':
            raise HTTPException(status_code=401, detail="Invalid email or password")
        elif error_code == 'UserNotConfirmedException':
            raise HTTPException(status_code=403, detail="User email not confirmed")
        elif error_code == 'UserNotFoundException':
            raise HTTPException(status_code=401, detail="Invalid email or password")
        elif error_code == 'InvalidParameterException':
            raise HTTPException(status_code=500, detail=f"Configuration error: {error_message}")
        else:
            raise HTTPException(status_code=500, detail=f"Authentication failed: {error_code}")


@router.post("/signup", response_model=MessageResponse)
async def signup(user: SignupRequest):
    """
    Register a new user with Cognito (DISABLED)

    DEPRECATED: This endpoint is disabled for security reasons.
    User creation must be done through the /user/management/invite endpoint by an administrator.
    Please contact your administrator to be invited to the platform.
    """
    raise HTTPException(
        status_code=403,
        detail="Direct signup is disabled. Please contact an administrator to be invited to the platform."
    )


@router.post("/confirm-signup", response_model=MessageResponse)
async def confirm_signup(confirmation: ConfirmSignupRequest):
    """
    Confirm user email with verification code sent during signup
    """
    client_id = os.environ.get('COGNITO_CLIENT_ID')
    
    if not client_id:
        raise HTTPException(status_code=500, detail="Cognito not configured")
    
    client = get_cognito_client()
    
    try:
        client.confirm_sign_up(
            ClientId=client_id,
            Username=confirmation.email,
            ConfirmationCode=confirmation.confirmation_code
        )
        
        logger.info(f"User {confirmation.email} confirmed successfully")
        
        return MessageResponse(message="Email verified successfully. You can now log in.")
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"Confirmation failed for {confirmation.email}: {error_code}")
        
        if error_code == 'CodeMismatchException':
            raise HTTPException(status_code=400, detail="Invalid verification code")
        elif error_code == 'ExpiredCodeException':
            raise HTTPException(status_code=400, detail="Verification code has expired")
        elif error_code == 'NotAuthorizedException':
            raise HTTPException(status_code=400, detail="User is already confirmed")
        else:
            raise HTTPException(status_code=500, detail=f"Confirmation failed: {error_code}")


@router.post("/resend-confirmation", response_model=MessageResponse)
async def resend_confirmation(user: dict):
    """
    Resend verification code to user's email
    """
    client_id = os.environ.get('COGNITO_CLIENT_ID')
    
    if not client_id:
        raise HTTPException(status_code=500, detail="Cognito not configured")
    
    email = user.get('email')
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    client = get_cognito_client()
    
    try:
        client.resend_confirmation_code(
            ClientId=client_id,
            Username=email
        )
        
        logger.info(f"Verification code resent to {email}")
        
        return MessageResponse(message="Verification code sent to your email.")
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"Resend confirmation failed for {email}: {error_code}")
        
        if error_code == 'UserNotFoundException':
            raise HTTPException(status_code=404, detail="User not found")
        elif error_code == 'InvalidParameterException':
            raise HTTPException(status_code=400, detail="User is already confirmed")
        else:
            raise HTTPException(status_code=500, detail=f"Resend failed: {error_code}")


@router.post("/logout", response_model=MessageResponse)
async def logout_endpoint(response: Response):
    """
    Logout user by clearing cookies
    """
    response.delete_cookie("idToken")
    response.delete_cookie("accessToken")
    response.delete_cookie("refreshToken")

    logger.info("User logged out")

    return MessageResponse(message="Logged out successfully")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Initiate forgot password flow - sends verification code to user's email
    """
    from ..awssdk.cognito import get_cognito_client as get_cognito_sdk_client

    cognito = get_cognito_sdk_client()
    if not cognito:
        raise HTTPException(status_code=500, detail="Cognito not configured")

    result = cognito.forgot_password(request.email)

    if result['status'] == 'SUCCESS':
        return MessageResponse(message=result['message'])
    else:
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed to initiate password reset'))


@router.post("/confirm-forgot-password", response_model=MessageResponse)
async def confirm_forgot_password(request: ConfirmForgotPasswordRequest):
    """
    Confirm forgot password with verification code and set new password
    """
    from ..awssdk.cognito import get_cognito_client as get_cognito_sdk_client

    cognito = get_cognito_sdk_client()
    if not cognito:
        raise HTTPException(status_code=500, detail="Cognito not configured")

    result = cognito.confirm_forgot_password(
        request.email,
        request.confirmation_code,
        request.new_password
    )

    if result['status'] == 'SUCCESS':
        return MessageResponse(message=result['message'])
    else:
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed to reset password'))
