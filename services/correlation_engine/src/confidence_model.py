"""
Confidence Model for ChangeTrace Correlation Engine

ML model for ranking root cause candidates using gradient boosted trees (LightGBM).
Features include graph distance, temporal proximity, change type, and historical patterns.
"""

import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from .models.correlation import (
    CandidateRanking,
    FeatureVector,
    Incident,
    ModelMetrics,
    TrainingExample,
)

logger = logging.getLogger(__name__)


class ConfidenceModel:
    """
    Gradient boosted tree model for root cause confidence scoring.

    Uses LightGBM with calibration for well-calibrated probabilities.
    Features: graph topology, temporal proximity, change characteristics, historical patterns.
    """

    def __init__(
        self,
        model_path: str | None = None,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        max_depth: int = 6,
        num_leaves: int = 31,
        min_child_samples: int = 20,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42,
        calibrate: bool = True,
    ):
        self.model_path = model_path
        self.calibrate = calibrate

        # Base model parameters
        self.base_params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "max_depth": max_depth,
            "num_leaves": num_leaves,
            "min_child_samples": min_child_samples,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
            "random_state": random_state,
            "verbosity": -1,
            "n_jobs": -1,
        }

        self.model: lgb.LGBMClassifier | None = None
        self.calibrated_model: CalibratedClassifierCV | None = None
        self.feature_names = FeatureVector.feature_names()
        self.is_trained = False
        self.model_version = "1.0"
        self.training_metrics: ModelMetrics | None = None

    def train(
        self,
        training_examples: list[TrainingExample],
        validation_split: float = 0.2,
        calibrate_method: str = "isotonic",
    ) -> ModelMetrics:
        """
        Train the confidence model on labeled examples.

        Args:
            training_examples: List of training examples with features and labels
            validation_split: Fraction of data to use for validation
            calibrate_method: Calibration method ('isotonic' or 'sigmoid')

        Returns:
            ModelMetrics with evaluation results
        """
        if len(training_examples) < 10:
            raise ValueError(f"Need at least 10 training examples, got {len(training_examples)}")

        logger.info(f"Training confidence model on {len(training_examples)} examples")

        # Prepare features and labels
        X = np.array([ex.features.to_array() for ex in training_examples])
        y = np.array([ex.label for ex in training_examples])
        weights = np.array([ex.weight for ex in training_examples])

        # Split data
        X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
            X, y, weights, test_size=validation_split, random_state=42, stratify=y
        )

        logger.info(f"Train: {len(X_train)}, Val: {len(X_val)}, Positive rate: {y.mean():.3f}")

        # Train base model
        self.model = lgb.LGBMClassifier(**self.base_params)
        self.model.fit(
            X_train, y_train,
            sample_weight=w_train,
            eval_set=[(X_val, y_val)],
            eval_sample_weight=[w_val],
            callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
        )

        # Calibrate if requested
        if self.calibrate:
            logger.info("Calibrating model probabilities...")
            self.calibrated_model = CalibratedClassifierCV(
                self.model, method=calibrate_method, cv=None, ensemble="auto"
            )
            self.calibrated_model.fit(X_val, y_val, sample_weight=w_val)
            predictor = self.calibrated_model
        else:
            predictor = self.model

        # Evaluate
        metrics = self._evaluate(predictor, X_val, y_val, w_val)

        self.is_trained = True
        self.model_version = f"1.0-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        self.training_metrics = metrics

        logger.info(f"Training complete. Precision@1: {metrics.precision_at_1:.3f}, "
                   f"Recall: {metrics.recall:.3f}, AUC: {metrics.auc_roc:.3f}")

        return metrics

    def _evaluate(
        self,
        predictor: Any,
        X_val: np.ndarray,
        y_val: np.ndarray,
        w_val: np.ndarray,
    ) -> ModelMetrics:
        """Evaluate model on validation set"""
        # Get predictions
        y_pred_proba = predictor.predict_proba(X_val)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)

        # Basic metrics
        precision, recall, f1, _ = precision_recall_fscore_support(y_val, y_pred, average="binary")
        auc_roc = roc_auc_score(y_val, y_pred_proba, sample_weight=w_val)
        auc_pr = average_precision_score(y_val, y_pred_proba, sample_weight=w_val)
        brier = brier_score_loss(y_val, y_pred_proba, sample_weight=w_val)

        # Ranking metrics - group by incident
        # For simplicity, compute overall ranking metrics
        mrr = self._compute_mrr(y_val, y_pred_proba)
        ndcg_3 = self._compute_ndcg(y_val, y_pred_proba, k=3)
        ndcg_5 = self._compute_ndcg(y_val, y_pred_proba, k=5)

        # Precision@k
        precision_at_1 = self._precision_at_k(y_val, y_pred_proba, k=1)
        precision_at_3 = self._precision_at_k(y_val, y_pred_proba, k=3)
        precision_at_5 = self._precision_at_k(y_val, y_pred_proba, k=5)

        # Calibration error (ECE)
        calibration_error = self._compute_ece(y_val, y_pred_proba)

        metrics = ModelMetrics(
            model_version=self.model_version,
            precision_at_1=precision_at_1,
            precision_at_3=precision_at_3,
            precision_at_5=precision_at_5,
            recall=recall,
            f1_score=f1,
            auc_roc=auc_roc,
            auc_pr=auc_pr,
            mean_reciprocal_rank=mrr,
            ndcg_at_3=ndcg_3,
            ndcg_at_5=ndcg_5,
            calibration_error=calibration_error,
            brier_score=brier,
            num_samples=len(y_val),
            num_positive=int(y_val.sum()),
            num_negative=int((1 - y_val).sum()),
        )

        return metrics

    def _compute_mrr(self, y_true: np.ndarray, y_scores: np.ndarray) -> float:
        """Compute Mean Reciprocal Rank"""
        # Sort by score descending
        sorted_indices = np.argsort(y_scores)[::-1]
        y_true_sorted = y_true[sorted_indices]

        # Find first positive
        positive_indices = np.where(y_true_sorted == 1)[0]
        if len(positive_indices) == 0:
            return 0.0

        first_positive_rank = positive_indices[0] + 1
        return 1.0 / first_positive_rank

    def _compute_ndcg(self, y_true: np.ndarray, y_scores: np.ndarray, k: int) -> float:
        """Compute NDCG@k"""
        # Simple implementation for binary relevance
        sorted_indices = np.argsort(y_scores)[::-1]
        y_true_sorted = y_true[sorted_indices]

        # DCG
        dcg = 0.0
        for i in range(min(k, len(y_true_sorted))):
            if y_true_sorted[i] == 1:
                dcg += 1.0 / np.log2(i + 2)

        # IDCG (ideal)
        ideal_sorted = np.sort(y_true)[::-1]
        idcg = 0.0
        for i in range(min(k, len(ideal_sorted))):
            if ideal_sorted[i] == 1:
                idcg += 1.0 / np.log2(i + 2)

        return dcg / idcg if idcg > 0 else 0.0

    def _precision_at_k(self, y_true: np.ndarray, y_scores: np.ndarray, k: int) -> float:
        """Compute Precision@k"""
        sorted_indices = np.argsort(y_scores)[::-1]
        top_k = sorted_indices[:k]
        return y_true[top_k].mean() if len(top_k) > 0 else 0.0

    def _compute_ece(self, y_true: np.ndarray, y_scores: np.ndarray, n_bins: int = 10) -> float:
        """Compute Expected Calibration Error"""
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        bin_lowers = bin_boundaries[:-1]
        bin_uppers = bin_boundaries[1:]

        ece = 0.0
        for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
            in_bin = (y_scores > bin_lower) & (y_scores <= bin_upper)
            prop_in_bin = in_bin.mean()

            if prop_in_bin > 0:
                accuracy_in_bin = y_true[in_bin].mean()
                avg_confidence_in_bin = y_scores[in_bin].mean()
                ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin

        return ece

    def predict_proba(self, features: list[FeatureVector]) -> np.ndarray:
        """Predict probability of being root cause for each feature vector"""
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        X = np.array([f.to_array() for f in features])

        if self.calibrate and self.calibrated_model:
            return self.calibrated_model.predict_proba(X)[:, 1]
        else:
            return self.model.predict_proba(X)[:, 1]

    def predict(self, features: list[FeatureVector], threshold: float = 0.5) -> np.ndarray:
        """Predict binary label for each feature vector"""
        probas = self.predict_proba(features)
        return (probas >= threshold).astype(int)

    def rank_candidates(
        self,
        incident: Incident,
        candidates: list[CandidateRanking],
        feature_vectors: list[FeatureVector],
    ) -> list[CandidateRanking]:
        """
        Rank candidates by confidence score.

        Args:
            incident: The incident being analyzed
            candidates: List of candidate rankings to score
            feature_vectors: Feature vectors for each candidate (same order)

        Returns:
            Candidates sorted by confidence score (descending)
        """
        if len(candidates) != len(feature_vectors):
            raise ValueError("Candidates and feature vectors must have same length")

        if not candidates:
            return candidates

        # Get confidence scores
        scores = self.predict_proba(feature_vectors)

        # Update candidates with scores
        for candidate, score, fv in zip(candidates, scores, feature_vectors):
            candidate.confidence_score = float(score)
            candidate.graph_distance_score = self._compute_graph_distance_score(fv)
            candidate.temporal_proximity_score = self._compute_temporal_score(fv)
            candidate.change_type_score = self._compute_change_type_score(fv)
            candidate.historical_base_rate_score = self._compute_historical_score(fv)
            candidate.model_version = self.model_version
            candidate.ranked_at = datetime.utcnow()

        # Sort by confidence descending
        ranked = sorted(candidates, key=lambda c: c.confidence_score, reverse=True)

        return ranked

    def _compute_graph_distance_score(self, fv: FeatureVector) -> float:
        """Compute graph distance component score (0-1, closer = higher)"""
        # Exponential decay with distance
        return float(np.exp(-fv.graph_distance / 3.0))

    def _compute_temporal_score(self, fv: FeatureVector) -> float:
        """Compute temporal proximity score (0-1, closer = higher)"""
        # Exponential decay with time (hours)
        return float(np.exp(-fv.time_delta_hours / 12.0))

    def _compute_change_type_score(self, fv: FeatureVector) -> float:
        """Compute change type score based on historical failure rates"""
        # Deployments and infra changes typically higher risk
        if fv.is_deployment:
            return 0.8
        elif fv.is_infra_change:
            return 0.7
        elif fv.is_config_change:
            return 0.5
        elif fv.is_rollback:
            return 0.3
        return 0.4

    def _compute_historical_score(self, fv: FeatureVector) -> float:
        """Compute historical base rate score"""
        # Combine service incident rate and change failure rate
        service_rate = min(fv.service_incident_rate_7d * 10, 1.0)
        change_rate = min(fv.change_failure_rate_7d * 5, 1.0)
        return float((service_rate + change_rate) / 2)

    def save(self, path: str | None = None) -> str:
        """Save model to disk"""
        save_path = path or self.model_path
        if not save_path:
            raise ValueError("No model path specified")

        if not self.is_trained:
            raise ValueError("Cannot save untrained model")

        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            "model": self.model,
            "calibrated_model": self.calibrated_model,
            "feature_names": self.feature_names,
            "base_params": self.base_params,
            "calibrate": self.calibrate,
            "model_version": self.model_version,
            "is_trained": self.is_trained,
            "training_metrics": self.training_metrics.model_dump() if self.training_metrics else None,
        }

        with open(save_path, "wb") as f:
            pickle.dump(model_data, f)

        logger.info(f"Model saved to {save_path}")
        return str(save_path)

    @classmethod
    def load(cls, path: str) -> "ConfidenceModel":
        """Load model from disk"""
        with open(path, "rb") as f:
            model_data = pickle.load(f)

        instance = cls()
        instance.model = model_data["model"]
        instance.calibrated_model = model_data.get("calibrated_model")
        instance.feature_names = model_data["feature_names"]
        instance.base_params = model_data["base_params"]
        instance.calibrate = model_data.get("calibrate", True)
        instance.model_version = model_data["model_version"]
        instance.is_trained = model_data["is_trained"]

        if model_data.get("training_metrics"):
            instance.training_metrics = ModelMetrics(**model_data["training_metrics"])

        logger.info(f"Model loaded from {path} (version: {instance.model_version})")
        return instance

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance from trained model"""
        if not self.is_trained or not self.model:
            return {}

        importance = self.model.feature_importances_
        return dict(zip(self.feature_names, importance.tolist()))


class HeuristicConfidenceModel:
    """
    Heuristic-based confidence model for when ML model is not yet trained.

    Uses simple rules based on graph distance, temporal proximity, and change type.
    """

    def __init__(self):
        self.model_version = "heuristic-1.0"
        self.is_trained = True  # Always "trained"

    def rank_candidates(
        self,
        incident: Incident,
        candidates: list[CandidateRanking],
        feature_vectors: list[FeatureVector],
    ) -> list[CandidateRanking]:
        """Rank candidates using heuristic scoring"""
        for candidate, fv in zip(candidates, feature_vectors):
            # Heuristic scoring
            graph_score = np.exp(-fv.graph_distance / 3.0)
            temporal_score = np.exp(-fv.time_delta_hours / 12.0)

            # Change type weights
            if fv.is_deployment:
                change_score = 0.8
            elif fv.is_infra_change:
                change_score = 0.7
            elif fv.is_config_change:
                change_score = 0.5
            elif fv.is_rollback:
                change_score = 0.3
            else:
                change_score = 0.4

            # Historical
            historical_score = min((fv.service_incident_rate_7d * 10 + fv.change_failure_rate_7d * 5) / 2, 1.0)

            # Weighted combination
            confidence = (
                0.35 * graph_score +
                0.30 * temporal_score +
                0.20 * change_score +
                0.15 * historical_score
            )

            candidate.confidence_score = float(confidence)
            candidate.graph_distance_score = float(graph_score)
            candidate.temporal_proximity_score = float(temporal_score)
            candidate.change_type_score = float(change_score)
            candidate.historical_base_rate_score = float(historical_score)
            candidate.model_version = self.model_version
            candidate.ranked_at = datetime.utcnow()

        return sorted(candidates, key=lambda c: c.confidence_score, reverse=True)

    def predict_proba(self, features: list[FeatureVector]) -> np.ndarray:
        """Predict probabilities using heuristic"""
        scores = []
        for fv in features:
            graph_score = np.exp(-fv.graph_distance / 3.0)
            temporal_score = np.exp(-fv.time_delta_hours / 12.0)

            if fv.is_deployment:
                change_score = 0.8
            elif fv.is_infra_change:
                change_score = 0.7
            elif fv.is_config_change:
                change_score = 0.5
            elif fv.is_rollback:
                change_score = 0.3
            else:
                change_score = 0.4

            historical_score = min((fv.service_incident_rate_7d * 10 + fv.change_failure_rate_7d * 5) / 2, 1.0)

            confidence = (
                0.35 * graph_score +
                0.30 * temporal_score +
                0.20 * change_score +
                0.15 * historical_score
            )
            scores.append(confidence)

        return np.array(scores)

    def save(self, path: str) -> str:
        """Save heuristic model (no-op)"""
        logger.info("Heuristic model has no persistent state")
        return path

    @classmethod
    def load(cls, path: str) -> "HeuristicConfidenceModel":
        """Load heuristic model"""
        return cls()

    def get_feature_importance(self) -> dict[str, float]:
        """Return heuristic feature weights"""
        return {
            "graph_distance": 0.35,
            "temporal_proximity": 0.30,
            "change_type": 0.20,
            "historical_base_rate": 0.15,
        }
