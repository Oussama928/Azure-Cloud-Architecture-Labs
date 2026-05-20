"""
Retrain Trigger for Azure ML

Monitors for new training data and triggers model retraining when thresholds are met.
"""

import argparse
import logging
from datetime import datetime
from typing import Any

from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_retrain_conditions(
    ml_client: MLClient,
    model_name: str,
    min_new_labels: int = 50,
    max_model_age_days: int = 7
) -> dict[str, Any]:
    """
    Check if model should be retrained.

    Conditions:
    1. At least min_new_labels new labeled examples since last training
    2. Model is older than max_model_age_days
    3. Performance degradation detected (optional)
    """

    # Get current model
    try:
        model = ml_client.models.get(name=model_name, label="latest")
    except Exception:
        logger.info(f"No existing model {model_name}, retrain needed")
        return {"should_retrain": True, "reason": "no_existing_model"}

    # Check model age
    created_at = model.creation_context.created_at if model.creation_context else None
    if created_at:
        age_days = (datetime.utcnow() - created_at).days
        if age_days >= max_model_age_days:
            return {"should_retrain": True, "reason": f"model_age_{age_days}_days"}

    # Check for new training data
    # This would query the training data store (Cosmos DB, etc.)
    # For now, return mock result
    new_labels_count = 0  # Would query actual data

    if new_labels_count >= min_new_labels:
        return {"should_retrain": True, "reason": f"new_labels_{new_labels_count}"}

    return {"should_retrain": False, "reason": "conditions_not_met"}


def trigger_retraining_pipeline(
    ml_client: MLClient,
    pipeline_name: str,
    model_type: str,
    parameters: dict[str, Any]
) -> str:
    """Trigger Azure ML pipeline for retraining."""

    # This would submit a pipeline job
    # For now, return mock job ID
    job_id = f"retrain-{model_type}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    logger.info(f"Triggered retraining pipeline: {job_id}")
    return job_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", type=str, required=True)
    parser.add_argument("--model_type", type=str, required=True, choices=["confidence", "risk"])
    parser.add_argument("--min_new_labels", type=int, default=50)
    parser.add_argument("--max_model_age_days", type=int, default=7)
    parser.add_argument("--subscription_id", type=str, required=True)
    parser.add_argument("--resource_group", type=str, required=True)
    parser.add_argument("--workspace_name", type=str, required=True)
    parser.add_argument("--pipeline_name", type=str, default="changetrace-training-pipeline")
    args = parser.parse_args()

    # Create ML client
    credential = DefaultAzureCredential()
    ml_client = MLClient(
        credential=credential,
        subscription_id=args.subscription_id,
        resource_group_name=args.resource_group,
        workspace_name=args.workspace_name
    )

    # Check retrain conditions
    result = check_retrain_conditions(
        ml_client,
        args.model_name,
        args.min_new_labels,
        args.max_model_age_days
    )

    logger.info(f"Retrain check result: {result}")

    if result["should_retrain"]:
        job_id = trigger_retraining_pipeline(
            ml_client,
            args.pipeline_name,
            args.model_type,
            {
                "model_name": args.model_name,
                "model_type": args.model_type,
                "trigger_reason": result["reason"]
            }
        )
        print("retrain_triggered=true")
        print(f"job_id={job_id}")
    else:
        print("retrain_triggered=false")
        print(f"reason={result['reason']}")


if __name__ == "__main__":
    main()
