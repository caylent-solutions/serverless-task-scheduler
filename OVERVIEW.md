# Serverless Task Scheduler - High-Level Overview

## What is This?

The Serverless Task Scheduler (STS) is a **cloud-based automation platform** that lets multiple organizations ("tenants") schedule and run their AWS services automatically - think of it as a universal "cron job" scheduler for the cloud that multiple companies can safely share.

**Real-world example**: Imagine you need to send daily sales reports at 9 AM, process customer data every hour, and run monthly billing at midnight on the first of each month. Instead of managing servers and writing scheduling code, you define these tasks once and let STS handle the execution automatically.

---

## The Three Main Components

### 1. **Web UI (React Application)**

**What it does**: Provides a browser-based interface where users can manage their automated tasks.

**AWS Services Used**:
- **Served from Lambda**: The React app is bundled and served directly from the API Lambda function
- **Cognito for Login**: Users sign in with email/password through AWS Cognito's hosted login page

**User Experience**:
- Click a link, log in, and manage everything through your browser
- View execution history with timestamps and results
- Create new schedules using familiar cron expressions (`0 9 * * *` for "every day at 9 AM")
- No command-line tools or AWS console knowledge required

**Why This Architecture**:
- **No separate hosting costs**: UI lives inside the API Lambda, not a separate S3 bucket + CloudFront
- **Single deployment**: Update the backend and frontend together with one command
- **Built-in authentication**: Cognito handles password security, email verification, and password resets

---

### 2. **API Layer (FastAPI + API Gateway)**

**What it does**: The "control panel" that manages all your schedules, users, and target definitions.

**AWS Services Used**:
- **API Gateway**: The front door - receives HTTPS requests from users
- **Lambda (Python/FastAPI)**: The brains - processes requests, enforces security, talks to databases
- **DynamoDB (6 tables)**: The memory - stores everything about tenants, schedules, users, and execution history
- **Cognito**: The security guard - verifies users are who they say they are
- **EventBridge Scheduler**: The alarm clock - triggers scheduled tasks at the right time

**What You Can Do Through the API**:
- **Create targets**: "This is my Lambda function ARN - let people schedule it"
- **Map targets to tenants**: "Company A gets v1.0, Company B gets v2.0"
- **Create schedules**: "Run this every Monday at 6 PM Eastern time"
- **Execute immediately**: "Run this task right now, don't wait for the schedule"
- **View execution history**: "Show me the last 100 runs and their results"

**Security Model - The "Bouncer" Approach**:

When a user makes a request:

1. **Authentication** ("Are you who you say you are?")
   - User sends JWT token from Cognito login
   - API verifies the token is valid and not expired
   - Extracts user email from token

2. **Authorization** ("Are you allowed to do this?")
   - API checks DynamoDB: "Which tenants does this user have access to?"
   - Returns list like: `["acme-corp", "globex-inc"]`
   - If user requests something for "other-company" → **403 Forbidden**

3. **Admin Privileges** (optional)
   - Special tenant called `admin` has cross-tenant access
   - Admins can create/update/delete target definitions
   - Regular users can only execute what admins have approved

**Why This Is Secure**:
- **No shared passwords**: Each user has their own Cognito account
- **Multi-tenant isolation**: Database queries always filter by tenant ID - you literally can't see other tenants' data
- **Least privilege**: Regular users can't add new Lambda functions, only execute what admins have pre-approved
- **Audit trail**: Every execution recorded with user, timestamp, and result

---

### 3. **Execution Engine (Step Functions Orchestration)**

**What it does**: The "worker" that actually runs your scheduled tasks - safely, reliably, and with full tracking.

**AWS Services Used**:
- **Step Functions State Machine**: The orchestrator - manages the 3-stage workflow
- **Lambda (Preprocessing)**: Looks up which actual Lambda/ECS/Step Function to run
- **Lambda (Execution Helper)**: Invokes Lambda targets and captures their logs
- **Lambda (Postprocessing)**: Records execution results to DynamoDB
- **EventBridge Rule**: Automatically triggers postprocessing when execution completes
- **IAM Roles**: Three separate permission sets (explained below)

**The Three-Stage Workflow**:

