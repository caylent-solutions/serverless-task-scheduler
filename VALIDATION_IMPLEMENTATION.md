# URL-Safe Identifier Validation Implementation

## Overview

Implemented comprehensive input validation for URL-safe identifiers to prevent URL injection attacks and ensure consistent data format across the application. This affects all user-facing identifier fields: `tenant_id`, `target_id`, `target_alias`, and `schedule_id`.

## Security Rationale

**Problem**: Without validation, malicious users could inject special characters into identifiers that could:
- Break URL routing
- Cause path traversal attacks
- Inject malicious code into URL parameters
- Create inconsistent data formats

**Solution**: Restrict identifiers to URL-safe characters only: lowercase letters, numbers, underscores, and hyphens (`[a-z0-9_-]`).

## Implementation Details

### 1. Client-Side Validation (React UI)

**File**: [ui/src/utils/validation.js](ui/src/utils/validation.js)

Created a validation utility module with:
- `isUrlSafe(value)`: Check if a string is URL-safe
- `sanitizeUrlSafe(value)`: Remove invalid characters and convert to lowercase
- `validateUrlSafeIdentifier(value, fieldName)`: Validate and return error message if invalid
- `handleUrlSafeInput(setter)`: React input handler that auto-sanitizes input

**Pattern**: `/^[a-z0-9_-]+$/`
**Length**: 1-36 characters (UUID-compatible)

**Updated Components**:
- [ui/src/components/tenants/TenantList.js](ui/src/components/tenants/TenantList.js)
  - Tenant ID input field
  - Real-time sanitization as user types
  - Validation on form submit

- [ui/src/components/tenants/TenantMappingList.js](ui/src/components/tenants/TenantMappingList.js)
  - Target Alias input field
  - Real-time sanitization
  - Validation on form submit

### 2. Server-Side Validation (Python/FastAPI)

**File**: [ExecutionAPI/app/validation.py](ExecutionAPI/app/validation.py)

Created validation module with:
- `is_url_safe(value)`: Check if string is URL-safe
- `validate_url_safe_identifier(value, field_name)`: Validate and raise ValueError if invalid
- Helper functions: `validate_tenant_id()`, `validate_target_id()`, `validate_target_alias()`, `validate_schedule_id()`

**Pattern**: `r'^[a-z0-9_-]+$'`
**Length**: 1-36 characters (UUID-compatible)

**Updated Pydantic Models**:

1. **[ExecutionAPI/app/models/tenant.py](ExecutionAPI/app/models/tenant.py)**
   ```python
   @field_validator('tenant_id')
   @classmethod
   def validate_tenant_id_format(cls, v):
       return validate_tenant_id(v)
   ```

2. **[ExecutionAPI/app/models/target.py](ExecutionAPI/app/models/target.py)**
   ```python
   @field_validator('target_id')
   @classmethod
   def validate_target_id_format(cls, v):
       return validate_target_id(v)
   ```

3. **[ExecutionAPI/app/models/tenantmapping.py](ExecutionAPI/app/models/tenantmapping.py)**
   ```python
   @field_validator('tenant_id')
   @field_validator('target_alias')
   @field_validator('target_id')
   @classmethod
   def validate_*_format(cls, v):
       return validate_*(v)
   ```

4. **[ExecutionAPI/app/models/schedule.py](ExecutionAPI/app/models/schedule.py)**
   ```python
   @field_validator('tenant_id')
   @field_validator('schedule_id')
   @field_validator('target_alias')
   @classmethod
   def validate_*_format(cls, v):
       return validate_*(v)
   ```

## Validation Rules

### Allowed Characters
- Lowercase letters: `a-z`
- Numbers: `0-9`
- Underscore: `_`
- Hyphen: `-`

### Restrictions
- **Minimum length**: 1 character
- **Maximum length**: 36 characters (UUID-compatible length)
- **Case**: Lowercase only (uppercase automatically converted to lowercase in UI)
- **No spaces**: Automatically removed
- **No special characters**: Automatically removed (except `_` and `-`)
- **Rationale**: 36 characters supports UUIDs while keeping URLs manageable (e.g., `/tenant/alias/schedule/execution` with all IDs)

### Valid Examples
- `acme-corp`
- `user_123`
- `my-target-alias`
- `schedule-2025`
- `lambda-calculator`

### Invalid Examples (Auto-corrected in UI)
- `Acme Corp` → `acmecorp`
- `user@123` → `user123`
- `my target` → `mytarget`
- `Test_123!` → `test_123`

## User Experience

### Client-Side (Immediate Feedback)
1. **Real-time Sanitization**: As users type, invalid characters are automatically removed
2. **Lowercase Conversion**: Uppercase letters are automatically converted to lowercase
3. **Form Validation**: Before submission, validates identifier format
4. **Clear Error Messages**: Shows specific error if validation fails

### Server-Side (Security Layer)
1. **Pydantic Validation**: Automatic validation on all API requests
2. **HTTP 422 Response**: Returns detailed validation error if request fails
3. **Database Protection**: Invalid data never reaches the database
4. **API Documentation**: OpenAPI schema shows validation rules

## Benefits

### Security
- ✅ Prevents URL injection attacks
- ✅ Prevents path traversal attacks
- ✅ Protects against malicious input
- ✅ Ensures data consistency

### User Experience
- ✅ Clear, predictable identifier format
- ✅ Real-time feedback prevents errors
- ✅ Auto-correction reduces frustration
- ✅ Consistent across all forms

### Development
- ✅ Centralized validation logic
- ✅ Easy to maintain and update
- ✅ Consistent validation rules across frontend and backend
- ✅ Type-safe with Pydantic models

## Testing

### Client-Side Testing
1. Navigate to Tenant Management
2. Click "Add Tenant"
3. Try entering: `Test Corp!@#`
4. Expected: Automatically converts to `testcorp`
5. Submit with valid name and description
6. Expected: Successfully creates tenant

### Server-Side Testing
```bash
# Test with invalid tenant_id (should fail with 422)
curl -X POST "https://76260jfmx1.execute-api.us-east-2.amazonaws.com/dev/tenants" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "Test Corp!", "tenant_name": "Test", "description": "Test"}'

# Expected Response: HTTP 422 Unprocessable Entity
# {
#   "detail": [
#     {
#       "type": "value_error",
#       "loc": ["body", "tenant_id"],
#       "msg": "tenant_id must contain only lowercase letters, numbers, underscores, and hyphens"
#     }
#   ]
# }
```

## Migration Notes

### Existing Data
- Existing identifiers in the database are **not automatically updated**
- If existing data contains uppercase or special characters, it will continue to work
- New identifiers must follow the validation rules

### Backward Compatibility
- API endpoints using existing identifiers continue to work
- Only **new** identifiers are validated
- To enforce validation on existing data, run a migration script (not included)

## Future Enhancements

### Potential Additions
1. **Schedule ID Validation**: Add UI validation for schedule IDs (currently backend-only)
2. **Target ID Validation**: Add UI validation when creating targets
3. **Migration Script**: Script to validate and optionally fix existing identifiers
4. **Admin Override**: Allow admins to bypass validation for special cases
5. **Custom Patterns**: Allow configuration of validation pattern per deployment

## References

- [OWASP Input Validation](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [Pydantic Validators](https://docs.pydantic.dev/latest/concepts/validators/)
- [React Form Validation](https://react.dev/reference/react-dom/components/input#controlling-an-input-with-a-state-variable)
