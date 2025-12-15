import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import authenticatedFetch from '../../utils/api';
import ExecutionHistoryModal from '../common/ExecutionHistoryModal';

const ScheduleList = ({ tenantName = 'admin' }) => {
  const [schedules, setSchedules] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');
  const [selectedSchedule, setSelectedSchedule] = useState(null);
  const [executionHistorySchedule, setExecutionHistorySchedule] = useState(null);

  // Fetch schedules and mappings from API
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);

        // Fetch mappings for target alias dropdown
        const mappingsResponse = await authenticatedFetch(`../tenants/${tenantName}/mappings`);
        if (mappingsResponse.ok) {
          const mappingsData = await mappingsResponse.json();
          setMappings(mappingsData || []);
        }

        // Fetch schedules for the tenant
        const schedulesResponse = await authenticatedFetch(`../tenants/${tenantName}/schedules`);

        if (!schedulesResponse.ok) {
          throw new Error(`Failed to fetch schedules: ${schedulesResponse.status}`);
        }

        const schedulesData = await schedulesResponse.json();
        setSchedules(Array.isArray(schedulesData) ? schedulesData : [schedulesData]);
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

  const filteredSchedules = schedules.filter(schedule =>
    schedule.schedule_id?.toLowerCase().includes(filter.toLowerCase()) ||
    schedule.target_alias?.toLowerCase().includes(filter.toLowerCase()) ||
    schedule.schedule_expression?.toLowerCase().includes(filter.toLowerCase()) ||
    schedule.description?.toLowerCase().includes(filter.toLowerCase())
  );

  const handleEdit = (schedule) => {
    setSelectedSchedule({
      ...schedule
    });
  };

  const handleDelete = async (targetAlias, scheduleId) => {
    if (!globalThis.confirm(`Are you sure you want to delete schedule ${scheduleId}?`)) {
      return;
    }

    try {
      const response = await authenticatedFetch(`../tenants/${tenantName}/mappings/${targetAlias}/schedules/${scheduleId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error(`Failed to delete schedule: ${response.status}`);
      }

      setSchedules(schedules.filter(s => s.schedule_id !== scheduleId));
    } catch (err) {
      console.error('Error deleting schedule:', err);
      alert(`Error deleting schedule: ${err.message}`);
    }
  };

  const handleAdd = () => {
    setSelectedSchedule({
      tenant_id: tenantName,
      schedule_id: '',
      target_alias: '',
      schedule_expression: '',
      description: '',
      state: 'ENABLED'
    });
  };

  const validateScheduleExpression = (expression) => {
    // Check if expression starts with rate(, cron(, or at(
    return expression.trim().match(/^(rate|cron|at)\(.+\)$/);
  };

  const handleSave = async (e) => {
    e.preventDefault();

    try {
      // Validate schedule expression
      if (!validateScheduleExpression(selectedSchedule.schedule_expression)) {
        alert('Invalid Schedule Expression. Must start with rate(, cron(, or at( and end with ).\nExamples:\n- rate(5 minutes)\n- cron(0 10 * * ? *)\n- at(2024-12-31T23:59:59)');
        return;
      }

      const isNew = !schedules.some(s => s.schedule_id === selectedSchedule.schedule_id);

      // Prepare schedule data
      const scheduleData = {
        schedule_expression: selectedSchedule.schedule_expression,
        description: selectedSchedule.description,
        state: selectedSchedule.state,
        target_input: selectedSchedule.target_input || {}
      };

      const url = isNew
        ? `../tenants/${tenantName}/mappings/${selectedSchedule.target_alias}/schedules`
        : `../tenants/${tenantName}/mappings/${selectedSchedule.target_alias}/schedules/${selectedSchedule.schedule_id}`;

      const method = isNew ? 'POST' : 'PUT';

      const response = await authenticatedFetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(scheduleData)
      });

      if (!response.ok) {
        let errorMessage = `Failed to save schedule: ${response.status}`;
        try {
          const contentType = response.headers.get('content-type');
          if (contentType?.includes('application/json')) {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorMessage;
          } else {
            const errorText = await response.text();
            errorMessage = errorText || errorMessage;
          }
        } catch (parseError) {
          // If parsing fails, use the default error message
          console.error('Error parsing error response:', parseError);
        }
        throw new Error(errorMessage);
      }

      // Refresh the schedules list
      const refreshResponse = await authenticatedFetch(`../tenants/${tenantName}/schedules`);
      const refreshData = await refreshResponse.json();
      setSchedules(Array.isArray(refreshData) ? refreshData : [refreshData]);

      setSelectedSchedule(null);
    } catch (err) {
      console.error('Error saving schedule:', err);
      alert(`Error saving schedule: ${err.message}`);
    }
  };

  if (loading) {
    return (
      <div className="content-view">
        <p>Loading schedules...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="content-view">
        <p className="text-red-600">Error loading schedules: {error}</p>
      </div>
    );
  }

  return (
    <div className="content-view">
      <div className="view-header">
        <h2>Schedule Management</h2>
        <div className="view-actions">
          <button className="btn btn-primary" onClick={handleAdd}>
            ➕ Add Schedule
          </button>
          <div className="filter-container">
            <input
              type="text"
              placeholder="Filter schedules..."
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
              <th>Schedule ID</th>
              <th>Target Alias</th>
              <th>Schedule Expression</th>
              <th>Description</th>
              <th>State</th>
              <th>History</th>
            </tr>
          </thead>
          <tbody>
            {filteredSchedules.length === 0 ? (
              <tr>
                <td colSpan="7" className="text-center">No schedules found</td>
              </tr>
            ) : (
              filteredSchedules.map(schedule => (
                <tr key={schedule.schedule_id}>
                  <td className="actions-cell">
                    <button
                      className="btn-icon btn-edit"
                      onClick={() => handleEdit(schedule)}
                      title="Edit"
                    >
                      ✏️
                    </button>
                    <button
                      className="btn-icon btn-delete"
                      onClick={() => handleDelete(schedule.target_alias, schedule.schedule_id)}
                      title="Delete"
                    >
                      🗑️
                    </button>
                  </td>
                  <td>{schedule.schedule_id}</td>
                  <td>{schedule.target_alias}</td>
                  <td>{schedule.schedule_expression}</td>
                  <td>{schedule.description}</td>
                  <td>
                    <span className={`status-badge ${schedule.state === 'ENABLED' ? 'status-enabled' : 'status-disabled'}`}>
                      {schedule.state}
                    </span>
                  </td>
                  <td className="actions-cell">
                    <button
                      className="btn-icon btn-history"
                      onClick={() => setExecutionHistorySchedule(schedule)}
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

      {selectedSchedule && (
        <div
          className="modal-overlay"
          onClick={() => setSelectedSchedule(null)}
          onKeyDown={(e) => e.key === 'Escape' && setSelectedSchedule(null)}
          role="dialog"
          aria-modal="true"
          aria-label="Schedule Modal"
          tabIndex={0}
        >
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            role="document"
          >
            <h3>{schedules.some(s => s.schedule_id === selectedSchedule.schedule_id) ? 'Edit Schedule' : 'Add Schedule'}</h3>
            <form onSubmit={handleSave}>
              <div className="form-group">
                <label htmlFor="schedule-target-alias">Target Alias</label>
                <select
                  id="schedule-target-alias"
                  value={selectedSchedule.target_alias}
                  onChange={(e) => setSelectedSchedule({...selectedSchedule, target_alias: e.target.value})}
                  disabled={schedules.some(s => s.schedule_id === selectedSchedule.schedule_id)}
                  required
                >
                  <option value="">Select a target alias...</option>
                  {mappings.map(mapping => (
                    <option key={mapping.target_alias} value={mapping.target_alias}>
                      {mapping.target_alias} ({mapping.target_id})
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="schedule-expression-input">Schedule Expression</label>
                <input
                  id="schedule-expression-input"
                  type="text"
                  value={selectedSchedule.schedule_expression}
                  onChange={(e) => setSelectedSchedule({...selectedSchedule, schedule_expression: e.target.value})}
                  placeholder="rate(5 minutes)"
                  required
                />
                <small className="form-hint">
                  Examples: rate(5 minutes), cron(0 10 * * ? *), at(2024-12-31T23:59:59)
                </small>
              </div>
              <div className="form-group">
                <label htmlFor="schedule-description">Description</label>
                <input
                  id="schedule-description"
                  type="text"
                  value={selectedSchedule.description}
                  onChange={(e) => setSelectedSchedule({...selectedSchedule, description: e.target.value})}
                  placeholder="Run calculator every 5 minutes"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="schedule-state">State</label>
                <select
                  id="schedule-state"
                  value={selectedSchedule.state}
                  onChange={(e) => setSelectedSchedule({...selectedSchedule, state: e.target.value})}
                  required
                >
                  <option value="ENABLED">Enabled</option>
                  <option value="DISABLED">Disabled</option>
                </select>
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedSchedule(null)}>
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

      {executionHistorySchedule && (
        <ExecutionHistoryModal
          tenantName={tenantName}
          filterType="schedule"
          filterValue={executionHistorySchedule.schedule_id}
          targetAlias={executionHistorySchedule.target_alias}
          title={`${executionHistorySchedule.description?.length > 50 ? executionHistorySchedule.description.substring(0, 50) + '...' : executionHistorySchedule.description} (${executionHistorySchedule.target_alias})`}
          onClose={() => setExecutionHistorySchedule(null)}
        />
      )}
    </div>
  );
};

ScheduleList.propTypes = {
  tenantName: PropTypes.string
};

export default ScheduleList;
