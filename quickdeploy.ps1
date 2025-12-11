# Quick Deploy Script for Serverless Task Scheduler (STS)
# This script builds the UI, copies assets, validates, builds, and deploys the SAM application

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Quick Deploy Process" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Read stack name from samconfig.toml
Write-Host "`nReading configuration from samconfig.toml..." -ForegroundColor Yellow
$stackName = $null

if (Test-Path "samconfig.toml") {
    $samConfig = Get-Content "samconfig.toml" -Raw
    if ($samConfig -match 'stack_name\s*=\s*"([^"]+)"') {
        $stackName = $matches[1]
        Write-Host "Found stack name: $stackName" -ForegroundColor Green
    } else {
        Write-Host "Error: Could not find stack_name in samconfig.toml" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Error: samconfig.toml not found" -ForegroundColor Red
    exit 1
}

# Step 1: Build the UI
Write-Host "`n[1/7] Building UI (Vite)..." -ForegroundColor Yellow
Push-Location ui-vite
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

# Step 2: SAM Validate
Write-Host "`n[2/7] Validating SAM template..." -ForegroundColor Yellow
sam validate --lint
if ($LASTEXITCODE -ne 0) {
    Write-Host "SAM validation failed!" -ForegroundColor Red
    exit 1
}
Write-Host "SAM validation completed successfully." -ForegroundColor Green

# Step 3: SAM Build
Write-Host "`n[3/7] Building SAM application..." -ForegroundColor Yellow
sam build
if ($LASTEXITCODE -ne 0) {
    Write-Host "SAM build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "SAM build completed successfully." -ForegroundColor Green

# Step 4: SAM Deploy
Write-Host "`n[4/7] Deploying SAM application..." -ForegroundColor Yellow
$deployOutput = sam deploy --no-confirm-changeset 2>&1
$deployExitCode = $LASTEXITCODE

if ($deployExitCode -ne 0) {
    # Check if it's just "no changes" error
    if ($deployOutput -match "No changes to deploy") {
        Write-Host "No SAM changes detected - stack is up to date." -ForegroundColor Yellow
    } else {
        Write-Host "SAM deployment failed!" -ForegroundColor Red
        Write-Host $deployOutput -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "SAM deployment completed successfully." -ForegroundColor Green
}

# Step 5: Upload UI files to S3
Write-Host "`n[5/7] Uploading UI files to S3..." -ForegroundColor Yellow
$bucketName = aws cloudformation describe-stacks --stack-name $stackName --query "Stacks[0].Outputs[?OutputKey=='StaticFilesBucketName'].OutputValue" --output text

if ($bucketName) {
    Write-Host "S3 Bucket: $bucketName" -ForegroundColor Gray

    # Sync all files with long cache except index.html
    aws s3 sync ui-vite/build/ "s3://$bucketName/" `
        --delete `
        --cache-control "public, max-age=31536000" `
        --exclude "index.html"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to upload UI files to S3!" -ForegroundColor Red
        exit 1
    }

    # Upload index.html with no-cache
    aws s3 cp ui-vite/build/index.html "s3://$bucketName/index.html" `
        --cache-control "no-cache, no-store, must-revalidate"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to upload index.html to S3!" -ForegroundColor Red
        exit 1
    }

    Write-Host "UI files uploaded successfully to S3." -ForegroundColor Green
} else {
    Write-Host "Could not retrieve S3 bucket name from stack outputs." -ForegroundColor Red
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Quick Deploy Completed Successfully!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Get stack outputs
Write-Host "`nGetting deployment information..." -ForegroundColor Yellow
$apiUrl = aws cloudformation describe-stacks --stack-name $stackName --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
$userPoolId = aws cloudformation describe-stacks --stack-name $stackName --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text
$clientId = aws cloudformation describe-stacks --stack-name $stackName --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolClientId'].OutputValue" --output text

if ($apiUrl -and $userPoolId -and $clientId) {
    Write-Host "`nApplication URL: " -NoNewline -ForegroundColor Green
    Write-Host "$apiUrl" -ForegroundColor Cyan

    # Step 6: Configure Cognito logout URLs
    Write-Host "`n[6/7] Configuring Cognito logout and callback URLs..." -ForegroundColor Yellow

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
