import React, { useState } from 'react';
import PropTypes from 'prop-types';
import Header from './Header';
import Sidebar from './Sidebar';

const Layout = ({ children, currentView, onNavigate, tenantName, onTenantChange, isAdmin = false, availableTenants = [], userEmail = '' }) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="layout">
      <Header userEmail={userEmail} />
      <div className="layout-body">
        <Sidebar
          currentView={currentView}
          onNavigate={onNavigate}
          tenantName={tenantName}
          onTenantChange={onTenantChange}
          isAdmin={isAdmin}
          availableTenants={availableTenants}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        />
        <main className={`main-content ${sidebarCollapsed ? 'expanded' : ''}`}>
          {children}
        </main>
      </div>
    </div>
  );
};

Layout.propTypes = {
  children: PropTypes.node.isRequired,
  currentView: PropTypes.string.isRequired,
  onNavigate: PropTypes.func.isRequired,
  tenantName: PropTypes.string,
  onTenantChange: PropTypes.func.isRequired,
  isAdmin: PropTypes.bool,
  availableTenants: PropTypes.arrayOf(PropTypes.string),
  userEmail: PropTypes.string
};

export default Layout;
