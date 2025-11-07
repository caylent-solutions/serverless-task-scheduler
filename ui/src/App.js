import { useState, useEffect } from 'react';
import Layout from './components/layout/Layout';
import ScheduleList from './components/schedules/ScheduleList';
import TargetList from './components/targets/TargetList';
import TenantMappingList from './components/tenants/TenantMappingList';
import TenantList from './components/tenants/TenantList';
import UserManagement from './components/users/UserManagement';
import Login from './components/auth/Login';

function App() {
  const [tenantName, setTenantName] = useState(undefined);
  const [currentView, setCurrentView] = useState('home');
  const [isAdmin, setIsAdmin] = useState(false);
  const [userEmail, setUserEmail] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [availableTenants, setAvailableTenants] = useState([]);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Check authentication and get user tenants
  const checkAuth = async () => {
    setIsLoading(true);
    try {
      // Get user info from the backend - use ../user/info to go up from /app/
      const response = await fetch('../user/info', {
        credentials: 'include'
      });

      if (response.ok) {
        const userInfo = await response.json();
        console.log('===== USER INFO DEBUG =====');
        console.log('Full user info response:', userInfo);
        console.log('User email:', userInfo.email);
        console.log('User username:', userInfo.username);
        console.log('Is admin:', userInfo.isAdmin);
        console.log('Available tenants:', userInfo.tenants);
        console.log('==========================');
        setUserEmail(userInfo.email || userInfo.username || 'User');
        setIsAdmin(userInfo.isAdmin || false);
        setAvailableTenants(userInfo.tenants || []);
        setIsAuthenticated(true);

        // Auto-set tenant if user is admin (member of 'admin' tenant)
        if (userInfo.isAdmin) {
          console.log('Admin user detected, setting tenant to admin'); // Debug log
          setTenantName('admin');
        } else if (userInfo.tenants && userInfo.tenants.length > 0) {
          // Regular users with tenant mappings - use first tenant
          console.log('Auto-selecting tenant:', userInfo.tenants[0]); // Debug log
          setTenantName(userInfo.tenants[0]);
        } else {
          console.log('No tenant set - user can browse without tenant context'); // Debug log
          // Leave tenantName as undefined - user can browse the welcome screen
        }
      } else if (response.status === 401) {
        // Unauthorized - need to log in
        console.log('User not authenticated');
        setIsAuthenticated(false);
      } else {
        console.error('Failed to fetch user info:', response.status);
        // On error, still proceed - don't block the UI
        setIsAuthenticated(false);
      }
    } catch (error) {
      console.error('Error checking authentication:', error);
      // On error, assume not authenticated
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const handleNavigate = (view) => {
    setCurrentView(view);
  };

  const handleTenantChange = (newTenant) => {
    setTenantName(newTenant);
  };

  // Show loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-600 text-lg">Loading...</div>
      </div>
    );
  }

  // Show login page if not authenticated
  if (!isAuthenticated) {
    return <Login onLoginSuccess={checkAuth} />;
  }

  // Render content based on current view
  const renderContent = () => {
    switch (currentView) {
      case 'home':
        return (
          <div className="content-view">
            <div className="welcome-section">
              <h1 className="welcome-title">Welcome to Serverless Task Scheduler</h1>
              {tenantName ? (
                <p className="welcome-subtitle">
                  You are logged into <span className="tenant-badge">{tenantName}</span>
                </p>
              ) : (
                <p className="welcome-subtitle">
                  No tenant context selected
                </p>
              )}
              {userEmail && (
                <p className="user-info">Logged in as: {userEmail}</p>
              )}

              <div className="quick-stats">
                <div className="stat-card">
                  <h3>Getting Started</h3>
                  <div className="instructions">
                    <div className="instruction-step">
                      <div className="step-number">1</div>
                      <div className="step-content">
                        <h4>Define Targets (Admin Only)</h4>
                        <p>Targets are AWS Lambda functions or other execution endpoints. Admins configure the ARN and parameter schema.</p>
                      </div>
                    </div>

                    <div className="instruction-step">
                      <div className="step-number">2</div>
                      <div className="step-content">
                        <h4>Create Tenants (Admin Only)</h4>
                        <p>Tenants represent different organizations or departments. Each tenant has isolated access to their resources.</p>
                      </div>
                    </div>

                    <div className="instruction-step">
                      <div className="step-number">3</div>
                      <div className="step-content">
                        <h4>Create Links</h4>
                        <p>Links connect Tenants to Targets with custom aliases, environment variables, and default payloads.</p>
                      </div>
                    </div>

                    <div className="instruction-step">
                      <div className="step-number">4</div>
                      <div className="step-content">
                        <h4>Schedule or Execute</h4>
                        <p>Once Links are created, you can schedule them to run on a cron/rate expression, or execute them on-demand.</p>
                      </div>
                    </div>
                  </div>
                </div>

                {tenantName && (
                  <div className="stat-card">
                    <h3>Quick Actions</h3>
                    <div className="action-buttons">
                      <button className="btn btn-primary" onClick={() => handleNavigate('schedules')}>
                        📅 View Schedules
                      </button>
                      <button className="btn btn-primary" onClick={() => handleNavigate('tenant-mappings')}>
                        🔗 View Links
                      </button>
                    </div>
                  </div>
                )}

                {!tenantName && (
                  <div className="stat-card">
                    <p className="text-gray-600">Select a tenant from the sidebar to begin</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      case 'targets':
        // Admin-only feature
        if (!isAdmin) {
          return <div className="content-view"><p>Access denied. Admin privileges required.</p></div>;
        }
        return <TargetList isAdmin={isAdmin} />;
      case 'schedules':
        return tenantName ? (
          <ScheduleList tenantName={tenantName} />
        ) : (
          <div className="content-view"><p>Please select a tenant to view schedules</p></div>
        );
      case 'tenant-mappings':
        // For admin users, show all mappings across tenants by using 'admin' as tenant
        // For regular users, show only their tenant's mappings
        return <TenantMappingList tenantName={tenantName || 'admin'} />;
      case 'users':
        // Admin-only feature
        if (!isAdmin) {
          return <div className="content-view"><p>Access denied. Admin privileges required.</p></div>;
        }
        return <UserManagement isAdmin={isAdmin} />;
      case 'tenants':
        // Admin-only feature
        if (!isAdmin) {
          return <div className="content-view"><p>Access denied. Admin privileges required.</p></div>;
        }
        return <TenantList isAdmin={isAdmin} />;
      default:
        return (
          <div className="content-view">
            <div className="welcome-section">
              <h1 className="welcome-title">Welcome to Serverless Task Scheduler</h1>
              {tenantName && (
                <p className="welcome-subtitle">
                  You are logged into <span className="tenant-badge">{tenantName}</span>
                </p>
              )}
            </div>
          </div>
        );
    }
  };

  return (
    <Layout
      currentView={currentView}
      onNavigate={handleNavigate}
      tenantName={tenantName}
      onTenantChange={handleTenantChange}
      isAdmin={isAdmin}
      availableTenants={availableTenants}
      userEmail={userEmail}
    >
      {renderContent()}
    </Layout>
  );
}

export default App;
