import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import authenticatedFetch from '../../utils/api';

const TargetList = ({ isAdmin }) => {
  const [targets, setTargets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterInput, setFilterInput] = useState('');
  const [filter, setFilter] = useState('');
  const [selectedTarget, setSelectedTarget] = useState(null);

  // Fetch targets from API
  const fetchTargets = async (searchFilter = '') => {
    try {
      setLoading(true);
      // Add filter parameter if provided
      const filterParam = searchFilter.trim() ? `?filter=${encodeURIComponent(searchFilter)}` : '';
      const response = await authenticatedFetch(`../targets${filterParam}`);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch targets: ${response.status}`);
      }
      
      const data = await response.json();
      setTargets(data.targets || []);
      setError(null);
    } catch (err) {
      console.error('Error fetching targets:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Initial fetch on mount
  useEffect(() => {
    if (isAdmin) {
      fetchTargets();
    }
  }, [isAdmin]);

  // Handle Enter key in filter input
  const handleFilterKeyDown = (e) => {
    if (e.key === 'Enter') {
      setFilter(filterInput);
      fetchTargets(filterInput);
    }
  };

  // Filtering is now handled by the API

  const handleEdit = (target) => {
    setSelectedTarget({
      ...target,
      target_parameter_schema: JSON.stringify(target.target_parameter_schema, null, 2)
    });
  };

  const handleDelete = async (targetId) => {
    if (!globalThis.confirm('Are you sure you want to delete this target?')) {
      return;
    }

    try {
      const response = await authenticatedFetch(`../targets/${targetId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error(`Failed to delete target: ${response.status}`);
      }

      setTargets(targets.filter(t => t.target_id !== targetId));
    } catch (err) {
      console.error('Error deleting target:', err);
      // Skip alert for authentication errors (handled by redirect)
      if (!err.message.includes('401')) {
        alert(`Error deleting target: ${err.message}`);
      }
    }
  };

  const handleAdd = () => {
    setSelectedTarget({
      target_id: '',
      target_description: '',
      target_arn: '',
      target_parameter_schema: ''
    });
  };

  const validateArn = (arn) => {
    // AWS ARN format: arn:partition:service:region:account-id:resource
    const arnRegex = /^arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:.+$/;
    return arnRegex.test(arn);
  };

  const validateOpenAPISchema = (schema) => {
    // Check if it has the basic OpenAPI schema structure
    if (!schema || typeof schema !== 'object') {
      return 'Schema must be a valid object';
    }

    if (!schema.schema || typeof schema.schema !== 'object') {
      return 'Schema must contain a "schema" property';
    }

    const innerSchema = schema.schema;

    // Validate it has type property
    if (!innerSchema.type) {
      return 'Schema must have a "type" property';
    }

    // If type is object, should have properties
    if (innerSchema.type === 'object' && !innerSchema.properties) {
      return 'Object schemas should have a "properties" field';
    }

    // Validate properties structure if it exists
    if (innerSchema.properties) {
      if (typeof innerSchema.properties !== 'object') {
        return 'Properties must be an object';
      }

      // Each property should have a type
      for (const [propName, propValue] of Object.entries(innerSchema.properties)) {
        if (!propValue.type) {
          return `Property "${propName}" must have a "type" field`;
        }
      }
    }

    return null; // Valid
  };

  const handleSave = async (e) => {
    e.preventDefault();

    try {
      // Validate ARN format
      if (!validateArn(selectedTarget.target_arn)) {
        alert('Invalid ARN format. Expected format: arn:aws:service:region:account-id:resource\nExample: arn:aws:lambda:us-east-2:123456789012:function:LambdaCalculator');
        return;
      }

      let parameterSchema = selectedTarget.target_parameter_schema;

      // Check if schema is empty or whitespace
      if (!parameterSchema || parameterSchema.trim() === '') {
        alert('Parameter schema is required. Please provide a valid OpenAPI JSON schema.');
        return;
      }

      if (typeof parameterSchema === 'string') {
        try {
          parameterSchema = JSON.parse(parameterSchema);
        } catch (err) {
          console.error('JSON parse error in parameter schema:', err);
          alert('Invalid JSON for parameter schema. Please ensure it is valid JSON format.');
          return;
        }
      }

      // Validate OpenAPI schema structure
      const schemaError = validateOpenAPISchema(parameterSchema);
      if (schemaError) {
        alert(`Invalid OpenAPI Schema: ${schemaError}\n\nExpected format:\n{\n  "schema": {\n    "type": "object",\n    "properties": {...}\n  }\n}`);
        return;
      }

      const targetData = {
        ...selectedTarget,
        target_parameter_schema: parameterSchema
      };

      // Detect if this is a new target or editing existing one
      const isNew = !targets.some(t => t.target_id === selectedTarget.target_id);

      // Use correct endpoint and method
      const url = isNew
        ? '../targets'
        : `../targets/${selectedTarget.target_id}`;

      const method = isNew ? 'POST' : 'PUT';

      const response = await authenticatedFetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(targetData)
      });

      if (!response.ok) {
        let errorData;
        try {
          errorData = await response.json();
        } catch (error_) {
          // Response body is not valid JSON, use status code for error message
          console.warn('Failed to parse error response as JSON:', error_);
          throw new Error(`Failed to save target: ${response.status}`);
        }
        throw new Error(errorData.detail || `Failed to save target: ${response.status}`);
      }

      // Refresh the targets list
      // Preserve filter when refreshing
      await fetchTargets(filter);

      setSelectedTarget(null);
    } catch (err) {
      console.error('Error saving target:', err);
      // Skip alert for authentication errors (handled by redirect)
      if (!err.message.includes('401')) {
        alert(`Error saving target: ${err.message}`);
      }
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
        <p>Loading targets...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="content-view">
        <p className="text-red-600">Error loading targets: {error}</p>
      </div>
    );
  }

  return (
    <div className="content-view">
      <div className="view-header">
        <h2>Target Management</h2>
        <div className="view-actions">
          <button className="btn btn-primary" onClick={handleAdd}>
            ➕ Add Target
          </button>
          <div className="filter-container">
            <input
              type="text"
              placeholder="Filter targets... (Press Enter to search)"
              value={filterInput}
              onChange={(e) => setFilterInput(e.target.value)}
              onKeyDown={handleFilterKeyDown}
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
              <th>Target ID</th>
              <th>Description</th>
              <th>ARN</th>
            </tr>
          </thead>
          <tbody>
            {targets.length === 0 ? (
              <tr>
                <td colSpan="4" className="text-center">No targets found</td>
              </tr>
            ) : (
              targets.map(target => (
                <tr key={target.target_id}>
                  <td className="actions-cell">
                    <button 
                      className="btn-icon btn-edit" 
                      onClick={() => handleEdit(target)}
                      title="Edit"
                    >
                      ✏️
                    </button>
                    <button 
                      className="btn-icon btn-delete" 
                      onClick={() => handleDelete(target.target_id)}
                      title="Delete"
                    >
                      🗑️
                    </button>
                  </td>
                  <td>{target.target_id}</td>
                  <td>{target.target_description}</td>
                  <td className="arn-cell">{target.target_arn}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedTarget && (
        <div className="modal-overlay">
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="target-modal-title"
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setSelectedTarget(null);
              }
            }}
            tabIndex={-1}
          >
            <h3 id="target-modal-title">{targets.some(t => t.target_id === selectedTarget.target_id) ? 'Edit Target' : 'Add Target'}</h3>
            <form onSubmit={handleSave}>
              <div className="form-group">
                <label htmlFor="target-id-input">Target ID</label>
                <input
                  id="target-id-input"
                  type="text"
                  value={selectedTarget.target_id}
                  onChange={(e) => setSelectedTarget({...selectedTarget, target_id: e.target.value})}
                  disabled={targets.some(t => t.target_id === selectedTarget.target_id)}
                  placeholder="LambdaCalculator"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="target-description">Description</label>
                <input
                  id="target-description"
                  type="text"
                  value={selectedTarget.target_description}
                  onChange={(e) => setSelectedTarget({...selectedTarget, target_description: e.target.value})}
                  placeholder="Arithmetic to calculate the result of two numbers"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="target-arn">Target ARN</label>
                <input
                  id="target-arn"
                  type="text"
                  value={selectedTarget.target_arn}
                  onChange={(e) => setSelectedTarget({...selectedTarget, target_arn: e.target.value})}
                  placeholder="arn:aws:lambda:us-east-2:123456789012:function:LambdaCalculator"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="target-parameter-schema">Parameter Schema (OpenAPI JSON Format)</label>
                <textarea
                  id="target-parameter-schema"
                  value={selectedTarget.target_parameter_schema}
                  onChange={(e) => setSelectedTarget({...selectedTarget, target_parameter_schema: e.target.value})}
                  rows={8}
                  placeholder={`{
  "schema": {
    "type": "object",
    "required": ["action", "x", "y"],
    "properties": {
      "action": {
        "type": "string",
        "enum": ["add", "subtract", "multiply", "divide"],
        "description": "The arithmetic operation to perform"
      },
      "x": {
        "type": "string",
        "description": "First operand"
      },
      "y": {
        "type": "string",
        "description": "Second operand"
      }
    }
  }
}`}
                  required
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedTarget(null)}>
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

TargetList.propTypes = {
  isAdmin: PropTypes.bool.isRequired
};

export default TargetList;
