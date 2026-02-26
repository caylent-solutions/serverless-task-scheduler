#!/bin/bash
# Quick Deploy Script for Serverless Task Scheduler (STS)
# This script builds the UI, copies assets, validates, builds, and deploys the SAM application
#
# Usage:
#   ./quickdeploy.sh                        Deploy primary region (default samconfig profile)
#   ./quickdeploy.sh --dr-region us-west-2  Deploy DR region (dr samconfig profile)
#                                           Fetches GlobalTable names from primary stack and
#                                           passes them as ExistingXxxTable parameters so the
#                                           DR stack reuses replicated tables instead of creating new ones.

# Color codes
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# ----------------------------------------------------------------------------
# Parse arguments
# ----------------------------------------------------------------------------
DR_REGION=""
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --dr-region) DR_REGION="$2"; shift 2 ;;
        *) echo -e "${RED}Unknown argument: $1${NC}"; echo "Usage: $0 [--dr-region REGION]"; exit 1 ;;
    esac
done

# ----------------------------------------------------------------------------
# Helper: read a value from a specific samconfig.toml section
# Usage: get_toml_value "default.deploy.parameters" "stack_name"
# ----------------------------------------------------------------------------
get_toml_value() {
    local section="[$1]"
    local key="$2"
    awk -v s="$section" -v k="$key" '
        { gsub(/\r$/, "") }
        $0 == s { found=1; next }
        /^\[/   { found=0 }
        found && $0 ~ "^" k "[[:space:]]*=" {
            gsub(/^[^=]*=[[:space:]]*"|"[[:space:]]*$/, "")
            print
            exit
        }
    ' samconfig.toml
}

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}Starting Quick Deploy Process${NC}"
if [ -n "$DR_REGION" ]; then
    echo -e "${CYAN}Mode: DR region ($DR_REGION)${NC}"
else
    echo -e "${CYAN}Mode: Primary region${NC}"
fi
echo -e "${CYAN}========================================${NC}"

# Check for samconfig.toml
if [ ! -f "samconfig.toml" ]; then
    echo -e "${RED}Error: samconfig.toml not found${NC}"
    exit 1
fi

# Determine config profile and stack/region info
if [ -n "$DR_REGION" ]; then
    CONFIG_ENV="dr"
    STACK_NAME=$(get_toml_value "dr.deploy.parameters" "stack_name")
    DEPLOY_REGION="$DR_REGION"
    PRIMARY_STACK=$(get_toml_value "default.deploy.parameters" "stack_name")
    PRIMARY_REGION=$(get_toml_value "default.global.parameters" "region")
else
    CONFIG_ENV="default"
    STACK_NAME=$(get_toml_value "default.deploy.parameters" "stack_name")
    DEPLOY_REGION=$(get_toml_value "default.global.parameters" "region")
fi

if [ -z "$STACK_NAME" ]; then
    echo -e "${RED}Error: Could not find stack_name for profile '$CONFIG_ENV' in samconfig.toml${NC}"
    exit 1
fi

echo -e "\n${YELLOW}Stack: ${WHITE}$STACK_NAME${YELLOW} | Region: ${WHITE}${DEPLOY_REGION}${YELLOW} | Profile: ${WHITE}$CONFIG_ENV${NC}"

# Check for required tools
echo -e "\n${YELLOW}Checking required tools...${NC}"
for tool in aws sam npm make; do
    if ! command -v "$tool" &> /dev/null; then
        echo -e "${RED}Error: '$tool' is not installed or not in PATH${NC}"
        exit 1
    fi
done
echo -e "${GREEN}All required tools found.${NC}"

