import React, { useState, useMemo } from 'react';
import './IncidentTimeline.css';

interface Incident {
  incident_id: string;
  title: string;
  severity: string;
  status: string;
  affected_service: string;
  detected_at: string;
  resolved_at?: string;
  root_cause_candidate?: string;
  confidence?: number;
  remediation_action?: string;
}

interface IncidentTimelineProps {
  incidents: Incident[];
  onIncidentClick?: (incident: Incident) => void;
  selectedIncidentId?: string;
  isLoading?: boolean;
}

const SEVERITY_LABELS: Record<string, string> = {
  sev1: 'SEV1 - Critical',
  sev2: 'SEV2 - Major',
  sev3: 'SEV3 - Minor',
  sev4: 'SEV4 - Low',
};

const STATUS_LABELS: Record<string, string> = {
  open: 'Open',
  investigating: 'Investigating',
  root_cause_identified: 'Root Cause Identified',
  remediating: 'Remediating',
  verifying: 'Verifying',
  resolved: 'Resolved',
  closed: 'Closed',
  unactioned: 'Unactioned',
};

const STATUS_COLORS: Record<string, string> = {
  open: 'var(--color-status-open)',
  investigating: 'var(--color-status-investigating)',
  root_cause_identified: 'var(--color-status-root-cause)',
  remediating: 'var(--color-status-remediating)',
  verifying: 'var(--color-status-verifying)',
  resolved: 'var(--color-status-resolved)',
  closed: 'var(--color-status-closed)',
  unactioned: 'var(--color-status-unactioned)',
};

const SEVERITY_COLORS: Record<string, string> = {
  sev1: 'var(--color-sev1)',
  sev2: 'var(--color-sev2)',
  sev3: 'var(--color-sev3)',
  sev4: 'var(--color-sev4)',
};

