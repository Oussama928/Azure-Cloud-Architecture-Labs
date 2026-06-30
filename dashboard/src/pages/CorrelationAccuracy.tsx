import { useState } from 'react';
import { useCorrelationAccuracy, useCorrelationAccuracyHistory } from '../api';
import ErrorState from '../components/ErrorState';

const PERIOD_OPTIONS = [7, 14, 30, 60, 90];

const CorrelationAccuracy: React.FC = () => {
  const [days, setDays] = useState(30);
  const { data: accuracy, isLoading, isError, refetch } = useCorrelationAccuracy(days);
  const { data: historyData } = useCorrelationAccuracyHistory(days);

  if (isError) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <h1 className="page-title">Correlation Accuracy</h1>
            <p className="page-subtitle">How accurately the correlation engine identifies root causes from change events</p>
          </div>
        </div>
        <ErrorState
          title="Unable to load correlation data"
          message="The correlation engine could not be reached. Please try again."
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const history = historyData?.history ?? [];

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(0)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
  };

  if (isLoading) {
    return (
      <div className="page-loading" role="status">
        <div className="loading-spinner" />
        <p>Loading correlation accuracy...</p>
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Correlation Accuracy</h1>
          <p className="page-subtitle">How accurately the correlation engine identifies root causes from change events</p>
        </div>
      </div>

      {accuracy && (
        <>
          <div className="summary-stats-bar" role="region">
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ color: accuracy.precision_at_1 >= 0.7 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                  {(accuracy.precision_at_1 * 100).toFixed(0)}%
                </span>
                <span className="summary-stat-label">Precision@1</span>
              </div>
            </div>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ color: accuracy.precision_at_3 >= 0.8 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                  {(accuracy.precision_at_3 * 100).toFixed(0)}%
                </span>
                <span className="summary-stat-label">Precision@3</span>
              </div>
            </div>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ color: accuracy.recall >= 0.7 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                  {(accuracy.recall * 100).toFixed(0)}%
                </span>
                <span className="summary-stat-label">Recall</span>
              </div>
            </div>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value">{accuracy.total_incidents}</span>
                <span className="summary-stat-label">Total Incidents</span>
              </div>
            </div>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value">{formatDuration(accuracy.mean_time_to_detection_seconds)}</span>
                <span className="summary-stat-label">Mean Time to Detect</span>
              </div>
            </div>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ fontSize: 'var(--text-sm)' }}>{accuracy.model_version}</span>
                <span className="summary-stat-label">Model Version</span>
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)', marginTop: 'var(--space-4)' }}>
            <div className="card" style={{ padding: 'var(--space-4)' }}>
              <h3 style={{ marginTop: 0 }}>Period</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
                <select
                  className="select"
                  style={{ maxWidth: '200px' }}
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                  aria-label="Analysis period"
                >
                  {PERIOD_OPTIONS.map((d) => (
                    <option key={d} value={d}>Last {d} days</option>
                  ))}
                </select>
              </div>
              <div className="detail-grid">
                <div className="detail-item">
                  <label>From</label>
                  <span>{new Date(accuracy.period_start).toLocaleDateString()}</span>
                </div>
                <div className="detail-item">
                  <label>To</label>
                  <span>{new Date(accuracy.period_end).toLocaleDateString()}</span>
                </div>
              </div>
            </div>

            <div className="card" style={{ padding: 'var(--space-4)' }}>
              <h3 style={{ marginTop: 0 }}>How it works</h3>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
                Precision@1 measures how often the top-ranked change candidate is the true root cause.
                Precision@3 measures how often the true root cause appears in the top 3 candidates.
                Recall measures how many true root causes were successfully identified.
              </p>
            </div>
          </div>
        </>
      )}

      {history.length > 0 && (
        <section className="dashboard-section">
          <h2>Accuracy History (Last {history.length} days)</h2>
          <div className="card" style={{ padding: 'var(--space-4)', marginTop: 'var(--space-3)', overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--color-border-primary)' }}>
                  <th style={{ textAlign: 'left', padding: 'var(--space-2) var(--space-3)' }}>Date</th>
                  <th style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)' }}>Incidents</th>
                  <th style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)' }}>P@1</th>
                  <th style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)' }}>P@3</th>
                  <th style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)' }}>Recall</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={entry.date} style={{ borderBottom: '1px solid var(--color-border-primary)' }}>
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>{entry.date}</td>
                    <td style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)' }}>{entry.total_incidents}</td>
                    <td style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)', color: entry.precision_at_1 >= 0.7 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                      {(entry.precision_at_1 * 100).toFixed(0)}%
                    </td>
                    <td style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)', color: entry.precision_at_3 >= 0.8 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                      {(entry.precision_at_3 * 100).toFixed(0)}%
                    </td>
                    <td style={{ textAlign: 'right', padding: 'var(--space-2) var(--space-3)', color: entry.recall >= 0.7 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                      {(entry.recall * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {!accuracy && !isLoading && (
        <div className="empty-state card" role="status">
          <p className="empty-text">No correlation accuracy data available</p>
          <p className="empty-subtext">Data appears after incidents have been resolved with root cause analysis</p>
        </div>
      )}
    </div>
  );
};

export default CorrelationAccuracy;
