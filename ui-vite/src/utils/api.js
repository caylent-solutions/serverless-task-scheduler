import { API_BASE_URL } from '../config';

/**
 * Convert relative URLs to absolute API URLs
 * @param {string} url - The URL (can be relative like '../tenants' or './schedules')
 * @returns {string} - Absolute URL with /api prefix
 */
const toApiUrl = (url) => {
  // If URL already starts with /api, return as-is
  if (url.startsWith('/api')) {
    return url;
  }

  // Remove leading './' or '../' and add /api prefix
  const cleanUrl = url.replace(/^\.\.?\//, '/');
  return `${API_BASE_URL}${cleanUrl}`;
};

/**
 * Wrapper for fetch that handles authentication errors globally
 * If a 401 response is received, redirects to login page
 * Automatically converts relative URLs to use /api prefix
 */
export const authenticatedFetch = async (url, options = {}) => {
  try {
    const apiUrl = toApiUrl(url);
    const response = await fetch(apiUrl, {
      ...options,
      credentials: options.credentials || 'include'
    });

    // If unauthorized, just return the response - let the app handle it
    // Don't redirect here as it causes issues with API Gateway stages
    if (response.status === 401) {
      console.log('Unauthorized request detected');
      // Just return the response - App.js will handle showing the login screen
      return response;
    }

    return response;
  } catch (error) {
    // Network errors or other fetch errors - log and rethrow
    console.error('Network error during fetch:', error);
    throw error;
  }
};

export default authenticatedFetch;
