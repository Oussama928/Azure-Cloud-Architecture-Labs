import React from 'react';
import './RiskScoreCard.css';

interface RiskScoreCardProps {
  service: string;
  riskScore: number;
  riskLevel: 'low' | 'medium' | 'high' | 'critical';
  factors: Record<string, number>;
  lastDeployment?: string;
  lastDeploymentTime?: string;
  onClick?: () => void;
}

const RiskScoreCard: React.FC<RiskScoreCardProps> = ({
  service,
  riskScore,
  riskLevel,
  factors,
  lastDeployment,
  lastDeploymentTime,
  onClick,
}) => {
  const getRiskColor = (level: string) => {
    switch (level) {
      case 'critical': return 'bg-red-600';
      case 'high': return 'bg-orange-500';
      case 'medium': return 'bg-yellow-500';
      case 'low': return 'bg-green-500';
      default: return 'bg-gray-500';
    }
  };

  const getRiskTextColor = (level: string) => {
    switch (level) {
      case 'critical': return 'text-red-600';
      case 'high': return 'text-orange-600';
      case 'medium': return 'text-yellow-600';
      case 'low': return 'text-green-600';
      default: return 'text-gray-600';
    }
  };

  const getRiskBgColor = (level: string) => {
    switch (level) {
      case 'critical': return 'bg-red-50 border-red-200';
      case 'high': return 'bg-orange-50 border-orange-200';
      case 'medium': return 'bg-yellow-50 border-yellow-200';
      case 'low': return 'bg-green-50 border-green-200';
      default: return 'bg-gray-50 border-gray-200';
    }
  };

  const formatFactorName = (name: string) => {
    return name
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase());
  };

  return (
    <div 
      className={`risk-score-card ${getRiskBgColor(riskLevel)} border rounded-xl p-6 ${onClick ? 'cursor-pointer hover:shadow-lg transition-shadow' : ''}`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">{service}</h3>
          <p className="text-sm text-gray-500 mt-1">Deployment Risk Assessment</p>
        </div>
        <div className={`risk-score-badge ${getRiskColor(riskLevel)} text-white px-4 py-2 rounded-full`}>
          <span className="text-2xl font-bold">{Math.round(riskScore * 100)}%</span>
          <span className="ml-2 text-sm opacity-90">{riskLevel.toUpperCase()}</span>
        </div>
      </div>

      {/* Risk Score Visualization */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-600">Risk Score</span>
          <span className={`text-sm font-medium ${getRiskTextColor(riskLevel)}`}>
            {Math.round(riskScore * 100)}%
          </span>
        </div>
        <div className="h-3 bg-gray-200 rounded-full overflow-hidden">
          <div 
            className={`h-full rounded-full transition-all duration-500 ${getRiskColor(riskLevel)}`}
            style={{ width: `${riskScore * 100}%` }}
          ></div>
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>Low (0%)</span>
          <span>Medium (50%)</span>
          <span>High (70%)</span>
          <span>Critical (90%)</span>
        </div>
      </div>

      {/* Risk Factors */}
      <div className="mb-6">
        <h4 className="text-sm font-medium text-gray-700 mb-3">Risk Factors</h4>
        <div className="space-y-2">
          {Object.entries(factors).map(([factor, value]) => (
            <div key={factor} className="factor-row">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">{formatFactorName(factor)}</span>
                <span className="font-medium text-gray-900">{Math.round(value * 100)}%</span>
              </div>
              <div className="h-1.5 bg-gray-200 rounded-full mt-1 overflow-hidden">
                <div 
                  className={`h-full rounded-full ${getRiskColor(riskLevel)}`}
                  style={{ width: `${value * 100}%` }}
                ></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Last Deployment Info */}
      {lastDeployment && (
        <div className="border-t border-gray-200 pt-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">Last Deployment</span>
            <span className="font-medium text-gray-900">{lastDeployment}</span>
          </div>
          {lastDeploymentTime && (
            <p className="text-xs text-gray-500 mt-1">{lastDeploymentTime}</p>
          )}
        </div>
      )}

      {/* Risk Level Thresholds */}
      <div className="mt-4 pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-500 mb-2">Risk Thresholds:</p>
        <div className="flex gap-4 text-xs">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-500"></span>
            Low: {'<'} 30%
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-yellow-500"></span>
            Medium: 30-70%
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-orange-500"></span>
            High: 70-90%
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-500"></span>
            Critical: {'>'} 90%
          </span>
        </div>
      </div>
    </div>
  );
};

export default RiskScoreCard;