"""
Risk Scorer for ChangeTrace Risk Engine

Scores deployment risk using ML model + heuristic factors.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import joblib
import numpy as np

logger = logging.getLogger(__name__)


class RiskScorer:
    """Scores deployment risk using ML model + heuristic factors."""
    
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.getenv("RISK_MODEL_PATH")
        self.model = None
        self.feature_names = [
            "change_size",
            "files_changed",
            "services_affected",
            "service_criticality",
            "dependency_count",
            "dependent_count",
            "recent_incidents_7d",
            "recent_incidents_30d",
            "change_failure_rate_7d",
            "change_failure_rate_30d",
            "time_since_last_deploy_hours",
            "is_weekend",
            "is_business_hours",
            "team_experience_score",
        ]
        
        if self.model_path and os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                logger.info(f"Loaded risk model from {self.model_path}")
            except Exception as e:
                logger.warning(f"Failed to load risk model: {e}")
    
    def score_deployment(
        self,
        service_name: str,
        namespace: str,
        version: str,
        change_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Score deployment risk.
        
        Returns risk score (0-1), risk level, and contributing factors.
        """
        # Extract features
        features = self._extract_features(service_name, namespace, change_details)
        
        # Get risk score
        risk_score = self._predict_risk(features)
        
        # Categorize risk
        risk_level = self._categorize_risk(risk_score)
        
        # Determine if approval required
        risk_threshold = float(os.getenv("RISK_THRESHOLD", "0.70"))
        approval_required = risk_score >= risk_threshold
        
        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "approval_required": approval_required,
            "risk_factors": features,
            "model_version": "risk-model-1.0",
            "scored_at": datetime.utcnow().isoformat()
        }
    
    def _extract_features(
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
        
        # Service properties (would query graph/DB in production)
        criticality = self._get_service_criticality(service_name)
        dependency_count = self._get_dependency_count(service_name)
        dependent_count = self._get_dependent_count(service_name)
        
        # Historical patterns
        recent_incidents_7d = self._get_recent_incidents(service_name, days=7)
        recent_incidents_30d = self._get_recent_incidents(service_name, days=30)
        change_failure_rate_7d = self._get_change_failure_rate(service_name, days=7)
        change_failure_rate_30d = self._get_change_failure_rate(service_name, days=30)
        
        # Temporal
        now = datetime.utcnow()
        is_weekend = 1.0 if now.weekday() >= 5 else 0.0
        is_business_hours = 1.0 if 9 <= now.hour <= 17 else 0.0
        time_since_last_deploy = self._get_time_since_last_deploy(service_name)
        
        # Team
        team_experience = self._get_team_experience_score(service_name)
        
        return {
            "change_size": min(change_size / 1000.0, 1.0),
            "files_changed": min(files_changed / 50.0, 1.0),
            "services_affected": min(services_affected / 5.0, 1.0),
            "service_criticality": criticality,
            "dependency_count": min(dependency_count / 10.0, 1.0),
            "dependent_count": min(dependent_count / 10.0, 1.0),
            "recent_incidents_7d": min(recent_incidents_7d / 5.0, 1.0),
            "recent_incidents_30d": min(recent_incidents_30d / 20.0, 1.0),
            "change_failure_rate_7d": change_failure_rate_7d,
            "change_failure_rate_30d": change_failure_rate_30d,
            "time_since_last_deploy_hours": min(time_since_last_deploy / 168.0, 1.0),
            "is_weekend": is_weekend,
            "is_business_hours": is_business_hours,
            "team_experience_score": team_experience,
        }
    
    def _predict_risk(self, features: Dict[str, float]) -> float:
        """Predict risk score using ML model or heuristic."""
        
        if self.model:
            try:
                feature_array = np.array([[features[name] for name in self.feature_names]])
                return float(self.model.predict_proba(feature_array)[0][1])
            except Exception as e:
                logger.warning(f"ML prediction failed: {e}, using heuristic")
        
        # Heuristic fallback
        return self._heuristic_risk_score(features)
    
    def _heuristic_risk_score(self, features: Dict[str, float]) -> float:
        """Heuristic risk scoring when ML model unavailable."""
        
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
            "is_business_hours": -0.02,
            "team_experience_score": -0.10,
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
    # Helper methods (mock implementations - would query DB/graph in production)
    # ============================================================
    
    def _get_service_criticality(self, service_name: str) -> float:
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
    
    def _get_dependency_count(self, service_name: str) -> int:
        return 3  # Mock
    
    def _get_dependent_count(self, service_name: str) -> int:
        return 2  # Mock
    
    def _get_recent_incidents(self, service_name: str, days: int) -> int:
        return 0  # Mock
    
    def _get_change_failure_rate(self, service_name: str, days: int) -> float:
        return 0.02  # Mock
    
    def _get_time_since_last_deploy(self, service_name: str) -> float:
        return 24.0  # Mock hours
    
    def _get_team_experience_score(self, service_name: str) -> float:
        return 0.7  # Mock