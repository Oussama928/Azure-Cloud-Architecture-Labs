"""
Risk Engine Service for ChangeTrace

Scores deployment risk, manages canary analysis with statistical validation,
and tracks SLO/error budgets.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import azure.functions as func
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class RiskEngine:
    """Scores deployment risk and manages canary analysis."""
    
    def __init__(self):
        self.cosmos_endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        self.cosmos_key = os.getenv("COSMOS_DB_KEY")
        self.database_name = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
        self.change_history_graph = os.getenv("COSMOS_DB_CHANGE_GRAPH", "change-history")
        
        # Risk thresholds
        self.risk_threshold = float(os.getenv("RISK_THRESHOLD", "0.70"))
        self.canary_stages = [
            {"traffic_percentage": 10, "duration_minutes": 5, "slo_threshold": 0.99},
            {"traffic_percentage": 50, "duration_minutes": 5, "slo_threshold": 0.99},
            {"traffic_percentage": 100, "duration_minutes": 5, "slo_threshold": 0.99},
        ]
    
    async def score_deployment_risk(
        self,
        deployment_id: str,
        service_name: str,
        namespace: str,
        version: str,
        change_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Score deployment risk using ML model + heuristic factors.
        
        Factors:
        - Change size (lines changed, files touched)
        - Service criticality
        - Recent incident history
        - Dependency risk
        - Time of day / day of week
        - Team experience
        """
        logger.info(f"Scoring risk for deployment {deployment_id} ({service_name} v{version})")
        
        # Extract features
        features = await self._extract_risk_features(
            service_name, namespace, change_details
        )
        
        # Get ML model prediction (or heuristic fallback)
        risk_score = await self._predict_risk(features)
        
        # Determine risk level
        risk_level = self._categorize_risk(risk_score)
        
        # Determine if approval required
        approval_required = risk_score >= self.risk_threshold
        
        return {
            "deployment_id": deployment_id,
            "service_name": service_name,
            "version": version,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "approval_required": approval_required,
            "risk_factors": features,
            "model_version": "risk-model-1.0",
            "scored_at": datetime.utcnow().isoformat()
        }
    
    async def _extract_risk_features(
        self,
        service_name: str,
        namespace: str,
        change_details: Dict[str, Any]
    ) -> Dict[str, float]:
        """Extract numerical features for risk model."""
        
        # Change characteristics
        change_size = change_details.get("lines_changed", 0)
        files_changed = change_details.get("files_changed", 0)
        services_affected = change_details.get("services_affected", 1)
        
        # Service properties
        criticality = await self._get_service_criticality(service_name)
        dependency_count = await self._get_dependency_count(service_name)
        dependent_count = await self._get_dependent_count(service_name)
        
        # Historical patterns
        recent_incidents_7d = await self._get_recent_incidents(service_name, days=7)
        recent_incidents_30d = await self._get_recent_incidents(service_name, days=30)
        change_failure_rate_7d = await self._get_change_failure_rate(service_name, days=7)
        change_failure_rate_30d = await self._get_change_failure_rate(service_name, days=30)
        
        # Temporal
        now = datetime.utcnow()
        is_weekend = 1.0 if now.weekday() >= 5 else 0.0
        is_business_hours = 1.0 if 9 <= now.hour <= 17 else 0.0
        time_since_last_deploy = await self._get_time_since_last_deploy(service_name)
        
        # Team
        team_experience = await self._get_team_experience_score(service_name)
        
        return {
            "change_size": min(change_size / 1000.0, 1.0),  # Normalize
            "files_changed": min(files_changed / 50.0, 1.0),
            "services_affected": min(services_affected / 5.0, 1.0),
            "service_criticality": criticality,
            "dependency_count": min(dependency_count / 10.0, 1.0),
            "dependent_count": min(dependent_count / 10.0, 1.0),
            "recent_incidents_7d": min(recent_incidents_7d / 5.0, 1.0),
            "recent_incidents_30d": min(recent_incidents_30d / 20.0, 1.0),
            "change_failure_rate_7d": change_failure_rate_7d,
            "change_failure_rate_30d": change_failure_rate_30d,
            "time_since_last_deploy_hours": min(time_since_last_deploy / 168.0, 1.0),  # Week
            "is_weekend": is_weekend,
            "is_business_hours": is_business_hours,
            "team_experience_score": team_experience,
        }
    
    async def _predict_risk(self, features: Dict[str, float]) -> float:
        """Predict risk score using ML model or heuristic."""
        
        # Try to load trained model
        model_path = os.getenv("RISK_MODEL_PATH")
        if model_path and os.path.exists(model_path):
            try:
                import joblib
                model = joblib.load(model_path)
                feature_array = np.array([list(features.values())])
                return float(model.predict_proba(feature_array)[0][1])
            except Exception as e:
                logger.warning(f"Failed to load ML model: {e}, using heuristic")
        
        # Heuristic fallback (weighted combination)
        weights = {
            "change_size": 0.15,
            "files_changed": 0.10,
            "services_affected": 0.10,
            "service_criticality": 0.20,
            "dependency_count": 0.05,
            "dependent_count": 0.05,
            "recent_incidents_7d": 0.10,
            "recent_incidents_30d": 0.05,
            "change_failure_rate_7d": 0.10,
            "change_failure_rate_30d": 0.05,
            "time_since_last_deploy_hours": 0.02,
            "is_weekend": 0.03,
            "is_business_hours": -0.02,  # Lower risk during business hours
            "team_experience_score": -0.10,  # More experience = lower risk
        }
        
        score = 0.0
        for feature, weight in weights.items():
            value = features.get(feature, 0.0)
            score += weight * value
        
        # Sigmoid to bound between 0 and 1
        return 1.0 / (1.0 + np.exp(-score * 5))
    
    def _categorize_risk(self, score: float) -> str:
        """Categorize risk score into level."""
        if score >= 0.9:
            return "critical"
        elif score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        elif score >= 0.2:
            return "low"
        return "minimal"
    
    # ============================================================
    # Canary Analysis
    # ============================================================
    
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
        Perform statistical canary analysis using Mann-Whitney U test.
        
        Compares canary metrics vs baseline metrics for:
        - Error rate
        - Latency (p50, p95, p99)
        - Request volume
        """
        logger.info(f"Analyzing canary stage {stage} for {service_name} ({traffic_percentage}% traffic)")
        
        # Get baseline metrics (stable version)
        baseline_metrics = await self._get_baseline_metrics(
            service_name, namespace, duration_minutes=duration_minutes
        )
        
        # Get canary metrics (new version)
        canary_metrics = await self._get_canary_metrics(
            service_name, namespace, duration_minutes=duration_minutes
        )
        
        # Statistical comparison
        results = {}
        passed = True
        
        for metric_name in ["error_rate", "latency_p50", "latency_p95", "latency_p99"]:
            baseline_values = baseline_metrics.get(metric_name, [])
            canary_values = canary_metrics.get(metric_name, [])
            
            if len(baseline_values) < 10 or len(canary_values) < 10:
                results[metric_name] = {
                    "passed": True,
                    "reason": "Insufficient data for statistical test",
                    "baseline_samples": len(baseline_values),
                    "canary_samples": len(canary_values)
                }
                continue
            
            # Mann-Whitney U test (non-parametric, doesn't assume normal distribution)
            statistic, p_value = stats.mannwhitneyu(
                canary_values, baseline_values, alternative="greater"
            )
            
            # Effect size (Cliff's delta)
            cliffs_delta = self._cliffs_delta(canary_values, baseline_values)
            
            # Determine if statistically significant degradation
            alpha = 0.05
            significant = p_value < alpha
            degraded = significant and cliffs_delta > 0.1  # Small effect size threshold
            
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
        current_slo = canary_metrics.get("availability", 1.0)
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
    
    # ============================================================
    # SLO / Error Budget Tracking
    # ============================================================
    
    async def get_slo_status(self, service_name: str) -> Dict[str, Any]:
        """Get current SLO status and error budget remaining."""
        
        # TODO: Query actual SLO data from Azure Monitor
        slos = {
            "availability": {"target": 0.999, "current": 0.9995, "window": "30d"},
            "latency_p99": {"target": 500, "current": 450, "window": "30d"},
            "error_rate": {"target": 0.001, "current": 0.0005, "window": "30d"}
        }
        
        results = {}
        for slo_name, slo_data in slos.items():
            target = slo_data["target"]
            current = slo_data["current"]
            
            if slo_name == "availability":
                # Error budget = 1 - availability
                error_budget_total = 1 - target
                error_budget_consumed = 1 - current
                error_budget_remaining = max(0, error_budget_total - error_budget_consumed)
                burn_rate = error_budget_consumed / error_budget_total if error_budget_total > 0 else 0
            elif slo_name == "latency_p99":
                # For latency, budget is how much over target we can be
                error_budget_total = target * 0.1  # 10% buffer
                error_budget_consumed = max(0, current - target)
                error_budget_remaining = max(0, error_budget_total - error_budget_consumed)
                burn_rate = error_budget_consumed / error_budget_total if error_budget_total > 0 else 0
            else:
                # Error rate
                error_budget_total = target
                error_budget_consumed = current
                error_budget_remaining = max(0, error_budget_total - error_budget_consumed)
                burn_rate = error_budget_consumed / error_budget_total if error_budget_total > 0 else 0
            
            results[slo_name] = {
                "target": target,
                "current": current,
                "error_budget_remaining_pct": (error_budget_remaining / error_budget_total * 100) if error_budget_total > 0 else 100,
                "burn_rate": burn_rate,
                "status": "healthy" if burn_rate < 1.0 else "exhausted"
            }
        
        return {
            "service_name": service_name,
            "slos": results,
            "overall_status": "healthy" if all(r["status"] == "healthy" for r in results.values()) else "degraded",
            "checked_at": datetime.utcnow().isoformat()
        }
    
    # ============================================================
    # Helper methods (mock implementations)
    # ============================================================
    
    async def _get_service_criticality(self, service_name: str) -> float:
        criticality_map = {
            "payment-service": 1.0,
            "database-primary": 1.0,
            "api-gateway": 0.9,
            "auth-service": 0.9,
            "order-service": 0.8,
            "fraud-service": 0.8,
            "inventory-service": 0.6,
            "notification-service": 0.4,
            "ml-model-service": 0.5,
        }
        return criticality_map.get(service_name, 0.5)
    
    async def _get_dependency_count(self, service_name: str) -> int:
        return 3  # Mock
    
    async def _get_dependent_count(self, service_name: str) -> int:
        return 2  # Mock
    
    async def _get_recent_incidents(self, service_name: str, days: int) -> int:
        return 0  # Mock
    
    async def _get_change_failure_rate(self, service_name: str, days: int) -> float:
        return 0.02  # Mock
    
    async def _get_time_since_last_deploy(self, service_name: str) -> float:
        return 24.0  # Mock hours
    
    async def _get_team_experience_score(self, service_name: str) -> float:
        return 0.7  # Mock


# Azure Function entry points
async def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger for risk engine operations."""
    
    engine = RiskEngine()
    action = req.params.get("action")
    
    try:
        if action == "score-deployment":
            body = req.get_json()
            result = await engine.score_deployment_risk(
                deployment_id=body.get("deployment_id"),
                service_name=body.get("service_name"),
                namespace=body.get("namespace", "production"),
                version=body.get("version"),
                change_details=body.get("change_details", {})
            )
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        elif action == "analyze-canary":
            body = req.get_json()
            result = await engine.analyze_canary_stage(
                service_name=body.get("service_name"),
                namespace=body.get("namespace", "production"),
                stage=body.get("stage"),
                traffic_percentage=body.get("traffic_percentage"),
                duration_minutes=body.get("duration_minutes"),
                slo_threshold=body.get("slo_threshold", 0.99)
            )
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        elif action == "slo-status":
            service = req.params.get("service")
            if not service:
                return func.HttpResponse("service parameter required", status_code=400)
            result = await engine.get_slo_status(service)
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        else:
            return func.HttpResponse("Invalid action", status_code=400)
            
    except Exception as e:
        logger.error(f"Risk engine error: {e}")
        return func.HttpResponse(str(e), status_code=500)