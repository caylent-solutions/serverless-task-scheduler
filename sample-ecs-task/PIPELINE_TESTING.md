# ECS Task Pipeline Testing - What Actually Happens

## What You're Thinking
"If I use `.sync` to wait for the ECS task to finish, then use `ResultSelector` to capture stdout output and pass it to the next state."

## What Actually Happens

### The ECS runTask.sync Response

When you use `arn:aws:states:::ecs:runTask.sync`, Step Functions returns this structure:

```json
{
  "tasks": [
    {
      "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/abc123",
      "clusterArn": "arn:aws:ecs:us-east-1:123456789012:cluster/my-cluster",
      "taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/calculator-task:1",
      "containers": [
        {
          "containerArn": "arn:aws:ecs:us-east-1:123456789012:container/abc123",
          "name": "calculator",
          "lastStatus": "STOPPED",
          "exitCode": 0,
          "reason": "Essential container in task exited"
        }
      ],
      "lastStatus": "STOPPED",
      "desiredStatus": "STOPPED",
      "cpu": "256",
      "memory": "512",
      "startedAt": "2025-11-25T10:00:00.000Z",
      "stoppedAt": "2025-11-25T10:05:00.000Z",
      "stoppedReason": "Essential container in task exited",
      "stopCode": "EssentialContainerExited"
    }
  ],
  "failures": []
}
```

### Notice What's Missing?

**There is NO field for stdout, application output, or results.**

You can access:
- ✅ `exitCode` (0 = success, non-zero = failure)
- ✅ `taskArn` (for CloudWatch logs lookup)
- ✅ `startedAt`, `stoppedAt` (timing)
- ✅ `lastStatus` (STOPPED, etc.)
- ❌ **NO stdout or application output**

### Your Current entrypoint.py Does This:

```python
result = {
    "status": "success",
    "result": {"result": 8},
    "execution_id": "ecs-task-123"
}
print(json.dumps(result))  # Goes to CloudWatch Logs ONLY
sys.exit(0)
```

That `print()` output goes to CloudWatch Logs at `/ecs/calculator-task`, but **Step Functions cannot see it**.

## Test Case: What ResultSelector Can Actually Capture

### State Machine Example:

```json
{
  "ExecuteECSTarget": {
    "Type": "Task",
    "Resource": "arn:aws:states:::ecs:runTask.sync",
    "Parameters": {
      "Cluster": "my-cluster",
      "TaskDefinition": "calculator-task",
      "LaunchType": "FARGATE",
      "NetworkConfiguration": {
        "AwsvpcConfiguration": {
          "Subnets": ["subnet-123"],
          "AssignPublicIp": "ENABLED"
        }
      },
      "Overrides": {
        "ContainerOverrides": [{
          "Name": "calculator",
          "Environment": [{
            "Name": "EXECUTION_PAYLOAD",
            "Value": "{\"action\":\"add\",\"x\":5,\"y\":3}"
          }]
        }]
      }
    },
    "ResultSelector": {
      "exitCode.$": "$.tasks[0].containers[0].exitCode",
      "taskArn.$": "$.tasks[0].taskArn",
      "status.$": "$.tasks[0].lastStatus",
      "startTime.$": "$.tasks[0].startedAt",
      "stopTime.$": "$.tasks[0].stoppedAt",
      "CANNOT_GET_THIS.$": "$.tasks[0].applicationOutput"  // DOES NOT EXIST
    },
    "ResultPath": "$.execution_result",
    "Next": "NextState"
  },
  "NextState": {
    "Type": "Pass",
    "Parameters": {
      "message": "The calculator result was...",
      "exitCode.$": "$.execution_result.exitCode",
      "comment": "We only know exitCode (0), not the actual calculation result (8)"
    },
    "End": true
  }
}
```

### What $.execution_result Contains:

```json
{
  "execution_result": {
    "exitCode": 0,
    "taskArn": "arn:aws:ecs:...",
    "status": "STOPPED",
    "startTime": "2025-11-25T10:00:00.000Z",
    "stopTime": "2025-11-25T10:05:00.000Z"
  }
}
```

**The calculation result (8) is nowhere to be found!**

## Why This Limitation Exists

The `.sync` integration works at the **ECS task control plane level**, not the application level:
- Step Functions polls ECS DescribeTasks API
- ECS only knows about task lifecycle, not container stdout
- CloudWatch Logs is separate from ECS task metadata

## The ONLY Ways to Pass Data to Downstream States

### Option 1: Task Token Callback ⭐ RECOMMENDED

**Change state machine to:**
```json
{
  "ExecuteECSTarget": {
    "Type": "Task",
    "Resource": "arn:aws:states:::ecs:runTask.waitForTaskToken",
    "HeartbeatSeconds": 300,
    "Parameters": {
      "Cluster": "my-cluster",
      "TaskDefinition": "calculator-task",
      "LaunchType": "FARGATE",
      "NetworkConfiguration": {
        "AwsvpcConfiguration": {
          "Subnets": ["subnet-123"],
          "AssignPublicIp": "ENABLED"
        }
      },
      "Overrides": {
        "ContainerOverrides": [{
          "Name": "calculator",
          "Environment": [
            {
              "Name": "TASK_TOKEN",
              "Value.$": "$$.Task.Token"
            },
            {
              "Name": "EXECUTION_PAYLOAD",
              "Value": "{\"action\":\"add\",\"x\":5,\"y\":3}"
            }
          ]
        }]
      }
    },
    "ResultPath": "$.execution_result",
    "Next": "NextState"
  },
  "NextState": {
    "Type": "Pass",
    "Parameters": {
      "message": "The calculator result was...",
      "result.$": "$.execution_result.result.result",
      "comment": "Now we have the actual result (8)!"
    },
    "End": true
  }
}
```

