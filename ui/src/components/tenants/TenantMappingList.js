import React, { useState, useEffect } from 'react';
import authenticatedFetch from '../../utils/api';

const TenantMappingList = ({ tenantName = 'admin' }) => {
  const [mappings, setMappings] = useState([]);
  const [targets, setTargets] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');
  const [selectedMapping, setSelectedMapping] = useState(null);

  // Fetch targets, tenants, and mappings from API
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);

        // Fetch targets for dropdown
        const targetsResponse = await authenticatedFetch('../targets');
        if (targetsResponse.ok) {
          const targetsData = await targetsResponse.json();
          setTargets(targetsData.targets || []);
        }

        // Fetch tenants for dropdown
        const tenantsResponse = await authenticatedFetch('../tenants');
        if (tenantsResponse.ok) {
          const tenantsData = await tenantsResponse.json();
          setTenants(tenantsData.tenants || []);
        }

        // Fetch mappings for admin tenant
        const mappingsResponse = await authenticatedFetch(`../tenants/${tenantName}/mappings`);

        if (!mappingsResponse.ok) {
          throw new Error(`Failed to fetch mappings: ${mappingsResponse.status}`);
        }

        const mappingsData = await mappingsResponse.json();
        setMappings(mappingsData || []);
        setError(null);
      } catch (err) {
        console.error('Error fetching data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [tenantName]);

  const filteredMappings = mappings.filter(mapping => 
    mapping.tenant_id?.toLowerCase().includes(filter.toLowerCase()) ||
    mapping.target_alias?.toLowerCase().includes(filter.toLowerCase()) ||
    mapping.target_id?.toLowerCase().includes(filter.toLowerCase()) ||
    mapping.description?.toLowerCase().includes(filter.toLowerCase())
  );

  const handleEdit = (mapping) => {
    setSelectedMapping({
      ...mapping,
      environment_variables: JSON.stringify(mapping.environment_variables || {}, null, 2),
      default_payload: JSON.stringify(mapping.default_payload || {}, null, 2)
    });
  };

  const handleDelete = async (tenantId, targetAlias) => {
    if (!window.confirm(`Are you sure you want to delete mapping ${targetAlias} for tenant ${tenantId}?`)) {
      return;
    }

    try {
      const response = await authenticatedFetch(`../tenants/${tenantId}/mappings/${targetAlias}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error(`Failed to delete mapping: ${response.status}`);
      }

      setMappings(mappings.filter(m => !(m.tenant_id === tenantId && m.target_alias === targetAlias)));
    } catch (err) {
      console.error('Error deleting mapping:', err);
      alert(`Error deleting mapping: ${err.message}`);
    }
  };

  const handleAdd = () => {
    setSelectedMapping({
      tenant_id: tenantName,
      target_alias: '',
      target_id: '',
      description: '',
      environment_variables: '',
      default_payload: '',
      authorized_groups: []
    });
  };

  const validateTargetAlias = (alias) => {
    // Only allow lowercase alphanumeric and underscores, max 12 characters
    const aliasRegex = /^[a-z0-9_]{1,12}$/;
    return aliasRegex.test(alias);
  };

  const handleSave = async (e) => {
    e.preventDefault();

    try {
      // Validate target_alias
      if (!validateTargetAlias(selectedMapping.target_alias)) {
        alert('Invalid Target Alias. Only lowercase letters, numbers, and underscores are allowed (max 12 characters).\nExample: calc_lambda');
        return;
      }
      const isNew = !mappings.find(m => 
        m.tenant_id === selectedMapping.tenant_id && 
        m.target_alias === selectedMapping.target_alias
      );

      // Parse JSON fields
      let environmentVariables = selectedMapping.environment_variables;
      let defaultPayload = selectedMapping.default_payload;

      // Handle environment variables
      if (typeof environmentVariables === 'string') {
        if (environmentVariables.trim() === '') {
          environmentVariables = {};
        } else {
          try {
            environmentVariables = JSON.parse(environmentVariables);
          } catch (err) {
            alert('Invalid JSON for environment variables. Please ensure it is valid JSON format.');
            return;
          }
        }
      }

      // Handle default payload
      if (typeof defaultPayload === 'string') {
        if (defaultPayload.trim() === '') {
          defaultPayload = {};
        } else {
          try {
            defaultPayload = JSON.parse(defaultPayload);
          } catch (err) {
            alert('Invalid JSON for default payload. Please ensure it is valid JSON format.');
            return;
          }
        }
      }

      const mappingData = {
        ...selectedMapping,
        environment_variables: environmentVariables,
        default_payload: defaultPayload,
        authorized_groups: selectedMapping.authorized_groups || []
      };

      const url = isNew 
        ? `../tenants/${selectedMapping.tenant_id}/mappings`
        : `../tenants/${selectedMapping.tenant_id}/mappings/${selectedMapping.target_alias}`;
      
      const method = isNew ? 'POST' : 'PUT';

      const response = await authenticatedFetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(mappingData)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to save mapping: ${response.status}`);
      }

      // Refresh the mappings list
      const refreshResponse = await authenticatedFetch(`../tenants/${tenantName}/mappings`);
      const refreshData = await refreshResponse.json();
      setMappings(refreshData || []);
      
      setSelectedMapping(null);
    } catch (err) {
      console.error('Error saving mapping:', err);
      alert(`Error saving mapping: ${err.message}`);
    }
  };

  if (loading) {
    return (
      <div className="content-view">
        <p>Loading tenant mappings...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="content-view">
        <p className="text-red-600">Error loading mappings: {error}</p>
      </div>
    );
  }

  return (
    <div className="content-view">
      <div className="view-header">
        <h2>Target Links</h2>
        <div className="view-actions">
          <button className="btn btn-primary" onClick={handleAdd}>
            ➕ Add Link
          </button>
          <div className="filter-container">
            <input
              type="text"
              placeholder="Filter links..."
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
              <th>Target Alias</th>
              <th>Target ID</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {filteredMappings.length === 0 ? (
              <tr>
                <td colSpan="5" className="text-center">No links found</td>
              </tr>
            ) : (
              filteredMappings.map((mapping) => (
                <tr key={`${mapping.tenant_id}-${mapping.target_alias}`}>
                  <td className="actions-cell">
                    <button 
                      className="btn-icon btn-edit" 
                      onClick={() => handleEdit(mapping)}
                      title="Edit"
                    >
                      ✏️
                    </button>
                    <button 
                      className="btn-icon btn-delete" 
                      onClick={() => handleDelete(mapping.tenant_id, mapping.target_alias)}
                      title="Delete"
                    >
                      🗑️
                    </button>
                  </td>
                  <td>{mapping.tenant_id}</td>
                  <td>{mapping.target_alias}</td>
                  <td>{mapping.target_id}</td>
                  <td>{mapping.description}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedMapping && (
        <div className="modal-overlay" onClick={() => setSelectedMapping(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{mappings.find(m => m.tenant_id === selectedMapping.tenant_id && m.target_alias === selectedMapping.target_alias) ? 'Edit Link' : 'Add Link'}</h3>
            <form onSubmit={handleSave}>
              <div className="form-group">
                <label>Tenant ID</label>
                <input
                  type="text"
                  value={selectedMapping.tenant_id}
                  readOnly
                  disabled
                  className="bg-gray-100"
                />
              </div>
              <div className="form-group">
                <label>Target Alias</label>
                <input
                  type="text"
                  value={selectedMapping.target_alias}
                  onChange={(e) => setSelectedMapping({...selectedMapping, target_alias: e.target.value.toLowerCase()})}
                  disabled={!!mappings.find(m => m.tenant_id === selectedMapping.tenant_id && m.target_alias === selectedMapping.target_alias)}
                  placeholder="calc_lambda"
                  maxLength={12}
                  pattern="[a-z0-9_]{1,12}"
                  title="Only lowercase letters, numbers, and underscores (max 12 characters)"
                  required
                />
              </div>
              <div className="form-group">
                <label>Target</label>
                <select
                  value={selectedMapping.target_id}
                  onChange={(e) => setSelectedMapping({...selectedMapping, target_id: e.target.value})}
                  required
                >
                  <option value="">Select a target...</option>
                  {targets.map(target => (
                    <option key={target.target_id} value={target.target_id}>
                      {target.target_id} - {target.target_description}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Description</label>
                <input 
                  type="text" 
                  value={selectedMapping.description}
                  onChange={(e) => setSelectedMapping({...selectedMapping, description: e.target.value})}
                  required
                />
              </div>
              <div className="form-group">
                <label>Environment Variables - ECS Only (JSON)</label>
                <textarea
                  value={selectedMapping.environment_variables}
                  onChange={(e) => setSelectedMapping({...selectedMapping, environment_variables: e.target.value})}
                  rows={4}
                  placeholder={`{
  "LOG_LEVEL": "INFO",
  "TIMEOUT": "30"
}`}
                />
                <small style={{ color: 'var(--color-text-light)', fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                  Note: Environment variables are only supported for ECS targets. Step Functions and Lambda targets do not support runtime environment injection.
                </small>
              </div>
              <div className="form-group">
                <label>Default Payload (JSON)</label>
                <textarea
                  value={selectedMapping.default_payload}
                  onChange={(e) => setSelectedMapping({...selectedMapping, default_payload: e.target.value})}
                  rows={6}
                  placeholder={`{
  "action": "add",
  "x": "5",
  "y": "3"
}`}
                />
              </div>
              {selectedMapping.last_update_user && (
                <>
                  <div className="form-group">
                    <label>Last Updated By</label>
                    <input 
                      type="text" 
                      value={selectedMapping.last_update_user}
                      readOnly
                      disabled
                    />
                  </div>
                  <div className="form-group">
                    <label>Last Updated</label>
                    <input 
                      type="text" 
                      value={selectedMapping.last_update_date ? new Date(selectedMapping.last_update_date).toLocaleString() : '-'}
                      readOnly
                      disabled
                    />
                  </div>
                </>
              )}
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedMapping(null)}>
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

export default TenantMappingList;