```
Stage 1: PREPROCESSING
├─ Input: "Run acme-corp's 'daily-report' schedule"
├─ Looks up: tenant_id + target_alias → actual Lambda ARN
├─ Merges: schedule payload + target defaults → final payload
└─ Output: "Invoke arn:aws:lambda:...:send-report with payload {…}"

Stage 2: EXECUTION (routes based on type)
├─ Lambda Target → Execution Helper invokes it, captures logs
├─ ECS Target → Step Functions runs Docker container, waits for callback
└─ Step Functions Target → Nested execution, waits for completion

Stage 3: POSTPROCESSING (automatic via EventBridge)
├─ Triggered when execution succeeds/fails
├─ Records to DynamoDB: status, result, timestamp, logs URL
└─ UI shows execution history with clickable CloudWatch logs link
```

**Why Use Step Functions Instead of Just Lambda?**

Imagine you want to run a long-running data processing job in a Docker container (ECS). A Lambda function times out after 15 minutes, but Step Functions can wait for hours or even days.

**Benefits**:
- **Visual workflow**: See execution flow in AWS console as a diagram
- **Built-in retries**: If preprocessing fails, Step Functions automatically retries
- **Long-running support**: ECS tasks can run for hours without timing out
- **Execution history**: Full audit trail of every step with input/output
- **No custom error handling**: Step Functions handles success/failure automatically

**The Security Model - "Defense in Depth"**

The system uses **three separate IAM roles** with different permissions:

1. **API Role** (used by the FastAPI Lambda)
   - ✅ **Can**: Read/write DynamoDB, create EventBridge schedules, manage users
   - ✅ **Can**: Start the Executor Step Functions
   - ❌ **Cannot**: Directly invoke target Lambda functions or run ECS tasks
   - **Why**: API should schedule things, not execute them directly

2. **Scheduler Role** (used by EventBridge Scheduler)
   - ✅ **Can**: ONLY start the Executor Step Functions
   - ❌ **Cannot**: Do literally anything else
   - **Why**: If the scheduler role is compromised, attacker can only trigger the orchestrator (which has its own validation)

3. **Executor Role** (used by Step Functions)
   - ✅ **Can**: Invoke any Lambda, run any ECS task, start any Step Functions
   - ✅ **Can**: Pass IAM roles to ECS tasks
   - **Why**: This is the ONLY role with broad execution permissions - centralized control point

**Why This Three-Tier Model Is Secure**:

Think of it like a restaurant:
- **API Role** = Waiter: Takes orders, checks if you can pay, but doesn't cook
- **Scheduler Role** = Alarm Clock: Tells the kitchen "it's time for the lunch rush" but doesn't place orders
- **Executor Role** = Chef: The only one who actually cooks food

If someone hacks the waiter's account, they can't cook food directly. If they hack the alarm clock, it can only ring at the kitchen door. Only the chef has access to the stove, and the chef only cooks food that came through proper channels (waiter → order ticket → kitchen).

**Additional Security Layers**:
- **Preprocessing validates**: "Does this tenant actually have access to this target alias?"
- **DynamoDB enforces**: All queries filtered by tenant ID - can't query other tenants' data
- **CloudTrail logs**: Every AWS API call logged for audit (who started which execution when)
- **No direct access**: Users never get IAM credentials - they only get Cognito tokens for the API

---

## How the Pieces Fit Together

### The Complete Flow (Scheduled Execution)

