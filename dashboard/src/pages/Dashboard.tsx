import { useState, useCallback, useMemo, useEffect } from 'react';
import DependencyGraph from '../components/DependencyGraph';
import IncidentTimeline from '../components/IncidentTimeline';
import RiskScoreCard from '../components/RiskScoreCard';
import SLOBurnChart from '../components/SLOBurnChart';
import ErrorState from '../components/ErrorState';
import { useToast } from '../components/Toast';
import {
  useDependencyGraph, useIncidents, useRiskScores, useSLOStatus,
  useRefreshDashboard,
  type ServiceNode,
} from '../api';

interface ServiceDetail {
  name: string;
  namespace?: string;
  criticality?: string;
  current_slo?: number;
  slo_target?: number;
  error_budget_remaining?: number;
  incident_count_24h: number;
  deployment_count_24h: number;
}

const Dashboard: React.FC = () => {
  const { data: graphData, isLoading: graphLoading, isError: graphError, refetch: refetchGraph } = useDependencyGraph();
  const { data: incidents, isLoading: incidentsLoading, isError: incidentsError } = useIncidents({ limit: 50 });
  const { data: riskScores, isError: riskError } = useRiskScores();
  const { data: sloStatus, isError: sloError } = useSLOStatus();
  const refreshDashboard = useRefreshDashboard();
  const toast = useToast();

  const [selectedService, setSelectedService] = useState<ServiceDetail | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<string[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const hasErrors = graphError || incidentsError || riskError || sloError;

  const handleRefresh = useCallback(async () => {
    try {
      await refreshDashboard.mutateAsync();
      setLastUpdated(new Date());
      toast.success('Dashboard refreshed');
    } catch {
      toast.error('Failed to refresh dashboard');
    }
  }, [refreshDashboard, toast]);

  const handleNodeClick = useCallback((node: ServiceNode) => {
    setSelectedService(node);
    setHighlightedNodes([node.id]);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case 'r':
          if (!e.metaKey && !e.ctrlKey) {
            e.preventDefault();
            handleRefresh();
          }
          break;
        case 'Escape':
          if (selectedService) {
            setSelectedService(null);
          }
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleRefresh, selectedService]);

  const stats = useMemo(() => {
    const activeIncidents = (incidents ?? []).filter(
      i => i.status !== 'resolved' && i.status !== 'closed'
    );
    const criticalIncidents = activeIncidents.filter(i => i.severity === 'sev1');
    const highRiskServices = (riskScores?.scores ?? []).filter(
      r => r.risk_level === 'high' || r.risk_level === 'critical'
    );
    const allSlos = sloStatus?.services?.flatMap(s => s.slos) ?? [];
    const availabilitySlos = allSlos.filter(s => s.name === 'availability');
    const avgSlo = availabilitySlos.length
      ? availabilitySlos.reduce((sum, s) => sum + s.current, 0) / availabilitySlos.length
      : null;

    return {
      totalServices: graphData?.nodes?.length ?? 0,
      activeIncidents: activeIncidents.length,
      criticalIncidents: criticalIncidents.length,
      highRiskServices: highRiskServices.length,
      avgSlo: avgSlo,
      totalDeployments24h: (riskScores?.scores ?? []).reduce((sum, r) => sum + ((r as any).deployment_count_24h ?? 0), 0),
    };
  }, [incidents, riskScores, sloStatus, graphData]);

  const isLoading = graphLoading || incidentsLoading;

  if (isLoading && !graphData) {
    return (
      <div className="page-loading" role="status" aria-label="Loading dashboard">
        <div className="loading-spinner" aria-hidden="true"></div>
        <p>Loading dashboard...</p>
      </div>
    );
  }

  if (hasErrors) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <h1 className="page-title">Dashboard</h1>
            <p className="page-subtitle">Real-time change intelligence and service health overview</p>
          </div>
          <div className="header-actions">
            <button
              onClick={handleRefresh}
              disabled={refreshDashboard.isPending}
              className="btn btn-secondary"
            >
              Refresh
            </button>
          </div>
        </div>
        <ErrorState
          title="Some dashboard data could not be loaded"
          message="One or more services are unreachable. Showing what data is available."
          onRetry={() => refreshDashboard.mutate()}
        />
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Real-time change intelligence and service health overview</p>
        </div>
        <div className="header-actions">
          <div className="status-indicator" role="status" aria-live="polite">
            <span className="status-dot" aria-hidden="true"></span>
            <span className="status-text">
              {stats.activeIncidents > 0
                ? `${stats.activeIncidents} Active Incident${stats.activeIncidents > 1 ? 's' : ''}`
                : 'All Systems Operational'}
            </span>
          </div>
          <div className="last-updated" aria-live="polite">
            <span>Last updated {lastUpdated.toLocaleTimeString()}</span>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshDashboard.isPending}
            className="btn btn-secondary"
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="summary-stats-bar" role="region" aria-label="Dashboard summary statistics">
        <div className="summary-stat">
          <div className="summary-stat-icon" style={{ color: 'var(--color-brand-primary)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
              <line x1="12" y1="22.08" x2="12" y2="12" />
            </svg>
          </div>
          <div className="summary-stat-content">
            <span className="summary-stat-value">{stats.totalServices}</span>
            <span className="summary-stat-label">Services</span>
          </div>
        </div>

        <div className="summary-stat">
          <div className="summary-stat-icon" style={{ color: stats.activeIncidents > 0 ? 'var(--color-error)' : 'var(--color-success)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <div className="summary-stat-content">
            <span className="summary-stat-value">{stats.activeIncidents}</span>
            <span className="summary-stat-label">Active Incidents</span>
          </div>
        </div>

        <div className="summary-stat">
          <div className="summary-stat-icon" style={{ color: stats.criticalIncidents > 0 ? 'var(--color-sev1)' : 'var(--color-text-quaternary)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <div className="summary-stat-content">
            <span className="summary-stat-value">{stats.criticalIncidents}</span>
            <span className="summary-stat-label">SEV1 Critical</span>
          </div>
        </div>

        <div className="summary-stat">
          <div className="summary-stat-icon" style={{ color: stats.highRiskServices > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <div className="summary-stat-content">
            <span className="summary-stat-value">{stats.highRiskServices}</span>
            <span className="summary-stat-label">High Risk</span>
          </div>
        </div>

        <div className="summary-stat">
          <div className="summary-stat-icon" style={{ color: stats.avgSlo == null ? 'var(--color-text-quaternary)' : stats.avgSlo >= 99 ? 'var(--color-success)' : stats.avgSlo >= 95 ? 'var(--color-warning)' : 'var(--color-error)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
          </div>
          <div className="summary-stat-content">
            <span className="summary-stat-value">{stats.avgSlo == null ? '\u2014' : `${stats.avgSlo.toFixed(2)}%`}</span>
            <span className="summary-stat-label">Avg SLO</span>
          </div>
        </div>
      </div>

      <section className="dashboard-section" aria-labelledby="dependency-graph-title">
        <DependencyGraph
          data={graphData ?? undefined}
          onNodeClick={handleNodeClick}
          highlightedNodes={highlightedNodes}
          width={1200}
          height={500}
          isLoading={graphLoading}
          showDetailPanel={false}
        />
      </section>

      <div className="dashboard-grid" role="region" aria-label="Risk and SLO metrics">
        <section className="dashboard-section" aria-labelledby="risk-scores-title">
            <div className="risk-cards-grid">
            {riskScores?.scores?.map((risk) => (
              <RiskScoreCard
                key={risk.service}
                service={risk.service}
                namespace={risk.namespace}
                riskScore={risk.risk_score}
                riskLevel={risk.risk_level}
                factors={risk.factors}
                lastDeployment={risk.last_deployment}
                lastDeploymentTime={risk.last_deployment_time}
                onClick={() => setSelectedService({
                  name: risk.service,
                  namespace: risk.namespace,
                  incident_count_24h: risk.incident_count_24h ?? 0,
                  deployment_count_24h: risk.deployment_count_24h ?? 0,
                })}
              />
            ))}
            {(!riskScores?.scores || riskScores.scores.length === 0) && (
              <div className="empty-state card" role="status">
                <p className="empty-text">No deployment risk data available</p>
              </div>
            )}
          </div>
        </section>

        <section className="dashboard-section" aria-labelledby="slo-burn-title">
          <div className="slo-charts-grid">
            {sloStatus?.services?.map((svc) => (
              <div key={svc.name} className="slo-chart-wrapper card">
                <SLOBurnChart
                  data={svc.slos.map(slo => ({
                    timestamp: sloStatus.updated_at,
                    service: svc.name,
                    slo_name: slo.name,
                    target: slo.target,
                    actual: slo.current,
                    burn_rate: slo.burn_rate,
                    error_budget_remaining: slo.error_budget_remaining,
                  }))}
                  service={svc.name}
                  height={280}
                />
              </div>
            ))}
            {(!sloStatus?.services || sloStatus.services.length === 0) && (
              <div className="empty-state card" role="status">
                <p className="empty-text">No SLO data available</p>
              </div>
            )}
          </div>
        </section>
      </div>

      <section className="dashboard-section full-width" aria-labelledby="incident-timeline-title">
        <IncidentTimeline
          incidents={incidents ?? []}
          isLoading={incidentsLoading}
        />
      </section>

      {selectedService && (
        <div
          className="modal-overlay"
          onClick={() => setSelectedService(null)}
          role="dialog"
          aria-modal="true"
        >
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{selectedService.name}</h3>
              <button className="modal-close" onClick={() => setSelectedService(null)}>X</button>
            </div>
            <div className="modal-body">
              <div className="detail-grid">
                <div className="detail-item">
                  <label>Namespace</label>
                  <span>{selectedService.namespace || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <label>Criticality</label>
                  <span>{selectedService.criticality || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <label>Current SLO</label>
                  <span>
                    {selectedService.current_slo != null
                      ? `${selectedService.current_slo.toFixed(2)}% / ${selectedService.slo_target}%`
                      : 'N/A'}
                  </span>
                </div>
                <div className="detail-item">
                  <label>Error Budget</label>
                  <span>
                    {selectedService.error_budget_remaining != null
                      ? `${selectedService.error_budget_remaining.toFixed(1)}%`
                      : 'N/A'}
                  </span>
                </div>
                <div className="detail-item">
                  <label>Incidents (24h)</label>
                  <span>{selectedService.incident_count_24h}</span>
                </div>
                <div className="detail-item">
                  <label>Deployments (24h)</label>
                  <span>{selectedService.deployment_count_24h}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
