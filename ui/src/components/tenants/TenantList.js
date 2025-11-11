import React, { useState, useEffect } from 'react';
import authenticatedFetch from '../../utils/api';

const TenantList = ({ isAdmin }) => {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');
  const [selectedTenant, setSelectedTenant] = useState(null);

  // Fetch tenants from API
  useEffect(() => {
    const fetchTenants = async () => {
      try {
        setLoading(true);
        const response = await authenticatedFetch('../tenants');

        if (!response.ok) {
          throw new Error(`Failed to fetch tenants: ${response.status}`);
        }

        const data = await response.json();
        setTenants(data.tenants || []);
        setError(null);
      } catch (err) {
        console.error('Error fetching tenants:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (isAdmin) {
      fetchTenants();
    }
  }, [isAdmin]);

  const filteredTenants = tenants.filter(tenant =>
    tenant.tenant_id?.toLowerCase().includes(filter.toLowerCase()) ||
    tenant.tenant_name?.toLowerCase().includes(filter.toLowerCase()) ||
    tenant.description?.toLowerCase().includes(filter.toLowerCase())
  );

  const handleEdit = (tenant) => {
    setSelectedTenant({
      ...tenant
    });
  };

  const handleDelete = async (tenantId) => {
    if (!window.confirm('Are you sure you want to delete this tenant?')) {
      return;
    }

    try {
      const response = await authenticatedFetch(`../tenants/${tenantId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error(`Failed to delete tenant: ${response.status}`);
      }

      setTenants(tenants.filter(t => t.tenant_id !== tenantId));
    } catch (err) {
      console.error('Error deleting tenant:', err);
      alert(`Error deleting tenant: ${err.message}`);
    }
  };

  const handleAdd = () => {
    setSelectedTenant({
      tenant_id: '',
      tenant_name: '',
      description: ''
    });
  };

  const validateTenantId = (tenantId) => {
    // Only allow lowercase alphanumeric and underscores, max 36 characters
    const tenantIdRegex = /^[a-z0-9_]{1,36}$/;
    return tenantIdRegex.test(tenantId);
  };

  const handleSave = async (e) => {
    e.preventDefault();

    try {
      // Validate tenant_id format
      if (!validateTenantId(selectedTenant.tenant_id)) {
        alert('Invalid Tenant ID. Only lowercase letters, numbers, and underscores are allowed (max 36 characters).\nExample: acme_corp');
        return;
      }

      const isNew = !tenants.find(t => t.tenant_id === selectedTenant.tenant_id);

      const url = isNew
        ? '../tenants'
        : `../tenants/${selectedTenant.tenant_id}`;

      const method = isNew ? 'POST' : 'PUT';

      const response = await authenticatedFetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(selectedTenant)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to save tenant: ${response.status}`);
      }

      // Refresh the tenants list
      const refreshResponse = await authenticatedFetch('../tenants');
      const refreshData = await refreshResponse.json();
      setTenants(refreshData.tenants || []);

      setSelectedTenant(null);
    } catch (err) {
      console.error('Error saving tenant:', err);
      alert(`Error saving tenant: ${err.message}`);
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
        <p>Loading tenants...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="content-view">
        <p className="text-red-600">Error loading tenants: {error}</p>
      </div>
    );
  }

  return (
    <div className="content-view">
      <div className="view-header">
        <h2>Tenant Management</h2>
        <div className="view-actions">
          <button className="btn btn-primary" onClick={handleAdd}>
            ➕ Add Tenant
          </button>
          <div className="filter-container">
            <input
              type="text"
              placeholder="Filter tenants..."
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
              <th>Actions</th>
              <th>Tenant ID</th>
              <th>Tenant Name</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {filteredTenants.length === 0 ? (
              <tr>
                <td colSpan="4" className="text-center">No tenants found</td>
              </tr>
            ) : (
              filteredTenants.map(tenant => (
                <tr key={tenant.tenant_id}>
                  <td className="actions-cell">
                    <button
                      className="btn-icon btn-edit"
                      onClick={() => handleEdit(tenant)}
                      title="Edit"
                    >
                      ✏️
                    </button>
                    <button
                      className="btn-icon btn-delete"
                      onClick={() => handleDelete(tenant.tenant_id)}
                      title="Delete"
                    >
                      🗑️
                    </button>
                  </td>
                  <td>{tenant.tenant_id}</td>
                  <td>{tenant.tenant_name}</td>
                  <td>{tenant.description}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedTenant && (
        <div className="modal-overlay" onClick={() => setSelectedTenant(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{tenants.find(t => t.tenant_id === selectedTenant.tenant_id) ? 'Edit Tenant' : 'Add Tenant'}</h3>
            <form onSubmit={handleSave}>
              <div className="form-group">
                <label>Tenant ID</label>
                <input
                  type="text"
                  value={selectedTenant.tenant_id}
                  onChange={(e) => setSelectedTenant({...selectedTenant, tenant_id: e.target.value.toLowerCase()})}
                  disabled={!!tenants.find(t => t.tenant_id === selectedTenant.tenant_id)}
                  placeholder="acme_corp"
                  maxLength={36}
                  pattern="[a-z0-9_]{1,36}"
                  title="Only lowercase letters, numbers, and underscores (max 36 characters)"
                  required
                />
              </div>
              <div className="form-group">
                <label>Tenant Name</label>
                <input
                  type="text"
                  value={selectedTenant.tenant_name}
                  onChange={(e) => setSelectedTenant({...selectedTenant, tenant_name: e.target.value})}
                  required
                />
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea
                  value={selectedTenant.description}
                  onChange={(e) => setSelectedTenant({...selectedTenant, description: e.target.value})}
                  rows={3}
                  required
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedTenant(null)}>
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
    </div>
  );
};

export default TenantList;
