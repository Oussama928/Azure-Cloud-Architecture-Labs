"""
Risk Model Training for ChangeTrace

Trains the deployment risk scoring model using historical deployment outcomes.
"""

import json
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

logger = logging.getLogger(__name__)


class RiskModelTrainer:
    """
    Trainer for the deployment risk scoring model.
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
        self.training_metrics: dict[str, Any] | None = None

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        weights: np.ndarray | None = None,
        validation_split: float = 0.2,
        early_stopping_rounds: int = 20,
    ) -> dict[str, Any]:
        """
        Train the risk model.
        """
        if len(X) < 10:
            raise ValueError(f"Need at least 10 training examples, got {len(X)}")

        if weights is None:
            weights = np.ones(len(X))

        X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
            X, y, weights, test_size=validation_split, random_state=42, stratify=y
        )

        logger.info(f"Train: {len(X_train)}, Val: {len(X_val)}, Positive rate: {y.mean():.3f}")

        self.model = lgb.LGBMClassifier(**self.params)
        self.model.fit(
            X_train, y_train,
            sample_weight=w_train,
            eval_set=[(X_val, y_val)],
            eval_sample_weight=[w_val],
            callbacks=[lgb.early_stopping(early_stopping_rounds), lgb.log_evaluation(0)],
        )

        if self.calibrate:
            logger.info("Calibrating model probabilities...")
            self.calibrated_model = CalibratedClassifierCV(
                self.model, method=self.calibration_method, cv="prefit"
            )
            self.calibrated_model.fit(X_val, y_val, sample_weight=w_val)
            predictor = self.calibrated_model
        else:
            predictor = self.model

        metrics = self._evaluate(predictor, X_val, y_val, w_val)

        self.is_trained = True
        self.training_metrics = metrics

        logger.info(f"Training complete. AUC-ROC: {metrics['auc_roc']:.3f}, "
                   f"Precision: {metrics['precision']:.3f}, Recall: {metrics['recall']:.3f}")

        return metrics

    def _evaluate(
        self,
        predictor: Any,
        X_val: np.ndarray,
        y_val: np.ndarray,
        w_val: np.ndarray,
    ) -> dict[str, Any]:
        """Evaluate model on validation set"""
        y_pred_proba = predictor.predict_proba(X_val)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)

        precision, recall, f1, _ = precision_recall_fscore_support(y_val, y_pred, average="binary")
        auc_roc = roc_auc_score(y_val, y_pred_proba, sample_weight=w_val)
        auc_pr = average_precision_score(y_val, y_pred_proba, sample_weight=w_val)
        brier = brier_score_loss(y_val, y_pred_proba, sample_weight=w_val)

        # Calibration error
        calibration_error = self._compute_ece(y_val, y_pred_proba)

        metrics = {
            "model_version": self.model_version,
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "auc_roc": float(auc_roc),
            "auc_pr": float(auc_pr),
            "brier_score": float(brier),
            "calibration_error": float(calibration_error),
            "num_samples": len(y_val),
            "num_positive": int(y_val.sum()),
            "num_negative": int((1 - y_val).sum()),
            "feature_importance": self.get_feature_importance(),
        }

        return metrics

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

        return float(ece)

    def predict_risk(self, features: np.ndarray) -> np.ndarray:
        """Predict deployment risk score (0-1)"""
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        if self.calibrate and self.calibrated_model:
            return self.calibrated_model.predict_proba(features)[:, 1]
        else:
            return self.model.predict_proba(features)[:, 1]

    def predict(self, features: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Predict binary label"""
        probas = self.predict_risk(features)
        return (probas >= threshold).astype(int)

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
            "training_metrics": self.training_metrics,
        }

        with open(save_path, "wb") as f:
            pickle.dump(model_data, f)

        logger.info(f"Risk model saved to {save_path}")
        return str(save_path)

    @classmethod
    def load(cls, path: str) -> "RiskModelTrainer":
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
        instance.training_metrics = model_data.get("training_metrics")

        logger.info(f"Risk model loaded from {path} (version: {instance.model_version})")
        return instance


