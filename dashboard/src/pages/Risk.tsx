import RiskScoreCard from '../components/RiskScoreCard';
import ErrorState from '../components/ErrorState';
import { useRiskScores, useRiskHistory } from '../api';

const RISK_COLORS: Record<string, string> = {
  low: 'var(--color-success)',
  medium: 'var(--color-warning)',
  high: 'var(--color-error)',
  critical: 'var(--color-sev1)',
};

const MINI_CHART_WIDTH = 280;
const MINI_CHART_HEIGHT = 80;

const RiskSparkline: React.FC<{ data: { timestamp: string; risk_score: number }[]; color: string }> = ({ data, color }) => {
  if (data.length < 2) return null;
  const scores = data.map(d => d.risk_score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;
  const w = MINI_CHART_WIDTH;
  const h = MINI_CHART_HEIGHT;
  const stepX = w / (data.length - 1);
  const points = data.map((d, i) => {
    const x = i * stepX;
    const y = h - ((d.risk_score - min) / range) * (h - 10) - 5;
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block', margin: 'var(--space-2) 0' }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
};

const Risk: React.FC = () => {
  const { data: riskScores, isLoading: scoresLoading, isError: scoresError, refetch: refetchScores } = useRiskScores();
  const { data: history, isError: historyError } = useRiskHistory({ hours: 336 }); // 14 days

  if (scoresError || historyError) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <h1 className="page-title">Risk Assessment</h1>
            <p className="page-subtitle">Deployment risk scoring based on change velocity, failure history, and blast radius</p>
          </div>
        </div>
        <ErrorState
          title="Unable to load risk data"
          message="The risk engine could not be reached. Please try again."
          onRetry={() => refetchScores()}
        />
      </div>
    );
  }

  const highRiskCount = riskScores?.scores?.filter(
    (r) => r.risk_level === 'high' || r.risk_level === 'critical'
  ).length ?? 0;

  const historyByService = new Map<string, { timestamp: string; risk_score: number }[]>();
  if (history) {
    for (const entry of history) {
      const arr = historyByService.get(entry.service) || [];
      arr.push({ timestamp: entry.timestamp, risk_score: entry.risk_score });
      historyByService.set(entry.service, arr);
    }
  }

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Risk Assessment</h1>
          <p className="page-subtitle">Deployment risk scoring based on change velocity, failure history, and blast radius</p>
        </div>
      </div>

      <div className="summary-stats-bar" role="region" aria-label="Risk summary">
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value">{riskScores?.scores?.length ?? 0}</span>
            <span className="summary-stat-label">Services Evaluated</span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value" style={{ color: highRiskCount > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
              {highRiskCount}
            </span>
            <span className="summary-stat-label">High / Critical Risk</span>
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-stat-content">
            <span className="summary-stat-value">{history?.length ?? 0}</span>
            <span className="summary-stat-label">Risk Data Points</span>
          </div>
        </div>
      </div>

      <section className="dashboard-section" aria-labelledby="risk-cards-title">
        <div className="risk-cards-grid">
          {scoresLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <RiskScoreCard
                key={i}
                service=""
                riskScore={0}
                riskLevel="low"
                factors={{}}
                isLoading
              />
            ))
          ) : riskScores?.scores?.map((risk) => {
            const svcHistory = historyByService.get(risk.service) || [];
            return (
              <div key={risk.service} className="card" style={{ padding: 'var(--space-4)' }}>
                <RiskScoreCard
                  service={risk.service}
                  namespace={risk.namespace}
                  riskScore={risk.risk_score}
                  riskLevel={risk.risk_level}
                  factors={risk.factors}
                  lastDeployment={risk.last_deployment}
                  lastDeploymentTime={risk.last_deployment_time}
                />
                {svcHistory.length > 1 && (
                  <div style={{ marginTop: 'var(--space-2)' }}>
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', marginBottom: 'var(--space-1)' }}>
                      14-Day Risk Trend
                    </div>
                    <RiskSparkline data={svcHistory} color={RISK_COLORS[risk.risk_level] || 'var(--color-text-tertiary)'} />
                  </div>
                )}
              </div>
            );
          })}
          {(!riskScores?.scores || riskScores.scores.length === 0) && (
            <div className="empty-state card" role="status">
              <p className="empty-text">No risk data available</p>
              <p className="empty-subtext">Risk scores appear after deployment activity is detected</p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default Risk;
