"""
Activity: Trigger Rollback via Argo Rollouts

Executes rollback or restart actions via Argo Rollouts API or Kubernetes API.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import azure.functions as func
import httpx

logger = logging.getLogger(__name__)


async def main(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute remediation action via Argo Rollouts / Kubernetes.
    
    Input:
    {
        "action": "rollback_deployment" | "restart_workload",
        "params": {
            "deployment_id": "deploy-123",
            "service": "payment-service",
            "namespace": "production"
        },
        "workflow_id": "wf-123"
    }
    
    Output:
    {
        "success": true,
        "action": "rollback_deployment",
        "details": {...},
        "executed_at": "2024-01-15T10:30:00Z"
    }
    """
    action = activity_input.get("action")
    params = activity_input.get("params", {})
    workflow_id = activity_input.get("workflow_id")
    
    logger.info(f"Executing remediation action: {action} for workflow {workflow_id}")
    
    if action == "rollback_deployment":
        result = await _rollback_deployment(params)
    elif action == "restart_workload":
        result = await _restart_workload(params)
    elif action == "revert_config":
        result = await _revert_config(params)
    elif action == "scale_up":
        result = await _scale_up(params)
    else:
        raise ValueError(f"Unknown action: {action}")
    
    result["action"] = action
    result["executed_at"] = datetime.utcnow().isoformat()
    result["workflow_id"] = workflow_id
    
    return result


async def _rollback_deployment(params: Dict[str, Any]) -> Dict[str, Any]:
    """Rollback Argo Rollout to previous version."""
    
    deployment_id = params.get("deployment_id")
    service = params.get("service")
    namespace = params.get("namespace", "production")
    
    if not deployment_id or not service:
        return {"success": False, "error": "deployment_id and service are required"}
    
    # Option 1: Argo Rollouts API 
    argo_api_url = os.getenv("ARGO_API_URL")
    argo_token = os.getenv("ARGO_API_TOKEN")
    
    if argo_api_url and argo_token:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Authorization": f"Bearer {argo_token}"}
                
                # Get rollout info
                rollout_name = f"{service}-rollout"
                response = await client.get(
                    f"{argo_api_url}/api/v1/namespaces/{namespace}/rollouts/{rollout_name}",
                    headers=headers
                )
                response.raise_for_status()
                rollout = response.json()
                
                # Trigger rollback
                response = await client.post(
                    f"{argo_api_url}/api/v1/namespaces/{namespace}/rollouts/{rollout_name}/rollback",
                    headers=headers,
                    json={"revision": 0}  # 0 = previous revision
                )
                response.raise_for_status()
                
                return {
                    "success": True,
                    "method": "argo_rollouts",
                    "rollout_name": rollout_name,
                    "namespace": namespace,
                    "deployment_id": deployment_id
                }
        except Exception as e:
            logger.warning(f"Argo Rollouts API failed: {e}, falling back to kubectl")
    
    # Option 2: kubectl fallback (requires kubectl in container)
    try:
        import subprocess
        rollout_name = f"{service}-rollout"
        
        # Get current revision
        result = subprocess.run(
            ["kubectl", "argo", "rollouts", "get", "rollout", rollout_name, "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=30
        )
        
        # Trigger rollback
        result = subprocess.run(
            ["kubectl", "argo", "rollouts", "rollback", rollout_name, "-n", namespace],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "method": "kubectl",
                "rollout_name": rollout_name,
                "namespace": namespace,
                "deployment_id": deployment_id
            }
        else:
            return {"success": False, "error": f"kubectl rollback failed: {result.stderr}"}
            
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        return {"success": False, "error": str(e)}


async def _restart_workload(params: Dict[str, Any]) -> Dict[str, Any]:
    """Restart Kubernetes workload (Deployment/StatefulSet/DaemonSet)."""
    
    service = params.get("service")
    namespace = params.get("namespace", "production")
    workload_type = params.get("workload_type", "deployment")
    
    if not service:
        return {"success": False, "error": "service is required"}
    
    try:
        import subprocess
        
        # Restart by patching annotation
        result = subprocess.run(
            [
                "kubectl", "patch", workload_type, service,
                "-n", namespace,
                "-p", f'"spec":{{"template":{{"metadata":{{"annotations":{{"kubectl.kubernetes.io/restartedAt":"{datetime.utcnow().isoformat()}"}}}}}}}}'
            ],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "method": "kubectl_patch",
                "service": service,
                "namespace": namespace,
                "workload_type": workload_type
            }
        else:
            return {"success": False, "error": f"kubectl patch failed: {result.stderr}"}
            
    except Exception as e:
        logger.error(f"Restart failed: {e}")
        return {"success": False, "error": str(e)}


async def _revert_config(params: Dict[str, Any]) -> Dict[str, Any]:
    """Revert ConfigMap/Secret to previous version."""
    
    # TODO: Implement config revert via Kubernetes API
    # This would require tracking config versions in change history
    
    return {
        "success": False,
        "error": "Config revert not yet implemented"
    }


async def _scale_up(params: Dict[str, Any]) -> Dict[str, Any]:
    """Scale up deployment replicas."""
    
    service = params.get("service")
    namespace = params.get("namespace", "production")
    replicas = params.get("replicas", 5)
    
    if not service:
        return {"success": False, "error": "service is required"}
    
    try:
        import subprocess
        
        result = subprocess.run(
            ["kubectl", "scale", "deployment", service, f"--replicas={replicas}", "-n", namespace],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "method": "kubectl_scale",
                "service": service,
                "namespace": namespace,
                "replicas": replicas
            }
        else:
            return {"success": False, "error": f"kubectl scale failed: {result.stderr}"}
            
    except Exception as e:
        logger.error(f"Scale up failed: {e}")
        return {"success": False, "error": str(e)}