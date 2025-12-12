import React, { useState, useEffect } from 'react';
import authenticatedFetch from '../../utils/api';
import ExecutionHistoryModal from '../common/ExecutionHistoryModal';
import { validateUrlSafeIdentifier, handleUrlSafeInput } from '../../utils/validation';

const TenantMappingList = ({ tenantName = 'admin' }) => {
  const [mappings, setMappings] = useState([]);
  const [targets, setTargets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');
  const [selectedMapping, setSelectedMapping] = useState(null);
  const [executionHistoryMapping, setExecutionHistoryMapping] = useState(null);

  // Fetch targets and mappings from API
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

  const handleSave = async (e) => {
    e.preventDefault();

    try {
      // Validate target_alias
      const validationError = validateUrlSafeIdentifier(selectedMapping.target_alias, 'Target Alias');
      if (validationError) {
        alert(validationError + '\nExample: calc-lambda');
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
              <th>History</th>
            </tr>
          </thead>
          <tbody>
            {filteredMappings.length === 0 ? (
              <tr>
                <td colSpan="6" className="text-center">No links found</td>
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
                  <td className="actions-cell">
                    <button
                      className="btn-icon btn-history"
                      onClick={() => setExecutionHistoryMapping(mapping)}
                      title="View Execution History"
                    >
                      📊
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedMapping && (
        <div
          className="modal-overlay"
          onClick={() => setSelectedMapping(null)}
          onKeyDown={(e) => e.key === 'Escape' && setSelectedMapping(null)}
          role="button"
          tabIndex={0}
          aria-label="Close modal"
        >
          <div className="modal" style={{ maxWidth: '900px' }} onClick={(e) => e.stopPropagation()}>
            <h3>{mappings.find(m => m.tenant_id === selectedMapping.tenant_id && m.target_alias === selectedMapping.target_alias) ? 'Edit Link' : 'Add Link'}</h3>
            <form onSubmit={handleSave}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                {/* Left Column - Basic Fields */}
                <div>
                  <div className="form-group">
                    <label>Target Alias</label>
                    <input
                      type="text"
                      value={selectedMapping.target_alias}
                      onChange={handleUrlSafeInput((value) => setSelectedMapping({...selectedMapping, target_alias: value}))}
                      disabled={!!mappings.find(m => m.tenant_id === selectedMapping.tenant_id && m.target_alias === selectedMapping.target_alias)}
                      placeholder="CalcLambda"
                      maxLength={36}
                      pattern="[a-zA-Z0-9_-]{1,36}"
                      title="Only letters, numbers, underscores, and hyphens (max 36 characters)"
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
                </div>

                {/* Right Column - JSON Fields */}
                <div>
                  <div className="form-group">
                    <label>Default Payload (JSON)</label>
                    <textarea
                      value={selectedMapping.default_payload}
                      onChange={(e) => setSelectedMapping({...selectedMapping, default_payload: e.target.value})}
                      rows={10}
                      placeholder={`{
  "action": "add",
  "x": "5",
  "y": "3"
}`}
                    />
                  </div>
                  <div className="form-group">
                    <label>Environment Variables - ECS Only (JSON)</label>
                    <textarea
                      value={selectedMapping.environment_variables}
                      onChange={(e) => setSelectedMapping({...selectedMapping, environment_variables: e.target.value})}
                      rows={10}
                      placeholder={`{
  "LOG_LEVEL": "INFO",
  "TIMEOUT": "30"
}`}
                    />
                    <small style={{ color: 'var(--color-text-light)', fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                      Note: Environment variables are only supported for ECS targets. Step Functions and Lambda targets do not support runtime environment injection.
                    </small>
                  </div>
                </div>
              </div>

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

      {executionHistoryMapping && (
        <ExecutionHistoryModal
          tenantName={executionHistoryMapping.tenant_id}
          filterType="alias"
          filterValue={executionHistoryMapping.target_alias}
          title={`${executionHistoryMapping.target_alias} (${executionHistoryMapping.target_id})`}
          onClose={() => setExecutionHistoryMapping(null)}
        />
      )}
    </div>
  );
};

export default TenantMappingList;
