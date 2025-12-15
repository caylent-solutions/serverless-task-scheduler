import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import authenticatedFetch from '../../utils/api';
import './ExecutionHistoryModal.css';

const ExecutionHistoryModal = ({
  tenantName,
  filterType, // 'schedule' or 'alias'
  filterValue, // schedule_id or target_alias
  targetAlias, // required when filterType is 'schedule'
  title,
  onClose
}) => {
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [redrivingExecutions, setRedrivingExecutions] = useState(new Set()); // Track which executions are being redriven

  // Filters
  const [statusFilter, setStatusFilter] = useState('all'); // 'all', 'SUCCESS', 'FAILED'
  const [startTimeLower, setStartTimeLower] = useState('');
  const [startTimeUpper, setStartTimeUpper] = useState('');

  // Fetch executions from API
  const fetchExecutions = async () => {
    try {
      setLoading(true);

      // Build the correct API endpoint based on filter type
      // For schedules: GET /tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}/executions
      // For aliases: GET /tenants/{tenant_id}/mappings/{target_alias}/executions

      // Build query parameters for filtering
      const params = new URLSearchParams();
      params.append('limit', '50');

      if (startTimeLower) {
        params.append('start_time_lower', new Date(startTimeLower).toISOString());
      }

      if (startTimeUpper) {
        params.append('start_time_upper', new Date(startTimeUpper).toISOString());
      }

      if (statusFilter !== 'all') {
        params.append('status', statusFilter);
      }

      let apiUrl;
      if (filterType === 'schedule') {
        // For schedule filtering: use schedule_id and target_alias
        apiUrl = `../tenants/${tenantName}/mappings/${targetAlias}/schedules/${filterValue}/executions?${params.toString()}`;
      } else {
        // For alias filtering: filterValue is the target_alias
        apiUrl = `../tenants/${tenantName}/mappings/${filterValue}/executions?${params.toString()}`;
      }

      const response = await authenticatedFetch(apiUrl);

      if (!response.ok) {
        throw new Error(`Failed to fetch executions: ${response.status}`);
      }

      const data = await response.json();

      // Handle both array response and object with executions property
      const executionsData = Array.isArray(data) ? data : (data.executions || []);
      setExecutions(executionsData);
      setError(null);

      // Clear redriving state when new data is fetched
      setRedrivingExecutions(new Set());
    } catch (err) {
      console.error('Error fetching executions:', err);
      setError(err.message);
      setExecutions([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchExecutions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantName, filterType, filterValue, targetAlias, statusFilter, startTimeLower, startTimeUpper]);

  // Format timestamp for display
  const formatTimestamp = (timestamp) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleString('en-US', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
    } catch (e) {
      console.error('Error formatting timestamp:', e);
      return timestamp;
    }
  };

  // Server-side filtering is now handled by the API, so we use executions directly
  const filteredExecutions = executions;

  // Get CloudWatch logs URL from execution record
  const getCloudWatchUrl = (execution) => {
    // CloudWatch URL is stored directly on the execution object, not in result
    return execution.cloudwatch_logs_url || '#';
  };

  // Handle re-drive execution
  const handleRedrive = async (execution) => {
    if (!globalThis.confirm('Are you sure you want to re-drive this failed execution? This will restart the execution from the point of failure.')) {
      return;
    }

    // Add execution to redriving set
    setRedrivingExecutions(prev => new Set(prev).add(execution.execution_id));

    try {
      // Determine the target alias based on filter type
      const effectiveTargetAlias = filterType === 'schedule' ? targetAlias : filterValue;

      // Use the execution_id (UUIDv7) directly - no encoding needed for UUID
      const redriveUrl = `../tenants/${tenantName}/mappings/${effectiveTargetAlias}/executions/${execution.execution_id}/redrive`;
      console.log('Redrive URL:', redriveUrl);
      console.log('Execution ID (UUID):', execution.execution_id);

      const response = await authenticatedFetch(
        redriveUrl,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          }
        }
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || `Failed to redrive execution: ${response.status}`);
      }

      const result = await response.json();
      console.log('Execution redriven successfully:', result);
      console.log('Message:', result.message);
      console.log('Execution ID:', result.execution_id);
      console.log('Note:', result.note);

      // Note: Button will remain disabled until executions are refetched
      // The redriving state will be cleared when the component receives new data

    } catch (err) {
      console.error('Error redriving execution:', err);
      alert(`Failed to redrive execution:\n\n${err.message}`);

      // Remove from redriving set on error
      setRedrivingExecutions(prev => {
        const next = new Set(prev);
        next.delete(execution.execution_id);
        return next;
      });
    }
  };

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      role="dialog"
      aria-modal="true"
      aria-label="Execution History Modal"
    >
      <div
        className="execution-history-modal"
        onClick={(e) => e.stopPropagation()}
        role="document"
      >
        <div className="modal-header">
          <h2>Execution History - {title}</h2>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {/* Filters Section */}
          <div className="filters-section">
            <div className="filter-group">
              <label htmlFor="status-filter">Status:</label>
              <select
                id="status-filter"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="filter-select"
              >
                <option value="all">All</option>
                <option value="SUCCESS">Success</option>
                <option value="FAILED">Failed</option>
              </select>
            </div>

            <div className="filter-group">
              <label htmlFor="time-lower">Start Time (After):</label>
              <input
                id="time-lower"
                type="datetime-local"
                value={startTimeLower}
                onChange={(e) => setStartTimeLower(e.target.value)}
                className="filter-input"
              />
            </div>

            <div className="filter-group">
              <label htmlFor="time-upper">Start Time (Before):</label>
              <input
                id="time-upper"
                type="datetime-local"
                value={startTimeUpper}
                onChange={(e) => setStartTimeUpper(e.target.value)}
                className="filter-input"
              />
            </div>

            <button
              className="btn btn-secondary"
              onClick={() => {
                setStatusFilter('all');
                setStartTimeLower('');
                setStartTimeUpper('');
              }}
            >
              Clear Filters
            </button>
          </div>

          {/* Results Info */}
          <div className="results-info-container">
            <div className="results-info">
              Showing {filteredExecutions.length} of {executions.length} executions (limited to 50 most recent)
            </div>
            <button
              className="btn btn-refresh"
              onClick={fetchExecutions}
              disabled={loading}
              title="Refresh executions list"
            >
              {loading ? '⟳ Refreshing...' : '🔄 Refresh'}
            </button>
          </div>

          {/* Executions Table */}
          {loading && (
            <div className="loading-state">Loading executions...</div>
          )}
          {!loading && error && (
            <div className="error-state">
              <p>Unable to load executions from API.</p>
              <p className="error-message">{error}</p>
            </div>
          )}
          {!loading && !error && (
            <div className="table-container">
              <table className="executions-table">
                <thead>
                  <tr>
                    <th>Execution ID</th>
                    <th>Start Time</th>
                    <th>Status</th>
                    <th>CloudWatch Logs</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredExecutions.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="no-data">
                        No executions found matching the filter criteria
                      </td>
                    </tr>
                  ) : (
                    filteredExecutions.map((execution, index) => {
                      const timestamp = execution.timestamp || execution.executed_at;
                      const isRedriving = redrivingExecutions.has(execution.execution_id);
                      const redriveButtonTitle = isRedriving
                        ? "Redrive in progress..."
                        : "Re-drive this failed execution from the point of failure";

                      return (
                        <tr key={execution.execution_id || index}>
                          <td>
                            <div className="execution-id-cell">
                              <div className="request-id" title={execution.execution_id}>
                                {execution.execution_id}
                              </div>
                            </div>
                          </td>
                          <td>{formatTimestamp(timestamp)}</td>
                          <td>
                            <span className={`status-badge status-${execution.status?.toLowerCase() || 'unknown'}`}>
                              {execution.status || 'UNKNOWN'}
                            </span>
                          </td>
                          <td>
                            <a
                              href={getCloudWatchUrl(execution)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="logs-link"
                              onClick={(e) => {
                                if (getCloudWatchUrl(execution) === '#') {
                                  e.preventDefault();
                                  globalThis.alert('CloudWatch logs URL not available for this execution');
                                }
                              }}
                            >
                              🔗 View Logs
                            </a>
                          </td>
                          <td>
                            {execution.status === 'FAILED' && execution.can_redrive !== false ? (
                              <button
                                className="btn btn-warning btn-sm"
                                onClick={() => handleRedrive(execution)}
                                disabled={isRedriving}
                                title={redriveButtonTitle}
                                style={{
                                  opacity: isRedriving ? 0.5 : 1,
                                  cursor: isRedriving ? 'not-allowed' : 'pointer'
                                }}
                              >
                                {isRedriving ? '⏳ Redriving...' : '🔄 Re-drive'}
                              </button>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

ExecutionHistoryModal.propTypes = {
  tenantName: PropTypes.string.isRequired,
  filterType: PropTypes.oneOf(['schedule', 'alias']).isRequired,
  filterValue: PropTypes.string.isRequired,
  targetAlias: PropTypes.string,
  title: PropTypes.string.isRequired,
  onClose: PropTypes.func.isRequired
};

export default ExecutionHistoryModal;
