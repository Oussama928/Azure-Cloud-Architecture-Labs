import { describe, it, expect } from 'vitest';

describe('Hook exports', () => {
  it('exports all hooks', async () => {
    const hooks = await import('../api/hooks');
    expect(typeof hooks.useDependencyGraph).toBe('function');
    expect(typeof hooks.useBlastRadius).toBe('function');
    expect(typeof hooks.useIncidents).toBe('function');
    expect(typeof hooks.useIncidentDetail).toBe('function');
    expect(typeof hooks.useSLOBurnRate).toBe('function');
    expect(typeof hooks.useSLOStatus).toBe('function');
    expect(typeof hooks.useRiskScores).toBe('function');
    expect(typeof hooks.useRiskHistory).toBe('function');
    expect(typeof hooks.useCorrelationAccuracy).toBe('function');
    expect(typeof hooks.useCorrelationAccuracyHistory).toBe('function');
    expect(typeof hooks.useChanges).toBe('function');
    expect(typeof hooks.useHealth).toBe('function');
    expect(typeof hooks.useReadiness).toBe('function');
    expect(typeof hooks.useRefreshDashboard).toBe('function');
  });
});

describe('Barrel exports', () => {
  it('re-exports everything from api/index.ts', async () => {
    const mod = await import('../api');
    expect(mod.api).toBeDefined();
    expect(mod.graphApi).toBeDefined();
    expect(typeof mod.useDependencyGraph).toBe('function');
  });
});
