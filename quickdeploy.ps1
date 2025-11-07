# Quick Deploy Script for Serverless Task Scheduler (STS)
# This script builds the UI, copies assets, validates, builds, and deploys the SAM application

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Quick Deploy Process" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Build the UI
Write-Host "`n[1/5] Building UI..." -ForegroundColor Yellow
Push-Location ui
try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "UI build failed!" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Write-Host "UI build completed successfully." -ForegroundColor Green
} finally {
    Pop-Location
}

# Step 2: Copy assets to wwwroot
Write-Host "`n[2/5] Copying assets to wwwroot..." -ForegroundColor Yellow
$sourcePath = "ui\build\*"
$destPath = "ExecutionAPI\app\wwwroot"

# Remove existing wwwroot contents completely
if (Test-Path $destPath) {
    Write-Host "Removing existing wwwroot contents..." -ForegroundColor Gray
    Remove-Item "$destPath\*" -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "Creating wwwroot directory..." -ForegroundColor Gray
    New-Item -Path $destPath -ItemType Directory -Force | Out-Null
}

# Copy new build
Copy-Item -Path $sourcePath -Destination $destPath -Recurse -Force
Write-Host "Assets copied successfully." -ForegroundColor Green

# Step 3: SAM Validate
Write-Host "`n[3/5] Validating SAM template..." -ForegroundColor Yellow
sam validate --lint
if ($LASTEXITCODE -ne 0) {
    Write-Host "SAM validation failed!" -ForegroundColor Red
    exit 1
}
Write-Host "SAM validation completed successfully." -ForegroundColor Green

# Step 4: SAM Build
Write-Host "`n[4/5] Building SAM application..." -ForegroundColor Yellow
sam build
if ($LASTEXITCODE -ne 0) {
    Write-Host "SAM build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "SAM build completed successfully." -ForegroundColor Green

# Step 5: SAM Deploy
Write-Host "`n[5/5] Deploying SAM application..." -ForegroundColor Yellow
sam deploy --no-confirm-changeset
if ($LASTEXITCODE -ne 0) {
    Write-Host "SAM deployment failed!" -ForegroundColor Red
    exit 1
}
Write-Host "SAM deployment completed successfully." -ForegroundColor Green

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Quick Deploy Completed Successfully!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Get stack outputs
Write-Host "`nGetting deployment information..." -ForegroundColor Yellow
$apiUrl = aws cloudformation describe-stacks --stack-name jyelle-sts-dev --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
$userPoolId = aws cloudformation describe-stacks --stack-name jyelle-sts-dev --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text
$clientId = aws cloudformation describe-stacks --stack-name jyelle-sts-dev --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolClientId'].OutputValue" --output text

if ($apiUrl -and $userPoolId -and $clientId) {
    Write-Host "`nApplication URL: " -NoNewline -ForegroundColor Green
    Write-Host "$apiUrl" -ForegroundColor Cyan
    
    # Step 6: Configure Cognito logout URLs
    Write-Host "`n[6/6] Configuring Cognito logout and callback URLs..." -ForegroundColor Yellow
    
    $callbackUrl = "${apiUrl}callback"
    $logoutUrl = "${apiUrl}app/"
    
    Write-Host "Callback URL: $callbackUrl" -ForegroundColor Gray
    Write-Host "Logout URL: $logoutUrl" -ForegroundColor Gray
    
    # Update the User Pool Client with logout URLs and auth flows
    $updateResult = aws cognito-idp update-user-pool-client `
        --user-pool-id $userPoolId `
        --client-id $clientId `
        --callback-urls $callbackUrl `
        --logout-urls $logoutUrl `
        --explicit-auth-flows "ALLOW_USER_SRP_AUTH" "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" `
        --allowed-o-auth-flows "code" `
        --allowed-o-auth-scopes "openid" "email" "profile" `
        --allowed-o-auth-flows-user-pool-client `
        --supported-identity-providers "COGNITO" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Cognito logout URLs configured successfully." -ForegroundColor Green
    } else {
        Write-Host "Warning: Failed to configure Cognito logout URLs." -ForegroundColor Yellow
        Write-Host "You may need to manually add the logout URL in the AWS Console:" -ForegroundColor Yellow
        Write-Host "  Logout URL: $logoutUrl" -ForegroundColor White
    }
    
    Write-Host "`nClick to open: $apiUrl" -ForegroundColor White
} else {
    Write-Host "Could not retrieve required information from stack outputs." -ForegroundColor Yellow
}
