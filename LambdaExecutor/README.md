# Lambda Executor

This Lambda function is invoked by EventBridge Scheduler to execute scheduled tasks.

## Purpose
- Receives schedule execution requests from EventBridge Scheduler
- Resolves tenant target mappings from DynamoDB
- Invokes the appropriate target (Lambda, ECS, Step Functions)
- Records execution results in DynamoDB

## Event Format
```json
{
    "tenant_id": "jer",
    "target_alias": "calculator",
    "schedule_id": "daily-calculation",
    "execution_time": "2025-01-15T10:00:00Z",
    "payload": {...}
}
```

## IAM Permissions
- DynamoDB: Read from tenant mappings and targets tables
- DynamoDB: Write to executions table
- Lambda: Invoke any Lambda function
- ECS: Run tasks
- Step Functions: Start executions

## Environment Variables
- DYNAMODB_TENANT_TABLE: Tenant mappings table name
- DYNAMODB_TABLE: Targets table name
- DYNAMODB_EXECUTIONS_TABLE: Executions table name

## Architecture
EventBridge Scheduler → LambdaExecutor (with IAM) → Target Lambda/ECS/Step Function

This architecture eliminates the need for API authentication when executing scheduled tasks,
as the LambdaExecutor has direct IAM permissions to invoke targets.
