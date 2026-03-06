# feat: Add Read-Only Role for Tenant Users (Ops/Troubleshooting Access)

## Background

The current permission model is binary: a user is either a **global admin** (member of the `admin` tenant) or a **tenant member** with full read/write/execute access to everything mapped to their tenant. There is no way to give an ops team member visibility into schedules, payloads, and execution history without also granting them the ability to create/modify/delete schedules or trigger executions.

### Relevant Data Model

**`{stack}-{env}-user-mappings` table** (Global Table)
- PK: `user_id` (email) + `tenant_id`
- Currently has no role or permission field — membership alone grants full access

**`{stack}-{env}-tenant-mappings` table** (Global Table)
- Has an `authorized_groups` attribute (stored but not enforced in authorization logic)

**`authorization.py`** contains a `require_group()` stub that is not yet implemented.

## Proposed Solution

Add a `role` attribute to the **UserMappings** table to distinguish between:

| Role | Access |
|------|--------|
| `member` (default, current behavior) | Full read/write/execute access within their tenant |
| `readonly` | Read-only: can view schedules, payloads, execution history; cannot create/modify/delete schedules or trigger executions |

### Required Changes

1. **DynamoDB — `user-mappings` table**
   - Add a `role` attribute (`"member"` \| `"readonly"`) to each user-tenant mapping record
   - Existing records default to `"member"` (backward compatible — no migration required if checks fall back to `"member"` when attribute is absent)

2. **API — `authorization.py`**
   - Implement `require_writable_tenant_access(tenant_id)`: wraps `require_tenant_access` and additionally enforces `role != "readonly"`
   - Apply this to all mutating routes within a tenant:
     - `POST/PUT/DELETE /tenants/{tenant_id}/schedules/...`
     - `POST /tenants/{tenant_id}/mappings/{target_alias}/_execute`
     - Any other write endpoints scoped to a tenant

3. **API — `user.py` (user management router)**
   - Expose `role` when inviting users (`POST /user/management/invite`) — default `"member"`
   - Expose `role` when updating user-tenant assignments (`PUT /user/management/{user_id}`)
   - Return `role` in `GET /users` and `GET /user/management` responses

4. **UI — User Management**
   - Add role selector (Member / Read-Only) when assigning a user to a tenant
   - Display role in the user list for each tenant

## Acceptance Criteria

- [ ] `role` attribute is stored on user-tenant mappings (`"member"` or `"readonly"`)
- [ ] Read-only users can view schedules, payloads, and execution history for their tenant
- [ ] Read-only users receive a `403` if they attempt to create/edit/delete a schedule or trigger an execution
- [ ] Admins can assign and update the `role` when inviting or managing users
- [ ] Existing users without a `role` attribute behave as `"member"` (no breaking change)
- [ ] Role is visible in the user management UI

### Error Handling Note

The frontend currently distinguishes between two auth error codes — behavior must remain correct for read-only users:

- **`401` (expired/missing token)** → global `auth-failure` handler in `App.jsx` clears session and redirects to login. This should continue to fire for unauthenticated requests regardless of role.
- **`403` (authenticated but unauthorized)** → currently has no global handler; each component surfaces it as a generic error. For read-only users hitting write endpoints, the UI should show a clear "You don't have permission to perform this action" message rather than a generic error alert — and must **not** redirect to login, since the user's session is still valid.

## Notes

- The `authorized_groups` field on `tenant-mappings` and the `require_group()` stub in `authorization.py` are not used by this change — they can be addressed separately if per-target-mapping group enforcement is ever needed.
- Admins retain full access to all tenants regardless of any role field.
