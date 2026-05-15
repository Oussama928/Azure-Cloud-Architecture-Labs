"""
Run Chaos Experiment for ChangeTrace

Executes Azure Chaos Studio experiments and captures results for evaluation.
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List

from azure.identity import DefaultAzureCredential
from azure.mgmt.chaos import ChaosManagementClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChaosExperimentRunner:
    """Runs Chaos Studio experiments and collects results."""
    
    def __init__(
        self,
        subscription_id: str,
        resource_group: str,
        workspace_name: str
    ):
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.workspace_name = workspace_name
        
        credential = DefaultAzureCredential()
        self.client = ChaosManagementClient(credential, subscription_id)
    
    def run_experiment(
        self,
        experiment_name: str,
        target_service: str,
        parameters: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Run a chaos experiment and wait for completion.
        
        Returns experiment results including status, duration, and any errors.
        """
        logger.info(f"Starting experiment: {experiment_name}")
        
        # Start experiment
        experiment = self.client.experiments.begin_start(
            resource_group_name=self.resource_group,
            experiment_name=experiment_name,
            parameters=parameters or {}
        ).result()
        
        experiment_id = experiment.id
        logger.info(f"Experiment started: {experiment_id}")
        
        # Wait for completion
        result = self._wait_for_completion(experiment_name)
        
        # Add metadata
        result["experiment_name"] = experiment_name
        result["target_service"] = target_service
        result["started_at"] = datetime.utcnow().isoformat()
        result["subscription_id"] = self.subscription_id
        result["resource_group"] = self.resource_group
        
        return result
    
    def _wait_for_completion(
        self,
        experiment_name: str,
        poll_interval: int = 10,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """Poll experiment until completion or timeout."""
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            experiment = self.client.experiments.get(
                resource_group_name=self.resource_group,
                experiment_name=experiment_name
            )
            
            status = experiment.properties.status
            logger.info(f"Experiment status: {status}")
            
            if status in ["Succeeded", "Failed", "Cancelled"]:
                return {
                    "status": status,
                    "duration_seconds": time.time() - start_time,
                    "error": experiment.properties.error if status == "Failed" else None,
                    "completed_at": datetime.utcnow().isoformat()
                }
            
            time.sleep(poll_interval)
        
        return {
            "status": "Timeout",
            "duration_seconds": timeout,
            "error": "Experiment did not complete within timeout",
            "completed_at": datetime.utcnow().isoformat()
        }
    
    def run_experiment_suite(
        self,
        experiments: List[Dict[str, Any]],
        target_service: str
    ) -> List[Dict[str, Any]]:
        """Run multiple experiments in sequence."""
        
        results = []
        
        for exp_config in experiments:
            exp_name = exp_config["name"]
            params = exp_config.get("parameters", {})
            
            logger.info(f"Running experiment {exp_name} for {target_service}")
            
            try:
                result = self.run_experiment(exp_name, target_service, params)
                results.append(result)
                
                # Wait between experiments
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Experiment {exp_name} failed: {e}")
                results.append({
                    "experiment_name": exp_name,
                    "status": "Error",
                    "error": str(e),
                    "completed_at": datetime.utcnow().isoformat()
                })
        
        return results


def main():
    parser = argparse.ArgumentParser(description="Run Chaos Studio experiments")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--workspace-name", required=True)
    parser.add_argument("--experiment-name", help="Single experiment to run")
    parser.add_argument("--target-service", required=True, help="Target service label")
    parser.add_argument("--suite", help="Path to experiment suite JSON")
    parser.add_argument("--output", help="Output file for results")
    args = parser.parse_args()
    
    runner = ChaosExperimentRunner(
        args.subscription_id,
        args.resource_group,
        args.workspace_name
    )
    
    if args.suite:
        with open(args.suite, "r") as f:
            suite = json.load(f)
        
        results = runner.run_experiment_suite(suite["experiments"], args.target_service)
        
    elif args.experiment_name:
        result = runner.run_experiment(args.experiment_name, args.target_service)
        results = [result]
    
    else:
        parser.error("Either --experiment-name or --suite is required")
        return
    
    # Save results
    output = {
        "target_service": args.target_service,
        "run_at": datetime.utcnow().isoformat(),
        "results": results
    }
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        logger.info(f"Results saved to {args.output}")
    else:
        print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()