import { useChanges, useSourceUrls } from '../api';
import ErrorState from '../components/ErrorState';

const CHANGE_TYPE_COLORS: Record<string, string> = {
  code_deployment: 'var(--color-success)',
  config_change: 'var(--color-warning)',
  infrastructure_change: 'var(--color-info)',
  release: 'var(--color-brand-primary)',
  rollback: 'var(--color-error)',
  scale_event: 'var(--color-sev3)',
};

const Deployments: React.FC = () => {
  const { data: changesData, isLoading, isError, refetch } = useChanges({ hours: 24, limit: 50 });

  const { data: sourceUrlsData } = useSourceUrls();
  const sourceUrls = sourceUrlsData?.sources ?? {};

  if (isError) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <h1 className="page-title">Deployments</h1>
            <p className="page-subtitle">Recent deployments and configuration changes across all services</p>
          </div>
        </div>
        <ErrorState
          title="Unable to load deployment data"
          message="The change feed could not be reached. Please try again."
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getLink = (change: Record<string, unknown>) => {
    const src = (change.source as string) || '';
    const baseUrl = sourceUrls[src];
    if (!baseUrl) return null;
    const val = (change.deploymentId as string) || (change.serviceName as string) || '';
    const cleanBase = baseUrl.replace(/\/+$/, '');
    return `${cleanBase}/${encodeURIComponent(val)}`;
  };

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Deployments</h1>
          <p className="page-subtitle">Recent deployments and configuration changes across all services</p>
        </div>
      </div>

      <div className="summary-stats-bar" role="region" aria-label="Deployment summary">
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value">{changesData?.count ?? 0}</span>
            <span className="summary-stat-label">Changes (24h)</span>
          </div>
        </div>
      </div>

      <section className="dashboard-section" aria-labelledby="changes-list-title">
        {isLoading ? (
          <div style={{ padding: 'var(--space-6)' }}>
            <div className="skeleton" style={{ height: '40px', width: '100%', marginBottom: 'var(--space-3)' }} />
            <div className="skeleton" style={{ height: '40px', width: '100%', marginBottom: 'var(--space-3)' }} />
            <div className="skeleton" style={{ height: '40px', width: '100%' }} />
          </div>
        ) : changesData?.changes && changesData.changes.length > 0 ? (
          <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
            <div role="list" aria-label="Recent deployments">
              {changesData.changes.map((change) => {
                const link = getLink(change);
                return (
                  <div
                    key={(change.eventId as string) || (change.deploymentId as string)}
                    role="listitem"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--color-border-primary)',
                      gap: 'var(--space-4)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', minWidth: 0, flex: 1 }}>
                      <span
                        style={{
                          width: '8px',
                          height: '8px',
                          borderRadius: 'var(--radius-full)',
                          background: CHANGE_TYPE_COLORS[(change.changeType as string)] || 'var(--color-info)',
                          flexShrink: 0,
                        }}
                        aria-hidden="true"
                      />
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--color-text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {change.serviceName as string}
                        </div>
                        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>
                          {(change.description as string) || (change.changeType as string)} 
                          {(change.author as string) && <span> &middot; {(change.author as string).split('@')[0]}</span>}
                          {(change.newVersion as string) && <span> &middot; v{change.newVersion as string}</span>}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexShrink: 0 }}>
                      {link ? (
                        <a
                          href={link}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ fontSize: 'var(--text-xs)', color: 'var(--color-brand-primary)', textDecoration: 'none' }}
                          title={`Open in ${change.source}`}
                        >
                          {change.source as string} ↗
                        </a>
                      ) : (
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>
                          {change.source as string}
                        </span>
                      )}
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-quaternary)' }}>
                        {formatDate(change.timestamp as string)}
                      </span>
                      {(change.status as string) && (
                        <span style={{
                          fontSize: '10px',
                          padding: '1px 6px',
                          borderRadius: 'var(--radius-sm)',
                          background: (change.status as string) === 'succeeded' ? 'var(--color-success)20' :
                                      (change.status as string) === 'failed' ? 'var(--color-error)20' :
                                      'var(--color-warning)20',
                          color: (change.status as string) === 'succeeded' ? 'var(--color-success)' :
                                  (change.status as string) === 'failed' ? 'var(--color-error)' :
                                  'var(--color-warning)',
                        }}>
                          {change.status as string}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="empty-state card" role="status">
            <p className="empty-text">No deployments in the last 24 hours</p>
          </div>
        )}
      </section>
    </div>
  );
};

export default Deployments;
