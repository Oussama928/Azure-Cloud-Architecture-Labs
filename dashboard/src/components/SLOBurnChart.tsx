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
  showBurnRate?: boolean;
  showErrorBudget?: boolean;
}

const SLOBurnChart: React.FC<SLOBurnChartProps> = ({
  data,
  service,
  sloName,
  height = 300,
  showTarget = true,
  showBurnRate = true,
  showErrorBudget = true,
}) => {
  if (!data || data.length === 0) {
    return (
      <div className="slo-burn-chart empty">
        <p className="text-gray-500 text-center py-8">No SLO burn rate data available</p>
      </div>
    );
  }

  // Filter data if service or sloName specified
  const filteredData = data.filter(d => 
    (!service || d.service === service) && 
    (!sloName || d.slo_name === sloName)
  );

  if (filteredData.length === 0) {
    return (
      <div className="slo-burn-chart empty">
        <p className="text-gray-500 text-center py-8">No data for selected filters</p>
      </div>
    );
  }

  // Sort by timestamp
  const sortedData = [...filteredData].sort((a, b) => 
    new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  // Format data for recharts
  const chartData = sortedData.map(d => ({
    time: new Date(d.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
    actual: d.actual,
    target: d.target,
    burnRate: d.burn_rate,
    errorBudget: d.error_budget_remaining,
    timestamp: d.timestamp,
  }));

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="recharts-tooltip-wrapper">
          <p className="label">{label}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className={`value ${entry.name.toLowerCase()}`}>
              <span className="dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {entry.value.toFixed(2)}%
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="slo-burn-chart">
      <div className="chart-header">
        <h3 className="chart-title">
          {service ? `${service} - ` : ''}{sloName || 'SLO'} Burn Rate
        </h3>
        <div className="chart-legend">
          {showTarget && <span className="legend-item target">Target</span>}
          <span className="legend-item actual">Actual</span>
          {showBurnRate && <span className="legend-item burn-rate">Burn Rate</span>}
          {showErrorBudget && <span className="legend-item error-budget">Error Budget</span>}
        </div>
      </div>

      <div className="chart-container" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 10, right: 30, left: 20, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" className="chart-grid" />
            <XAxis 
              dataKey="time" 
              className="chart-axis"
              tick={{ fontSize: 11 }}
              interval={Math.max(1, Math.floor(chartData.length / 10))}
            />
            <YAxis 
              className="chart-axis"
              tick={{ fontSize: 11 }}
              domain={showErrorBudget ? [0, 100] : [0, 'auto']}
              label={{ value: 'Percentage (%)', angle: -90, position: 'insideLeft', offset: 10 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend />
            
            {showTarget && (
              <Line
                type="monotone"
                dataKey="target"
                stroke="#64748b"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
                name="Target"
                isAnimationActive={false}
              />
            )}
            
            <Line
              type="monotone"
              dataKey="actual"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              name="Actual"
              isAnimationActive={false}
            />
            
            {showBurnRate && (
              <Line
                type="monotone"
                dataKey="burnRate"
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="3 3"
                dot={false}
                name="Burn Rate"
                yAxisId="right"
                isAnimationActive={false}
              />
            )}
            
            {showErrorBudget && (
              <Line
                type="monotone"
                dataKey="errorBudget"
                stroke="#22c55e"
                strokeWidth={2}
                dot={false}
                name="Error Budget"
                isAnimationActive={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Summary Stats */}
      <div className="chart-summary">
        <div className="summary-item">
          <span className="summary-label">Current Actual</span>
          <span className="summary-value">{chartData[chartData.length - 1]?.actual.toFixed(2)}%</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Target</span>
          <span className="summary-value">{chartData[chartData.length - 1]?.target.toFixed(2)}%</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Burn Rate</span>
          <span className="summary-value burn-rate">{chartData[chartData.length - 1]?.burnRate.toFixed(2)}x</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Error Budget</span>
          <span className="summary-value error-budget">{chartData[chartData.length - 1]?.errorBudget.toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
};

export default SLOBurnChart;