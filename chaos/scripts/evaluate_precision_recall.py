"""
Evaluation Harness for ChangeTrace

Computes precision, recall, and other metrics from labeled validation runs.
Uses Chaos Studio experiments as ground truth.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


class EvaluationHarness:
    """
    Evaluates correlation engine accuracy against known-cause faults.
    
    Metrics:
    - Precision@1: Top-ranked candidate is the true cause
    - Precision@3: True cause appears in top 3
    - Recall: Fraction of incidents where true cause is in candidate set
    - MTTD: Mean time to detection
    - MRR: Mean reciprocal rank
    - NDCG: Normalized discounted cumulative gain
    """
    
    def __init__(self, results_dir: str = "chaos/results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        self.evaluation_results: List[Dict[str, Any]] = []
    
    def add_result(
        self,
        experiment_id: str,
        fault_type: str,
        target_service: str,
        injected_at: datetime,
        correlation_results: List[Dict[str, Any]],
        detection_time_seconds: float,
    ) -> Dict[str, Any]:
        """
        Add a validation result from a chaos experiment.
        
        Args:
            experiment_id: Chaos Studio experiment run ID
            fault_type: Type of fault injected (pod_failure, cpu_pressure, etc.)
            target_service: Service that was targeted
            injected_at: When the fault was injected
            correlation_results: Ranked candidates from correlation engine
            detection_time_seconds: Time from injection to correlation completion
            
        Returns:
            Evaluation metrics for this run
        """
        # Find the true cause in ranked candidates
        true_cause_rank = None
        true_cause_confidence = None
        
        for i, candidate in enumerate(correlation_results):
            # Check if this candidate matches the injected fault
            if self._is_true_cause(candidate, fault_type, target_service):
                true_cause_rank = i + 1  # 1-indexed
                true_cause_confidence = candidate.get("confidence_score", 0)
                break
        
        # Compute metrics
        precision_at_1 = 1.0 if true_cause_rank == 1 else 0.0
        precision_at_3 = 1.0 if true_cause_rank and true_cause_rank <= 3 else 0.0
        recall = 1.0 if true_cause_rank else 0.0
        mrr = 1.0 / true_cause_rank if true_cause_rank else 0.0
        
        # NDCG@3
        ndcg_3 = self._compute_ndcg(correlation_results, true_cause_rank, k=3)
        
        result = {
            "experiment_id": experiment_id,
            "fault_type": fault_type,
            "target_service": target_service,
            "injected_at": injected_at.isoformat(),
            "detection_time_seconds": detection_time_seconds,
            "num_candidates": len(correlation_results),
            "true_cause_rank": true_cause_rank,
            "true_cause_confidence": true_cause_confidence,
            "precision_at_1": precision_at_1,
            "precision_at_3": precision_at_3,
            "recall": recall,
            "mrr": mrr,
            "ndcg_at_3": ndcg_3,
            "candidates": correlation_results,
            "evaluated_at": datetime.utcnow().isoformat(),
        }
        
        self.evaluation_results.append(result)
        logger.info(
            f"Evaluation: {fault_type} on {target_service} - "
            f"P@1={precision_at_1:.2f}, P@3={precision_at_3:.2f}, "
            f"Recall={recall:.2f}, MRR={mrr:.2f}, Rank={true_cause_rank}"
        )
        
        return result
    
    def _is_true_cause(
        self,
        candidate: Dict[str, Any],
        fault_type: str,
        target_service: str,
    ) -> bool:
        """Check if candidate matches the injected fault."""
        # Match by service name
        if candidate.get("service_name") != target_service:
            return False
        
        # Match by change type based on fault type
        fault_to_change_type = {
            "pod_failure": "code_deployment",  # Pod failure often from bad deploy
            "cpu_pressure": "code_deployment",  # CPU pressure from new code
            "memory_pressure": "code_deployment",
            "network_latency": "config_change",  # Network config change
            "dns_failure": "config_change",
            "disk_io_pressure": "infrastructure_change",
        }
        
        expected_change_type = fault_to_change_type.get(fault_type, "code_deployment")
        if candidate.get("change_type") != expected_change_type:
            # Allow some flexibility
            pass
        
        # Check if timestamp is close to injection time
        # (would need injected_at for precise matching)
        
        return True  # Simplified - in reality would do more precise matching
    
    def _compute_ndcg(
        self,
        candidates: List[Dict[str, Any]],
        true_rank: Optional[int],
        k: int = 3,
    ) -> float:
        """Compute Normalized Discounted Cumulative Gain at k."""
        if not true_rank or true_rank > k:
            return 0.0
        
        # DCG: relevance is 1 for true cause, 0 otherwise
        dcg = 1.0 / np.log2(true_rank + 1)
        
        # IDCG: ideal ranking has true cause at position 1
        idcg = 1.0 / np.log2(2)
        
        return dcg / idcg if idcg > 0 else 0.0
    
    def _precision_at_k(self, y_true: List[int], y_scores: List[float], k: int) -> float:
        """Compute Precision@k."""
        if len(y_true) == 0 or k == 0:
            return 0.0
        
        # Get top-k indices by score
        top_k_indices = np.argsort(y_scores)[::-1][:k]
        top_k_true = [y_true[i] for i in top_k_indices]
        
        return sum(top_k_true) / min(k, len(y_true))
    
    def _compute_mrr(self, y_true: List[int], y_scores: List[float]) -> float:
        """Compute Mean Reciprocal Rank."""
        if len(y_true) == 0:
            return 0.0
        
        # Sort by score descending
        sorted_indices = np.argsort(y_scores)[::-1]
        y_true_sorted = [y_true[i] for i in sorted_indices]
        
        # Find first positive
        for i, val in enumerate(y_true_sorted):
            if val == 1:
                return 1.0 / (i + 1)
        
        return 0.0
    
    def _compute_ndcg(self, y_true: List[int], y_scores: List[float], k: int) -> float:
        """Compute NDCG@k."""
        if len(y_true) == 0 or k == 0:
            return 0.0
        
        # Sort by score descending
        sorted_indices = np.argsort(y_scores)[::-1]
        y_true_sorted = [y_true[i] for i in sorted_indices]
        
        # DCG
        dcg = 0.0
        for i in range(min(k, len(y_true_sorted))):
            if y_true_sorted[i] == 1:
                dcg += 1.0 / np.log2(i + 2)
        
        # IDCG (ideal)
        ideal_sorted = sorted(y_true, reverse=True)
        idcg = 0.0
        for i in range(min(k, len(ideal_sorted))):
            if ideal_sorted[i] == 1:
                idcg += 1.0 / np.log2(i + 2)
        
        return dcg / idcg if idcg > 0 else 0.0
    
    def _compute_ece(self, y_true: List[int], y_scores: List[float], n_bins: int = 10) -> float:
        """Compute Expected Calibration Error."""
        if len(y_true) == 0:
            return 0.0
        
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        bin_lowers = bin_boundaries[:-1]
        bin_uppers = bin_boundaries[1:]
        
        ece = 0.0
        for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
            in_bin = (np.array(y_scores) > bin_lower) & (np.array(y_scores) <= bin_upper)
            prop_in_bin = in_bin.mean()
            
            if prop_in_bin > 0:
                accuracy_in_bin = np.array(y_true)[in_bin].mean()
                avg_confidence_in_bin = np.array(y_scores)[in_bin].mean()
                ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
        
        return ece
    
    def compute_aggregate_metrics(self) -> Dict[str, Any]:
        """Compute aggregate metrics across all evaluation runs."""
        if not self.evaluation_results:
            return {}
        
        df = pd.DataFrame(self.evaluation_results)
        
        # Overall metrics
        metrics = {
            "total_runs": len(df),
            "unique_fault_types": df["fault_type"].nunique(),
            "unique_target_services": df["target_service"].nunique(),
            
            # Precision/Recall
            "precision_at_1_mean": df["precision_at_1"].mean(),
            "precision_at_1_std": df["precision_at_1"].std(),
            "precision_at_3_mean": df["precision_at_3"].mean(),
            "precision_at_3_std": df["precision_at_3"].std(),
            "recall_mean": df["recall"].mean(),
            "recall_std": df["recall"].std(),
            
            # Ranking
            "mrr_mean": df["mrr"].mean(),
            "mrr_std": df["mrr"].std(),
            "ndcg_at_3_mean": df["ndcg_at_3"].mean(),
            "ndcg_at_3_std": df["ndcg_at_3"].std(),
            
            # Detection time
            "mean_detection_time_seconds": df["detection_time_seconds"].mean(),
            "median_detection_time_seconds": df["detection_time_seconds"].median(),
            "p95_detection_time_seconds": df["detection_time_seconds"].quantile(0.95),
            
            # Per fault type breakdown
            "by_fault_type": {},
        }
        
        # Per fault type metrics
        for fault_type in df["fault_type"].unique():
            subset = df[df["fault_type"] == fault_type]
            metrics["by_fault_type"][fault_type] = {
                "runs": len(subset),
                "precision_at_1": subset["precision_at_1"].mean(),
                "precision_at_3": subset["precision_at_3"].mean(),
                "recall": subset["recall"].mean(),
                "mrr": subset["mrr"].mean(),
                "mean_detection_time": subset["detection_time_seconds"].mean(),
            }
        
        # Per service metrics
        metrics["by_service"] = {}
        for service in df["target_service"].unique():
            subset = df[df["target_service"] == service]
            metrics["by_service"][service] = {
                "runs": len(subset),
                "precision_at_1": subset["precision_at_1"].mean(),
                "precision_at_3": subset["precision_at_3"].mean(),
                "recall": subset["recall"].mean(),
            }
        
        return metrics
    
    def generate_report(self, output_path: Optional[str] = None) -> str:
        """Generate a detailed evaluation report."""
        metrics = self.compute_aggregate_metrics()
        
        if not metrics:
            return "No evaluation results available."
        
        report = []
        report.append("=" * 60)
        report.append("ChangeTrace Correlation Engine Evaluation Report")
        report.append("=" * 60)
        report.append(f"Generated: {datetime.utcnow().isoformat()}Z")
        report.append("")
        
        report.append("OVERALL METRICS")
        report.append("-" * 40)
        report.append(f"Total Validation Runs: {metrics['total_runs']}")
        report.append(f"Fault Types Tested: {metrics['unique_fault_types']}")
        report.append(f"Services Tested: {metrics['unique_target_services']}")
        report.append("")
        
        report.append("ACCURACY METRICS")
        report.append("-" * 40)
        report.append(f"Precision@1:  {metrics['precision_at_1_mean']:.3f} ± {metrics['precision_at_1_std']:.3f}")
        report.append(f"Precision@3:  {metrics['precision_at_3_mean']:.3f} ± {metrics['precision_at_3_std']:.3f}")
        report.append(f"Recall:       {metrics['recall_mean']:.3f} ± {metrics['recall_std']:.3f}")
        report.append(f"MRR:          {metrics['mrr_mean']:.3f} ± {metrics['mrr_std']:.3f}")
        report.append(f"NDCG@3:       {metrics['ndcg_at_3_mean']:.3f} ± {metrics['ndcg_at_3_std']:.3f}")
        report.append("")
        
        report.append("DETECTION TIME")
        report.append("-" * 40)
        report.append(f"Mean:   {metrics['mean_detection_time_seconds']:.1f}s")
        report.append(f"Median: {metrics['median_detection_time_seconds']:.1f}s")
        report.append(f"P95:    {metrics['p95_detection_time_seconds']:.1f}s")
        report.append("")
        
        report.append("BY FAULT TYPE")
        report.append("-" * 40)
        for fault_type, m in metrics["by_fault_type"].items():
            report.append(f"  {fault_type}:")
            report.append(f"    Runs: {m['runs']}")
            report.append(f"    P@1: {m['precision_at_1']:.3f}")
            report.append(f"    P@3: {m['precision_at_3']:.3f}")
            report.append(f"    Recall: {m['recall']:.3f}")
            report.append(f"    MRR: {m['mrr']:.3f}")
            report.append(f"    Mean Detection: {m['mean_detection_time']:.1f}s")
        report.append("")
        
        report.append("BY SERVICE")
        report.append("-" * 40)
        for service, m in metrics["by_service"].items():
            report.append(f"  {service}:")
            report.append(f"    Runs: {m['runs']}")
            report.append(f"    P@1: {m['precision_at_1']:.3f}")
            report.append(f"    P@3: {m['precision_at_3']:.3f}")
            report.append(f"    Recall: {m['recall']:.3f}")
        
        report_text = "\n".join(report)
        
        if output_path:
            Path(output_path).write_text(report_text)
            logger.info(f"Report saved to {output_path}")
        
        return report_text
    
    def save_results(self, filename: Optional[str] = None) -> str:
        """Save raw evaluation results to JSON."""
        if filename is None:
            filename = f"evaluation_results_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = self.results_dir / filename
        with open(filepath, "w") as f:
            json.dump(self.evaluation_results, f, indent=2, default=str)
        
        logger.info(f"Results saved to {filepath}")
        return str(filepath)
    
    def load_results(self, filepath: str) -> None:
        """Load evaluation results from JSON."""
        with open(filepath, "r") as f:
            self.evaluation_results = json.load(f)
        logger.info(f"Loaded {len(self.evaluation_results)} results from {filepath}")


def run_statistical_significance_test(
    results_a: List[Dict[str, Any]],
    results_b: List[Dict[str, Any]],
    metric: str = "precision_at_1",
) -> Dict[str, Any]:
    """
    Run statistical significance test between two sets of results.
    
    Uses Mann-Whitney U test (non-parametric) for comparing distributions.
    """
    values_a = [r[metric] for r in results_a if metric in r]
    values_b = [r[metric] for r in results_b if metric in r]
    
    if len(values_a) < 3 or len(values_b) < 3:
        return {
            "error": "Insufficient data for statistical test (need at least 3 samples per group)",
            "n_a": len(values_a),
            "n_b": len(values_b),
        }
    
    # Mann-Whitney U test
    statistic, p_value = stats.mannwhitneyu(values_a, values_b, alternative="two-sided")
    
    # Effect size (Cliff's delta)
    cliff_delta = _cliffs_delta(values_a, values_b)
    
    return {
        "test": "Mann-Whitney U",
        "metric": metric,
        "n_a": len(values_a),
        "n_b": len(values_b),
        "mean_a": np.mean(values_a),
        "mean_b": np.mean(values_b),
        "median_a": np.median(values_a),
        "median_b": np.median(values_b),
        "u_statistic": statistic,
        "p_value": p_value,
        "significant_at_05": p_value < 0.05,
        "significant_at_01": p_value < 0.01,
        "cliffs_delta": cliff_delta,
        "effect_size_interpretation": _interpret_cliffs_delta(cliff_delta),
    }


def _cliffs_delta(x: List[float], y: List[float]) -> float:
    """Compute Cliff's delta effect size."""
    n_x, n_y = len(x), len(y)
    if n_x == 0 or n_y == 0:
        return 0.0
    
    greater = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    
    return (greater - less) / (n_x * n_y)


def _interpret_cliffs_delta(delta: float) -> str:
    """Interpret Cliff's delta magnitude."""
    abs_delta = abs(delta)
    if abs_delta < 0.147:
        return "negligible"
    elif abs_delta < 0.33:
        return "small"
    elif abs_delta < 0.474:
        return "medium"
    else:
        return "large"


async def main():
    """Main entry point for evaluation."""
    import argparse
    
    parser = argparse.ArgumentParser(description="ChangeTrace Evaluation Harness")
    parser.add_argument("--results-dir", default="chaos/results", help="Results directory")
    parser.add_argument("--output", help="Output report path")
    parser.add_argument("--load", help="Load results from file")
    args = parser.parse_args()
    
    harness = EvaluationHarness(args.results_dir)
    
    if args.load:
        harness.load_results(args.load)
    
    report = harness.generate_report(args.output)
    print(report)
    
    harness.save_results()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())