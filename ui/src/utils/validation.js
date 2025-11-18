/**
 * Validation utilities for URL-safe identifiers
 *
 * These validators ensure that user input is safe for use in URLs and API paths,
 * preventing URL injection attacks and ensuring consistent data format.
 */

// Pattern for URL-safe identifiers: alphanumeric (upper and lowercase), underscores, and hyphens
export const URL_SAFE_PATTERN = /^[a-zA-Z0-9_-]+$/;

/**
 * Validates if a string is URL-safe (lowercase alphanumeric, underscores, hyphens only)
 * @param {string} value - The value to validate
 * @returns {boolean} - True if valid, false otherwise
 */
export const isUrlSafe = (value) => {
  if (!value || typeof value !== 'string') {
    return false;
  }
  return URL_SAFE_PATTERN.test(value);
};

/**
 * Sanitizes input to be URL-safe by removing invalid characters
 * @param {string} value - The value to sanitize
 * @returns {string} - Sanitized value
 */
export const sanitizeUrlSafe = (value) => {
  if (!value || typeof value !== 'string') {
    return '';
  }
  // Remove any characters that aren't alphanumeric, underscore, or hyphen (allow both upper and lowercase)
  return value.replace(/[^a-zA-Z0-9_-]/g, '');
};

/**
 * Validates URL-safe identifier and returns error message if invalid
 * @param {string} value - The value to validate
 * @param {string} fieldName - Name of the field for error message
 * @returns {string|null} - Error message or null if valid
 */
export const validateUrlSafeIdentifier = (value, fieldName = 'Field') => {
  if (!value) {
    return `${fieldName} is required`;
  }
  if (!isUrlSafe(value)) {
    return `${fieldName} must contain only letters, numbers, underscores, and hyphens`;
  }
  if (value.length < 1) {
    return `${fieldName} must be at least 1 character long`;
  }
  if (value.length > 36) {
    return `${fieldName} must be less than 36 characters`;
  }
  return null;
};

/**
 * React input handler that enforces URL-safe input
 * @param {Function} setter - State setter function
 * @returns {Function} - Event handler function
 */
export const handleUrlSafeInput = (setter) => (e) => {
  const sanitized = sanitizeUrlSafe(e.target.value);
  setter(sanitized);
};
