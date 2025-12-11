# Bruno Collection Update Summary

## ✅ ALL UPDATES COMPLETE

The Bruno collection has been fully updated to match the OpenAPI specification from:
`https://y4ne2vk0hf.execute-api.us-east-2.amazonaws.com/dev/api/openapi.json`

## Completed Updates

### Collection Configuration
- ✅ Updated `collection.bru` with correct baseUrl format
- ✅ Added all common variables: tenant_id, target_alias, target_id, schedule_id, execution_id, user_id
- ✅ Updated documentation with correct terminology

### Target Endpoints (Admin)
- ✅ `Create Target.bru` - Renamed from "Create Function", updated terminology
- ✅ `Get Targets.bru` - Renamed from "Get Functions"
- ✅ `Update Target.bru` - NEW - Update target definitions
- ✅ `Delete Target.bru` - NEW - Delete target definitions

### Authentication Endpoints
- ✅ `Auth - Login.bru` - New authentication endpoint

### Tenant Endpoints (Admin)
- ✅ `Get Tenants.bru` - NEW - List all tenants
- ✅ `Create Tenant.bru` - NEW - Create new tenant
- ✅ `Get Tenant.bru` - NEW - Get tenant details
- ✅ `Update Tenant.bru` - NEW - Update tenant
- ✅ `Delete Tenant.bru` - NEW - Delete tenant

### Tenant Mapping Endpoints
- ✅ `Create Tenant Mapping.bru` - Updated to use {{variables}}
- ✅ `Get Tenant Mappings.bru` - Updated to use {{variables}}
- ✅ `Get Tenant Function Mapping.bru` - Updated to use {{variables}}
- ✅ `Update Tenant Function Mapping.bru` - Updated to use {{variables}}
- ✅ `Delete Tenant Function Mapping.bru` - Updated to use {{variables}}
- ✅ `Execute Tenant Function.bru` - Updated to use {{variables}}

### Schedule Endpoints
- ✅ `Create Schedule.bru` - Updated to use {{variables}}
- ✅ `Update Schedule.bru` - Updated to use {{variables}}
- ✅ `Delete Schedule.bru` - Updated to use {{variables}}
- ✅ `Get Target Schedules.bru` - Updated to use {{variables}}
- ✅ `Get Tenant Schedules.bru` - Updated to use {{variables}}

### Execution History Endpoints
- ✅ `Get Executions.bru` - NEW - List executions for a mapping
- ✅ `Get Execution Details.bru` - NEW - Get detailed execution info
- ✅ `Redrive Execution.bru` - NEW - Retry a failed execution

### User Management Endpoints (Admin)
- ✅ `Get User Info.bru` - NEW - Get current user info
- ✅ `Get Users.bru` - NEW - List all users
- ✅ `Invite User.bru` - NEW - Create and invite new user
- ✅ `Grant Tenant Access.bru` - NEW - Grant user access to tenant
- ✅ `Revoke Tenant Access.bru` - NEW - Revoke user access
- ✅ `Get User Tenants.bru` - NEW - List user's tenant access

### Utility Endpoints
- ✅ `Health Check.bru` - Already using {{baseUrl}}
- ✅ `Root.bru` - Already using {{baseUrl}}
- ✅ `Get Open Api Endpoint.bru` - Already using {{baseUrl}}

### Removed Old Files
- ❌ Deleted `Create Function.bru` (replaced with Create Target.bru)
- ❌ Deleted `Get Functions.bru` (replaced with Get Targets.bru)
- ❌ Deleted `Delete Function.bru` (replaced with Delete Target.bru)

## Key Changes

1. **URL Format**: All URLs now use `{{baseUrl}}` which includes `/api` prefix
   - Old: `http://localhost:8080/targets`
   - New: `{{baseUrl}}/targets` where baseUrl = `https://...amazonaws.com/dev/api`

2. **Terminology**: "Functions" → "Targets"
   - Reflects the actual API naming convention
   - Targets can be Lambda, ECS, or Step Functions

3. **Variables**: Using Bruno's `{{variable}}` syntax instead of `:param`
   - More consistent with collection-level variables
   - Easier to update in one place

## Notable Endpoints Still Not Implemented

These endpoints are mentioned in the OpenAPI spec but may not be fully implemented in the backend:

### Authentication (Not Yet Added)
- POST /auth/signup - User self-registration
- POST /auth/logout - Logout endpoint
- POST /auth/forgot-password - Password reset request
- POST /auth/confirm-forgot-password - Confirm password reset

These were not added because they may not be implemented in the backend yet.
Add them once backend implementation is confirmed.

## Testing Checklist

To verify the collection works correctly with your deployment:

1. **Setup**
   - Open the collection in Bruno
   - Update the `authToken` variable after logging in
   - Update `tenant_id`, `target_alias`, etc. as needed

2. **Test Authentication**
   - [ ] Login and get JWT token (Auth - Login.bru)
   - [ ] Get current user info (Get User Info.bru)

3. **Test Admin Operations** (requires admin tenant membership)
   - [ ] List targets (Get Targets.bru)
   - [ ] Create a target (Create Target.bru)
   - [ ] Update a target (Update Target.bru)
   - [ ] List tenants (Get Tenants.bru)
   - [ ] Create a tenant (Create Tenant.bru)

4. **Test Tenant Operations**
   - [ ] Create a tenant mapping (Create Tenant Mapping.bru)
   - [ ] Get tenant mappings (Get Tenant Mappings.bru)
   - [ ] Execute the mapping (Execute Tenant Function.bru)

5. **Test Schedule Operations**
   - [ ] Create a schedule (Create Schedule.bru)
   - [ ] List schedules (Get Target Schedules.bru)
   - [ ] Update schedule (Update Schedule.bru)
   - [ ] Delete schedule (Delete Schedule.bru)

6. **Test Execution History**
   - [ ] List executions (Get Executions.bru)
   - [ ] Get execution details (Get Execution Details.bru)
   - [ ] Redrive failed execution (Redrive Execution.bru)

7. **Test User Management** (admin only)
   - [ ] List users (Get Users.bru)
   - [ ] Invite user (Invite User.bru)
   - [ ] Grant tenant access (Grant Tenant Access.bru)
   - [ ] List user's tenants (Get User Tenants.bru)
   - [ ] Revoke tenant access (Revoke Tenant Access.bru)

## Collection Variables

All requests now use these collection-level variables:

```
baseUrl: https://y4ne2vk0hf.execute-api.us-east-2.amazonaws.com/dev/api
authToken: your-jwt-token-here
tenant_id: test-tenant
target_alias: test-target
target_id: my-lambda-v1
schedule_id: schedule-uuid
execution_id: execution-uuid
user_id: user-cognito-sub
```

Update these in [collection.bru](collection.bru:1-9) as needed for your testing.
