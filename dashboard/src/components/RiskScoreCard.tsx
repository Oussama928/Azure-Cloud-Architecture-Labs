import React from 'react';
import './RiskScoreCard.css';

interface RiskScoreCardProps {
  service: string;
  namespace?: string;
  riskScore: number;
  riskLevel: 'low' | 'medium' | 'high' | 'critical';
  factors: Record<string, number>;
  lastDeployment?: string;
  lastDeploymentTime?: string;
  onClick?: () => void;
  isLoading?: boolean;
}

const RiskScoreCard: React.FC<RiskScoreCardProps> = ({
  service,
  namespace,
  riskScore,
  riskLevel,
  factors,
  lastDeployment,
  lastDeploymentTime,
  onClick,
  isLoading = false,
}) => {
  const getRiskColor = (level: string) => {
    switch (level) {
      case 'critical': return 'var(--color-risk-critical)';
      case 'high': return 'var(--color-risk-high)';
      case 'medium': return 'var(--color-risk-medium)';
      case 'low': return 'var(--color-risk-low)';
      default: return 'var(--color-text-quaternary)';
    }
  };

  const getRiskBgColor = (level: string) => {
    switch (level) {
      case 'critical': return 'var(--color-error-bg)';
      case 'high': return 'var(--color-warning-bg)';
      case 'medium': return 'var(--color-warning-bg)';
      case 'low': return 'var(--color-success-bg)';
      default: return 'var(--color-bg-tertiary)';
    }
  };

  const getRiskBorderColor = (level: string) => {
    switch (level) {
      case 'critical': return 'var(--color-error-border)';
      case 'high': return 'var(--color-warning-border)';
      case 'medium': return 'var(--color-warning-border)';
      case 'low': return 'var(--color-success-border)';
      default: return 'var(--color-border-primary)';
    }
  };

  const formatFactorName = (name: string) => {
    return name
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase());
  };

  const riskPercentage = Math.round(riskScore * 100);

  if (isLoading) {
    return (
      <div className="risk-score-card skeleton-loading" aria-busy="true">
        <div className="skeleton" style={{ height: '24px', width: '60%' }} />
        <div className="skeleton" style={{ height: '14px', width: '40%', marginTop: '8px' }} />
        <div className="skeleton" style={{ height: '8px', width: '100%', marginTop: '16px', borderRadius: 'var(--radius-full)' }} />
        <div className="skeleton" style={{ height: '8px', width: '80%', marginTop: '12px', borderRadius: 'var(--radius-full)' }} />
        <div className="skeleton" style={{ height: '8px', width: '60%', marginTop: '12px', borderRadius: 'var(--radius-full)' }} />
        <div className="skeleton" style={{ height: '8px', width: '40%', marginTop: '12px', borderRadius: 'var(--radius-full)' }} />
      </div>
    );
  }

  return (
    <article
      className="risk-score-card"
      style={{
        background: getRiskBgColor(riskLevel),
        borderColor: getRiskBorderColor(riskLevel),
      }}
      onClick={onClick}
      role={onClick ? 'button' : 'article'}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }} : undefined}
      aria-label={onClick ? `View details for ${service}` : undefined}
    >
      <div className="card-header">
        <div className="service-info">
          <h3 className="service-name">{service}</h3>
          {namespace && (
            <span className="service-namespace">{namespace}</span>
          )}
        </div>
        <div
          className="risk-badge"
          style={{
            background: getRiskColor(riskLevel),
            color: 'var(--color-text-inverse)',
          }}
        >
          <span className="risk-score">{riskPercentage}%</span>
          <span className="risk-level">{riskLevel.toUpperCase()}</span>
        </div>
      </div>

      <div className="risk-visualization">
        <div className="risk-score-bar-container">
          <div className="risk-score-bar-labels">
            <span>Low</span>
            <span>Medium</span>
            <span>High</span>
            <span>Critical</span>
          </div>
          <div className="risk-score-bar-track">
            <div
              className="risk-score-bar-fill"
              style={{
                width: `${riskPercentage}%`,
                background: getRiskColor(riskLevel),
              }}
              role="progressbar"
              aria-valuenow={riskPercentage}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Risk score ${riskPercentage} percent`}
            >
              <span className="risk-score-bar-thumb" aria-hidden="true"></span>
            </div>
            <div className="risk-score-bar-markers">
              <span style={{ left: '30%' }} aria-hidden="true"></span>
              <span style={{ left: '70%' }} aria-hidden="true"></span>
              <span style={{ left: '90%' }} aria-hidden="true"></span>
            </div>
          </div>
        </div>
      </div>

      <div className="risk-factors">
        <h4 className="section-title">Risk Factors</h4>
        <div className="factors-list">
          {Object.entries(factors).map(([factor, value]) => (
            <div key={factor} className="factor-item">
              <div className="factor-header">
                <span className="factor-name">{formatFactorName(factor)}</span>
                <span className="factor-value" style={{ color: getRiskColor(riskLevel) }}>
                  {Math.round(value * 100)}%
                </span>
              </div>
              <div className="factor-bar">
                <div
                  className="factor-bar-fill"
                  style={{
                    width: `${Math.round(value * 100)}%`,
                    background: getRiskColor(riskLevel),
                  }}
                  aria-hidden="true"
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {lastDeployment && (
        <div className="deployment-info">
          <div className="deployment-header">
            <span className="deployment-label">Last Deployment</span>
            <span className="deployment-name">{lastDeployment}</span>
          </div>
          {lastDeploymentTime && (
            <div className="deployment-time">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
              <span>{lastDeploymentTime}</span>
            </div>
          )}
        </div>
      )}

      <div className="risk-thresholds">
        <span className="thresholds-label">Thresholds:</span>
        <div className="thresholds-list">
          <span className="threshold-item" style={{ '--threshold-color': 'var(--color-risk-low)' } as React.CSSProperties & Record<string, string>}>
            <span className="threshold-dot" aria-hidden="true"></span>
            <span>Low &lt; 30%</span>
          </span>
          <span className="threshold-item" style={{ '--threshold-color': 'var(--color-risk-medium)' } as React.CSSProperties & Record<string, string>}>
            <span className="threshold-dot" aria-hidden="true"></span>
            <span>Medium 30-70%</span>
          </span>
          <span className="threshold-item" style={{ '--threshold-color': 'var(--color-risk-high)' } as React.CSSProperties & Record<string, string>}>
            <span className="threshold-dot" aria-hidden="true"></span>
            <span>High 70-90%</span>
          </span>
          <span className="threshold-item" style={{ '--threshold-color': 'var(--color-risk-critical)' } as React.CSSProperties & Record<string, string>}>
            <span className="threshold-dot" aria-hidden="true"></span>
            <span>Critical &gt; 90%</span>
          </span>
        </div>
      </div>
    </article>
  );
};

export default RiskScoreCard;