```
┌──────────────────────────────────────────────────────────────┐
│ 1. USER CREATES SCHEDULE (via Web UI)                       │
├──────────────────────────────────────────────────────────────┤
│ User: "Run my 'daily-report' function every day at 9 AM"    │
│ ↓                                                            │
│ Web UI → API Gateway → API Lambda                           │
│ ↓                                                            │
│ API Lambda:                                                  │
│   • Verifies JWT token (Cognito)                            │
│   • Checks user has access to tenant (DynamoDB)             │
│   • Creates EventBridge schedule:                           │
│     "Every day at 9 AM, invoke Step Functions with payload" │
│   • Saves schedule metadata to DynamoDB                     │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 2. EVENTBRIDGE TRIGGERS AT SCHEDULED TIME                   │
├──────────────────────────────────────────────────────────────┤
│ EventBridge (at 9 AM): "Time to run daily-report!"          │
│ ↓                                                            │
│ Assumes Scheduler Role (limited permissions)                │
│ ↓                                                            │
│ Starts Executor Step Functions with:                        │
│   {                                                          │
│     "tenant_id": "acme-corp",                               │
│     "target_alias": "daily-report",                         │
│     "schedule_id": "report-9am",                            │
│     "payload": {"email": "sales@acme.com"}                  │
│   }                                                          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 3. EXECUTOR ORCHESTRATES (Step Functions)                   │
├──────────────────────────────────────────────────────────────┤
│ Stage 1: Preprocessing Lambda                               │
│   • Query DynamoDB: "What's acme-corp's daily-report?"     │
│   • Result: Target ID "send-report-v2"                      │
│   • Query DynamoDB: "What's send-report-v2's config?"      │
│   • Result: ARN "arn:aws:lambda:...send-report"            │
│   • Merge payloads: schedule + target defaults             │
│ ↓                                                            │
│ Stage 2: Execute (routes by type)                           │
│   • Lambda target? → Execution Helper invokes it           │
│   • ECS target? → Run Docker container                     │
│   • Step Functions target? → Nested execution              │
│ ↓                                                            │
│ Stage 3: Postprocessing (automatic via EventBridge rule)    │
│   • EventBridge detects: "Execution succeeded!"            │
│   • Triggers Postprocessing Lambda                         │
│   • Writes to DynamoDB:                                    │
│     - Status: "SUCCEEDED"                                   │
│     - Result: {…} (response from target)                   │
│     - Timestamp: "2024-11-26T09:00:15Z"                    │
│     - Logs URL: "https://console.aws.amazon.com/..."       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 4. USER VIEWS RESULTS (via Web UI)                          │
├──────────────────────────────────────────────────────────────┤
│ User: "Show me execution history for daily-report"          │
│ ↓                                                            │
│ Web UI → API Gateway → API Lambda                           │
│ ↓                                                            │
│ API Lambda queries DynamoDB:                                │
│   • Filter: tenant_id = "acme-corp", schedule = "9am"      │
│   • Sort: By timestamp (newest first)                       │
│   • Return: Last 100 executions with status, result, logs  │
│ ↓                                                            │
│ Web UI displays:                                            │
│   ✅ 2024-11-26 09:00 - Success - "Report sent" - [Logs]   │
│   ✅ 2024-11-25 09:00 - Success - "Report sent" - [Logs]   │
│   ❌ 2024-11-24 09:00 - Failed - "Email error" - [Logs]    │
└──────────────────────────────────────────────────────────────┘
```

### Interdependencies

**API ↔ Execution Engine**:
- API creates EventBridge schedules → EventBridge triggers Executor
- API can start Executor directly for on-demand execution
- Executor reads data API wrote to DynamoDB (targets, mappings)
- Executor writes execution results → API reads them for history display

**Web UI ↔ API**:
- UI gets Cognito tokens → sends to API with every request
- UI makes REST calls → API returns JSON responses
- UI displays execution history → API queries DynamoDB and returns results

**All Components ↔ DynamoDB**:
- API: Reads/writes targets, tenants, mappings, schedules, users
- Executor Preprocessing: Reads targets and mappings
- Executor Postprocessing: Writes execution results
- **Tenant isolation**: All queries filter by tenant_id - no cross-tenant data leakage

**All Components ↔ CloudWatch Logs & X-Ray**:
- Every Lambda logs to CloudWatch (debugging)
- X-Ray traces requests across all services (performance monitoring)
- Execution Helper captures target's CloudWatch logs URL → stored in DynamoDB → clickable in UI

---

## CI/CD and Deployment

### Technology Stack

**Frontend**:
- React (JavaScript UI framework)
- npm (package manager)
- Build output: Static HTML/CSS/JS files

**Backend**:
- Python 3.13 (runtime)
- FastAPI (web framework)
- Boto3 (AWS SDK)
- Mangum (Lambda adapter for FastAPI)

**Infrastructure**:
- AWS SAM (Serverless Application Model - CloudFormation extension)
- CloudFormation (infrastructure as code)

### The Deployment Process (Automated)

**One-Command Deploy**: `.\quickdeploy.ps1` (PowerShell) or `./quickdeploy.sh` (Bash)

**What happens behind the scenes**:

