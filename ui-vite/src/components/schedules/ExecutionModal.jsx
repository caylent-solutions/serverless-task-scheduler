import React, { useState } from 'react';

const ExecutionModal = ({ schedule, onClose }) => {
  const [executions] = useState([
    {
      id: 'exec-001',
      startDate: '2025-11-04 08:00:00',
      endDate: '2025-11-04 08:05:23',
      status: 'SUCCESS',
      cloudWatchLink: 'https://console.aws.amazon.com/cloudwatch/...'
    },
    {
      id: 'exec-002',
      startDate: '2025-11-03 08:00:00',
      endDate: '2025-11-03 08:04:15',
      status: 'SUCCESS',
      cloudWatchLink: 'https://console.aws.amazon.com/cloudwatch/...'
    },
    {
      id: 'exec-003',
      startDate: '2025-11-02 08:00:00',
      endDate: '2025-11-02 08:10:45',
      status: 'FAILED',
      cloudWatchLink: 'https://console.aws.amazon.com/cloudwatch/...'
    },
  ]);

  // Safe URL navigation handler - validates URL before opening
  const handleLinkClick = (e, url) => {
    e.preventDefault();
    if (!url) return;

    try {
      // Use URL constructor to validate and parse the URL
      const urlObj = new URL(url);

      // Only allow https protocol
      if (urlObj.protocol !== 'https:') {
        console.error('Only HTTPS URLs are allowed');
        return;
      }

      // Allowlist for CloudWatch and AWS Console domains
      const allowedDomains = [
        'console.aws.amazon.com',
        'console.amazonaws-us-gov.com', // GovCloud
      ];

      // Check if hostname matches allowed domains
      const isAllowed = allowedDomains.some(domain =>
        urlObj.hostname === domain || urlObj.hostname.endsWith('.' + domain)
      );

      if (isAllowed) {
        window.open(urlObj.href, '_blank', 'noopener,noreferrer');
      } else {
        console.error('URL domain not allowed:', urlObj.hostname);
      }
    } catch (err) {
      // Invalid URL, do nothing
      console.error('Invalid URL:', err);
    }
  };

  const [filter, setFilter] = useState('');

  const filteredExecutions = executions.filter(exec =>
    exec.id.toLowerCase().includes(filter.toLowerCase()) ||
    exec.status.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-large" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Executions - {schedule.name}</h3>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>
        
        <div className="modal-body">
          <div className="view-actions">
            <button className="btn btn-primary">
              ➕ Add Execution
            </button>
            <div className="filter-container">
              <input
                type="text"
                placeholder="Filter executions..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="filter-input"
              />
              <span className="filter-icon">🔍</span>
            </div>
          </div>

          <div className="data-table">
            <table>
              <thead>
                <tr>
                  <th>Execution ID</th>
                  <th>Start Date</th>
                  <th>End Date</th>
                  <th>Status</th>
                  <th>CloudWatch</th>
                </tr>
              </thead>
              <tbody>
                {filteredExecutions.map(execution => (
                  <tr key={execution.id}>
                    <td>{execution.id}</td>
                    <td>{execution.startDate}</td>
                    <td>{execution.endDate}</td>
                    <td>
                      <span className={`status-badge status-${execution.status.toLowerCase()}`}>
                        {execution.status}
                      </span>
                    </td>
                    <td>
                      <button
                        onClick={(e) => handleLinkClick(e, execution.cloudWatchLink)}
                        className="btn-link"
                        style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', textDecoration: 'underline' }}
                      >
                        🔗 View Logs
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExecutionModal;
