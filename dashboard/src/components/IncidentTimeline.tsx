import React, { useState } from 'react';
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
}

const IncidentTimeline: React.FC<IncidentTimelineProps> = ({
  incidents,
  onIncidentClick,
  selectedIncidentId,
}) => {
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredIncidents = incidents.filter(incident => {
    if (filterSeverity !== 'all' && incident.severity !== filterSeverity) return false;
    if (filterStatus !== 'all' && incident.status !== filterStatus) return false;
    if (searchQuery && !incident.title.toLowerCase().includes(searchQuery.toLowerCase()) &&
        !incident.incident_id.toLowerCase().includes(searchQuery.toLowerCase()) &&
        !incident.affected_service.toLowerCase().includes(searchQuery.toLowerCase())) {
      return false;
    }
    return true;
  });

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'sev1': return 'bg-red-600';
      case 'sev2': return 'bg-orange-500';
      case 'sev3': return 'bg-yellow-500';
      case 'sev4': return 'bg-blue-500';
      default: return 'bg-gray-500';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'open': return 'bg-red-100 text-red-800';
      case 'investigating': return 'bg-yellow-100 text-yellow-800';
      case 'root_cause_identified': return 'bg-blue-100 text-blue-800';
      case 'remediating': return 'bg-purple-100 text-purple-800';
      case 'verifying': return 'bg-indigo-100 text-indigo-800';
      case 'resolved': return 'bg-green-100 text-green-800';
      case 'closed': return 'bg-gray-100 text-gray-800';
      case 'unactioned': return 'bg-orange-100 text-orange-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

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

  return (
    <div className="incident-timeline">
      <div className="timeline-header">
        <h3>Incident Timeline</h3>
        <div className="timeline-filters">
          <input
            type="text"
            placeholder="Search incidents..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
          <select value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)} className="filter-select">
            <option value="all">All Severities</option>
            <option value="sev1">SEV1 - Critical</option>
            <option value="sev2">SEV2 - Major</option>
            <option value="sev3">SEV3 - Minor</option>
            <option value="sev4">SEV4 - Low</option>
          </select>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="filter-select">
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

      <div className="timeline-stats">
        <div className="stat-card">
          <span className="stat-value">{filteredIncidents.length}</span>
          <span className="stat-label">Total Incidents</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{filteredIncidents.filter(i => i.severity === 'sev1').length}</span>
          <span className="stat-label">SEV1</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{filteredIncidents.filter(i => i.status === 'resolved' || i.status === 'closed').length}</span>
          <span className="stat-label">Resolved</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{filteredIncidents.filter(i => i.status === 'open' || i.status === 'investigating').length}</span>
          <span className="stat-label">Active</span>
        </div>
      </div>

      <div className="timeline-list">
        {filteredIncidents.length === 0 ? (
          <div className="timeline-empty">
            <p>No incidents match the current filters.</p>
          </div>
        ) : (
          filteredIncidents.map((incident, index) => (
            <div
              key={incident.incident_id}
              className={`timeline-item ${selectedIncidentId === incident.incident_id ? 'selected' : ''}`}
              onClick={() => onIncidentClick?.(incident)}
            >
              <div className="timeline-marker">
                <div className={`severity-dot ${getSeverityColor(incident.severity)}`}></div>
                <div className="timeline-line"></div>
              </div>
              <div className="timeline-content">
                <div className="incident-header">
                  <span className="incident-id">{incident.incident_id}</span>
                  <span className={`status-badge ${getStatusColor(incident.status)}`}>
                    {incident.status.replace(/_/g, ' ').toUpperCase()}
                  </span>
                </div>
                <h4 className="incident-title">{incident.title}</h4>
                <div className="incident-meta">
                  <span className="meta-item">
                    <strong>Service:</strong> {incident.affected_service}
                  </span>
                  <span className="meta-item">
                    <strong>Detected:</strong> {formatDate(incident.detected_at)}
                  </span>
                  <span className="meta-item">
                    <strong>Duration:</strong> {getDuration(incident.detected_at, incident.resolved_at)}
                  </span>
                </div>
                {incident.root_cause_candidate && (
                  <div className="incident-root-cause">
                    <span className="root-cause-label">Root Cause Candidate:</span>
                    <span className="root-cause-value">{incident.root_cause_candidate}</span>
                    {incident.confidence !== undefined && (
                      <span className="confidence-badge">
                        {Math.round(incident.confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                )}
                {incident.remediation_action && (
                  <div className="incident-remediation">
                    <span className="remediation-label">Action:</span>
                    <span className="remediation-value">{incident.remediation_action.replace(/_/g, ' ')}</span>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default IncidentTimeline;