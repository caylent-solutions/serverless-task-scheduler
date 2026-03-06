# feat: SES Email Notifications for User Management Events

## Background

Several user management actions in the platform currently happen silently from the user's perspective:

- Being granted or revoked access to a tenant
- Having their tenant access bulk-reassigned by an admin
- Having their account deleted

The only current notification is the Cognito-generated password reset email sent during the invite flow — and that email gives no context about the platform or which tenants the user has been given access to.

Since `user_id` in DynamoDB is the user's email address (from Cognito), we have a natural delivery address for every event.

## SES Verification — How It Actually Works

> **The user's concern:** Do we need to put each user's email into a verified state before sending?

**No — only the sender identity needs to be verified, not each recipient.** The distinction:

- **SES sandbox mode**: Both sender *and* every recipient must be verified identities in SES. This would completely break the use case — a newly invited user can't be in a pre-verified state.
- **SES production mode** (out of sandbox): Only the *sender* email or domain needs to be verified. You can send to any recipient at any address. This is the standard for any transactional email use case.

**Action required:** Submit an AWS SES production access request for each environment. This is routine for production applications and does not affect Cognito's existing email flows.

**Cognito emails are unaffected.** Cognito is currently configured with `EmailSendingAccount: COGNITO_DEFAULT` and should stay that way — Cognito's own password reset emails are a separate system. The API Lambda sends SES notifications independently without changing Cognito's configuration.

## Events to Notify

| Event | Recipient | Trigger | Admin notified? |
|---|---|---|---|
| User invited | New user | `POST /management/invite` | No (admin initiated it) |
| Tenant access granted | User | `POST /users/{user_id}/tenants/{tenant_id}` | No |
| Tenant access revoked | User | `DELETE /users/{user_id}/tenants/{tenant_id}` | No |
| Tenant access bulk-reassigned | User | `PUT /management/{user_id}` | No |
| User account deleted | Admin who performed deletion | `DELETE /management/{user_id}` | Yes (user no longer has an account to receive email) |

### Notes on specific events:

- **Invite**: Cognito already sends a password reset/verification code email. The SES notification complements it — it provides platform context (which tenants the user has been granted access to, a link to the app, who invited them). Both emails are sent.
- **Bulk reassignment**: Only send if something actually changed. Compute `tenants_added` and `tenants_removed` diffs (already computed in the endpoint) and send only if at least one is non-empty.
- **Deletion**: The user's account is gone, so email goes to the admin who performed the action as an audit confirmation.
- **Role changes** (future): When the read-only role feature is implemented, a role-change event should be added to this system.

## Proposed Implementation

### 1. AWS Prerequisites — `template.yaml`

**Do not change Cognito's email configuration.** Only the Lambda needs SES access.

Add `SES_SENDER_EMAIL` as a deploy-time parameter and environment variable:
```yaml
Parameters:
  SesNotificationEmail:
    Type: String
    Default: ''
    Description: Verified SES sender email for user notifications. Leave empty to disable.
```

Add to `AppLambda` environment:
```yaml
SES_NOTIFICATION_EMAIL: !Ref SesNotificationEmail
```

Add `ses:SendEmail` and `ses:SendRawEmail` to `AppLambdaRole`:
```yaml
- Effect: Allow
  Action:
    - ses:SendEmail
    - ses:SendRawEmail
  Resource: '*'
```

If `SES_NOTIFICATION_EMAIL` is empty, the notification service silently no-ops. This allows deployments that don't have SES configured to continue working unchanged.

### 2. SES Client Wrapper — `api/app/awssdk/ses.py`

New file following the pattern of the existing `cognito.py` wrapper:

```python
import boto3
import os
import logging

logger = logging.getLogger(__name__)
_ses_client = None

def get_ses_client():
    global _ses_client
    if _ses_client is None:
        _ses_client = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return _ses_client

def send_notification(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send an SES email. Returns True on success, False on failure (never raises)."""
    sender = os.environ.get('SES_NOTIFICATION_EMAIL', '')
    if not sender:
        return False  # Notifications disabled
    try:
        get_ses_client().send_email(
            Source=sender,
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject},
                'Body': {
                    'Html': {'Data': html_body},
                    'Text': {'Data': text_body}
                }
            }
        )
        logger.info(f"Notification sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send notification to {to_email}: {e}")
        return False
```

