import { useEffect, useRef, useState } from 'react';
import SLOBurnChart from '../components/SLOBurnChart';
import ErrorState from '../components/ErrorState';
import { useSLOStatus, useSLOBurnRate } from '../api';

const RANGE_OPTIONS: Array<{ label: string; hours: number; interval_minutes: number }> = [
  { label: '15m', hours: 0.25, interval_minutes: 5 },
  { label: '1h', hours: 1, interval_minutes: 5 },
  { label: '3h', hours: 3, interval_minutes: 5 },
  { label: '6h', hours: 6, interval_minutes: 10 },
  { label: '12h', hours: 12, interval_minutes: 15 },
  { label: '24h', hours: 24, interval_minutes: 15 },
  { label: '7d', hours: 168, interval_minutes: 60 },
];

const SLO: React.FC = () => {
  const [range, setRange] = useState(RANGE_OPTIONS[5]);
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { data: sloStatus, isLoading: statusLoading, isError: statusError, refetch: refetchStatus } = useSLOStatus();
  const { data: burnRateData } = useSLOBurnRate({ hours: range.hours, interval_minutes: range.interval_minutes });

  useEffect(() => {
    const onOutsideClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onOutsideClick);
    return () => document.removeEventListener('mousedown', onOutsideClick);
  }, []);

  if (statusError) {
    return (
      <div className="dashboard-page">
        <div className="page-header">
          <div className="header-content">
            <h1 className="page-title">SLO Burn Rate</h1>
            <p className="page-subtitle">Service Level Objective tracking, error budgets, and burn rate monitoring</p>
          </div>
        </div>
        <ErrorState
          title="Unable to load SLO data"
          message="The SLO service could not be reached. Please try again."
          onRetry={() => refetchStatus()}
        />
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">SLO Burn Rate</h1>
          <p className="page-subtitle">Service Level Objective tracking, error budgets, and burn rate monitoring</p>
        </div>
        <div className="range-dropdown" ref={dropdownRef}>
          <button
            type="button"
            className="range-dropdown-toggle"
            aria-haspopup="listbox"
            aria-expanded={open}
            onClick={() => setOpen((prev) => !prev)}
          >
            <span>Last {range.label}</span>
            <svg className="range-dropdown-caret" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M6 8l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {open && (
            <ul className="range-dropdown-menu" role="listbox" aria-label="Time range">
              {RANGE_OPTIONS.map((option) => (
                <li key={option.label} role="option" aria-selected={option.hours === range.hours}>
                  <button
                    type="button"
                    className={`range-dropdown-item${option.hours === range.hours ? ' active' : ''}`}
                    onClick={() => {
                      setRange(option);
                      setOpen(false);
                    }}
                  >
                    Last {option.label}
                    {option.hours === range.hours && (
                      <svg className="range-dropdown-check" viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <path d="M5 10l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="summary-stats-bar" role="region" aria-label="SLO summary">
        {sloStatus?.services?.map((svc) => {
          if (svc.slos.length === 0) {
            return null; // no real SLO data — don't fabricate a stat
          }
          const pctSlos = svc.slos.filter((s) => !s.name.toLowerCase().includes('latency'));
          const avgCurrent = pctSlos.length
            ? pctSlos.reduce((sum, s) => sum + s.current, 0) / pctSlos.length
            : 0;
          const avgTarget = pctSlos.length
            ? pctSlos.reduce((sum, s) => sum + s.target, 0) / pctSlos.length
            : 0;
          const isHealthy = avgCurrent >= avgTarget;
          return (
            <div key={svc.name} className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ color: isHealthy ? 'var(--color-success)' : 'var(--color-error)' }}>
                  {avgCurrent.toFixed(2)}%
                </span>
                <span className="summary-stat-label">{svc.name}</span>
              </div>
            </div>
          );
        })}
        {(!sloStatus?.services || sloStatus.services.length === 0) && !statusLoading && (
          <div className="summary-stat">
            <div className="summary-stat-content">
              <span className="summary-stat-label">No SLO data available</span>
            </div>
          </div>
        )}
      </div>

      <section className="dashboard-section full-width" aria-labelledby="slo-charts-title">
          {(() => {
            const services = sloStatus?.services ?? [];
            const entries = services.flatMap((svc) =>
              svc.slos.map((slo) => ({ service: svc.name, slo }))
            );
            const byName = new Map<string, Array<{ service: string; slo: typeof entries[number]['slo'] }>>();
            for (const entry of entries) {
              const arr = byName.get(entry.slo.name) ?? [];
              arr.push(entry);
              byName.set(entry.slo.name, arr);
            }
            const groupNames = [...byName.keys()].sort((a, b) => {
              const rank = (name: string) => (name.toLowerCase().includes('latency') ? 0 : 1);
              return rank(a) - rank(b) || a.localeCompare(b);
            });
            const prettyName = (name: string) =>
              name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

            return (
              <>
                {groupNames.map((name) => (
                  <div key={name} className="slo-group">
                    <h2 className="slo-group-title">{prettyName(name)}</h2>
                    <div className="slo-charts-grid">
                      {byName.get(name)!.map(({ service, slo }) => {
                        const svcBurn = (burnRateData ?? []).filter(
                          (d) => d.service === service && d.slo_name === slo.name
                        );
                        const data = svcBurn.length > 0
                          ? svcBurn
                          : [{
                              timestamp: sloStatus?.updated_at ?? '',
                              service,
                              slo_name: slo.name,
                              target: slo.target,
                              actual: slo.current,
                              burn_rate: slo.burn_rate,
                              error_budget_remaining: slo.error_budget_remaining,
                            }];
                        return (
                          <div key={service} className="slo-chart-wrapper card">
                            <SLOBurnChart
                              data={data}
                              service={service}
                              sloName={slo.name}
                              height={320}
                              titleVariant="service"
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
                {services.length === 0 && (
                  <div className="empty-state card" role="status">
                    <p className="empty-text">No SLO data available</p>
                    <p className="empty-subtext">SLO charts appear when objectives are configured</p>
                  </div>
                )}
              </>
            );
          })()}
        </section>
    </div>
  );
};

export default SLO;