def generate_synthetic_deployment_data(
    num_examples: int = 1000,
    positive_ratio: float = 0.15,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic deployment data for training.

    Features:
    - change_size: lines of code changed (log scale)
    - files_changed: number of files modified
    - services_affected: number of services touched
    - service_criticality: 0-1 criticality score
    - dependency_count: number of upstream dependencies
    - dependent_count: number of downstream dependents
    - recent_incidents_7d: incidents in last 7 days
    - recent_incidents_30d: incidents in last 30 days
    - change_failure_rate_7d: failure rate of recent changes
    - change_failure_rate_30d: failure rate of recent changes (30d)
    - time_since_last_deploy_hours: hours since last deployment
    - is_weekend: 1 if deployed on weekend
    - is_business_hours: 1 if deployed during business hours
    - team_experience_score: 0-1 team experience score
    """
    np.random.seed(42)

    n = num_examples
    n_pos = int(n * positive_ratio)
    n_neg = n - n_pos

    # Generate negative examples (safe deployments)
    X_neg = np.column_stack([
        np.random.lognormal(4, 1, n_neg),      # change_size
        np.random.poisson(5, n_neg),            # files_changed
        np.random.poisson(1, n_neg),            # services_affected
        np.random.beta(2, 5, n_neg),            # service_criticality
        np.random.poisson(3, n_neg),            # dependency_count
        np.random.poisson(2, n_neg),            # dependent_count
        np.random.poisson(0.5, n_neg),          # recent_incidents_7d
        np.random.poisson(2, n_neg),            # recent_incidents_30d
        np.random.beta(1, 50, n_neg),           # change_failure_rate_7d
        np.random.beta(1, 30, n_neg),           # change_failure_rate_30d
        np.random.exponential(48, n_neg),       # time_since_last_deploy_hours
        np.random.binomial(1, 0.3, n_neg),      # is_weekend
        np.random.binomial(1, 0.7, n_neg),      # is_business_hours
        np.random.beta(5, 2, n_neg),            # team_experience_score
    ])

    # Generate positive examples (failed deployments)
    X_pos = np.column_stack([
        np.random.lognormal(6, 1.5, n_pos),     # change_size (larger)
        np.random.poisson(20, n_pos),           # files_changed (more)
        np.random.poisson(3, n_pos),            # services_affected (more)
        np.random.beta(5, 2, n_pos),            # service_criticality (higher)
        np.random.poisson(6, n_pos),            # dependency_count (more)
        np.random.poisson(5, n_pos),            # dependent_count (more)
        np.random.poisson(2, n_pos),            # recent_incidents_7d (more)
        np.random.poisson(8, n_pos),            # recent_incidents_30d (more)
        np.random.beta(2, 20, n_pos),           # change_failure_rate_7d (higher)
        np.random.beta(2, 15, n_pos),           # change_failure_rate_30d (higher)
        np.random.exponential(12, n_pos),       # time_since_last_deploy_hours (shorter)
        np.random.binomial(1, 0.4, n_pos),      # is_weekend (more)
        np.random.binomial(1, 0.5, n_pos),      # is_business_hours (less)
        np.random.beta(2, 5, n_pos),            # team_experience_score (lower)
    ])

    X = np.vstack([X_neg, X_pos])
    y = np.hstack([np.zeros(n_neg), np.ones(n_pos)])

    indices = np.random.permutation(n)
    X = X[indices]
    y = y[indices]

    return X, y


def main():
    """Main training entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Train ChangeTrace risk model")
    parser.add_argument("--num-examples", type=int, default=1000)
    parser.add_argument("--output-dir", type=str, default="models")
    parser.add_argument("--positive-ratio", type=float, default=0.15)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Training risk model...")
    trainer = RiskModelTrainer()

    X, y = generate_synthetic_deployment_data(args.num_examples, args.positive_ratio)
    metrics = trainer.train(X, y)

    model_path = output_dir / f"risk_model_{trainer.model_version}.pkl"
    trainer.save(model_path)

    logger.info(f"Risk model metrics: {json.dumps(metrics, indent=2)}")
    logger.info("Training complete!")


if __name__ == "__main__":
    main()