**Update entrypoint.py:**
```python
import boto3

def main():
    task_token = os.environ.get('TASK_TOKEN')
    payload_json = os.environ.get('EXECUTION_PAYLOAD')

    try:
        event = json.loads(payload_json)
        context = MockContext()

        # Call the calculator
        handler_result = lambda_handler(event, context)

        result = {
            "status": "success",
            "result": handler_result,
            "execution_id": context.aws_request_id,
            "timestamp": datetime.now().isoformat()
        }

        if task_token:
            # Send result DIRECTLY to Step Functions
            sfn = boto3.client('stepfunctions')
            sfn.send_task_success(
                taskToken=task_token,
                output=json.dumps(result)
            )
            logger.info("Sent result to Step Functions")
        else:
            # Fallback: just log
            print(json.dumps(result))

        sys.exit(0)

    except Exception as e:
        logger.error(f"Task failed: {e}")

        if task_token:
            sfn = boto3.client('stepfunctions')
            sfn.send_task_failure(
                taskToken=task_token,
                error='CalculationError',
                cause=str(e)
            )

        sys.exit(1)
```

**What $.execution_result contains now:**
```json
{
  "execution_result": {
    "status": "success",
    "result": {
      "result": 8
    },
    "execution_id": "ecs-task-abc123",
    "timestamp": "2025-11-25T10:05:00.123456"
  }
}
```

✅ **The downstream state CAN access the calculation result!**

### Option 2: S3 + Lambda Bridge

**ECS writes to S3:**
```python
# In entrypoint.py
execution_id = os.environ['EXECUTION_ID']
s3 = boto3.client('s3')

result = lambda_handler(event, context)

s3.put_object(
    Bucket='pipeline-results',
    Key=f'executions/{execution_id}/result.json',
    Body=json.dumps(result)
)

print(json.dumps({'s3_key': f'executions/{execution_id}/result.json'}))
sys.exit(0)
```

**State machine retrieves it:**
```json
{
  "ExecuteECSTarget": {
    "Type": "Task",
    "Resource": "arn:aws:states:::ecs:runTask.sync",
    "Parameters": { /* ... */ },
    "ResultPath": "$.ecs_metadata",
    "Next": "GetResults"
  },
  "GetResults": {
    "Type": "Task",
    "Resource": "arn:aws:states:::lambda:invoke",
    "Parameters": {
      "FunctionName": "GetECSResults",
      "Payload": {
        "taskArn.$": "$.ecs_metadata.tasks[0].taskArn",
        "executionId.$": "$$.Execution.Name"
      }
    },
    "ResultSelector": {
      "result.$": "$.Payload"
    },
    "ResultPath": "$.execution_result",
    "Next": "NextState"
  }
}
```

**GetECSResults Lambda:**
```python
def handler(event, context):
    s3 = boto3.client('s3')
    execution_id = event['executionId']

    response = s3.get_object(
        Bucket='pipeline-results',
        Key=f'executions/{execution_id}/result.json'
    )

    return json.loads(response['Body'].read())
```

### Option 3: DynamoDB + Native Integration

**ECS writes to DynamoDB:**
```python
# In entrypoint.py
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('pipeline-results')
execution_id = os.environ['EXECUTION_ID']

result = lambda_handler(event, context)

table.put_item(Item={
    'execution_id': execution_id,
    'result': result,
    'timestamp': datetime.now().isoformat()
})

sys.exit(0)
```

**State machine queries it:**
```json
{
  "ExecuteECSTarget": {
    "Type": "Task",
    "Resource": "arn:aws:states:::ecs:runTask.sync",
    "Parameters": { /* ... */ },
    "ResultPath": "$.ecs_metadata",
    "Next": "GetResults"
  },
  "GetResults": {
    "Type": "Task",
    "Resource": "arn:aws:states:::dynamodb:getItem",
    "Parameters": {
      "TableName": "pipeline-results",
      "Key": {
        "execution_id": {
          "S.$": "$$.Execution.Name"
        }
      }
    },
    "ResultSelector": {
      "result.$": "States.StringToJson($.Item.result.S)"
    },
    "ResultPath": "$.execution_result",
    "Next": "NextState"
  }
}
```

## Comparison Table

| Method | Pros | Cons | Latency | Complexity |
|--------|------|------|---------|------------|
| **.sync + ResultSelector** | ❌ **DOESN'T WORK** | Can't access stdout | N/A | N/A |
| **Task Token Callback** | Direct output to Step Functions | Requires IAM permissions | Low | Medium |
| **S3 + Lambda Bridge** | Handles large payloads | Extra Lambda invocation | Medium | Medium |
| **DynamoDB + Native** | Native integration, fast queries | 400KB item limit | Low | Medium |

## Recommendation

**Use the Task Token Callback pattern** for your sample ECS task. It's the cleanest solution for pipeline processing:

1. ✅ Results flow directly to downstream states
2. ✅ No additional services needed (no Lambda bridge)
3. ✅ Works for payloads up to 256KB
4. ✅ Native Step Functions pattern

Would you like me to update the sample ECS task to support the callback pattern?
