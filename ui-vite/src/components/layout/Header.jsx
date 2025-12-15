import React from 'react';
import PropTypes from 'prop-types';
import authenticatedFetch from '../../utils/api';

const Header = ({ userEmail }) => {
  const handleLogout = async () => {
    try {
      // Call the auth logout endpoint
      const response = await authenticatedFetch('../auth/logout', {
        method: 'POST'
      });
      
      if (response.ok) {
        // Reload the page to show login screen
        globalThis.location.reload();
      }
    } catch (error) {
      console.error('Logout failed:', error);
      // Reload anyway to clear state
      globalThis.location.reload();
    }
  };

  return (
    <header className="header">
      <div className="header-content">
        <h1 className="header-title">Serverless Task Scheduler</h1>
        {userEmail && (
          <div className="header-user">
            <span className="user-email">{userEmail}</span>
            <button 
              onClick={handleLogout}
              className="logout-button"
              title="Logout"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 3a1 1 0 00-1 1v12a1 1 0 102 0V4a1 1 0 00-1-1zm10.293 9.293a1 1 0 001.414 1.414l3-3a1 1 0 000-1.414l-3-3a1 1 0 10-1.414 1.414L14.586 9H7a1 1 0 100 2h7.586l-1.293 1.293z" clipRule="evenodd" />
              </svg>
              Logout
            </button>
          </div>
        )}
      </div>
    </header>
  );
};

Header.propTypes = {
  userEmail: PropTypes.string
};

export default Header;
