import React from 'react';

const Sidebar = ({ currentView, onNavigate, tenantName, onTenantChange, isAdmin = false, availableTenants = [], collapsed = false, onToggleCollapse }) => {
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-content">
        {/* Tenant Selector */}
        {!collapsed && (
          <div className="sidebar-section">
            <select 
              className="tenant-selector"
              value={tenantName || ''}
              onChange={(e) => onTenantChange(e.target.value)}
            >
              <option value="">Select Tenant...</option>
              {availableTenants.map(tenant => (
                <option key={tenant} value={tenant}>
                  {tenant}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Navigation Items */}
        <nav className="sidebar-nav">
          <button 
            className={`nav-item ${currentView === 'home' ? 'active' : ''}`}
            onClick={() => onNavigate('home')}
            title="Home"
          >
            <span className="nav-icon">🏠</span>
            {!collapsed && <span className="nav-label">Home</span>}
          </button>

          <button 
            className={`nav-item ${currentView === 'tenant-mappings' ? 'active' : ''}`}
            onClick={() => onNavigate('tenant-mappings')}
            title="Target Links"
          >
            <span className="nav-icon">🔗</span>
            {!collapsed && <span className="nav-label">Target Links</span>}
          </button>

          <button 
            className={`nav-item ${currentView === 'schedules' ? 'active' : ''}`}
            onClick={() => onNavigate('schedules')}
            title="Schedules"
          >
            <span className="nav-icon">🕐</span>
            {!collapsed && <span className="nav-label">Schedules</span>}
          </button>
        </nav>

        {/* Admin Section - Only show when logged into admin tenant */}
        {isAdmin && tenantName === 'admin' && (
          <>
            <div className="sidebar-divider"></div>
            <nav className="sidebar-nav admin-section">
              <button
                className={`nav-item ${currentView === 'targets' ? 'active' : ''}`}
                onClick={() => onNavigate('targets')}
                title="Targets"
              >
                <span className="nav-icon">🎯</span>
                {!collapsed && <span className="nav-label">Target Management</span>}
              </button>

              <button
                className={`nav-item ${currentView === 'users' ? 'active' : ''}`}
                onClick={() => onNavigate('users')}
                title="User Management"
              >
                <span className="nav-icon">👤</span>
                {!collapsed && <span className="nav-label">User Management</span>}
              </button>

              <button
                className={`nav-item ${currentView === 'tenants' ? 'active' : ''}`}
                onClick={() => onNavigate('tenants')}
                title="Tenant Management"
              >
                <span className="nav-icon">📋</span>
                {!collapsed && <span className="nav-label">Tenant Management</span>}
              </button>
            </nav>
          </>
        )}
      </div>
    </aside>
  );
};

export default Sidebar;
