/**
 * Wrapper for fetch that handles authentication errors globally
 * If a 401 response is received, redirects to login page
 */
export const authenticatedFetch = async (url, options = {}) => {
  try {
    const response = await fetch(url, {
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
    // Network errors or other fetch errors
    throw error;
  }
};

export default authenticatedFetch;
