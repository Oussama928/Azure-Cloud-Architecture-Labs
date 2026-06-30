"""
Retrain Trigger for Azure ML

Monitors for new training data and triggers model retraining when thresholds are met.
"""

import argparse
import logging
from datetime import datetime, timedelta
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
    """

    try:
        model = ml_client.models.get(name=model_name, label="latest")
    except Exception:
        logger.info(f"No existing model {model_name}, retrain needed")
        return {"should_retrain": True, "reason": "no_existing_model"}

    created_at = model.creation_context.created_at if model.creation_context else None
    if created_at:
        age_days = (datetime.utcnow() - created_at).days
        if age_days >= max_model_age_days:
            return {"should_retrain": True, "reason": f"model_age_{age_days}_days"}

    new_labels_count = _count_new_labels_since(ml_client, model_name, created_at)

    if new_labels_count >= min_new_labels:
        return {"should_retrain": True, "reason": f"new_labels_{new_labels_count}"}

    return {"should_retrain": False, "reason": "conditions_not_met"}


def _count_new_labels_since(ml_client: MLClient, model_name: str, since: datetime) -> int:
    """Count new labeled examples since last model training"""
    try:
        from services.shared.gremlin_client import get_gremlin_client
        client = get_gremlin_client()
        if client:
            since_iso = since.isoformat()
            query = f"g.V().hasLabel('TrainingRecord').has('recordedAt', gte('{since_iso}')).count()"
            res = client.submit(query)
            count = 0
            for item in res:
                count = int(item)
            return count
        logger.info(f"Checking for new labels since {since} for model {model_name}")
        return 0
    except Exception as e:
        logger.warning(f"Failed to count new labels: {e}")
        return 0


def trigger_retraining_pipeline(
    ml_client: MLClient,
    pipeline_name: str,
    model_type: str,
    parameters: dict[str, Any]
) -> str:
    """Trigger Azure ML pipeline for retraining."""

    from azure.ai.ml import command
    from azure.ai.ml import Input, Output

    job = command(
        code="./ml/training",
        command="python train_confidence_model.py --model_type ${{inputs.model_type}} --data_path ${{inputs.data_path}} --output_path ${{outputs.model_output}}",
        inputs={
            "model_type": model_type,
            "data_path": Input(type="uri_folder", path="azureml://datastores/workspaceblobstore/paths/training-data"),
        },
        outputs={
            "model_output": Output(type="uri_folder", mode="rw_mount"),
        },
        environment="changetrace-training-env",
        compute="cpu-cluster",
        display_name=f"retrain-{model_type}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
    )

    returned_job = ml_client.jobs.create_or_update(job)
    logger.info(f"Triggered retraining pipeline: {returned_job.name}")
    return returned_job.name


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

    credential = DefaultAzureCredential()
    ml_client = MLClient(
        credential=credential,
        subscription_id=args.subscription_id,
        resource_group_name=args.resource_group,
        workspace_name=args.workspace_name
    )

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
