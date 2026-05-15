"""
Register Model Component for Azure ML

Registers trained models in the Azure ML model registry.
"""

import argparse
import json
import logging
import os
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.entities import Model
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_path", type=str, required=True, help="Path to model directory")
    parser.add_argument("--model_name", type=str, required=True, help="Model name")
    parser.add_argument("--model_type", type=str, required=True, help="Model type (confidence or risk)")
    parser.add_argument("--metrics_path", type=str, required=True, help="Path to evaluation metrics JSON")
    parser.add_argument("--subscription_id", type=str, required=True)
    parser.add_argument("--resource_group", type=str, required=True)
    parser.add_argument("--workspace_name", type=str, required=True)
    args = parser.parse_args()
    
    # Load metrics
    with open(args.metrics_path, "r") as f:
        metrics = json.load(f)
    
    # Create ML client
    credential = DefaultAzureCredential()
    ml_client = MLClient(
        credential=credential,
        subscription_id=args.subscription_id,
        resource_group_name=args.resource_group,
        workspace_name=args.workspace_name
    )
    
    # Create model entity
    model = Model(
        path=args.model_path,
        name=args.model_name,
        version=None,  # Auto-increment
        type="custom_model",
        description=f"{args.model_type} model for ChangeTrace",
        tags={
            "model_type": args.model_type,
            "training_date": os.getenv("BUILD_BUILDDATE", "unknown"),
            "build_id": os.getenv("BUILD_BUILDID", "local"),
            **{f"metric_{k}": str(v) for k, v in metrics.items() if isinstance(v, (int, float))}
        }
    )
    
    # Register model
    registered_model = ml_client.models.create_or_update(model)
    
    logger.info(f"Registered model: {registered_model.name} version {registered_model.version}")
    
    # Output for pipeline
    print(f"model_name={registered_model.name}")
    print(f"model_version={registered_model.version}")


if __name__ == "__main__":
    main()