```
Step 1: Build Frontend
├─ cd ui/
├─ npm run build
└─ Output: ui/build/ (HTML, CSS, JS, images)

Step 2: Bundle Frontend with Backend
├─ Copy ui/build/* → ExecutionAPI/app/wwwroot/
└─ Result: API Lambda will serve these files

Step 3: Validate Infrastructure
├─ sam validate --lint
└─ Checks template.yaml for syntax errors

Step 4: Build Lambda Packages
├─ sam build
├─ For each Lambda function:
│   ├─ Install Python dependencies (requirements.txt)
│   ├─ Copy source code
│   └─ Create deployment package (.zip)
└─ Output: .aws-sam/build/ directory

Step 5: Deploy to AWS
├─ sam deploy --no-confirm-changeset
├─ Uploads Lambda .zip files to S3
├─ Creates/updates CloudFormation stack:
│   ├─ Creates API Gateway (if first deploy)
│   ├─ Creates 6 DynamoDB tables (if first deploy)
│   ├─ Creates Cognito User Pool (if first deploy)
│   ├─ Creates/updates Lambda functions
│   ├─ Creates Step Functions state machine
│   └─ Creates IAM roles with proper permissions
└─ Waits for deployment to complete (~2-5 minutes)

Step 6: Post-Deployment Configuration
├─ Query CloudFormation for outputs (API URL, Cognito IDs)
├─ Update Cognito User Pool Client:
│   ├─ Set callback URL: https://{api-url}/callback
│   └─ Set logout URL: https://{api-url}/app/
└─ Display deployment info to user
```

**Output Example**:
```
Application URL: https://xyz123.execute-api.us-east-1.amazonaws.com/dev/
Click to open: https://xyz123.execute-api.us-east-1.amazonaws.com/dev/

Deployment complete!
```

### How to Clone and Deploy Your Own

**Prerequisites**:
- AWS Account with admin permissions
- AWS CLI installed and configured (`aws configure`)
- AWS SAM CLI installed (`pip install aws-sam-cli`)
- Node.js and npm installed (for React build)
- Python 3.13 installed
- Git installed

**Step-by-Step**:

```bash
# 1. Clone the repository
git clone https://github.com/your-org/serverless-task-scheduler.git
cd serverless-task-scheduler

# 2. Install UI dependencies
cd ui
npm install
cd ..

# 3. Configure deployment parameters
# Edit samconfig.toml and set:
#   - parameter_overrides: Owner="your-email@example.com" Environment="dev"
#   - stack_name: "your-stack-name"
#   - region: "us-east-1" (or your preferred region)

# 4. Run first-time guided deployment
sam deploy --guided

# You'll be prompted for:
#   - Stack name: e.g., "my-sts-dev"
#   - AWS Region: e.g., "us-east-1"
#   - Owner: your-email@example.com (becomes bootstrap admin)
#   - Environment: e.g., "dev"
#   - StackName: e.g., "sts"
#   - Confirm: Y (to all prompts)

# SAM saves your choices to samconfig.toml for future deployments

# 5. After first deploy, use quick deploy script
.\quickdeploy.ps1   # Windows PowerShell
# OR
./quickdeploy.sh    # Linux/Mac

# 6. Open the URL shown and log in
# First-time login:
#   - Check your email for temporary password from Cognito
#   - Log in with your email + temporary password
#   - You'll be prompted to set a new password
```

**Environment Variables** (configured in template.yaml, automatically set):
- `DYNAMODB_TABLE`, `DYNAMODB_TENANTS_TABLE`, etc. - Table names
- `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID` - Authentication config
- `API_BASE_PATH` - Stage name (e.g., "dev")
- `SCHEDULER_ROLE_ARN` - IAM role for EventBridge
- `STEP_FUNCTIONS_EXECUTOR_ARN` - State machine ARN

**No manual configuration needed** - SAM sets everything up automatically!

### Multi-Environment Deployment

Deploy separate dev/staging/prod environments:

```bash
# Deploy dev
sam deploy --config-env dev --parameter-overrides Environment=dev

# Deploy staging
sam deploy --config-env staging --parameter-overrides Environment=staging

# Deploy prod
sam deploy --config-env prod --parameter-overrides Environment=prod
```

Each environment gets:
- Separate DynamoDB tables: `sts-dev-targets-*`, `sts-prod-targets-*`
- Separate Lambda functions: `sts-dev-api-*`, `sts-prod-api-*`
- Separate Cognito User Pools (separate user accounts per environment)
- Separate API Gateway stages: `/dev/`, `/prod/`

**Why This Matters**:
- Test changes in dev without affecting prod users
- Promote changes: dev → staging → prod
- Rollback: Redeploy previous version to prod
- Cost isolation: See dev vs prod costs separately

