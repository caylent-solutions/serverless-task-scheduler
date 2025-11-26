# Implementation Plan: S3-Based Static File Hosting for React App

## Current State Analysis

### What We Have Now:
- React app built in `ui/` directory (output: `ui/build/`)
- Build artifacts copied to `ExecutionAPI/app/wwwroot/`
- FastAPI Lambda serves static files via `StaticFiles` mount at `/app`
- Files bundled with Lambda deployment package (~several MB)
- API Gateway routes `/{proxy+}` to Lambda for everything

### Problems with Current Approach:
1. **Lambda package size**: Static files increase deployment package size
2. **Lambda execution cost**: Every static file request invokes Lambda
3. **Performance**: Lambda cold starts affect initial page load
4. **Binary media**: Lambda needs special handling for images/fonts
5. **Caching**: Limited control over browser/CDN caching

## Proposed Solution Architecture

### High-Level Design:
```
API Gateway (Route Priority Order)
├── /api/*           → Lambda (FastAPI backend) - MATCHED FIRST
└── /{proxy+}        → S3 (React SPA at root)
```

**Key Points:**
- **React app at root** (`/`, `/tenants`, `/schedules`, etc.) - Clean URLs, no hash routing needed!
- **All API routes under `/api`** (`/api/targets`, `/api/tenants`, `/api/user`, etc.)
- `/api/*` route defined FIRST in API Gateway to match before S3 catch-all
- SPA routing works naturally: any non-API path returns `index.html` from S3
- `/artifacts` NOT publicly exposed (remains private in S3, accessible only via backend)
- **Even simpler**: No SpaFallbackLambda needed!

### S3 Bucket Structure:
```
${StackName}-${Environment}-static-${StackIdSuffix}/
├── index.html                    # React SPA root (PUBLIC via /)
├── manifest.json
├── favicon.ico
├── static/                       # React assets (PUBLIC)
│   ├── css/
│   ├── js/
│   └── media/
└── artifacts/                    # Deployment artifacts (PRIVATE)
    └── [private files]           # Accessible only to backend Lambda if needed
```

## Implementation Plan

### Phase 1: Infrastructure Setup (SAM Template Changes)

#### 1.1 Add S3 Bucket Resource
Add to `template.yaml` after the CloudWatch Log Groups section:

```yaml
  # --------------------------------------------------------------------------
  # S3 Bucket - Static file hosting for React app and private artifacts
  # --------------------------------------------------------------------------
  StaticFilesBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub
        - ${StackName}-${Environment}-static-${StackIdSuffix}
        - StackIdSuffix: !Select [4, !Split ['-', !Select [2, !Split ['/', !Ref 'AWS::StackId']]]]
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      CorsConfiguration:
        CorsRules:
          - AllowedOrigins:
              - '*'
            AllowedMethods:
              - GET
              - HEAD
            AllowedHeaders:
              - '*'
            MaxAge: 3600
      Tags:
        - Key: caylent:owner
          Value: !Ref Owner
        - Key: caylent:env
          Value: !Ref Environment
        - Key: cfn:stack
          Value: !Ref StackName

  # IAM Role for API Gateway S3 Integration
  ApiGatewayS3Role:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub
        - ${StackName}-${Environment}-apigw-s3-${StackIdSuffix}
        - StackIdSuffix: !Select [4, !Split ['-', !Select [2, !Split ['/', !Ref 'AWS::StackId']]]]
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: apigateway.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: S3ReadPolicy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - s3:GetObject
                Resource:
                  - !Sub ${StaticFilesBucket.Arn}/*
                  - !Sub ${StaticFilesBucket.Arn}
              - Effect: Allow
                Action:
                  - s3:ListBucket
                Resource: !GetAtt StaticFilesBucket.Arn
                Condition:
                  StringLike:
                    s3:prefix:
                      - '*'
                      - 'static/*'
      Tags:
        - Key: caylent:owner
          Value: !Ref Owner
        - Key: caylent:env
          Value: !Ref Environment
        - Key: cfn:stack
          Value: !Ref StackName
```

**Important Changes:**
- Public access is BLOCKED (no public bucket policy needed)
- API Gateway role has access to all files in bucket root (for React app)
- `/artifacts/` remains fully private (not exposed via API Gateway routes)

#### 1.2 Add API Gateway S3 Integration

**IMPORTANT:** The `/api/*` route must be defined BEFORE the S3 `/{proxy+}` catch-all to ensure proper route matching priority.

**Recommended Approach: Using OpenAPI/Swagger Definition with DefinitionBody**