# ----------------------------------------------------------------------------
# DR mode: fetch GlobalTable names from primary stack
# ----------------------------------------------------------------------------
EXTRA_PARAM_OVERRIDES=()
if [ -n "$DR_REGION" ]; then
    echo -e "\n${YELLOW}Fetching GlobalTable names from primary stack '$PRIMARY_STACK' ($PRIMARY_REGION)...${NC}"

    get_primary_output() {
        aws cloudformation describe-stacks \
            --stack-name "$PRIMARY_STACK" \
            --region "$PRIMARY_REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
            --output text
    }

    TENANTS_TABLE=$(get_primary_output "TenantsTableName")
    TENANT_MAPPINGS_TABLE=$(get_primary_output "TenantMappingsTableName")
    EXECUTIONS_TABLE=$(get_primary_output "TargetExecutionsTableName")
    SCHEDULES_TABLE=$(get_primary_output "SchedulesTableName")
    USER_MAPPINGS_TABLE=$(get_primary_output "UserMappingsTableName")

    # Validate all values were retrieved
    declare -A TABLE_VARS=(
        [TenantsTableName]="$TENANTS_TABLE"
        [TenantMappingsTableName]="$TENANT_MAPPINGS_TABLE"
        [TargetExecutionsTableName]="$EXECUTIONS_TABLE"
        [SchedulesTableName]="$SCHEDULES_TABLE"
        [UserMappingsTableName]="$USER_MAPPINGS_TABLE"
    )
    for OUTPUT_KEY in "${!TABLE_VARS[@]}"; do
        VAL="${TABLE_VARS[$OUTPUT_KEY]}"
        if [ -z "$VAL" ] || [ "$VAL" == "None" ]; then
            echo -e "${RED}Error: Could not retrieve '$OUTPUT_KEY' from stack '$PRIMARY_STACK' in $PRIMARY_REGION${NC}"
            echo -e "${RED}Ensure the primary stack is deployed and outputs are available.${NC}"
            exit 1
        fi
        echo -e "${GRAY}  $OUTPUT_KEY = $VAL${NC}"
    done

    # SAM CLI replaces (not merges) parameter_overrides when --parameter-overrides
    # is passed on the CLI. Read the static params from the DR samconfig profile
    # and combine with the dynamic table names into one complete override list.
    BASE_PARAMS_RAW=$(get_toml_value "dr.deploy.parameters" "parameter_overrides" | sed 's/\\"/"/g')
    PARAM_OVERRIDES=()
    while IFS= read -r pair; do
        [[ -n "$pair" ]] && PARAM_OVERRIDES+=("$pair")
    done < <(echo "$BASE_PARAMS_RAW" | grep -oE '[A-Za-z][A-Za-z0-9_]*="[^"]*"')
    PARAM_OVERRIDES+=(
        "ExistingTenantsTable=$TENANTS_TABLE"
        "ExistingTenantMappingsTable=$TENANT_MAPPINGS_TABLE"
        "ExistingTargetExecutionsTable=$EXECUTIONS_TABLE"
        "ExistingSchedulesTable=$SCHEDULES_TABLE"
        "ExistingUserMappingsTable=$USER_MAPPINGS_TABLE"
    )
    EXTRA_PARAM_OVERRIDES=(--parameter-overrides "${PARAM_OVERRIDES[@]}")
    echo -e "${GREEN}GlobalTable names fetched successfully.${NC}"
fi

# Step 1: Build the UI
echo -e "\n${YELLOW}[1/6] Building UI (Vite)...${NC}"
(
    cd ui-vite || exit 1
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

# Step 2: SAM Validate
echo -e "\n${YELLOW}[2/6] Validating SAM template...${NC}"
sam validate --lint
if [ $? -ne 0 ]; then
    echo -e "${RED}SAM validation failed!${NC}"
    exit 1
fi
echo -e "${GREEN}SAM validation completed successfully.${NC}"

# Step 3: SAM Build
echo -e "\n${YELLOW}[3/6] Building SAM application...${NC}"
sam build --config-env "$CONFIG_ENV"
if [ $? -ne 0 ]; then
    echo -e "${RED}SAM build failed!${NC}"
    exit 1
fi
echo -e "${GREEN}SAM build completed successfully.${NC}"

# Step 4: SAM Deploy
echo -e "\n${YELLOW}[4/6] Deploying SAM application...${NC}"
sam deploy \
    --config-env "$CONFIG_ENV" \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --capabilities CAPABILITY_NAMED_IAM \
    "${EXTRA_PARAM_OVERRIDES[@]}"
if [ $? -ne 0 ]; then
    echo -e "${RED}SAM deployment failed!${NC}"
    exit 1
fi
echo -e "${GREEN}SAM deployment completed successfully.${NC}"

# Step 5: Upload UI files to S3
echo -e "\n${YELLOW}[5/6] Uploading UI files to S3...${NC}"
REGION_ARG=""
[ -n "$DEPLOY_REGION" ] && REGION_ARG="--region $DEPLOY_REGION"

s3Bucket=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    $REGION_ARG \
    --query "Stacks[0].Outputs[?OutputKey=='StaticFilesBucketName'].OutputValue" \
    --output text)

if [[ -n "$s3Bucket" ]]; then
    echo -e "${GRAY}S3 Bucket: $s3Bucket${NC}"
    aws s3 sync ui-vite/build/ s3://$s3Bucket/ $REGION_ARG --delete --cache-control "public, max-age=31536000" --exclude "index.html"
    aws s3 cp ui-vite/build/index.html s3://$s3Bucket/index.html $REGION_ARG --cache-control "no-cache, no-store, must-revalidate"

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}UI files uploaded successfully to S3.${NC}"
    else
        echo -e "${RED}Failed to upload UI files to S3!${NC}"
        exit 1
    fi
else
    echo -e "${RED}Could not retrieve S3 bucket name from stack outputs.${NC}"
    exit 1
fi

echo -e "\n${CYAN}========================================${NC}"
echo -e "${CYAN}Quick Deploy Completed Successfully!${NC}"
echo -e "${CYAN}========================================${NC}"

# Get stack outputs
echo -e "\n${YELLOW}Getting deployment information...${NC}"
apiUrl=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" $REGION_ARG --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
userPoolId=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" $REGION_ARG --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text)
clientId=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" $REGION_ARG --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolClientId'].OutputValue" --output text)

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
        $REGION_ARG \
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
