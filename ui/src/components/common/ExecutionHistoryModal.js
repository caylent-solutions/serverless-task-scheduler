import React, { useState, useEffect } from 'react';
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

  // Filters
  const [statusFilter, setStatusFilter] = useState('all'); // 'all', 'SUCCESS', 'FAILED'
  const [startTimeLower, setStartTimeLower] = useState('');
  const [startTimeUpper, setStartTimeUpper] = useState('');

  // Fetch executions from API
  useEffect(() => {
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
      } catch (err) {
        console.error('Error fetching executions:', err);
        setError(err.message);
        // Set mock data for development if API not available
        setExecutions(generateMockExecutions(filterValue));
      } finally {
        setLoading(false);
      }
    };

    fetchExecutions();
  }, [tenantName, filterType, filterValue, targetAlias, statusFilter, startTimeLower, startTimeUpper]);

  // Generate mock data for development/testing
  const generateMockExecutions = (id) => {
    const mockData = [];
    const now = new Date();

    for (let i = 0; i < 10; i++) {
      const timestamp = new Date(now.getTime() - i * 3600000); // 1 hour intervals
      const lambdaRequestId = `${Math.random().toString(36).substring(7)}-${Math.random().toString(36).substring(7)}`;
      const executionId = `${timestamp.toISOString()}#${lambdaRequestId}`;

      mockData.push({
        execution_id: executionId,
        timestamp: timestamp.toISOString(),
        status: i % 5 === 0 ? 'FAILED' : 'SUCCESS',
        lambda_request_id: lambdaRequestId,
        result: {
          cloudwatch_logs_url: `https://console.aws.amazon.com/cloudwatch/home#logsV2:log-groups/log-group/$252Faws$252Flambda$252FLambdaCalculator/log-events/${timestamp.getFullYear()}$252F${(timestamp.getMonth() + 1).toString().padStart(2, '0')}$252F${timestamp.getDate().toString().padStart(2, '0')}$252F$255B$2524LATEST$255D${lambdaRequestId}`
        }
      });
    }

    return mockData;
  };

  // Extract timestamp from execution_id (format: timestamp#request_id)
  const getTimestampFromExecutionId = (executionId) => {
    if (!executionId) return '';
    const parts = executionId.split('#');
    return parts[0] || '';
  };

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
    if (!window.confirm('Are you sure you want to re-drive this failed execution? This will restart the execution from the point of failure.')) {
      return;
    }

    try {
      const response = await authenticatedFetch(
        `../tenants/${tenantName}/executions/${execution.execution_id}/redrive`,
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
      alert(`Execution redriven successfully!\n\n${result.message}\n\nRefresh the page to see the updated status.`);

      // Refresh executions list after short delay
      setTimeout(() => {
        window.location.reload();
      }, 2000);

    } catch (err) {
      console.error('Error redriving execution:', err);
      alert(`Failed to redrive execution:\n\n${err.message}`);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="execution-history-modal" onClick={(e) => e.stopPropagation()}>
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
          <div className="results-info">
            Showing {filteredExecutions.length} of {executions.length} executions (limited to 50 most recent)
          </div>

          {/* Executions Table */}
          {loading ? (
            <div className="loading-state">Loading executions...</div>
          ) : error ? (
            <div className="error-state">
              <p>Unable to load executions from API. Showing sample data.</p>
              <p className="error-message">{error}</p>
            </div>
          ) : (
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
                      const timestamp = execution.timestamp || getTimestampFromExecutionId(execution.execution_id);
                      const requestId = execution.lambda_request_id || execution.execution_id.split('#')[1] || 'unknown';

                      return (
                        <tr key={execution.execution_id || index}>
                          <td>
                            <div className="execution-id-cell">
                              <div className="request-id" title={execution.execution_id}>
                                {requestId}
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
                                  alert('CloudWatch logs URL not available for this execution');
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
                                title="Re-drive this failed execution from the point of failure"
                              >
                                🔄 Re-drive
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

export default ExecutionHistoryModal;