Modify the existing `ApiGateway` resource in `template.yaml` to use inline OpenAPI definition:

```yaml
  ApiGateway:
    Type: AWS::Serverless::Api
    Properties:
      Name: !Sub
        - ${StackName}-${Environment}-api-${StackIdSuffix}
        - StackIdSuffix: !Select [4, !Split ['-', !Select [2, !Split ['/', !Ref 'AWS::StackId']]]]
      StageName: !Ref Environment
      TracingEnabled: true
      DisableExecuteApiEndpoint: false
      BinaryMediaTypes:
        - image/*
        - application/octet-stream
      DefinitionBody:
        openapi: 3.0.0
        info:
          title: Serverless Task Scheduler API
          version: 1.0.0

        paths:
          # CRITICAL: /api/* defined FIRST for route priority
          /api/{proxy+}:
            x-amazon-apigateway-any-method:
              parameters:
                - name: proxy
                  in: path
                  required: true
                  schema:
                    type: string
              x-amazon-apigateway-integration:
                type: aws_proxy
                httpMethod: POST
                uri: !Sub 'arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${AppLambda.Arn}/invocations'

          # S3 catch-all for React SPA (serves index.html for all non-API routes)
          /{proxy+}:
            get:
              parameters:
                - name: proxy
                  in: path
                  required: true
                  schema:
                    type: string
              responses:
                '200':
                  description: Successful response
                  headers:
                    Content-Type:
                      schema:
                        type: string
                    Cache-Control:
                      schema:
                        type: string
                '404':
                  description: Not found - Returns index.html for SPA routing
              x-amazon-apigateway-integration:
                type: aws
                httpMethod: GET
                uri: !Sub 'arn:aws:apigateway:${AWS::Region}:s3:path/${StaticFilesBucket}/{proxy}'
                credentials: !GetAtt ApiGatewayS3Role.Arn
                requestParameters:
                  integration.request.path.proxy: method.request.path.proxy
                responses:
                  default:
                    statusCode: '200'
                    responseParameters:
                      method.response.header.Content-Type: integration.response.header.Content-Type
                      method.response.header.Cache-Control: "'public, max-age=31536000'"
                  '4\d{2}':
                    statusCode: '200'
                    responseParameters:
                      method.response.header.Content-Type: "'text/html'"
                      method.response.header.Cache-Control: "'no-cache'"
                    responseTemplates:
                      text/html: !Sub |
                        #set($context.requestOverride.path.proxy = "index.html")

          # Root path - serve index.html
          /:
            get:
              responses:
                '200':
                  description: React app root
                  headers:
                    Content-Type:
                      schema:
                        type: string
              x-amazon-apigateway-integration:
                type: aws
                httpMethod: GET
                uri: !Sub 'arn:aws:apigateway:${AWS::Region}:s3:path/${StaticFilesBucket}/index.html'
                credentials: !GetAtt ApiGatewayS3Role.Arn
                responses:
                  default:
                    statusCode: '200'
                    responseParameters:
                      method.response.header.Content-Type: "'text/html'"

      Tags:
        caylent:owner: !Ref Owner
        caylent:env: !Ref Environment
        cfn:stack: !Ref StackName
```

**Route Matching Order:**
1. `/api/{proxy+}` - Matches first, goes to Lambda (FastAPI backend)
2. `/` - Root path, serves `index.html` from S3
3. `/{proxy+}` - Catch-all for everything else, goes to S3 (returns `index.html` on 404 for SPA routing)

#### 1.3 Update Lambda Environment Variables (Optional)
Optionally add S3 bucket reference if Lambda needs to access artifacts:
```yaml
  AppLambda:
    Type: AWS::Serverless::Function
    Properties:
      # ... existing properties
      Environment:
        Variables:
          # Optional: If Lambda needs to access private artifacts
          STATIC_FILES_BUCKET: !Ref StaticFilesBucket
          # Note: /app is now served from S3, Lambda no longer serves static files
```

#### 1.4 Update AppLambda Events
Remove the existing API Gateway event definitions since we're using OpenAPI definition:
```yaml
  AppLambda:
    Type: AWS::Serverless::Function
    DependsOn: AppLambdaLogGroup
    Properties:
      FunctionName: !Sub
        - ${StackName}-${Environment}-api-${StackIdSuffix}
        - StackIdSuffix: !Select [4, !Split ['-', !Select [2, !Split ['/', !Ref 'AWS::StackId']]]]
      CodeUri: ExecutionAPI/
      Handler: app/lambda_handler.handler
      Role: !GetAtt AppLambdaRole.Arn
      # ... existing Environment and other properties
      # REMOVE the Events section - routes now defined in ApiGateway DefinitionBody
      # Events:
      #   ApiAny:
      #     Type: Api
      #     Properties:
      #       RestApiId: !Ref ApiGateway
      #       Path: /{proxy+}
      #       Method: ANY
```

