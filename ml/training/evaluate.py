"""
Model Evaluation for ChangeTrace

Evaluates trained models and generates metrics reports.
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, precision_recall_fscore_support,
    roc_auc_score, average_precision_score,
    ndcg_score, brier_score_loss
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def evaluate_confidence_model(
    model_path: str,
    test_data_path: str,
    output_path: str
) -> Dict[str, Any]:
    """Evaluate confidence model (root cause ranking)."""
    
    import joblib
    
    # Load model
    model = joblib.load(model_path)
    
    # Load test data
    test_data = pd.read_parquet(test_data_path)
    
    # Prepare features and labels
    feature_cols = [c for c in test_data.columns if c not in ["label", "incident_id", "change_event_id"]]
    X = test_data[feature_cols].values
    y = test_data["label"].values
    
    # Predict probabilities
    y_pred_proba = model.predict_proba(X)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)
    
    # Compute metrics
    precision, recall, f1, _ = precision_recall_fscore_support(y, y_pred, average="binary")
    auc_roc = roc_auc_score(y, y_pred_proba)
    auc_pr = average_precision_score(y, y_pred_proba)
    brier = brier_score_loss(y, y_pred_proba)
    
    # Ranking metrics (group by incident)
    ranking_metrics = compute_ranking_metrics(test_data, y_pred_proba)
    
    # Calibration
    calibration_error = compute_calibration_error(y, y_pred_proba)
    
    metrics = {
        "model_type": "confidence",
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "auc_roc": float(auc_roc),
        "auc_pr": float(auc_pr),
        "brier_score": float(brier),
        "calibration_error": float(calibration_error),
        "precision_at_1": ranking_metrics.get("precision_at_1", 0),
        "precision_at_3": ranking_metrics.get("precision_at_3", 0),
        "precision_at_5": ranking_metrics.get("precision_at_5", 0),
        "mrr": ranking_metrics.get("mrr", 0),
        "ndcg_at_3": ranking_metrics.get("ndcg_at_3", 0),
        "ndcg_at_5": ranking_metrics.get("ndcg_at_5", 0),
        "num_samples": len(y),
        "num_positive": int(y.sum()),
        "num_negative": int((1 - y).sum())
    }
    
    # Save metrics
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"Evaluation metrics saved to {output_path}")
    return metrics


def evaluate_risk_model(
    model_path: str,
    test_data_path: str,
    output_path: str
) -> Dict[str, Any]:
    """Evaluate risk model (deployment risk scoring)."""
    
    import joblib
    
    # Load model
    model = joblib.load(model_path)
    
    # Load test data
    test_data = pd.read_parquet(test_data_path)
    
    # Prepare features and labels
    feature_cols = [c for c in test_data.columns if c not in ["label", "deployment_id"]]
    X = test_data[feature_cols].values
    y = test_data["label"].values
    
    # Predict
    y_pred_proba = model.predict_proba(X)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)
    
    # Metrics
    precision, recall, f1, _ = precision_recall_fscore_support(y, y_pred, average="binary")
    auc_roc = roc_auc_score(y, y_pred_proba)
    auc_pr = average_precision_score(y, y_pred_proba)
    brier = brier_score_loss(y, y_pred_proba)
    calibration_error = compute_calibration_error(y, y_pred_proba)
    
    metrics = {
        "model_type": "risk",
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "auc_roc": float(auc_roc),
        "auc_pr": float(auc_pr),
        "brier_score": float(brier),
        "calibration_error": float(calibration_error),
        "num_samples": len(y),
        "num_positive": int(y.sum()),
        "num_negative": int((1 - y).sum())
    }
    
    # Save metrics
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"Risk model evaluation saved to {output_path}")
    return metrics


def compute_ranking_metrics(
    test_data: pd.DataFrame,
    scores: np.ndarray
) -> Dict[str, float]:
    """Compute ranking metrics grouped by incident."""
    
    test_data = test_data.copy()
    test_data["score"] = scores
    
    # Group by incident
    grouped = test_data.groupby("incident_id")
    
    precisions_at_1 = []
    precisions_at_3 = []
    precisions_at_5 = []
    mrrs = []
    ndcgs_at_3 = []
    ndcgs_at_5 = []
    
    for _, group in grouped:
        # Sort by score descending
        group = group.sort_values("score", ascending=False)
        
        # True labels in ranked order
        y_true = group["label"].values
        
        # Precision@k
        for k in [1, 3, 5]:
            if len(y_true) >= k:
                prec = y_true[:k].sum() / k
                if k == 1:
                    precisions_at_1.append(prec)
                elif k == 3:
                    precisions_at_3.append(prec)
                elif k == 5:
                    precisions_at_5.append(prec)
        
        # MRR
        positive_ranks = np.where(y_true == 1)[0]
        if len(positive_ranks) > 0:
            mrrs.append(1.0 / (positive_ranks[0] + 1))
        else:
            mrrs.append(0.0)
        
        # NDCG
        for k in [3, 5]:
            if len(y_true) >= k:
                # Ideal ranking (all positives first)
                ideal = np.sort(y_true)[::-1]
                dcg = sum(y_true[i] / np.log2(i + 2) for i in range(min(k, len(y_true))))
                idcg = sum(ideal[i] / np.log2(i + 2) for i in range(min(k, len(ideal))))
                ndcg = dcg / idcg if idcg > 0 else 0
                if k == 3:
                    ndcgs_at_3.append(ndcg)
                elif k == 5:
                    ndcgs_at_5.append(ndcg)
    
    return {
        "precision_at_1": float(np.mean(precisions_at_1)) if precisions_at_1 else 0,
        "precision_at_3": float(np.mean(precisions_at_3)) if precisions_at_3 else 0,
        "precision_at_5": float(np.mean(precisions_at_5)) if precisions_at_5 else 0,
        "mrr": float(np.mean(mrrs)) if mrrs else 0,
        "ndcg_at_3": float(np.mean(ndcgs_at_3)) if ndcgs_at_3 else 0,
        "ndcg_at_5": float(np.mean(ndcgs_at_5)) if ndcgs_at_5 else 0,
    }


def compute_calibration_error(
    y_true: np.ndarray,
    y_pred_proba: np.ndarray,
    n_bins: int = 10
) -> float:
    """Compute Expected Calibration Error (ECE)."""
    
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    
    ece = 0.0
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        in_bin = (y_pred_proba > bin_lower) & (y_pred_proba <= bin_upper)
        prop_in_bin = in_bin.mean()
        
        if prop_in_bin > 0:
            accuracy_in_bin = y_true[in_bin].mean()
            avg_confidence_in_bin = y_pred_proba[in_bin].mean()
            ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
    
    return float(ece)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_type", type=str, required=True, choices=["confidence", "risk"])
    parser.add_argument("--model_path", type=str, required=True)
    parser.add_argument("--test_data_path", type=str, required=True)
    parser.add_argument("--output_path", type=str, required=True)
    args = parser.parse_args()
    
    if args.model_type == "confidence":
        evaluate_confidence_model(args.model_path, args.test_data_path, args.output_path)
    else:
        evaluate_risk_model(args.model_path, args.test_data_path, args.output_path)


if __name__ == "__main__":
    main()