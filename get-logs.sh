#!/bin/bash
# Get Lambda logs from the past 10 minutes
# Usage: ./get-logs.sh [function-name] [region]

# Set AWS profile and region
export AWS_PROFILE=cy
export AWS_DEFAULT_REGION=us-east-1

# Get function name from argument or try to get from stack
FUNCTION_NAME="${1:-}"
REGION="${2:-us-east-1}"

# If function name not provided, try to get from stack outputs
if [ -z "$FUNCTION_NAME" ]; then
    # Try to get stack name from samconfig.toml or use default
    STACK_NAME=""
    if [ -f "samconfig.toml" ]; then
        STACK_NAME=$(grep -E "^stack_name\s*=" samconfig.toml | sed 's/.*=\s*"\(.*\)".*/\1/' | tr -d ' ')
    fi
    
    if [ -z "$STACK_NAME" ]; then
        STACK_NAME="ireis-sts-dev"
    fi
    
    echo "Getting Lambda function name from stack: $STACK_NAME" >&2
    FUNCTION_NAME=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='LambdaName'].OutputValue" \
        --output text \
        --region "$REGION" 2>/dev/null)
    
    if [ -z "$FUNCTION_NAME" ] || [ "$FUNCTION_NAME" == "None" ]; then
        echo "Error: Could not determine Lambda function name." >&2
        echo "Usage: $0 [function-name] [region]" >&2
        echo "Example: $0 my-function-name us-east-1" >&2
        exit 1
    fi
fi

echo "Fetching logs for function: $FUNCTION_NAME" >&2
echo "Time range: Last 10 minutes" >&2
echo "---" >&2

# Get logs using AWS CLI (--since accepts relative time like "10m")
aws logs tail "/aws/lambda/$FUNCTION_NAME" \
    --since 10m \
    --format short \
    --region "$REGION"

