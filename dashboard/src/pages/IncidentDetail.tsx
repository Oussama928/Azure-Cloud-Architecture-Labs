import { useParams, useNavigate } from 'react-router-dom';
import { useIncidentDetail, useUpdateIncidentStatus } from '../api';
import ErrorState from '../components/ErrorState';
import { useState } from 'react';

const STATUS_OPTIONS = [
  'open',
  'investigating',
  'root_cause_identified',
  'remediating',
  'verifying',
  'resolved',
  'closed',
];

const SEVERITY_COLORS: Record<string, string> = {
  sev1: 'var(--color-sev1)',
  sev2: 'var(--color-sev2)',
  sev3: 'var(--color-sev3)',
  sev4: 'var(--color-sev4)',
};

const STATUS_COLORS: Record<string, string> = {
  open: 'var(--color-status-open)',
  investigating: 'var(--color-status-investigating)',
  root_cause_identified: 'var(--color-status-root-cause)',
  remediating: 'var(--color-status-remediating)',
  verifying: 'var(--color-status-verifying)',
  resolved: 'var(--color-status-resolved)',
  closed: 'var(--color-status-closed)',
};

const IncidentDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: incident, isLoading, isError, refetch } = useIncidentDetail(id || '');
  const updateStatus = useUpdateIncidentStatus();
  const [updating, setUpdating] = useState(false);

  const handleStatusChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    if (!incident) return;
    const next = e.target.value;
    if (next === incident.status) return;
    setUpdating(true);
    try {
      await updateStatus.mutateAsync({ incidentId: incident.incident_id, status: next });
      await refetch();
    } finally {
      setUpdating(false);
    }
  };

  if (isError) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <button className="btn btn-ghost" onClick={() => navigate('/incidents')}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="19" y1="12" x2="5" y2="12" />
                <polyline points="12 19 5 12 12 5" />
              </svg>
            </button>
          </div>
        </div>
        <ErrorState
          title="Unable to load incident"
          message="The incident could not be loaded. Please try again."
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="page-loading" role="status">
        <div className="loading-spinner" />
        <p>Loading incident details...</p>
      </div>
    );
  }

  if (!incident) {
    return (
      <div className="dashboard-page">
        <div className="empty-state card">
          <p className="empty-text">Incident not found</p>
          <button className="btn btn-secondary" onClick={() => navigate('/incidents')}>Back to Incidents</button>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <button className="btn btn-ghost" onClick={() => navigate('/incidents')}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="19" y1="12" x2="5" y2="12" />
                <polyline points="12 19 5 12 12 5" />
              </svg>
            </button>
            <h1 className="page-title" style={{ margin: 0 }}>{incident.title}</h1>
          </div>
          <p className="page-subtitle">{incident.incident_id}</p>
        </div>
      </div>

      <div className="summary-stats-bar" role="region">
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value" style={{ color: SEVERITY_COLORS[incident.severity] || 'inherit' }}>
              {incident.severity?.toUpperCase()}
            </span>
            <span className="summary-stat-label">Severity</span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value" style={{ color: STATUS_COLORS[incident.status] || 'inherit' }}>
              {incident.status?.replace(/_/g, ' ')}
            </span>
            <span className="summary-stat-label">
              Status &middot;{' '}
              <select
                className="status-select"
                value={incident.status}
                onChange={handleStatusChange}
                disabled={updating}
                aria-label="Update incident status"
                style={{ marginLeft: 'var(--space-1)' }}
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value">{incident.affected_service}</span>
            <span className="summary-stat-label">Affected Service</span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value">{new Date(incident.detected_at).toLocaleString()}</span>
            <span className="summary-stat-label">Detected At</span>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        <div className="card" style={{ padding: 'var(--space-4)' }}>
          <h3 style={{ marginTop: 0 }}>Details</h3>
          <div className="detail-grid">
            <div className="detail-item">
              <label>Namespace</label>
              <span>{incident.affected_namespace || 'production'}</span>
            </div>
            <div className="detail-item">
              <label>SLO Name</label>
              <span>{incident.slo_name || 'availability'}</span>
            </div>
            <div className="detail-item">
              <label>Error Budget Burn Rate</label>
              <span>{incident.error_budget_burn_rate?.toFixed(1)}x</span>
            </div>
            <div className="detail-item">
              <label>Started At</label>
              <span>{new Date(incident.started_at).toLocaleString()}</span>
            </div>
            <div className="detail-item">
              <label>Resolved At</label>
              <span>{incident.resolved_at ? new Date(incident.resolved_at).toLocaleString() : 'N/A'}</span>
            </div>
          </div>
        </div>

        <div className="card" style={{ padding: 'var(--space-4)' }}>
          <h3 style={{ marginTop: 0 }}>Remediation</h3>
          <div className="detail-grid">
            <div className="detail-item">
              <label>Action</label>
              <span>{incident.remediation_action?.replace(/_/g, ' ') || 'N/A'}</span>
            </div>
            <div className="detail-item">
              <label>Status</label>
              <span>{incident.remediation_status?.replace(/_/g, ' ') || 'N/A'}</span>
            </div>
            <div className="detail-item">
              <label>Root Cause Candidate</label>
              <span style={{ fontWeight: 700 }}>{incident.root_cause_candidate || 'Unknown'}</span>
            </div>
            <div className="detail-item">
              <label>Confidence</label>
              <span style={{ color: incident.confidence > 0.8 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                {(incident.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {incident.candidates && incident.candidates.length > 0 && (
        <section className="dashboard-section">
          <h2>Change Candidates ({incident.candidates.length})</h2>
          <div className="card" style={{ padding: 'var(--space-4)', marginTop: 'var(--space-3)' }}>
            <div role="list">
              {[...incident.candidates]
                .sort((a, b) => b.confidence_score - a.confidence_score)
                .map((c, i) => (
                  <div
                    key={c.change_event_id}
                    role="listitem"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: i < incident.candidates.length - 1 ? '1px solid var(--color-border-primary)' : 'none',
                      background: i === 0 ? 'var(--color-brand-primary)10' : 'transparent',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flex: 1 }}>
                      {i === 0 && (
                        <span style={{
                          background: 'var(--color-brand-primary)',
                          color: 'white',
                          fontSize: '10px',
                          padding: '2px 6px',
                          borderRadius: 'var(--radius-sm)',
                          fontWeight: 600,
                        }}>TOP</span>
                      )}
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                          {c.service_name}
                        </div>
                        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>
                          {c.change_type} &middot; {c.source}
                        </div>
                        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-quaternary)' }}>
                          {new Date(c.timestamp).toLocaleString()}
                        </div>
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontWeight: 700, color: c.confidence_score > 0.8 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                        {(c.confidence_score * 100).toFixed(0)}%
                      </div>
                      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>confidence</div>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
};

export default IncidentDetail;