**Note:** The old `Events` section had separate routes for `/` and `/{proxy+}`, but with our OpenAPI definition, we only need `/{proxy+}` which catches everything (including `/`) except `/app/*`.

#### 1.5 Add Outputs
```yaml
Outputs:
  StaticFilesBucketName:
    Description: Name of the S3 bucket for static files and private artifacts
    Value: !Ref StaticFilesBucket

  StaticFilesBucketArn:
    Description: ARN of the S3 bucket for static files and private artifacts
    Value: !GetAtt StaticFilesBucket.Arn

  ReactAppUrl:
    Description: URL for accessing the React application
    Value: !Sub 'https://${ApiGateway}.execute-api.${AWS::Region}.amazonaws.com/${Environment}/'

  ApiDocsUrl:
    Description: URL for accessing API documentation (Swagger UI)
    Value: !Sub 'https://${ApiGateway}.execute-api.${AWS::Region}.amazonaws.com/${Environment}/api/docs'
```

### Phase 2: Application Code Changes

#### 2.1 Update FastAPI main.py
Major changes needed to move all routes under `/api` prefix:

```python
# In ExecutionAPI/app/main.py

# Change the app initialization to use /api prefix
app = FastAPI(
    title="Serverless Task Scheduler API",
    # ... other config
    root_path="/api"  # ADD THIS - all routes now under /api
)

# Remove or comment out the StaticFiles mount
# app.mount(mount_path, StaticFiles(directory=wwwroot_path, html=True), name="static")

# Remove the root redirect since React is now at root
# @app.get("/", include_in_schema=False)
# async def root(request: Request):
#     return RedirectResponse(url=f"{request.base_url}app/", status_code=302)

# Update logout redirect to go to root
@app.get("/logout", include_in_schema=False)
async def logout():
    response = RedirectResponse(url="/")  # Redirect to React app root
    response.delete_cookie("idToken")
    response.delete_cookie("accessToken")
    response.delete_cookie("refreshToken")
    return response
```

#### 2.2 Update Router Prefixes
All your routers already have prefixes, so they'll automatically work under `/api`:
- `/api/targets` - already has `router = APIRouter(prefix="/targets")`
- `/api/tenants` - already has `router = APIRouter(prefix="/tenants")`
- `/api/user` - already has `router = APIRouter(prefix="/user")`

#### 2.3 Update React App API Calls
Update your React app to call `/api/*` endpoints:
```javascript
// Before: fetch('/tenants')
// After:  fetch('/api/tenants')

// Before: fetch('/targets')
// After:  fetch('/api/targets')
```

Or better yet, set a base URL constant:
```javascript
// src/config.js
export const API_BASE_URL = '/api';

// Then in your API calls:
fetch(`${API_BASE_URL}/tenants`)
```

#### 2.4 Update Build Process
Modify the build/deployment to sync React build to S3 root:

PowerShell version `scripts/deploy-static.ps1`:
```powershell
param(
    [Parameter(Mandatory=$true)]
    [string]$StackName,

    [Parameter(Mandatory=$true)]
    [string]$Environment
)

# Get bucket name from CloudFormation outputs
$BucketName = aws cloudformation describe-stacks `
    --stack-name "$StackName-$Environment" `
    --query "Stacks[0].Outputs[?OutputKey=='StaticFilesBucketName'].OutputValue" `
    --output text

Write-Host "Building React app..."
Set-Location ui
npm run build
Set-Location ..

Write-Host "Deploying to S3 bucket: $BucketName"

# Sync all files with long cache (except HTML)
aws s3 sync ui/build/ "s3://$BucketName/" `
    --delete `
    --cache-control "public, max-age=31536000" `
    --exclude "*.html" `
    --exclude "manifest.json"

# HTML files with shorter cache (for updates)
aws s3 sync ui/build/ "s3://$BucketName/" `
    --cache-control "public, max-age=300" `
    --exclude "*" `
    --include "*.html" `
    --include "manifest.json"

Write-Host "Static files deployed successfully!"
Write-Host "React app available at root URL"
```

**Key Changes:**
- Sync to bucket root (`s3://$BucketName/`) instead of `s3://$BucketName/app/`
- Files go directly to root: `index.html`, `static/`, etc.

