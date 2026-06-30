import { useNavigate } from 'react-router-dom';
import IncidentTimeline from '../components/IncidentTimeline';
import ErrorState from '../components/ErrorState';
import { useIncidents } from '../api';

const Incidents: React.FC = () => {
  const navigate = useNavigate();
  const { data: incidents, isLoading, isError, refetch } = useIncidents({ limit: 100 });

  if (isError) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <h1 className="page-title">Incidents</h1>
            <p className="page-subtitle">Incident tracking with correlation results and remediation status</p>
          </div>
        </div>
        <ErrorState
          title="Unable to load incidents"
          message="The incidents service could not be reached. Please try again."
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const activeCount = (incidents ?? []).filter(
    (i) => i.status !== 'resolved' && i.status !== 'closed'
  ).length;

  const sev1Count = (incidents ?? []).filter((i) => i.severity === 'sev1').length;

  const handleIncidentClick = (incident: { incident_id: string }) => {
    navigate(`/incidents/${incident.incident_id}`);
  };

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Incidents</h1>
          <p className="page-subtitle">Incident tracking with correlation results and remediation status</p>
        </div>
      </div>

      <div className="summary-stats-bar" role="region" aria-label="Incident summary">
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value">{incidents?.length ?? 0}</span>
            <span className="summary-stat-label">Total Incidents</span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value" style={{ color: activeCount > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
              {activeCount}
            </span>
            <span className="summary-stat-label">Active</span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value" style={{ color: sev1Count > 0 ? 'var(--color-error)' : 'var(--color-text-quaternary)' }}>
              {sev1Count}
            </span>
            <span className="summary-stat-label">SEV1 Critical</span>
          </div>
        </div>
      </div>

      <section className="dashboard-section full-width" aria-labelledby="incident-timeline-title">
        <IncidentTimeline
          incidents={incidents ?? []}
          isLoading={isLoading}
          onIncidentClick={handleIncidentClick}
        />
      </section>
    </div>
  );
};

export default Incidents;
