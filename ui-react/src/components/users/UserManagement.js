import React, { useState, useEffect } from 'react';
import authenticatedFetch from '../../utils/api';

const UserManagement = ({ isAdmin }) => {
  const [users, setUsers] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');
  const [selectedUser, setSelectedUser] = useState(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteTenants, setInviteTenants] = useState([]);
  const [inviteLoading, setInviteLoading] = useState(false);
  const [syncLoading, setSyncLoading] = useState(false);

  // Fetch users and tenants from API
  useEffect(() => {
    const fetchData = async () => {
      if (!isAdmin) return;

      try {
        setLoading(true);

        // Fetch users
        const usersResponse = await authenticatedFetch('../user/management');
        if (!usersResponse.ok) {
          throw new Error(`Failed to fetch users: ${usersResponse.status}`);
        }
        const usersData = await usersResponse.json();
        setUsers(usersData.users || []);

        // Fetch tenants for the dropdown
        const tenantsResponse = await authenticatedFetch('../tenants');
        if (!tenantsResponse.ok) {
          throw new Error(`Failed to fetch tenants: ${tenantsResponse.status}`);
        }
        const tenantsData = await tenantsResponse.json();
        setTenants(tenantsData.tenants || []);

        setError(null);
      } catch (err) {
        console.error('Error fetching data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [isAdmin]);

  const filteredUsers = users.filter(user =>
    user.user_id?.toLowerCase().includes(filter.toLowerCase()) ||
    user.email?.toLowerCase().includes(filter.toLowerCase()) ||
    user.full_name?.toLowerCase().includes(filter.toLowerCase()) ||
    user.tenants?.some(t => t.toLowerCase().includes(filter.toLowerCase()))
  );

  const handleEdit = (user) => {
    setSelectedUser({
      user_id: user.user_id,
      email: user.email,
      tenants: [...user.tenants],
      user_status: user.user_status,
      in_cognito: user.in_cognito,
      in_database: user.in_database
    });
  };

  const handleDelete = async (user) => {
    const deleteFromCognito = user.in_cognito;
    const deleteFromDatabase = user.in_database;

    let confirmMessage = `Are you sure you want to delete user ${user.email}?\n\n`;
    if (deleteFromCognito && deleteFromDatabase) {
      confirmMessage += 'This will:\n- Remove the user from Cognito (they will not be able to log in)\n- Remove all tenant associations from the database';
    } else if (deleteFromCognito) {
      confirmMessage += 'This will remove the user from Cognito (they will not be able to log in)';
    } else if (deleteFromDatabase) {
      confirmMessage += 'This will remove all tenant associations from the database';
    }

    if (!window.confirm(confirmMessage)) {
      return;
    }

    try {
      const response = await authenticatedFetch(`../user/management/${encodeURIComponent(user.user_id)}?delete_from_cognito=${deleteFromCognito}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to delete user: ${response.status}`);
      }

      // Refresh the users list
      const refreshResponse = await authenticatedFetch('../user/management');
      const refreshData = await refreshResponse.json();
      setUsers(refreshData.users || []);
    } catch (err) {
      console.error('Error deleting user:', err);
      alert(`Error deleting user: ${err.message}`);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();

    try {
      const response = await authenticatedFetch(`../user/management/${encodeURIComponent(selectedUser.user_id)}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(selectedUser.tenants)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to update user: ${response.status}`);
      }

      // Refresh the users list
      const refreshResponse = await authenticatedFetch('../user/management');
      const refreshData = await refreshResponse.json();
      setUsers(refreshData.users || []);

      setSelectedUser(null);
    } catch (err) {
      console.error('Error saving user:', err);
      alert(`Error saving user: ${err.message}`);
    }
  };

  const handleTenantToggle = (tenantId) => {
    setSelectedUser(prev => {
      const tenants = [...prev.tenants];
      const index = tenants.indexOf(tenantId);

      if (index === -1) {
        tenants.push(tenantId);
      } else {
        tenants.splice(index, 1);
      }

      return { ...prev, tenants };
    });
  };

  const handleInviteTenantToggle = (tenantId) => {
    setInviteTenants(prev => {
      const tenants = [...prev];
      const index = tenants.indexOf(tenantId);

      if (index === -1) {
        tenants.push(tenantId);
      } else {
        tenants.splice(index, 1);
      }

      return tenants;
    });
  };

  const handleInviteUser = async (e) => {
    e.preventDefault();
    setInviteLoading(true);

    try {
      const response = await authenticatedFetch('../user/management/invite', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          email: inviteEmail,
          tenants: inviteTenants
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to invite user: ${response.status}`);
      }

      await response.json();

      // Refresh the users list
      const refreshResponse = await authenticatedFetch('../user/management');
      const refreshData = await refreshResponse.json();
      setUsers(refreshData.users || []);

      // Close modal and reset form
      setShowInviteModal(false);
      setInviteEmail('');
      setInviteTenants([]);

    } catch (err) {
      console.error('Error inviting user:', err);
      alert(`Error inviting user: ${err.message}`);
    } finally {
      setInviteLoading(false);
    }
  };

  const handleSyncIdP = async () => {
    if (!window.confirm('This will remove any user-tenant mappings for users that no longer exist in Cognito.\n\nAre you sure you want to sync?')) {
      return;
    }

    setSyncLoading(true);

    try {
      const response = await authenticatedFetch('../user/management/sync', {
        method: 'POST'
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to sync: ${response.status}`);
      }

      await response.json();

      // Refresh the users list
      const refreshResponse = await authenticatedFetch('../user/management');
      const refreshData = await refreshResponse.json();
      setUsers(refreshData.users || []);
    } catch (err) {
      console.error('Error syncing IdP:', err);
      alert(`Error syncing IdP: ${err.message}`);
    } finally {
      setSyncLoading(false);
    }
  };

  if (!isAdmin) {
    return (
      <div className="content-view">
        <p>Access denied. Admin privileges required.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="content-view">
        <p>Loading users...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="content-view">
        <p className="text-red-600">Error loading users: {error}</p>
      </div>
    );
  }

  return (
    <div className="content-view">
      <div className="view-header">
        <h2>User Management</h2>
        <div className="view-actions">
          <button className="btn btn-primary" onClick={() => setShowInviteModal(true)}>
            ➕ Invite User
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleSyncIdP}
            disabled={syncLoading}
            title="Remove orphaned user mappings for users that no longer exist in Cognito"
          >
            {syncLoading ? '🔄 Syncing...' : '🔄 Sync IdP'}
          </button>
          <div className="filter-container">
            <input
              type="text"
              placeholder="Filter users..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="filter-input"
            />
            <span className="filter-icon">🔍</span>
          </div>
        </div>
      </div>

      <div className="data-table">
        <table>
          <thead>
            <tr>
              <th style={{width: '100px'}}>Actions</th>
              <th style={{width: '250px'}}>User ID (Email)</th>
              <th>Allowed Tenants</th>
              <th style={{width: '120px'}}>Status</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.length === 0 ? (
              <tr>
                <td colSpan="4" className="text-center">No users found</td>
              </tr>
            ) : (
              filteredUsers.map(user => (
                <tr key={user.user_id} className={!user.in_database ? 'opacity-60' : ''}>
                  <td className="actions-cell">
                    <button
                      className="btn-icon btn-edit"
                      onClick={() => handleEdit(user)}
                      title="Edit"
                    >
                      ✏️
                    </button>
                    <button
                      className="btn-icon btn-delete"
                      onClick={() => handleDelete(user)}
                      title="Delete"
                    >
                      🗑️
                    </button>
                  </td>
                  <td>
                    {user.email}
                    {!user.in_database && <span className="text-gray-400 text-xs ml-2">(Cognito only)</span>}
                  </td>
                  <td>
                    {user.tenants && user.tenants.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {user.tenants.map(tenant => (
                          <span key={tenant} className="inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                            {tenant}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-400">No tenants assigned</span>
                    )}
                  </td>
                  <td>
                    {user.in_cognito ? (
                      <span className={`text-xs px-2 py-1 rounded ${
                        user.user_status === 'CONFIRMED' ? 'bg-green-100 text-green-800' :
                        user.user_status === 'FORCE_CHANGE_PASSWORD' ? 'bg-yellow-100 text-yellow-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {user.user_status || 'ACTIVE'}
                      </span>
                    ) : (
                      <span className="text-gray-400 text-xs">Not in Cognito</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedUser && (
        <div className="modal-overlay" onClick={() => setSelectedUser(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{maxWidth: '800px', width: '90%'}}>
            <h3>Edit User Access</h3>
            <form onSubmit={handleSave}>
              <div className="form-group">
                <label>User Email</label>
                <input
                  type="text"
                  value={selectedUser.email}
                  disabled
                  className="bg-gray-100"
                />
              </div>

              <div className="form-group">
                <label>Tenant Access</label>
                <div style={{maxHeight: '400px', overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: '4px'}}>
                  {tenants.length === 0 ? (
                    <p className="text-gray-500 text-sm p-2">No tenants available</p>
                  ) : (
                    <table style={{width: '100%', fontSize: '12px'}}>
                      <thead style={{position: 'sticky', top: 0, backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb'}}>
                        <tr>
                          <th style={{padding: '8px', textAlign: 'left', width: '60px'}}>Enabled</th>
                          <th style={{padding: '8px', textAlign: 'left', width: '200px'}}>Tenant ID</th>
                          <th style={{padding: '8px', textAlign: 'left'}}>Tenant Name</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tenants.map(tenant => (
                          <tr
                            key={tenant.tenant_id}
                            onClick={() => handleTenantToggle(tenant.tenant_id)}
                            style={{
                              cursor: 'pointer',
                              height: '20px',
                              backgroundColor: selectedUser.tenants.includes(tenant.tenant_id) ? '#eff6ff' : 'transparent'
                            }}
                            onMouseEnter={(e) => {
                              if (!selectedUser.tenants.includes(tenant.tenant_id)) {
                                e.currentTarget.style.backgroundColor = '#f9fafb';
                              }
                            }}
                            onMouseLeave={(e) => {
                              if (!selectedUser.tenants.includes(tenant.tenant_id)) {
                                e.currentTarget.style.backgroundColor = 'transparent';
                              }
                            }}
                          >
                            <td style={{padding: '2px 8px'}}>
                              <input
                                type="checkbox"
                                checked={selectedUser.tenants.includes(tenant.tenant_id)}
                                onChange={() => handleTenantToggle(tenant.tenant_id)}
                                onClick={(e) => e.stopPropagation()}
                                style={{width: '14px', height: '14px', cursor: 'pointer'}}
                              />
                            </td>
                            <td style={{padding: '2px 8px'}}>{tenant.tenant_id}</td>
                            <td style={{padding: '2px 8px'}}>{tenant.tenant_name}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  {selectedUser.tenants.length} tenant(s) selected
                </p>
              </div>

              {!selectedUser.in_cognito && (
                <div className="bg-yellow-50 border border-yellow-200 rounded p-3 mb-4">
                  <p className="text-sm text-yellow-800">
                    ⚠️ This user exists in the database but not in Cognito. They will not be able to log in.
                  </p>
                </div>
              )}

              {selectedUser.in_cognito && !selectedUser.in_database && (
                <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-4">
                  <p className="text-sm text-blue-800">
                    ℹ️ This user exists in Cognito but has no tenant assignments yet. Assign at least one tenant to grant them access.
                  </p>
                </div>
              )}

              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedUser(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Invite User Modal */}
      {showInviteModal && (
        <div className="modal-overlay" onClick={() => setShowInviteModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{maxWidth: '800px', width: '90%'}}>
            <h3>Invite New User</h3>
            <form onSubmit={handleInviteUser}>
              <div className="form-group">
                <label>Email Address *</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="user@example.com"
                  required
                />
              </div>

              <div className="form-group">
                <label>Tenant Access</label>
                <div style={{maxHeight: '400px', overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: '4px'}}>
                  {tenants.length === 0 ? (
                    <p className="text-gray-500 text-sm p-2">No tenants available</p>
                  ) : (
                    <table style={{width: '100%', fontSize: '12px'}}>
                      <thead style={{position: 'sticky', top: 0, backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb'}}>
                        <tr>
                          <th style={{padding: '8px', textAlign: 'left', width: '60px'}}>Enabled</th>
                          <th style={{padding: '8px', textAlign: 'left', width: '200px'}}>Tenant ID</th>
                          <th style={{padding: '8px', textAlign: 'left'}}>Tenant Name</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tenants.map(tenant => (
                          <tr
                            key={tenant.tenant_id}
                            onClick={() => handleInviteTenantToggle(tenant.tenant_id)}
                            style={{
                              cursor: 'pointer',
                              height: '20px',
                              backgroundColor: inviteTenants.includes(tenant.tenant_id) ? '#eff6ff' : 'transparent'
                            }}
                            onMouseEnter={(e) => {
                              if (!inviteTenants.includes(tenant.tenant_id)) {
                                e.currentTarget.style.backgroundColor = '#f9fafb';
                              }
                            }}
                            onMouseLeave={(e) => {
                              if (!inviteTenants.includes(tenant.tenant_id)) {
                                e.currentTarget.style.backgroundColor = 'transparent';
                              }
                            }}
                          >
                            <td style={{padding: '2px 8px'}}>
                              <input
                                type="checkbox"
                                checked={inviteTenants.includes(tenant.tenant_id)}
                                onChange={() => handleInviteTenantToggle(tenant.tenant_id)}
                                onClick={(e) => e.stopPropagation()}
                                style={{width: '14px', height: '14px', cursor: 'pointer'}}
                              />
                            </td>
                            <td style={{padding: '2px 8px'}}>{tenant.tenant_id}</td>
                            <td style={{padding: '2px 8px'}}>{tenant.tenant_name}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  {inviteTenants.length} tenant(s) selected
                </p>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-4">
                <p className="text-sm text-blue-800">
                  ℹ️ After creating the user, they should:
                  <br />1. Visit the login page
                  <br />2. Click "Forgot Password"
                  <br />3. Enter their email to receive a password reset code
                  <br />4. Use the code to set their new password
                </p>
              </div>

              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setShowInviteModal(false);
                    setInviteEmail('');
                    setInviteTenants([]);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={inviteLoading}
                >
                  {inviteLoading ? 'Inviting...' : 'Invite User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserManagement;
