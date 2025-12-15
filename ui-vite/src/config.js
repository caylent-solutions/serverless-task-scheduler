/**
 * Application configuration
 */

// API base URL - all backend API calls should use this prefix
// Use relative path that works in all environments (dev, staging, prod)
// The React app is served from the same API Gateway that hosts the API,
// so we can construct the path dynamically based on the current location
const getApiBaseUrl = () => {
  // Extract the stage from the current pathname
  // URL format: https://{api-gateway-id}.execute-api.{region}.amazonaws.com/{stage}/
  const pathname = globalThis.location.pathname;
  const pathParts = pathname.split('/').filter(Boolean);

  // If we have a stage prefix (first part of path), use it
  // Otherwise default to 'api' for local development
  if (pathParts.length > 0) {
    const stage = pathParts[0];
    return `/${stage}/api`;
  }

  return '/api';
};

export const API_BASE_URL = getApiBaseUrl();

const config = {
  API_BASE_URL
};

export default config;
