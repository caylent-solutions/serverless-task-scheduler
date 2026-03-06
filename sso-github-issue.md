# feat: Add SSO / Social Login Support via OAuth2 (Google, Microsoft)

## Background

The application currently uses a Cognito user pool for authentication. Many customers will expect SSO support (e.g. "Sign in with Microsoft" or "Sign in with Google") rather than managing a separate username and password.

## Proposed Solution

Integrate OAuth2 social login (Google and/or Microsoft) that:

1. Allows users to authenticate via their existing Google or Microsoft account
2. Creates a corresponding user in the Cognito user pool on first login
3. Does **not** automatically grant the new user access to any tenant — tenant access must be provisioned separately by an admin

This approach keeps identity management in Cognito while offloading credential handling to the social identity provider.

## Considerations

**Throttling / abuse prevention:** Without rate limiting, a malicious actor could trigger bulk user creation in the Cognito pool by repeatedly initiating social logins with new accounts. Mitigation options include:

- Cognito's built-in [Lambda triggers](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-sign-up.html) (Pre Sign-up trigger) to reject or flag suspicious registrations
- Rate limiting at the API Gateway / ALB level on the OAuth2 callback endpoint
- Optionally require admin approval before a social-login-created account becomes active

## References

- [FastAPI OAuth2 guide](https://fastapi.tiangolo.com/tutorial/security/simple-oauth2/)
- [Cognito social identity provider docs](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-social-idp.html)

## Acceptance Criteria

- [ ] Users can sign in with Google and/or Microsoft
- [ ] A Cognito user is created on first social login
- [ ] New social-login users have no tenant access until explicitly granted by an admin
- [ ] Existing username/password login continues to work
- [ ] The OAuth2 callback / sign-up flow is rate-limited to prevent bulk user creation abuse
