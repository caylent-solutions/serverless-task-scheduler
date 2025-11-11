# Get Lambda logs from the past 10 minutes
# Usage: ./get-logs.ps1 [function-name] [region]

param(
    [string]$FunctionName = "",
    [string]$Region = "us-east-1"
)

# Set AWS profile and region
$env:AWS_PROFILE = "cy"
$env:AWS_DEFAULT_REGION = "us-east-1"

# If function name not provided, try to get from stack outputs
if ([string]::IsNullOrEmpty($FunctionName)) {
    # Try to get stack name from samconfig.toml or use default
    $StackName = "ireis-sts-dev"
    
    if (Test-Path "samconfig.toml") {
        $configContent = Get-Content "samconfig.toml" -Raw
        if ($configContent -match 'stack_name\s*=\s*"([^"]+)"') {
            $StackName = $matches[1].Trim()
        }
    }
    
    Write-Host "Getting Lambda function name from stack: $StackName"
    
    try {
        $output = aws cloudformation describe-stacks `
            --stack-name $StackName `
            --query "Stacks[0].Outputs[?OutputKey=='LambdaName'].OutputValue" `
            --output text `
            --region $Region 2>&1
        
        if ($LASTEXITCODE -eq 0 -and $output -and $output -ne "None") {
            $FunctionName = $output.Trim()
        }
    } catch {
        # Ignore errors
    }
    
    if ([string]::IsNullOrEmpty($FunctionName)) {
        Write-Host "Error: Could not determine Lambda function name." -ForegroundColor Red
        Write-Host "Usage: $($MyInvocation.MyCommand.Name) [function-name] [region]"
        Write-Host "Example: $($MyInvocation.MyCommand.Name) my-function-name us-east-1"
        exit 1
    }
}

Write-Host "Fetching logs for function: $FunctionName"
Write-Host "Time range: Last 10 minutes"
Write-Host "---"

# Get logs using AWS CLI (--since accepts relative time like "10m")
aws logs tail "/aws/lambda/$FunctionName" --since 10m --format short --region $Region

