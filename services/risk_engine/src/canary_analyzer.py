"""
Canary Analyzer for ChangeTrace Risk Engine

Performs statistical canary analysis using Mann-Whitney U test.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class CanaryAnalyzer:
    """Performs statistical canary analysis."""
    
    def __init__(self):
        self.alpha = 0.05  # Significance level
        self.min_samples = 10  # Minimum samples for statistical test
        self.effect_size_threshold = 0.1  # Cliff's delta threshold
    
    async def analyze_canary_stage(
        self,
        service_name: str,
        namespace: str,
        stage: int,
        traffic_percentage: int,
        duration_minutes: int,
        slo_threshold: float
    ) -> Dict[str, Any]:
        """
        Perform statistical canary analysis.
        
        Compares canary metrics vs baseline using Mann-Whitney U test.
        """
        logger.info(f"Analyzing canary stage {stage} for {service_name} ({traffic_percentage}% traffic)")
        
        # Get baseline metrics (stable version)
        baseline_metrics = await self._get_baseline_metrics(
            service_name, namespace, duration_minutes
        )
        
        # Get canary metrics (new version)
        canary_metrics = await self._get_canary_metrics(
            service_name, namespace, duration_minutes
        )
        
        # Statistical comparison
        results = {}
        passed = True
        
        for metric_name in ["error_rate", "latency_p50", "latency_p95", "latency_p99"]:
            baseline_values = baseline_metrics.get(metric_name, [])
            canary_values = canary_metrics.get(metric_name, [])
            
            if len(baseline_values) < self.min_samples or len(canary_values) < self.min_samples:
                results[metric_name] = {
                    "passed": True,
                    "reason": "Insufficient data for statistical test",
                    "baseline_samples": len(baseline_values),
                    "canary_samples": len(canary_values)
                }
                continue
            
            # Mann-Whitney U test
            statistic, p_value = stats.mannwhitneyu(
                canary_values, baseline_values, alternative="greater"
            )
            
            # Effect size (Cliff's delta)
            cliffs_delta = self._cliffs_delta(canary_values, baseline_values)
            
            # Determine if statistically significant degradation
            significant = p_value < self.alpha
            degraded = significant and cliffs_delta > self.effect_size_threshold
            
            metric_passed = not degraded
            if not metric_passed:
                passed = False
            
            results[metric_name] = {
                "passed": metric_passed,
                "p_value": float(p_value),
                "statistic": float(statistic),
                "cliffs_delta": float(cliffs_delta),
                "baseline_median": float(np.median(baseline_values)),
                "canary_median": float(np.median(canary_values)),
                "significant": significant,
                "degraded": degraded
            }
        
        # Overall SLO check
        current_slo = canary_metrics.get("availability", [1.0])
        if isinstance(current_slo, list):
            current_slo = current_slo[-1] if current_slo else 1.0
        slo_passed = current_slo >= slo_threshold
        if not slo_passed:
            passed = False
        
        results["availability"] = {
            "passed": slo_passed,
            "current": current_slo,
            "threshold": slo_threshold
        }
        
        return {
            "stage": stage,
            "traffic_percentage": traffic_percentage,
            "duration_minutes": duration_minutes,
            "passed": passed,
            "metrics": results,
            "recommendation": "promote" if passed else "rollback",
            "analyzed_at": datetime.utcnow().isoformat()
        }
    
    def _cliffs_delta(self, x: List[float], y: List[float]) -> float:
        """Compute Cliff's delta effect size."""
        n_x, n_y = len(x), len(y)
        if n_x == 0 or n_y == 0:
            return 0.0
        
        greater = sum(1 for xi in x for yi in y if xi > yi)
        less = sum(1 for xi in x for yi in y if xi < yi)
        
        return (greater - less) / (n_x * n_y)
    
    async def _get_baseline_metrics(
        self, service_name: str, namespace: str, duration_minutes: int
    ) -> Dict[str, List[float]]:
        """Get baseline metrics from stable version."""
        # TODO: Query Application Insights / Prometheus
        # Return mock data for now
        return {
            "error_rate": np.random.exponential(0.001, 100).tolist(),
            "latency_p50": np.random.normal(50, 10, 100).tolist(),
            "latency_p95": np.random.normal(200, 30, 100).tolist(),
            "latency_p99": np.random.normal(500, 50, 100).tolist(),
            "availability": [0.999] * 100
        }
    
    async def _get_canary_metrics(
        self, service_name: str, namespace: str, duration_minutes: int
    ) -> Dict[str, List[float]]:
        """Get canary metrics from new version."""
        # TODO: Query Application Insights / Prometheus
        return {
            "error_rate": np.random.exponential(0.001, 100).tolist(),
            "latency_p50": np.random.normal(55, 12, 100).tolist(),
            "latency_p95": np.random.normal(220, 35, 100).tolist(),
            "latency_p99": np.random.normal(550, 60, 100).tolist(),
            "availability": [0.998] * 100
        }