#!/bin/bash
# Quick Deploy Script for Agentic Functions
# This script builds the UI, copies assets, validates, builds, and deploys the SAM application

# Set AWS profile and region
export AWS_PROFILE=cy
export AWS_DEFAULT_REGION=us-east-1
export STACK_NAME=ireis-sts-dev

# Color codes
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}Starting Quick Deploy Process${NC}"
echo -e "${CYAN}========================================${NC}"

# Step 1: Build the UI
echo -e "\n${YELLOW}[1/5] Building UI...${NC}"
(
    cd ui || exit 1
    npm run build
    if [ $? -ne 0 ]; then
        echo -e "${RED}UI build failed!${NC}"
        exit 1
    fi
    echo -e "${GREEN}UI build completed successfully.${NC}"
)

if [ $? -ne 0 ]; then
    exit 1
fi

# Step 2: Copy assets to wwwroot
echo -e "\n${YELLOW}[2/5] Copying assets to wwwroot...${NC}"
sourcePath="ui/build"
destPath="ExecutionAPI/app/wwwroot"

# Remove existing wwwroot contents completely
if [ -d "$destPath" ]; then
    echo -e "${GRAY}Removing existing wwwroot contents...${NC}"
    rm -rf "${destPath:?}"/*
else
    echo -e "${GRAY}Creating wwwroot directory...${NC}"
    mkdir -p "$destPath"
fi

# Copy new build
cp -r "${sourcePath}"/* "$destPath"
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to copy assets!${NC}"
    exit 1
fi
echo -e "${GREEN}Assets copied successfully.${NC}"

# Step 3: SAM Validate
echo -e "\n${YELLOW}[3/5] Validating SAM template...${NC}"
sam validate --lint
if [ $? -ne 0 ]; then
    echo -e "${RED}SAM validation failed!${NC}"
    exit 1
fi
echo -e "${GREEN}SAM validation completed successfully.${NC}"

# Step 4: SAM Build
echo -e "\n${YELLOW}[4/5] Building SAM application...${NC}"
sam build
if [ $? -ne 0 ]; then
    echo -e "${RED}SAM build failed!${NC}"
    exit 1
fi
echo -e "${GREEN}SAM build completed successfully.${NC}"

# Step 5: SAM Deploy
echo -e "\n${YELLOW}[5/5] Deploying SAM application...${NC}"
# The --no-fail-on-empty-changeset flag will prevent deployment error if no changes detected
sam deploy --no-confirm-changeset --no-fail-on-empty-changeset
if [ $? -ne 0 ]; then
    echo -e "${RED}SAM deployment failed!${NC}"
    exit 1
fi
echo -e "${GREEN}SAM deployment completed successfully.${NC}"

echo -e "\n${CYAN}========================================${NC}"
echo -e "${CYAN}Quick Deploy Completed Successfully!${NC}"
echo -e "${CYAN}========================================${NC}"

# Get stack outputs
echo -e "\n${YELLOW}Getting deployment information...${NC}"
apiUrl=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
userPoolId=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text)
clientId=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolClientId'].OutputValue" --output text)

if [ -n "$apiUrl" ] && [ -n "$userPoolId" ] && [ -n "$clientId" ]; then
    echo -e "\n${GREEN}Application URL: ${NC}${CYAN}${apiUrl}${NC}"
    
    # Step 6: Configure Cognito logout URLs
    echo -e "\n${YELLOW}[6/6] Configuring Cognito logout and callback URLs...${NC}"
    
    callbackUrl="${apiUrl}callback"
    logoutUrl="${apiUrl}app/"
    
    echo -e "${GRAY}Callback URL: $callbackUrl${NC}"
    echo -e "${GRAY}Logout URL: $logoutUrl${NC}"
    
    # Update the User Pool Client with logout URLs and auth flows
    aws cognito-idp update-user-pool-client \
        --user-pool-id "$userPoolId" \
        --client-id "$clientId" \
        --callback-urls "$callbackUrl" \
        --logout-urls "$logoutUrl" \
        --explicit-auth-flows "ALLOW_USER_SRP_AUTH" "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" \
        --allowed-o-auth-flows "code" \
        --allowed-o-auth-scopes "openid" "email" "profile" \
        --allowed-o-auth-flows-user-pool-client \
        --supported-identity-providers "COGNITO" > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Cognito logout URLs configured successfully.${NC}"
    else
        echo -e "${YELLOW}Warning: Failed to configure Cognito logout URLs.${NC}"
        echo -e "${YELLOW}You may need to manually add the logout URL in the AWS Console:${NC}"
        echo -e "${WHITE}  Logout URL: $logoutUrl${NC}"
    fi
    
    echo -e "\n${WHITE}Click to open: $apiUrl${NC}"
else
    echo -e "${YELLOW}Could not retrieve required information from stack outputs.${NC}"
fi

