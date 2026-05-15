import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import './App.css';
import DependencyGraph from './components/DependencyGraph';
import IncidentTimeline from './components/IncidentTimeline';
import RiskScoreCard from './components/RiskScoreCard';
import SLOBurnChart from './components/SLOBurnChart';

interface GraphData {
  nodes: Array<{ 
    id: string; 
    name: string; 
    namespace?: string;
    criticality?: string;
    slo_target?: number;
    current_slo?: number;
    error_budget_remaining?: number;
    incident_count_24h?: number;
    deployment_count_24h?: number;
    dependencies?: string[];
  }>;
  links: Array<{ source: string; target: string }>;
}

interface Incident {
  id: string;
  title: string;
  severity: string;
  status: string;
  affected_service: string;
  detected_at: string;
}

interface RiskScoreResponse {
  scores: Array<{
    service: string;
    risk_score: number;
    risk_level: string;
    factors: Record<string, number>;
    last_deployment?: string;
    last_deployment_time?: string;
  }>;
}

interface SLODataResponse {
  services: Array<{
    name: string;
    namespace: string;
    value: number;
    target: number;
    criticality: number;
    current_slo: number;
    slo_target: number;
    error_budget_remaining: number;
    incident_count_24h: number;
    deployment_count_24h: number;
  }>;
}

interface IncidentsResponse {
  incidents: Incident[];
}

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

const apiBase = import.meta.env.VITE_API_BASE || 'http://localhost:8002';

function Dashboard() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [incidents, setIncidents] = useState<IncidentsResponse>({ incidents: [] });
  const [riskScores, setRiskScores] = useState<RiskScoreResponse | null>(null);
  const [sloData, setSloData] = useState<SLODataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedService, setSelectedService] = useState<ServiceDetail | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<string[]>([]);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      const [graphRes, incidentsRes, riskRes, sloRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/graph/dependency`).catch(() => null),
        fetch(`${apiBase}/api/v1/incidents?limit=50`).catch(() => null),
        fetch(`${apiBase}/api/v1/risk/current`).catch(() => null),
        fetch(`${apiBase}/api/v1/slo/burn-rate?hours=24`).catch(() => null),
      ]);

      if (graphRes?.ok) setGraphData(await graphRes.json());
      if (incidentsRes?.ok) setIncidents(await incidentsRes.json());
      if (riskRes?.ok) setRiskScores(await riskRes.json());
      if (sloRes?.ok) setSloData(await sloRes.json());
      
      setError(null);
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
      setError('Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  const handleNodeClick = (node: any) => {
    setSelectedService(node);
    setHighlightedNodes([node.id, ...node.dependencies || []]);
  };

  if (loading) {
    return (
      <div className="app-loading">
        <div className="spinner"></div>
        <p>Loading dashboard...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-error">
        <h2>Error</h2>
        <p>{error}</p>
        <button onClick={fetchDashboardData} className="btn btn-primary">Retry</button>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>ChangeTrace</h1>
          <span className="header-subtitle">Change Intelligence Platform</span>
        </div>
        <div className="header-right">
          <div className="status-indicator">
            <span className="status-dot healthy"></span>
            <span>All Systems Operational</span>
          </div>
          <button className="btn btn-secondary" onClick={fetchDashboardData}>
            🔄 Refresh
          </button>
        </div>
      </header>

      <main className="app-main">
        {/* Top Row - Dependency Graph */}
        <section className="dashboard-section">
          <div className="section-header">
            <h2>Service Dependency Graph</h2>
            <p className="section-description">
              Live topology from OpenTelemetry traces. Click a service to see details.
            </p>
          </div>
          <DependencyGraph
            data={graphData}
            onNodeClick={handleNodeClick}
            highlightedNodes={highlightedNodes}
            width={1200}
            height={500}
          />
        </section>

        {/* Middle Row - Risk Scores & SLO Burn */}
        <div className="dashboard-grid">
          <section className="dashboard-section">
            <div className="section-header">
              <h2>Deployment Risk Scores</h2>
              <p className="section-description">
                ML-powered risk assessment for pending deployments.
              </p>
            </div>
            <div className="risk-cards-grid">
              {riskScores?.scores?.map((risk: any) => (
                <RiskScoreCard
                  key={risk.service}
                  service={risk.service}
                  riskScore={risk.risk_score}
                  riskLevel={risk.risk_level}
                  factors={risk.factors}
                  lastDeployment={risk.last_deployment}
                  lastDeploymentTime={risk.last_deployment_time}
                  onClick={() => setSelectedService(risk.service as unknown as ServiceDetail)}
                />
              ))}
              {(!riskScores?.scores || riskScores.scores.length === 0) && (
                <div className="empty-state">
                  <p>No deployment risk data available</p>
                </div>
              )}
            </div>
          </section>

          <section className="dashboard-section">
            <div className="section-header">
              <h2>SLO Burn Rate</h2>
              <p className="section-description">
                Error budget consumption over the last 24 hours.
              </p>
            </div>
            <div className="slo-charts-grid">
              {sloData?.services?.map((svc: any) => (
                <div key={svc.name} className="slo-chart-wrapper">
                  <h3>{svc.name}</h3>
                  <SLOBurnChart
                    data={sloData}
                    service={svc.name}
                    height={250}
                  />
                </div>
              ))}
              {(!sloData?.services || sloData.services.length === 0) && (
                <div className="empty-state">
                  <p>No SLO data available</p>
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Bottom Row - Incident Timeline */}
        <section className="dashboard-section full-width">
          <div className="section-header">
            <h2>Incident Timeline</h2>
            <p className="section-description">
              Recent incidents with correlation results and remediation status.
            </p>
          </div>
          <IncidentTimeline
            incidents={incidents.incidents || []}
            onIncidentClick={(incident) => console.log('Incident clicked:', incident)}
          />
        </section>
      </main>

      {/* Service Detail Modal */}
      {selectedService && (
        <div className="modal-overlay" onClick={() => setSelectedService(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{selectedService.name}</h3>
              <button className="modal-close" onClick={() => setSelectedService(null)}>×</button>
            </div>
            <div className="modal-body">
              <div className="detail-grid">
                <div className="detail-item">
                  <label>Namespace</label>
                  <span>{selectedService.namespace || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <label>Criticality</label>
                  <span className={`criticality-${selectedService.criticality?.toLowerCase() || 'unknown'}`}>
                    {selectedService.criticality || 'N/A'}
                  </span>
                </div>
                <div className="detail-item">
                  <label>Current SLO</label>
                  <span>
                    {selectedService.current_slo !== undefined 
                      ? `${selectedService.current_slo.toFixed(2)}% / ${selectedService.slo_target}%`
                      : 'N/A'}
                  </span>
                </div>
                <div className="detail-item">
                  <label>Error Budget</label>
                  <span>
                    {selectedService.error_budget_remaining !== undefined
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
            <div className="modal-footer">
              <button className="btn btn-primary" onClick={() => setSelectedService(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Dashboard />} />
      </Routes>
    </Router>
  );
}

export default App;