"""Model Monitoring and Drift Detection for ChangeTrace."""

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ModelAlert:
    """Model monitoring alert."""
    model_name: str
    alert_type: str
    severity: AlertSeverity
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "alert_type": self.alert_type,
            "severity": self.severity.value,
            "message": self.message,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class PredictionRecord:
    """Record of a single prediction for monitoring."""
    model_name: str
    model_version: str
    prediction: float
    features: Dict[str, float]
    actual: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0
    request_id: str = ""


class DriftDetector:
    """Statistical drift detection for model inputs and predictions."""
    
    def __init__(
        self,
        model_name: str,
        reference_window_days: int = 7,
        detection_window_days: int = 1,
        psi_threshold: float = 0.2,
        ks_threshold: float = 0.05,
        min_samples: int = 100,
    ):
        self.model_name = model_name
        self.reference_window_days = reference_window_days
        self.detection_window_days = detection_window_days
        self.psi_threshold = psi_threshold
        self.ks_threshold = ks_threshold
        self.min_samples = min_samples
        
        # Storage for reference and current windows
        self.reference_predictions: List[float] = []
        self.current_predictions: List[float] = []
        self.reference_features: Dict[str, List[float]] = defaultdict(list)
        self.current_features: Dict[str, List[float]] = defaultdict(list)
    
    def add_prediction(self, record: PredictionRecord) -> None:
        """Add a prediction record to current window."""
        self.current_predictions.append(record.prediction)
        for feature_name, value in record.features.items():
            self.current_features[feature_name].append(value)
    
    def set_reference_data(
        self,
        predictions: List[float],
        features: Dict[str, List[float]],
    ) -> None:
        """Set reference (baseline) data for drift comparison."""
        self.reference_predictions = predictions
        self.reference_features = defaultdict(list, features)
    
    def compute_psi(
        self,
        reference: List[float],
        current: List[float],
        bins: int = 10,
    ) -> float:
        """Compute Population Stability Index (PSI)."""
        if len(reference) < self.min_samples or len(current) < self.min_samples:
            return 0.0
        
        # Create bins based on reference distribution
        _, bin_edges = np.histogram(reference, bins=bins)
        bin_edges[0] = -np.inf
        bin_edges[-1] = np.inf
        
        # Calculate distributions
        ref_hist, _ = np.histogram(reference, bins=bin_edges)
        cur_hist, _ = np.histogram(current, bins=bin_edges)
        
        # Normalize to percentages
        ref_pct = ref_hist / len(reference)
        cur_pct = cur_hist / len(current)
        
        # Avoid division by zero
        ref_pct = np.where(ref_pct == 0, 0.0001, ref_pct)
        cur_pct = np.where(cur_pct == 0, 0.0001, cur_pct)
        
        # Calculate PSI
        psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
        return float(psi)
    
    def compute_ks_statistic(
        self,
        reference: List[float],
        current: List[float],
    ) -> Tuple[float, float]:
        """Compute Kolmogorov-Smirnov test statistic and p-value."""
        if len(reference) < self.min_samples or len(current) < self.min_samples:
            return 0.0, 1.0
        
        ks_stat, p_value = stats.ks_2samp(reference, current)
        return float(ks_stat), float(p_value)
    
    def check_drift(self) -> List[ModelAlert]:
        """Check for drift in predictions and features."""
        alerts = []
        
        # Check prediction drift
        if len(self.reference_predictions) >= self.min_samples and \
           len(self.current_predictions) >= self.min_samples:
            
            # PSI for predictions
            psi = self.compute_psi(self.reference_predictions, self.current_predictions)
            if psi >= self.psi_threshold:
                alerts.append(ModelAlert(
                    model_name=self.model_name,
                    alert_type="prediction_drift_psi",
                    severity=AlertSeverity.WARNING if psi < 0.5 else AlertSeverity.CRITICAL,
                    message=f"Prediction distribution drift detected (PSI={psi:.3f})",
                    metric_value=psi,
                    threshold=self.psi_threshold,
                    metadata={"method": "PSI", "bins": 10},
                ))
            
            # KS test for predictions
            ks_stat, p_value = self.compute_ks_statistic(
                self.reference_predictions, self.current_predictions
            )
            if p_value < self.ks_threshold:
                alerts.append(ModelAlert(
                    model_name=self.model_name,
                    alert_type="prediction_drift_ks",
                    severity=AlertSeverity.WARNING,
                    message=f"Prediction distribution shift detected (KS p-value={p_value:.4f})",
                    metric_value=p_value,
                    threshold=self.ks_threshold,
                    metadata={"method": "KS-test", "ks_statistic": ks_stat},
                ))
        
        # Check feature drift
        for feature_name in self.reference_features:
            if feature_name in self.current_features:
                ref_vals = self.reference_features[feature_name]
                cur_vals = self.current_features[feature_name]
                
                if len(ref_vals) >= self.min_samples and len(cur_vals) >= self.min_samples:
                    psi = self.compute_psi(ref_vals, cur_vals)
                    if psi >= self.psi_threshold:
                        alerts.append(ModelAlert(
                            model_name=self.model_name,
                            alert_type="feature_drift_psi",
                            severity=AlertSeverity.WARNING if psi < 0.5 else AlertSeverity.CRITICAL,
                            message=f"Feature '{feature_name}' drift detected (PSI={psi:.3f})",
                            metric_value=psi,
                            threshold=self.psi_threshold,
                            metadata={"feature": feature_name, "method": "PSI"},
                        ))
        
        return alerts
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get current monitoring statistics."""
        stats = {
            "model_name": self.model_name,
            "reference_samples": len(self.reference_predictions),
            "current_samples": len(self.current_predictions),
            "reference_features": len(self.reference_features),
            "current_features": len(self.current_features),
        }
        
        if self.reference_predictions and self.current_predictions:
            stats["prediction_psi"] = self.compute_psi(
                self.reference_predictions, self.current_predictions
            )
            ks_stat, p_value = self.compute_ks_statistic(
                self.reference_predictions, self.current_predictions
            )
            stats["prediction_ks_statistic"] = ks_stat
            stats["prediction_ks_p_value"] = p_value
        
        return stats


class PerformanceMonitor:
    """Monitor model performance metrics over time."""
    
    def __init__(
        self,
        model_name: str,
        window_size: int = 1000,
        alert_thresholds: Optional[Dict[str, float]] = None,
    ):
        self.model_name = model_name
        self.window_size = window_size
        self.alert_thresholds = alert_thresholds or {
            "accuracy_drop": 0.05,
            "latency_p99_ms": 5000,
            "error_rate": 0.05,
        }
        
        # Rolling windows
        self.predictions: List[PredictionRecord] = []
        self.latencies: List[float] = []
        self.errors: List[bool] = []
    
    def record_prediction(self, record: PredictionRecord) -> None:
        """Record a prediction for monitoring."""
        self.predictions.append(record)
        self.latencies.append(record.latency_ms)
        
        # Track errors (predictions that failed)
        self.errors.append(record.prediction is None or np.isnan(record.prediction))
        
        # Maintain window size
        if len(self.predictions) > self.window_size:
            self.predictions.pop(0)
            self.latencies.pop(0)
            self.errors.pop(0)
    
    def record_actual(self, request_id: str, actual: float) -> bool:
        """Record actual outcome for a prediction (for accuracy tracking)."""
        for record in self.predictions:
            if record.request_id == request_id:
                record.actual = actual
                return True
        return False
    
    def compute_metrics(self) -> Dict[str, float]:
        """Compute current performance metrics."""
        if not self.predictions:
            return {}
        
        # Filter predictions with actuals
        labeled = [p for p in self.predictions if p.actual is not None]
        
        metrics = {
            "total_predictions": len(self.predictions),
            "labeled_predictions": len(labeled),
            "labeling_rate": len(labeled) / len(self.predictions) if self.predictions else 0,
        }
        
        if labeled:
            preds = np.array([p.prediction for p in labeled])
            actuals = np.array([p.actual for p in labeled])
            
            # Binary classification metrics (threshold at 0.5)
            pred_binary = (preds >= 0.5).astype(int)
            actual_binary = (actuals >= 0.5).astype(int)
            
            tp = np.sum((pred_binary == 1) & (actual_binary == 1))
            fp = np.sum((pred_binary == 1) & (actual_binary == 0))
            tn = np.sum((pred_binary == 0) & (actual_binary == 0))
            fn = np.sum((pred_binary == 0) & (actual_binary == 1))
            
            metrics["accuracy"] = (tp + tn) / len(labeled) if labeled else 0
            metrics["precision"] = tp / (tp + fp) if (tp + fp) > 0 else 0
            metrics["recall"] = tp / (tp + fn) if (tp + fn) > 0 else 0
            metrics["f1"] = 2 * metrics["precision"] * metrics["recall"] / (metrics["precision"] + metrics["recall"]) if (metrics["precision"] + metrics["recall"]) > 0 else 0
            
            # AUC if we have probabilities
            try:
                from sklearn.metrics import roc_auc_score
                metrics["auc_roc"] = roc_auc_score(actual_binary, preds)
            except:
                pass
        
        # Latency metrics
        if self.latencies:
            metrics["latency_mean_ms"] = float(np.mean(self.latencies))
            metrics["latency_p50_ms"] = float(np.percentile(self.latencies, 50))
            metrics["latency_p95_ms"] = float(np.percentile(self.latencies, 95))
            metrics["latency_p99_ms"] = float(np.percentile(self.latencies, 99))
        
        # Error rate
        if self.errors:
            metrics["error_rate"] = sum(self.errors) / len(self.errors)
        
        # Prediction distribution
        valid_preds = [p.prediction for p in self.predictions if p.prediction is not None and not np.isnan(p.prediction)]
        if valid_preds:
            metrics["prediction_mean"] = float(np.mean(valid_preds))
            metrics["prediction_std"] = float(np.std(valid_preds))
            metrics["prediction_min"] = float(np.min(valid_preds))
            metrics["prediction_max"] = float(np.max(valid_preds))
        
        return metrics
    
    def check_alerts(self) -> List[ModelAlert]:
        """Check for performance alerts."""
        alerts = []
        metrics = self.compute_metrics()
        
        # Accuracy drop alert
        if "accuracy" in metrics and metrics["accuracy"] < self.alert_thresholds.get("min_accuracy", 0.70):
            alerts.append(ModelAlert(
                model_name=self.model_name,
                alert_type="low_accuracy",
                severity=AlertSeverity.CRITICAL,
                message=f"Model accuracy {metrics['accuracy']:.2f} fell below threshold",
                metric_value=metrics["accuracy"],
                threshold=self.alert_thresholds.get("min_accuracy", 0.70),
            ))
        
        # Latency alert
        if metrics.get("latency_p99_ms", 0) > self.alert_thresholds.get("latency_p99_ms", 5000):
            alerts.append(ModelAlert(
                model_name=self.model_name,
                alert_type="high_latency",
                severity=AlertSeverity.WARNING,
                message=f"P99 latency {metrics['latency_p99_ms']:.0f}ms exceeds threshold",
                metric_value=metrics["latency_p99_ms"],
                threshold=self.alert_thresholds["latency_p99_ms"],
            ))
        
        # Error rate alert
        if metrics.get("error_rate", 0) > self.alert_thresholds.get("error_rate", 0.05):
            alerts.append(ModelAlert(
                model_name=self.model_name,
                alert_type="high_error_rate",
                severity=AlertSeverity.CRITICAL,
                message=f"Error rate {metrics['error_rate']:.2%} exceeds threshold",
                metric_value=metrics["error_rate"],
                threshold=self.alert_thresholds["error_rate"],
            ))
        
        return alerts


class ModelMonitor:
    """Unified model monitoring combining drift detection and performance monitoring."""
    
    def __init__(
        self,
        model_name: str,
        model_version: str,
        drift_config: Optional[Dict[str, Any]] = None,
        performance_config: Optional[Dict[str, Any]] = None,
    ):
        self.model_name = model_name
        self.model_version = model_version
        
        drift_cfg = drift_config or {}
        perf_cfg = performance_config or {}
        
        self.drift_detector = DriftDetector(
            model_name=model_name,
            reference_window_days=drift_cfg.get("reference_window_days", 7),
            detection_window_days=drift_cfg.get("detection_window_days", 1),
            psi_threshold=drift_cfg.get("psi_threshold", 0.2),
            ks_threshold=drift_cfg.get("ks_threshold", 0.05),
            min_samples=drift_cfg.get("min_samples", 100),
        )
        
        self.performance_monitor = PerformanceMonitor(
            model_name=model_name,
            window_size=perf_cfg.get("window_size", 1000),
            alert_thresholds=perf_cfg.get("alert_thresholds"),
        )
        
        self.alerts: List[ModelAlert] = []
        self.alert_handlers: List[Callable[[ModelAlert], None]] = []
    
    def add_alert_handler(self, handler: Callable[[ModelAlert], None]) -> None:
        """Add a handler for alerts (e.g., send to monitoring system)."""
        self.alert_handlers.append(handler)
    
    def record_prediction(self, record: PredictionRecord) -> None:
        """Record a prediction for both drift and performance monitoring."""
        self.drift_detector.add_prediction(record)
        self.performance_monitor.record_prediction(record)
    
    def record_actual(self, request_id: str, actual: float) -> bool:
        """Record actual outcome for a prediction."""
        return self.performance_monitor.record_actual(request_id, actual)
    
    def set_reference_data(
        self,
        predictions: List[float],
        features: Dict[str, List[float]],
    ) -> None:
        """Set reference data for drift detection."""
        self.drift_detector.set_reference_data(predictions, features)
    
    def check_alerts(self) -> List[ModelAlert]:
        """Check for all alerts."""
        alerts = []
        alerts.extend(self.drift_detector.check_drift())
        alerts.extend(self.performance_monitor.check_alerts())
        
        # Fire alert handlers
        for alert in alerts:
            self.alerts.append(alert)
            for handler in self.alert_handlers:
                try:
                    handler(alert)
                except Exception:
                    pass  # Don't let handler errors break monitoring
        
        return alerts
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all monitoring data for dashboard."""
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "drift_statistics": self.drift_detector.get_statistics(),
            "performance_metrics": self.performance_monitor.compute_metrics(),
            "recent_alerts": [a.to_dict() for a in self.alerts[-10:]],
            "alert_count": len(self.alerts),
        }
    
    def export_metrics_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        metrics = self.performance_monitor.compute_metrics()
        drift_stats = self.drift_detector.get_statistics()
        
        # Performance metrics
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                lines.append(f'changetrace_model_{self.model_name}_{key} {value}')
        
        # Drift metrics
        for key, value in drift_stats.items():
            if isinstance(value, (int, float)):
                lines.append(f'changetrace_model_{self.model_name}_drift_{key} {value}')
        
        # Alert count
        lines.append(f'changetrace_model_{self.model_name}_alerts_total {len(self.alerts)}')
        
        return "\n".join(lines)


# Global model monitors registry
_model_monitors: Dict[str, ModelMonitor] = {}


def get_model_monitor(model_name: str, model_version: str = "1.0") -> ModelMonitor:
    """Get or create a model monitor."""
    key = f"{model_name}:{model_version}"
    if key not in _model_monitors:
        _model_monitors[key] = ModelMonitor(model_name, model_version)
    return _model_monitors[key]


def record_prediction(
    model_name: str,
    model_version: str,
    prediction: float,
    features: Dict[str, float],
    request_id: str = "",
    latency_ms: float = 0.0,
) -> None:
    """Convenience function to record a prediction."""
    monitor = get_model_monitor(model_name, model_version)
    record = PredictionRecord(
        model_name=model_name,
        model_version=model_version,
        prediction=prediction,
        features=features,
        request_id=request_id,
        latency_ms=latency_ms,
    )
    monitor.record_prediction(record)


def record_actual(model_name: str, model_version: str, request_id: str, actual: float) -> bool:
    """Convenience function to record actual outcome."""
    monitor = get_model_monitor(model_name, model_version)
    return monitor.record_actual(request_id, actual)