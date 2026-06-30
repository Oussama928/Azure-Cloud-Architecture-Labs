import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import './SLOBurnChart.css';

interface BurnDataPoint {
  timestamp: string;
  service: string;
  slo_name: string;
  target: number;
  actual: number;
  burn_rate: number;
  error_budget_remaining: number;
}

interface SLOBurnChartProps {
  data: BurnDataPoint[];
  service?: string;
  sloName?: string;
  height?: number;
  showTarget?: boolean;
  isLoading?: boolean;
  titleVariant?: 'full' | 'service';
}

const SLOBurnChart: React.FC<SLOBurnChartProps> = ({
  data,
  service,
  sloName,
  height = 300,
  showTarget = true,
  isLoading = false,
  titleVariant = 'full',
}) => {
  if (isLoading) {
    return (
      <div className="slo-burn-chart skeleton-loading" aria-busy="true">
        <div className="skeleton" style={{ height: '24px', width: '60%' }} />
        <div className="skeleton" style={{ height: '100%', minHeight: '200px', marginTop: '16px', borderRadius: 'var(--radius-md)' }} />
        <div className="skeleton" style={{ height: '32px', width: '100%', marginTop: '16px', display: 'flex', gap: '24px' }}>
          <div style={{ flex: 1 }} />
          <div style={{ flex: 1 }} />
          <div style={{ flex: 1 }} />
          <div style={{ flex: 1 }} />
        </div>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="slo-burn-chart empty" role="status">
        <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <path d="M18 20V10M12 20V4M6 20V16" />
        </svg>
        <p className="empty-text">No SLO burn rate data available</p>
        <p className="empty-subtext">Data will appear here when SLOs are configured</p>
      </div>
    );
  }

  const filteredData = data.filter(d => 
    (!service || d.service === service) && 
    (!sloName || d.slo_name === sloName)
  );

  if (filteredData.length === 0) {
    return (
      <div className="slo-burn-chart empty" role="status">
        <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <p className="empty-text">No data for selected filters</p>
        <p className="empty-subtext">Try adjusting your service or SLO selection</p>
      </div>
    );
  }

  const sortedData = [...filteredData].sort((a, b) => 
    new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  // Latency SLOs are in milliseconds; availability/error budgets are percentages.
  // Use the sloName (or the actual magnitude) to pick the correct unit.
  const isLatency = (d: BurnDataPoint) =>
    (sloName || d.slo_name || '').toLowerCase().includes('latency');
  const unitLabel = isLatency(sortedData[0]) ? 'ms' : '%';

  // Numeric x value (epoch ms) so the time axis is truly continuous/evenly
  // spaced even when points are sparse or gapped.
  const times = sortedData.map((d) => new Date(d.timestamp).getTime());
  const dataMin = Math.min(...times);
  const dataMax = Math.max(...times);
  const spanMs = dataMax - dataMin;
  const padMs = spanMs === 0 ? 5 * 60 * 1000 : Math.max(spanMs * 0.05, 60 * 1000);
  const showDate = spanMs > 36 * 60 * 60 * 1000;

  // Break lines across large gaps so recharts doesn't draw a continuous line
  // through periods with no data (the backend can leave multi-hour holes).
  const intervals = times.slice(1).map((t, i) => t - times[i]);
  const medianInterval = intervals.length
    ? intervals.slice().sort((a, b) => a - b)[Math.floor(intervals.length / 2)]
    : 0;
  const gapMs = Math.max(medianInterval * 3, 5 * 60 * 1000);
  let hasGap = false;
  const chartData: Array<{
    time: string;
    timeMs: number;
    actual: number | null;
    target: number | null;
    burnRate: number | null;
    errorBudget: number | null;
    timestamp: string;
  }> = [];
  for (let i = 0; i < sortedData.length; i++) {
    const d = sortedData[i];
    const ms = times[i];
    if (i > 0 && ms - times[i - 1] > gapMs) {
      const bridgeMs = (times[i - 1] + ms) / 2;
      chartData.push({
        time: new Date(bridgeMs).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
        timeMs: bridgeMs,
        actual: null,
        target: null,
        burnRate: null,
        errorBudget: null,
        timestamp: new Date(bridgeMs).toISOString(),
      });
      hasGap = true;
    }
    chartData.push({
      time: new Date(d.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
      timeMs: ms,
      actual: d.actual,
      target: d.target,
      burnRate: d.burn_rate,
      errorBudget: d.error_budget_remaining,
      timestamp: d.timestamp,
    });
  }

  // Padded time domain so sparse or single-point series still render a sane axis.
  const xMin = dataMin - padMs;
  const xMax = dataMax + padMs;
  const TICK_COUNT = 6;
  const xTicks = Array.from(
    { length: TICK_COUNT },
    (_, i) => xMin + ((xMax - xMin) * i) / (TICK_COUNT - 1)
  );

  const formatTime = (ms: number) => {
    const d = new Date(ms);
    return showDate
      ? d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  // Y-axis scaling — always linear (recharts' log scale is buggy and rendered
  // garbage/huge tick labels):
  // - Percent SLOs (availability): zoom around the real range so a 99.9 target
  //   vs 100.0 actual are visually distinct instead of two flat lines at the top.
  // - Latency: scale to the live values so a normal 5-40ms oscillation is
  //   actually visible instead of being squished flat against a 500ms target.
  //   When there's huge headroom (target far above the data) we zoom to the data
  //   and the target line runs off the top — the summary stat still shows it.
  const actualValues = sortedData.map((d) => d.actual).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  const targetValues = sortedData.map((d) => d.target).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  const actualMin = actualValues.length ? Math.min(...actualValues) : 0;
  const actualMax = actualValues.length ? Math.max(...actualValues) : 0;
  const targetMin = targetValues.length ? Math.min(...targetValues) : 0;
  const targetMax = targetValues.length ? Math.max(...targetValues) : 0;

  const positiveActuals = actualValues.filter((v) => v > 0);
  const sortedActuals = [...positiveActuals].sort((a, b) => a - b);
  const median = sortedActuals.length > 0 ? sortedActuals[Math.floor(sortedActuals.length / 2)] : 0;

  // Log scale for latency when there's a huge dynamic range (e.g. a 1500ms fault
  // spike against a 20-30ms normal band) so both are visible. Ticks are pinned
  // to nice values — recharts' auto-generated log ticks are unreliable.
  const LATENCY_TICKS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
  const useLogScale =
    unitLabel === 'ms' &&
    median > 0 &&
    positiveActuals.length === actualValues.length &&
    actualMax / median > 10;

  let yDomain: [number, number];
  let yTicks: number[] | undefined;
  let targetVisible = true;
  if (unitLabel === '%') {
    const lo = Math.min(actualMin, targetMin);
    const hi = Math.max(actualMax, targetMax);
    const range = Math.max(hi - lo, 0.01);
    const pad = Math.max(range * 0.25, 0.25);
    yDomain = [Math.max(0, lo - pad), Math.min(100.5, hi + pad)];
  } else if (useLogScale) {
    const lo = Math.min(...positiveActuals, targetMax);
    const hi = Math.max(actualMax, targetMax);
    const domainMin = [...LATENCY_TICKS].reverse().find((t) => t <= lo) ?? lo * 0.9;
    const domainMax = LATENCY_TICKS.find((t) => t >= hi * 1.05) ?? hi * 1.15;
    yTicks = LATENCY_TICKS.filter((t) => t >= domainMin && t <= domainMax);
    yDomain = [domainMin, domainMax];
  } else if (actualMax * 4 < targetMax) {
    yDomain = [0, Math.max(actualMax * 1.5, 1)];
    targetVisible = false;
  } else {
    yDomain = [0, Math.max(actualMax, targetMax) * 1.15];
  }
  const yAxisLabel = unitLabel === 'ms' ? (useLogScale ? 'Latency (ms, log)' : 'Latency (ms)') : 'Percentage (%)';
  const lineType: 'linear' | 'monotone' = hasGap ? 'linear' : 'monotone';
  const isSnapshot = filteredData.length === 1;

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="recharts-tooltip-wrapper">
          <p className="tooltip-label">{typeof label === 'number' ? formatTime(label) : label}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className={`tooltip-value ${entry.name.toLowerCase().replace(/\s+/g, '-')}`}>
              <span className="tooltip-dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {entry.value != null ? `${entry.value.toFixed(isLatency(sortedData[0]) ? 1 : 2)}${unitLabel}` : '\u2014'}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  const latestData = chartData[chartData.length - 1];

  return (
    <div className="slo-burn-chart">
      <div className="chart-header">
        <div className="chart-title-group">
          <h3 className="chart-title">
            {titleVariant === 'service'
              ? (service || sloName || 'SLO')
              : (
                <>
                  {service && (
                    <>
                      <span className="service-name">{service}</span>
                      <span className="title-separator" aria-hidden="true">—</span>
                    </>
                  )}
                  {sloName || 'SLO'} Burn Rate
                </>
              )}
          </h3>
          {isSnapshot && (
            <span className="chart-badge" role="status">Latest snapshot</span>
          )}
          {service && (
            <span className="chart-subtitle">Service Level Objective Monitoring</span>
          )}
        </div>
        <div className="chart-legend" role="group" aria-label="Chart series">
          {showTarget && <span className="legend-item legend-target" aria-label="Target SLO">Target</span>}
          <span className="legend-item legend-actual" aria-label="Actual SLO">Actual</span>
        </div>
      </div>

      <div className="chart-container" style={{ height }} role="img" aria-label={`${service || 'SLO'} burn rate chart over time`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 10, right: 30, left: 20, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" className="chart-grid" />
            <XAxis 
              dataKey="timeMs" 
              type="number" 
              scale="time"
              domain={[xMin, xMax]}
              ticks={xTicks}
              className="chart-axis"
              tick={{ fontSize: 11 }}
              tickFormatter={formatTime}
              tickLine={false}
              axisLine={{ stroke: 'var(--color-border-primary)' }}
              padding={{ left: 10, right: 10 }}
            />
            <YAxis 
              className="chart-axis"
              tick={{ fontSize: 11 }}
              domain={yDomain}
              scale={useLogScale ? 'log' : 'auto'}
              ticks={yTicks}
              label={{ value: yAxisLabel, angle: -90, position: 'insideLeft', offset: 10, fill: 'var(--color-text-tertiary)', fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--color-border-primary)' }}
            />
            <Tooltip content={<CustomTooltip />} wrapperStyle={{ outline: 'none' }} />
            <Legend 
              wrapperStyle={{ paddingTop: 20 }} 
              formatter={(value) => value}
              iconType="line"
            />
            
            {showTarget && targetVisible && (
              <Line
                type={lineType}
                dataKey="target"
                stroke="var(--color-text-tertiary)"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
                connectNulls={false}
                name="Target"
                isAnimationActive={false}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}
            
            <Line
              type={lineType}
              dataKey="actual"
              stroke="var(--color-brand-primary)"
              strokeWidth={2.5}
              dot={false}
              connectNulls={false}
              name="Actual"
              isAnimationActive={false}
              strokeLinecap="round"
              strokeLinejoin="round"
              animationDuration={800}
              animationEasing="ease-out"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {!targetVisible && (
        <div className="chart-offscale-note" role="note">
          Target {latestData?.target != null ? `${latestData.target.toFixed(isLatency(sortedData[0]) ? 1 : 2)}${unitLabel}` : ''} is above the visible range — axis scaled to live data.
        </div>
      )}

      <div className="chart-summary" role="region" aria-label="Current SLO metrics">
        <div className="summary-item">
          <span className="summary-label">Current Actual</span>
          <span className="summary-value summary-actual">{latestData?.actual != null ? `${latestData.actual.toFixed(isLatency(sortedData[0]) ? 1 : 2)}${unitLabel}` : '\u2014'}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Target</span>
          <span className="summary-value summary-target">{latestData?.target != null ? `${latestData.target.toFixed(isLatency(sortedData[0]) ? 1 : 2)}${unitLabel}` : '\u2014'}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Burn Rate</span>
          <span className="summary-value summary-burn-rate">{latestData?.burnRate != null ? `${latestData.burnRate.toFixed(2)}x` : '\u2014'}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Error Budget</span>
          <span className="summary-value summary-error-budget">{latestData?.errorBudget != null ? `${latestData.errorBudget.toFixed(1)}%` : '\u2014'}</span>
        </div>
      </div>
    </div>
  );
};

export default SLOBurnChart;