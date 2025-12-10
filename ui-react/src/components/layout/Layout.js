import React, { useState } from 'react';
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

export default Layout;
