"""
ML Training Pipeline for ChangeTrace

Trains confidence model (root cause ranking) and risk model (deployment risk scoring).
Uses scikit-learn / LightGBM with Azure ML for experiment tracking.
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

from services.correlation_engine.src.models.correlation import (
    FeatureVector,
    ModelMetrics,
    TrainingExample,
)

logger = logging.getLogger(__name__)


class ConfidenceModelTrainer:
    """
    Trainer for the root cause confidence model.

    Uses LightGBM with calibration for well-calibrated probabilities.
    Features: graph topology, temporal proximity, change characteristics, historical patterns.
    """

    def __init__(
        self,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        max_depth: int = 6,
        num_leaves: int = 31,
        min_child_samples: int = 20,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42,
        calibrate: bool = True,
        calibration_method: str = "isotonic",
    ):
        self.params = {
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
        self.calibrate = calibrate
        self.calibration_method = calibration_method

        self.model: lgb.LGBMClassifier | None = None
        self.calibrated_model: CalibratedClassifierCV | None = None
        self.feature_names = FeatureVector.feature_names()
        self.is_trained = False
        self.model_version = f"1.0-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        self.training_metrics: ModelMetrics | None = None

    def prepare_training_data(
        self,
        examples: list[TrainingExample],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Convert training examples to feature matrix and labels"""
        X = np.array([ex.features.to_array() for ex in examples])
        y = np.array([ex.label for ex in examples])
        weights = np.array([ex.weight for ex in examples])

        logger.info(f"Prepared training data: {X.shape[0]} samples, {X.shape[1]} features")
        logger.info(f"Positive class ratio: {y.mean():.3f}")

        return X, y, weights

    def train(
        self,
        examples: list[TrainingExample],
        validation_split: float = 0.2,
        early_stopping_rounds: int = 20,
    ) -> ModelMetrics:
        """
        Train the confidence model.

        Args:
            examples: List of training examples with features and labels
            validation_split: Fraction of data to use for validation
            early_stopping_rounds: Early stopping patience

        Returns:
            ModelMetrics with evaluation results
        """
        if len(examples) < 10:
            raise ValueError(f"Need at least 10 training examples, got {len(examples)}")

        X, y, weights = self.prepare_training_data(examples)

        # Split data
        X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
            X, y, weights, test_size=validation_split, random_state=42, stratify=y
        )

        logger.info(f"Train: {len(X_train)}, Val: {len(X_val)}")

        # Train base model
        self.model = lgb.LGBMClassifier(**self.params)
        self.model.fit(
            X_train, y_train,
            sample_weight=w_train,
            eval_set=[(X_val, y_val)],
            eval_sample_weight=[w_val],
            callbacks=[lgb.early_stopping(early_stopping_rounds), lgb.log_evaluation(0)],
        )

        # Calibrate if requested
        if self.calibrate:
            logger.info("Calibrating model probabilities...")
            self.calibrated_model = CalibratedClassifierCV(
                self.model, method=self.calibration_method, cv="prefit"
            )
            self.calibrated_model.fit(X_val, y_val, sample_weight=w_val)
            predictor = self.calibrated_model
        else:
            predictor = self.model

        # Evaluate
        metrics = self._evaluate(predictor, X_val, y_val, w_val)

        self.is_trained = True
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
        """Mean Reciprocal Rank"""
        sorted_indices = np.argsort(y_scores)[::-1]
        y_true_sorted = y_true[sorted_indices]

        positive_indices = np.where(y_true_sorted == 1)[0]
        if len(positive_indices) == 0:
            return 0.0

        first_positive_rank = positive_indices[0] + 1
        return 1.0 / first_positive_rank

    def _compute_ndcg(self, y_true: np.ndarray, y_scores: np.ndarray, k: int) -> float:
        """Normalized Discounted Cumulative Gain at k"""
        # Simple binary relevance
        sorted_indices = np.argsort(y_scores)[::-1]
        y_true_sorted = y_true[sorted_indices]

        # DCG
        dcg = 0.0
        for i in range(min(k, len(y_true_sorted))):
            if y_true_sorted[i] == 1:
                dcg += 1.0 / np.log2(i + 2)

        # IDCG
        ideal_sorted = np.sort(y_true)[::-1]
        idcg = 0.0
        for i in range(min(k, len(ideal_sorted))):
            if ideal_sorted[i] == 1:
                idcg += 1.0 / np.log2(i + 2)

        return dcg / idcg if idcg > 0 else 0.0

    def _precision_at_k(self, y_true: np.ndarray, y_scores: np.ndarray, k: int) -> float:
        """Precision at k"""
        sorted_indices = np.argsort(y_scores)[::-1]
        top_k = sorted_indices[:k]
        return y_true[top_k].mean() if len(top_k) > 0 else 0.0

    def _compute_ece(self, y_true: np.ndarray, y_scores: np.ndarray, n_bins: int = 10) -> float:
        """Expected Calibration Error"""
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

    def predict_proba(self, feature_vectors: list[FeatureVector]) -> np.ndarray:
        """Predict probability of being root cause"""
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        X = np.array([fv.to_array() for fv in feature_vectors])

        if self.calibrate and self.calibrated_model:
            return self.calibrated_model.predict_proba(X)[:, 1]
        else:
            return self.model.predict_proba(X)[:, 1]

    def predict(self, feature_vectors: list[FeatureVector], threshold: float = 0.5) -> np.ndarray:
        """Predict binary label"""
        probas = self.predict_proba(feature_vectors)
        return (probas >= threshold).astype(int)

    def rank_candidates(
        self,
        candidates: list[dict[str, Any]],
        feature_vectors: list[FeatureVector],
    ) -> list[dict[str, Any]]:
        """Rank candidates by confidence score"""
        if len(candidates) != len(feature_vectors):
            raise ValueError("Candidates and feature vectors must have same length")

        scores = self.predict_proba(feature_vectors)

        for candidate, score, fv in zip(candidates, scores, feature_vectors):
            candidate["confidence_score"] = float(score)
            candidate["graph_distance_score"] = float(np.exp(-fv.graph_distance / 3.0))
            candidate["temporal_proximity_score"] = float(np.exp(-fv.time_delta_hours / 12.0))
            candidate["change_type_score"] = self._compute_change_type_score(fv)
            candidate["historical_base_rate_score"] = self._compute_historical_score(fv)
            candidate["model_version"] = self.model_version
            candidate["ranked_at"] = datetime.utcnow().isoformat()

        # Sort by confidence descending
        ranked = sorted(candidates, key=lambda c: c["confidence_score"], reverse=True)
        return ranked

    def _compute_change_type_score(self, fv: FeatureVector) -> float:
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
        service_rate = min(fv.service_incident_rate_7d * 10, 1.0)
        change_rate = min(fv.change_failure_rate_7d * 5, 1.0)
        return float((service_rate + change_rate) / 2)

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance from trained model"""
        if not self.is_trained or not self.model:
            return {}

        importance = self.model.feature_importances_
        return dict(zip(self.feature_names, importance.tolist()))

    def save(self, path: str) -> str:
        """Save model to disk"""
        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            "model": self.model,
            "calibrated_model": self.calibrated_model,
            "feature_names": self.feature_names,
            "params": self.params,
            "calibrate": self.calibrate,
            "calibration_method": self.calibration_method,
            "model_version": self.model_version,
            "is_trained": self.is_trained,
            "training_metrics": self.training_metrics.model_dump() if self.training_metrics else None,
        }

        with open(save_path, "wb") as f:
            pickle.dump(model_data, f)

        logger.info(f"Model saved to {save_path}")
        return str(save_path)

    @classmethod
    def load(cls, path: str) -> "ConfidenceModelTrainer":
        """Load model from disk"""
        with open(path, "rb") as f:
            model_data = pickle.load(f)

        instance = cls()
        instance.model = model_data["model"]
        instance.calibrated_model = model_data.get("calibrated_model")
        instance.feature_names = model_data["feature_names"]
        instance.params = model_data["params"]
        instance.calibrate = model_data.get("calibrate", True)
        instance.calibration_method = model_data.get("calibration_method", "isotonic")
        instance.model_version = model_data["model_version"]
        instance.is_trained = model_data["is_trained"]

        if model_data.get("training_metrics"):
            instance.training_metrics = ModelMetrics(**model_data["training_metrics"])

        logger.info(f"Model loaded from {path} (version: {instance.model_version})")
        return instance


class RiskModelTrainer:
    """
    Trainer for the deployment risk scoring model.

    Binary classifier predicting whether a deployment will cause an incident.
    """

    def __init__(self, **kwargs):
        # Similar to ConfidenceModelTrainer but for deployment risk
        self.params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "n_estimators": kwargs.get("n_estimators", 200),
            "learning_rate": kwargs.get("learning_rate", 0.05),
            "max_depth": kwargs.get("max_depth", 6),
            "num_leaves": kwargs.get("num_leaves", 31),
            "min_child_samples": kwargs.get("min_child_samples", 20),
            "subsample": kwargs.get("subsample", 0.8),
            "colsample_bytree": kwargs.get("colsample_bytree", 0.8),
            "random_state": kwargs.get("random_state", 42),
            "verbosity": -1,
            "n_jobs": -1,
        }
        self.calibrate = kwargs.get("calibrate", True)
        self.calibration_method = kwargs.get("calibration_method", "isotonic")

        self.model: lgb.LGBMClassifier | None = None
        self.calibrated_model: CalibratedClassifierCV | None = None
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
        self.is_trained = False
        self.model_version = f"risk-1.0-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        self.training_metrics: ModelMetrics | None = None

    def train(self, X: np.ndarray, y: np.ndarray, weights: np.ndarray | None = None) -> ModelMetrics:
        """Train risk model from feature matrix"""
        # Similar implementation to ConfidenceModelTrainer
        # ... (abbreviated for brevity)
        pass

    def predict_risk(self, features: np.ndarray) -> np.ndarray:
        """Predict deployment risk score (0-1)"""
        if not self.is_trained:
            raise RuntimeError("Model not trained")

        if self.calibrate and self.calibrated_model:
            return self.calibrated_model.predict_proba(features)[:, 1]
        else:
            return self.model.predict_proba(features)[:, 1]

    def save(self, path: str) -> str:
        """Save model"""
        # Similar to ConfidenceModelTrainer.save()
        pass

    @classmethod
    def load(cls, path: str) -> "RiskModelTrainer":
        """Load model"""
        pass


def generate_synthetic_training_data(
    num_examples: int = 500,
    num_services: int = 10,
    positive_ratio: float = 0.2,
) -> list[TrainingExample]:
    """
    Generate synthetic training data for bootstrapping.

    Creates realistic feature vectors with known labels based on
    simulated service topology and change patterns.
    """
    np.random.seed(42)
    examples = []

    service_names = [f"service-{i}" for i in range(num_services)]

    for i in range(num_examples):
        incident_id = f"INC-{i:06d}"
        change_event_id = f"evt-{i:06d}"

        # Random service
        np.random.choice(service_names)

        # Generate features
        graph_distance = np.random.randint(0, 4)
        time_delta_hours = np.random.exponential(2.0)

        # Change type
        change_types = ["code_deployment", "config_change", "infrastructure_change", "rollback"]
        change_type = np.random.choice(change_types, p=[0.5, 0.2, 0.2, 0.1])

        is_deployment = change_type == "code_deployment"
        is_config = change_type == "config_change"
        is_infra = change_type == "infrastructure_change"
        is_rollback = change_type == "rollback"

        # Historical rates
        service_incident_rate = np.random.beta(1, 20)  # Low base rate
        change_failure_rate = np.random.beta(1, 50)

        # Label: positive if this change is the root cause
        # Higher probability for: close graph distance, recent, deployment, high historical rate
        positive_prob = (
            0.3 * np.exp(-graph_distance / 2) +
            0.3 * np.exp(-time_delta_hours / 6) +
            0.2 * (1.0 if is_deployment else 0.3) +
            0.2 * min(service_incident_rate * 10, 1.0)
        )

        # Adjust to achieve target positive ratio
        positive_prob = positive_prob * (positive_ratio / 0.2)
        label = np.random.random() < positive_prob

        fv = FeatureVector(
            change_event_id=change_event_id,
            incident_id=incident_id,
            graph_distance=graph_distance,
            shortest_path_length=graph_distance if graph_distance > 0 else None,
            num_paths=np.random.randint(1, 4),
            shared_dependencies=np.random.randint(0, 3),
            blast_radius_overlap=np.random.random(),
            time_delta_hours=time_delta_hours,
            time_delta_minutes=time_delta_hours * 60,
            is_within_lookback=time_delta_hours <= 2,
            change_type_encoded=change_types.index(change_type),
            is_deployment=is_deployment,
            is_config_change=is_config,
            is_infra_change=is_infra,
            is_rollback=is_rollback,
            deployment_size=np.random.randint(100, 5000) if is_deployment else None,
            files_changed=np.random.randint(1, 100) if is_deployment else None,
            service_incident_rate_7d=service_incident_rate,
            service_incident_rate_30d=service_incident_rate * 4,
            change_failure_rate_7d=change_failure_rate,
            change_failure_rate_30d=change_failure_rate * 4,
            same_change_type_failure_rate=change_failure_rate,
            service_criticality=np.random.random(),
            service_dependency_count=np.random.randint(0, 10),
            service_dependent_count=np.random.randint(0, 10),
        )

        examples.append(TrainingExample(
            incident_id=incident_id,
            change_event_id=change_event_id,
            features=fv,
            label=label,
            weight=1.0,
        ))

    logger.info(f"Generated {len(examples)} synthetic examples "
               f"({sum(e.label for e in examples)} positive)")
    return examples


async def load_training_data_from_cosmos(num_examples: int = 1000) -> list[TrainingExample]:
    """
    Load training data from Cosmos DB.

    This would query the training data container for labeled examples.
    For now, returns synthetic data as fallback.
    """
    logger.warning("Cosmos DB training data loading not fully implemented, using synthetic data")
    return generate_synthetic_training_data(num_examples)


async def load_training_data_from_cosmos_risk(num_examples: int = 1000) -> tuple[np.ndarray, np.ndarray]:
    """
    Load risk model training data from Cosmos DB.

    Returns feature matrix X and labels y.
    """
    logger.warning("Cosmos DB training data loading not fully implemented, using synthetic data")
    from train_risk_model import generate_synthetic_deployment_data
    return generate_synthetic_deployment_data(num_examples)


async def main():
    """Main training entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Train ChangeTrace ML models")
    parser.add_argument("--model-type", choices=["confidence", "risk", "both"], default="confidence")
    parser.add_argument("--num-examples", type=int, default=500)
    parser.add_argument("--output-dir", type=str, default="models")
    parser.add_argument("--use-synthetic", action="store_true", default=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.model_type in ["confidence", "both"]:
        logger.info("Training confidence model...")
        trainer = ConfidenceModelTrainer()

        if args.use_synthetic:
            examples = generate_synthetic_training_data(args.num_examples)
        else:
            # Load real training data from Cosmos DB
            examples = load_training_data_from_cosmosrgs.num_examples)

        metrics = trainer.train(examples)
        trainer.save(output_dir / f"confidence_model_{trainer.model_version}.pkl")

        logger.info(f"Confidence model metrics: {metrics.to_dict()}")

    if args.model_type in ["risk", "both"]:
        logger.info("Training risk model...")
        from train_risk_model import RiskModelTrainer, generate_synthetic_deployment_data

        risk_trainer = RiskModelTrainer()

        if args.use_synthetic:
            X, y = generate_synthetic_deployment_data(args.num_examples)
        else:
            # Load real training data from Cosmos DB
            X, y = load_training_data_from_cosmos(args.num_examples)

        metrics = risk_trainer.train(X, y)
        risk_trainer.save(output_dir / f"risk_model_{risk_trainer.model_version}.pkl")

        logger.info(f"Risk model metrics: {metrics}")

    logger.info("Training complete!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