const IncidentTimeline: React.FC<IncidentTimelineProps> = ({
  incidents,
  onIncidentClick,
  selectedIncidentId,
  isLoading = false,
}) => {
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredIncidents = useMemo(() => {
    return incidents.filter(incident => {
      if (filterSeverity !== 'all' && incident.severity !== filterSeverity) return false;
      if (filterStatus !== 'all' && incident.status !== filterStatus) return false;
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!incident.title.toLowerCase().includes(query) &&
            !incident.incident_id.toLowerCase().includes(query) &&
            !incident.affected_service.toLowerCase().includes(query)) {
          return false;
        }
      }
      return true;
    });
  }, [incidents, filterSeverity, filterStatus, searchQuery]);

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getDuration = (start: string, end?: string) => {
    const startTime = new Date(start).getTime();
    const endTime = end ? new Date(end).getTime() : Date.now();
    const diffMs = endTime - startTime;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    
    if (diffHours > 0) {
      return `${diffHours}h ${diffMins % 60}m`;
    }
    return `${diffMins}m`;
  };

  const getStatusBgColor = (status: string) => {
    return STATUS_COLORS[status] || 'var(--color-bg-tertiary)';
  };

  if (isLoading) {
    return (
      <div className="incident-timeline skeleton-loading" aria-busy="true">
        <div className="skeleton" style={{ height: '24px', width: '30%' }} />
        <div className="skeleton" style={{ height: '40px', width: '100%', marginTop: '16px' }} />
        <div className="skeleton" style={{ height: '40px', width: '100%', marginTop: '16px' }} />
        <div className="skeleton" style={{ height: '40px', width: '100%', marginTop: '16px' }} />
        <div className="skeleton" style={{ height: '40px', width: '100%', marginTop: '16px' }} />
        <div className="skeleton" style={{ height: '40px', width: '100%', marginTop: '16px' }} />
      </div>
    );
  }

  return (
    <div className="incident-timeline">
      <div className="timeline-header">
        <div className="header-content">
          <h2 className="timeline-title">Incident Timeline</h2>
          <p className="timeline-subtitle">
            Recent incidents with correlation results and remediation status
          </p>
        </div>
        <div className="timeline-filters">
          <div className="search-wrapper">
            <svg className="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              placeholder="Search incidents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input search-input"
              aria-label="Search incidents"
            />
          </div>
          <select 
            value={filterSeverity} 
            onChange={(e) => setFilterSeverity(e.target.value)} 
            className="input select filter-select"
            aria-label="Filter by severity"
          >
            <option value="all">All Severities</option>
            <option value="sev1">SEV1 - Critical</option>
            <option value="sev2">SEV2 - Major</option>
            <option value="sev3">SEV3 - Minor</option>
            <option value="sev4">SEV4 - Low</option>
          </select>
          <select 
            value={filterStatus} 
            onChange={(e) => setFilterStatus(e.target.value)} 
            className="input select filter-select"
            aria-label="Filter by status"
          >
            <option value="all">All Statuses</option>
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="root_cause_identified">Root Cause Identified</option>
            <option value="remediating">Remediating</option>
            <option value="verifying">Verifying</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
            <option value="unactioned">Unactioned</option>
          </select>
        </div>
      </div>

      <div className="timeline-stats" role="status" aria-live="polite">
        <div className="stat-card">
          <span className="stat-value">{filteredIncidents.length}</span>
          <span className="stat-label">Total Incidents</span>
        </div>
        <div className="stat-card">
          <span className="stat-value stat-sev1">{filteredIncidents.filter(i => i.severity === 'sev1').length}</span>
          <span className="stat-label">SEV1</span>
        </div>
        <div className="stat-card">
          <span className="stat-value stat-resolved">{filteredIncidents.filter(i => i.status === 'resolved' || i.status === 'closed').length}</span>
          <span className="stat-label">Resolved</span>
        </div>
        <div className="stat-card">
          <span className="stat-value stat-active">{filteredIncidents.filter(i => i.status === 'open' || i.status === 'investigating').length}</span>
          <span className="stat-label">Active</span>
        </div>
      </div>

      <div className="timeline-list" role="list" aria-label="Incidents">
        {filteredIncidents.length === 0 ? (
          <div className="timeline-empty" role="status">
            <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p className="empty-text">No incidents match the current filters</p>
            <p className="empty-subtext">Try adjusting your search or filter criteria</p>
          </div>
        ) : (
          filteredIncidents.map((incident, index) => (
            <article
              key={incident.incident_id}
              className={`timeline-item ${selectedIncidentId === incident.incident_id ? 'selected' : ''}`}
              onClick={() => onIncidentClick?.(incident)}
              role="listitem"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onIncidentClick?.(incident); }}}
              aria-selected={selectedIncidentId === incident.incident_id}
              aria-label={`Incident ${incident.incident_id}: ${incident.title}`}
            >
              <div className="timeline-marker">
                <div 
                  className="severity-dot" 
                  style={{ backgroundColor: SEVERITY_COLORS[incident.severity] || 'var(--color-text-quaternary)' }}
                  aria-hidden="true"
                ></div>
                <div className="timeline-line" aria-hidden="true"></div>
              </div>
              <div className="timeline-content">
                <div className="incident-header">
                  <span className="incident-id">{incident.incident_id}</span>
                  <span 
                    className="status-badge"
                    style={{
                      backgroundColor: `${STATUS_COLORS[incident.status] || 'var(--color-bg-tertiary)'}20`,
                      color: STATUS_COLORS[incident.status] || 'var(--color-text-secondary)',
                      borderColor: `${STATUS_COLORS[incident.status] || 'var(--color-border-primary)'}40`,
                    }}
                  >
                    {STATUS_LABELS[incident.status] || incident.status}
                  </span>
                </div>
                <h3 className="incident-title">{incident.title}</h3>
                <div className="incident-meta">
                  <span className="meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                      <line x1="12" y1="22.08" x2="12" y2="12" />
                    </svg>
                    <span><strong>Service:</strong> {incident.affected_service}</span>
                  </span>
                  <span className="meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 16 14" />
                    </svg>
                    <span><strong>Detected:</strong> {formatDate(incident.detected_at)}</span>
                  </span>
                  <span className="meta-item">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <span><strong>Duration:</strong> {getDuration(incident.detected_at, incident.resolved_at)}</span>
                  </span>
                </div>
                {incident.root_cause_candidate && (
                  <div className="incident-root-cause">
                    <div className="root-cause-header">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="16" x2="12" y2="12" />
                        <line x1="12" y1="8" x2="12.01" y2="8" />
                      </svg>
                      <span className="root-cause-label">Root Cause Candidate</span>
                    </div>
                    <span className="root-cause-value">{incident.root_cause_candidate}</span>
                    {incident.confidence !== undefined && (
                      <span className="confidence-badge" style={{ backgroundColor: 'var(--color-brand-primary)20', color: 'var(--color-brand-primary)' }}>
                        {Math.round(incident.confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                )}
                {incident.remediation_action && (
                  <div className="incident-remediation">
                    <div className="remediation-header">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                      </svg>
                      <span className="remediation-label">Remediation Action</span>
                    </div>
                    <span className="remediation-value">{incident.remediation_action.replace(/_/g, ' ')}</span>
                  </div>
                )}
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
};

export default IncidentTimeline;