### CI/CD Integration (GitHub Actions Example)

```yaml
# .github/workflows/deploy.yml
name: Deploy to AWS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.13'

      - name: Setup AWS SAM
        uses: aws-actions/setup-sam@v2

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Deploy
        run: ./quickdeploy.sh
```

**What this does**:
- Every push to `main` branch triggers deployment
- GitHub Actions runner builds UI + Lambda packages
- SAM deploys to AWS automatically
- Takes ~5-10 minutes end-to-end

---

## Why This Architecture?

### Serverless Benefits

**No Servers to Manage**:
- No EC2 instances to patch or update
- No capacity planning ("do we need 2 servers or 10?")
- No SSH keys or security groups to manage

**Pay Only for What You Use**:
- Lambda: Charged per request + execution time (milliseconds)
- DynamoDB: Charged per read/write operation (on-demand mode)
- Step Functions: Charged per state transition
- Example: 10,000 executions/month might cost $5-10

**Auto-Scaling**:
- 1 user or 10,000 users - same code, AWS handles scaling
- Black Friday traffic spike? No problem
- Overnight low traffic? Costs drop automatically

### Security Benefits

**Defense in Depth**:
- Multiple security layers (Cognito, IAM roles, DynamoDB filtering)
- If one layer is bypassed, others still protect

**Least Privilege**:
- Each component has ONLY the permissions it needs
- Compromise of one role doesn't give access to everything

**Audit Trail**:
- CloudTrail logs every AWS API call (who did what when)
- Execution history in DynamoDB (full history of all runs)
- CloudWatch Logs (detailed logs for debugging)

**Multi-Tenant Isolation**:
- Database-level isolation (every query filters by tenant_id)
- Users can't even query other tenants' data
- No shared secrets between tenants

### Operational Benefits

**One-Command Deploy**:
- Infrastructure + backend + frontend deployed together
- No "frontend works but backend is down" issues

**Built-in Monitoring**:
- CloudWatch Logs for debugging
- X-Ray for performance tracing
- DynamoDB execution history for audit

**Automatic Recovery**:
- Lambda automatically retries on transient failures
- Step Functions has built-in retry logic
- EventBridge scheduler retries on target unavailability

**No Downtime Deploys**:
- SAM gradually shifts traffic to new version
- Old version stays active during deploy
- Automatic rollback on errors

---

## Real-World Use Cases

### 1. SaaS Application Backend
Multiple customers share the platform, each with their own:
- Users (isolated via Cognito + DynamoDB)
- Automated workflows (isolated via tenant_id)
- Execution history (can't see other customers' data)

### 2. Enterprise Automation Hub
Different departments schedule their own tasks:
- Marketing: Send campaigns every Tuesday at 10 AM
- Finance: Generate reports first of every month
- IT: Health checks every 5 minutes
- Each department sees only their own schedules

### 3. Event-Driven Workflows
Chain multiple services together:
- User uploads file to S3 → triggers processing Lambda
- Processing complete → triggers notification Lambda
- All executions tracked with full history

### 4. Multi-Region Disaster Recovery
Deploy to multiple AWS regions:
- Primary: us-east-1 (Virginia)
- Failover: us-west-2 (Oregon)
- If primary region fails, Route 53 redirects to failover

---

## Summary: Why Choose This Architecture?

**For Students/Developers**:
- Learn modern cloud architecture patterns
- See IAM security model in practice
- Understand multi-tenant SaaS design
- Experience infrastructure as code (SAM/CloudFormation)

**For Businesses**:
- **Fast deployment**: Clone repo → deploy → running in 10 minutes
- **Low cost**: Pay only for executions, not idle servers
- **Secure by default**: Multiple security layers built-in
- **Multi-tenant ready**: Serve multiple customers with one deployment
- **Scalable**: Handles 10 or 10,000,000 executions with same code

**For Operations Teams**:
- **No servers to manage**: Fully serverless
- **Automatic scaling**: AWS handles capacity
- **Built-in monitoring**: CloudWatch, X-Ray, execution history
- **One-command deploy**: `./quickdeploy.ps1` does everything
- **Multi-environment**: Dev/staging/prod with parameter overrides

**The Bottom Line**: A production-ready, secure, multi-tenant task scheduler that you can deploy in minutes and scale to millions of executions - without managing any servers.