### 3. Notification Service — `api/app/services/notifications.py`

New file with one function per event type. Each function composes the subject/body and calls `send_notification()`. Email failures are logged but never raised — they must not fail the API operation.

Example:
```python
def notify_tenant_access_granted(user_email: str, tenant_id: str, granted_by: str):
    send_notification(
        to_email=user_email,
        subject=f"[STS] Access granted to tenant: {tenant_id}",
        html_body=render_tenant_granted(user_email, tenant_id, granted_by),
        text_body=f"You have been granted access to tenant '{tenant_id}' by {granted_by}."
    )
```

Functions needed:
- `notify_user_invited(user_email, tenants, invited_by)`
- `notify_tenant_access_granted(user_email, tenant_id, granted_by)`
- `notify_tenant_access_revoked(user_email, tenant_id, revoked_by)`
- `notify_access_reassigned(user_email, tenants_added, tenants_removed, updated_by)`
- `notify_user_deleted(admin_email, deleted_user_id, deleted_by)`

### 4. Integration Points — `api/app/routers/user.py`

Call the appropriate notification function after the DynamoDB write succeeds at each endpoint. Notifications fire after the state change is committed — if the notification fails, the operation still succeeded.

| Endpoint | After which operation | Function |
|---|---|---|
| `POST /management/invite` | After Cognito user created + DynamoDB mappings written | `notify_user_invited` |
| `POST /users/{user_id}/tenants/{tenant_id}` | After DynamoDB put_item | `notify_tenant_access_granted` |
| `DELETE /users/{user_id}/tenants/{tenant_id}` | After DynamoDB delete_item | `notify_tenant_access_revoked` |
| `PUT /management/{user_id}` | After DynamoDB batch write, if diff is non-empty | `notify_access_reassigned` |
| `DELETE /management/{user_id}` | After deletion | `notify_user_deleted` (to admin) |

## Email Content Guidelines

- **Plain language** — avoid jargon; users may not know what a "tenant" means in business terms
- **Always state who performed the action** — "granted by admin@example.com" — for auditability
- **Include a link to the platform** (configurable via an env var or derive from `API_BASE_PATH`)
- **No sensitive data in email body** — tenant IDs are acceptable; payloads, ARNs, and credentials are not
- **Both HTML and plain text** — SES supports both; plain text is a fallback for email clients that strip HTML

## What This Does Not Change

- Cognito's `EmailSendingAccount: COGNITO_DEFAULT` — untouched; password reset emails continue to be sent by Cognito
- Any existing user management logic — notifications are fire-and-forget additions, not modifications
- Behavior when `SES_NOTIFICATION_EMAIL` is not set — existing deployments are unaffected

## Relevant Files

- [`api/app/routers/user.py`](api/app/routers/user.py) — all trigger points
- [`api/app/awssdk/cognito.py`](api/app/awssdk/cognito.py) — reference pattern for new SES wrapper
- [`template.yaml`](template.yaml) — `AppLambdaRole` IAM additions, new parameter + env var
- New: `api/app/awssdk/ses.py`
- New: `api/app/services/notifications.py`

## Acceptance Criteria

- [ ] AWS SES production access requested for each environment (prerequisite — not a code change)
- [ ] Sender identity (domain or email) verified in SES for each environment (prerequisite)
- [ ] `SES_NOTIFICATION_EMAIL` deploy parameter exists; when empty, all notifications are silently skipped
- [ ] `AppLambdaRole` has `ses:SendEmail` and `ses:SendRawEmail`
- [ ] Email is sent on: user invite, tenant grant, tenant revoke, bulk reassignment (when diff is non-empty), user deletion (to admin)
- [ ] Invite email includes the list of tenants the user has been granted access to
- [ ] All emails include who performed the action
- [ ] SES send failure is logged as a warning and does not fail or roll back the API operation
- [ ] Cognito's email configuration is unchanged
- [ ] Existing deployments without `SES_NOTIFICATION_EMAIL` configured behave identically to today