#### 2.3 Update samconfig.toml
Add post-deployment hook:
```toml
[default.deploy.parameters]
# ... existing parameters
hooks = [
    "after_deploy = pwsh scripts/deploy-static.ps1 {stack-name} {environment}"
]
```

Or create a separate deployment script that does both:
```bash
# deploy.sh
sam build
sam deploy --config-file samconfig.toml
pwsh scripts/deploy-static.ps1 $STACK_NAME $ENVIRONMENT
```

### Phase 3: SPA Routing (Built-in!)

**Great News:** SPA routing is handled automatically by the API Gateway configuration!

#### How It Works:
1. User navigates to `/tenants/123`
2. API Gateway tries to fetch `/tenants/123` from S3
3. S3 returns 404 (file doesn't exist)
4. API Gateway catches the 404 and returns `index.html` instead (via response template)
5. React Router loads and handles `/tenants/123` client-side

#### No Additional Changes Needed:
- ✅ No hash routing needed - clean URLs work!
- ✅ No fallback Lambda needed - API Gateway handles it
- ✅ Refresh works on any route
- ✅ Direct deep linking works

This is already configured in the `/{proxy+}` route where 404 responses return `index.html`.

### Phase 4: Testing and Validation

1. **Deploy the infrastructure**:
   ```bash
   sam build
   sam deploy
   ```

2. **Deploy static files**:
   ```powershell
   .\scripts\deploy-static.ps1 -StackName sts -Environment dev
   ```

3. **Test endpoints**:
   - `https://{api-gateway-url}/dev/` → React app root from S3
   - `https://{api-gateway-url}/dev/tenants` → React app (SPA route)
   - `https://{api-gateway-url}/dev/schedules/123` → React app (deep link)
   - `https://{api-gateway-url}/dev/static/js/main.*.js` → JS files from S3
   - `https://{api-gateway-url}/dev/api/tenants` → FastAPI backend
   - `https://{api-gateway-url}/dev/api/targets` → FastAPI backend
   - `https://{api-gateway-url}/dev/api/user` → FastAPI backend
   - `https://{api-gateway-url}/dev/api/docs` → Swagger UI (if enabled)

4. **Verify SPA routing**:
   - Navigate to `/tenants` (should load React app)
   - Navigate to `/schedules/123` (should load React app with route)
   - Refresh the page on any route (should still work)
   - Verify all React API calls go to `/api/*` endpoints

## Benefits of This Approach

### ✅ Advantages:
1. **Reduced Lambda costs**: Static files don't invoke Lambda
2. **Better performance**: Direct S3 access via API Gateway is faster than Lambda
3. **Smaller Lambda package**: No static files bundled (faster deploys)
4. **Better caching**: Full control over cache headers for static assets
5. **SAM-managed**: Entire infrastructure in one template
6. **FastAPI control**: Root path kept for OpenAPI docs, Swagger UI
7. **Private artifacts**: `/artifacts` folder available for backend use only
8. **Simple routing**: `/app/*` matched first, everything else goes to Lambda
9. **Security**: S3 bucket remains private, API Gateway is the only access point

### ⚠️ Considerations:
1. **Two-step deployment**: Must deploy SAM + sync S3 files
2. **API Gateway pricing**: Each static file request goes through API Gateway
3. **SPA routing**: Requires hash routing or fallback Lambda
4. **Binary media**: Image/font files need proper Content-Type headers
5. **No CloudFront**: For better performance/cost, add CloudFront in Phase 5

## Future Enhancements

### Phase 5: Add CloudFront (Optional)
```yaml
  CloudFrontDistribution:
    Type: AWS::CloudFront::Distribution
    Properties:
      DistributionConfig:
        Origins:
          - Id: S3Origin
            DomainName: !GetAtt StaticFilesBucket.RegionalDomainName
            S3OriginConfig:
              OriginAccessIdentity: !Sub 'origin-access-identity/cloudfront/${CloudFrontOAI}'
          - Id: ApiGatewayOrigin
            DomainName: !Sub '${ApiGateway}.execute-api.${AWS::Region}.amazonaws.com'
            OriginPath: !Sub '/${Environment}'
            CustomOriginConfig:
              OriginProtocolPolicy: https-only
        DefaultCacheBehavior:
          TargetOriginId: S3Origin
          # ... cache configuration
        CacheBehaviors:
          - PathPattern: /api/*
            TargetOriginId: ApiGatewayOrigin
            # ... no caching for API
```

### Phase 6: Automated CI/CD
Integrate with GitHub Actions or CodePipeline to automatically:
1. Build React app on commit
2. Deploy SAM template
3. Sync static files to S3
4. Invalidate CloudFront cache (if using CloudFront)

## Migration Checklist

### Infrastructure (template.yaml)
- [ ] Add S3 bucket resource (StaticFilesBucket)
- [ ] Add IAM role for API Gateway S3 access (ApiGatewayS3Role) with bucket root access
- [ ] Convert ApiGateway to use DefinitionBody with OpenAPI
- [ ] Define `/api/{proxy+}` route FIRST (Lambda integration)
- [ ] Define `/` route (S3 integration to index.html)
- [ ] Define `/{proxy+}` route (S3 integration with 404 fallback to index.html)
- [ ] Remove Events section from AppLambda
- [ ] Add outputs for bucket name and React app URL

### Application Code
- [ ] Add `root_path="/api"` to FastAPI app initialization
- [ ] Remove StaticFiles mount from FastAPI main.py
- [ ] Remove root `/` redirect endpoint
- [ ] Update logout redirect to go to `/` (React root)
- [ ] Update all React API calls to use `/api/*` prefix
- [ ] Add API_BASE_URL constant to React app
- [ ] Remove wwwroot from .gitignore if needed

### Deployment Scripts
- [ ] Create `scripts/deploy-static.ps1` for S3 sync to bucket root
- [ ] Build React app before deployment
- [ ] Set proper cache headers for assets vs HTML
- [ ] Test deployment script locally

### Testing
- [ ] Deploy infrastructure: `sam build && sam deploy`
- [ ] Deploy static files: `.\scripts\deploy-static.ps1`
- [ ] Test React app loads at `/` (root)
- [ ] Test static assets load (`/static/js/*`, `/static/css/*`)
- [ ] Test API endpoints work at `/api/*`
- [ ] Test Swagger UI at `/api/docs`
- [ ] Test SPA routing (navigate to `/tenants`, `/schedules`)
- [ ] Test refresh on SPA routes (should serve index.html)
- [ ] Verify authentication redirects work
- [ ] Test on mobile/different browsers

### Documentation
- [ ] Update README with new deployment process
- [ ] Document S3 bucket structure
- [ ] Add troubleshooting section
- [ ] Note any breaking changes

### Future Considerations
- [ ] Consider adding CloudFront for production
- [ ] Monitor API Gateway costs for static files
- [ ] Consider Lambda@Edge for SPA routing at edge

## Recommended Implementation Order

1. **Phase 1: Infrastructure First**
   - Add S3 bucket and IAM role
   - Convert API Gateway to OpenAPI with `/app/*` route
   - Deploy and verify bucket exists

2. **Phase 2: Manual Testing**
   - Manually build React app: `cd ui && npm run build`
   - Manually sync to S3: `aws s3 sync ui/build/ s3://{bucket}/`
   - Test that `/` loads React from S3
   - Test that `/api/*` routes don't exist yet (expected - Lambda not updated)

3. **Phase 2: Update Lambda Code**
   - Add `root_path="/api"` to FastAPI
   - Remove StaticFiles mount
   - Remove root redirect
   - Test that `/api/docs` works (Swagger UI)

4. **Phase 2: Automate Deployment**
   - Create `deploy-static.ps1` script
   - Test automated deployment
   - Document the process

5. **Phase 3: Update React App**
   - Update all API calls to use `/api/*` prefix
   - Test that API calls work
   - Test client-side navigation (no hash routing needed!)

6. **Phase 4: Full Testing**
   - Test all endpoints
   - Verify authentication flows
   - Check caching behavior

7. **Phase 5+: Future Enhancements**
   - Add CloudFront if needed
   - Implement CI/CD pipeline
   - Optimize cache strategies

## Key Differences from Original Plan

1. **React at root, API at `/api`**: Most intuitive URL structure!
   - `/` → React app (clean URLs)
   - `/api/*` → FastAPI backend
2. **No hash routing needed**: SPA routing works with clean URLs
3. **No fallback Lambda needed**: API Gateway handles 404 → index.html
4. **Simple route priority**: `/api/*` matched first, everything else goes to S3
5. **Private S3**: Bucket has public access blocked, only API Gateway can read
6. **No public artifacts**: `/artifacts` folder stays private in S3
7. **FastAPI root_path**: Simple `root_path="/api"` configuration
8. **Standard web app pattern**: Matches industry best practices
