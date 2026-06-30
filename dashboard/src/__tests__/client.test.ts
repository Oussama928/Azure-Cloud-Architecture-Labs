import { describe, it, expect } from 'vitest';
import type { ServiceNode, Incident, RiskScore, ChangeEvent } from '../api/client';

describe('API client exports', () => {
  it('exports api singleton', async () => {
    const { api } = await import('../api/client');
    expect(api).toBeDefined();
    expect(typeof api.get).toBe('function');
    expect(typeof api.post).toBe('function');
    expect(typeof api.put).toBe('function');
    expect(typeof api.delete).toBe('function');
  });

  it('exports graphApi', async () => {
    const { graphApi } = await import('../api/client');
    expect(typeof graphApi.getDependencyGraph).toBe('function');
    expect(typeof graphApi.getBlastRadius).toBe('function');
  });

  it('exports incidentsApi', async () => {
    const { incidentsApi } = await import('../api/client');
    expect(typeof incidentsApi.getIncidents).toBe('function');
    expect(typeof incidentsApi.getIncidentDetail).toBe('function');
  });

  it('exports sloApi', async () => {
    const { sloApi } = await import('../api/client');
    expect(typeof sloApi.getBurnRate).toBe('function');
    expect(typeof sloApi.getStatus).toBe('function');
  });

  it('exports riskApi', async () => {
    const { riskApi } = await import('../api/client');
    expect(typeof riskApi.getHistory).toBe('function');
    expect(typeof riskApi.getCurrent).toBe('function');
  });

  it('exports correlationApi', async () => {
    const { correlationApi } = await import('../api/client');
    expect(typeof correlationApi.getAccuracy).toBe('function');
    expect(typeof correlationApi.getAccuracyHistory).toBe('function');
  });

  it('exports changesApi', async () => {
    const { changesApi } = await import('../api/client');
    expect(typeof changesApi.getChanges).toBe('function');
  });

  it('exports healthApi', async () => {
    const { healthApi } = await import('../api/client');
    expect(typeof healthApi.check).toBe('function');
    expect(typeof healthApi.ready).toBe('function');
  });
});

describe('Type definitions', () => {
  it('exports ServiceNode interface fields', () => {
    const node: ServiceNode = {
      id: 'test',
      name: 'test-service',
      criticality: 'high',
      incident_count_24h: 0,
      deployment_count_24h: 0,
    };
    expect(node.id).toBe('test');
  });

  it('exports Incident interface fields', () => {
    const incident: Incident = {
      incident_id: 'INC-001',
      title: 'Test',
      severity: 'sev2',
      status: 'open',
      affected_service: 'svc',
      detected_at: '2024-01-01T00:00:00Z',
    };
    expect(incident.incident_id).toBe('INC-001');
  });

  it('exports RiskScore interface fields', () => {
    const risk: RiskScore = {
      service: 'svc',
      risk_score: 0.5,
      risk_level: 'medium',
      factors: {},
    };
    expect(risk.risk_level).toBe('medium');
  });

  it('exports ChangeEvent interface fields', () => {
    const change: ChangeEvent = {
      eventId: 'evt-1',
      serviceName: 'svc',
      changeType: 'code_deployment',
      source: 'github',
      timestamp: '2024-01-01T00:00:00Z',
    };
    expect(change.changeType).toBe('code_deployment');
  });
});
