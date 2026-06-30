
"""
Seed Demo Data for ChangeTrace

Populates the system with realistic demo data for development and testing.
"""

import asyncio
import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any
import uuid

# Demo service topology (matches the deployed demo app in k8s/deployments)
SERVICES = [
    {"name": "api-gateway", "criticality": "high", "namespace": "production", "dependencies": ["auth-service", "payment-service", "order-service"]},
    {"name": "auth-service", "criticality": "high", "namespace": "production", "dependencies": []},
    {"name": "payment-service", "criticality": "critical", "namespace": "production", "dependencies": ["auth-service", "fraud-service"]},
    {"name": "fraud-service", "criticality": "high", "namespace": "production", "dependencies": []},
    {"name": "order-service", "criticality": "high", "namespace": "production", "dependencies": ["payment-service", "inventory-service"]},
    {"name": "inventory-service", "criticality": "medium", "namespace": "production", "dependencies": []},
    {"name": "notification-service", "criticality": "medium", "namespace": "production", "dependencies": []},
]

CHANGE_TYPES = ["code_deployment", "config_change", "infrastructure_change", "release", "rollback", "scale_event"]
SOURCES = ["github", "terraform", "kubernetes", "azure_resource_graph", "argo_rollouts"]

# SLO configurations
SLOS = {
    "api-gateway": {"availability": 99.9, "latency_p99": 200},
    "auth-service": {"availability": 99.95, "latency_p99": 100},
    "payment-service": {"availability": 99.99, "latency_p99": 500},
    "fraud-service": {"availability": 99.9, "latency_p99": 300},
    "order-service": {"availability": 99.9, "latency_p99": 400},
    "inventory-service": {"availability": 99.9, "latency_p99": 200},
    "notification-service": {"availability": 99.5, "latency_p99": 1000},
}


async def generate_dependency_graph() -> List[Dict[str, Any]]:
    """Generate service dependency graph vertices and edges."""
    vertices = []
    edges = []
    
    for svc in SERVICES:
        vertices.append({
            "id": svc["name"],
            "label": "Service",
            "properties": {
                "serviceName": svc["name"],
                "criticality": svc["criticality"],
                "namespace": svc["namespace"],
                "sloTargets": SLOS.get(svc["name"], {}),
            }
        })
        
        for dep in svc["dependencies"]:
            edges.append({
                "source": svc["name"],
                "target": dep,
                "label": "depends_on",
                "properties": {
                    "type": "runtime",
                    "latencyP99": random.randint(5, 100),
                }
            })
    
    return {"vertices": vertices, "edges": edges}


async def generate_change_events(count: int = 100) -> List[Dict[str, Any]]:
    """Generate realistic change events."""
    events = []
    now = datetime.utcnow()
    
    for i in range(count):
        service = random.choice(SERVICES)
        change_type = random.choice(CHANGE_TYPES)
        source = random.choice(SOURCES)
        
        # Time distribution: more recent changes more likely
        hours_ago = random.expovariate(1/12)  # Mean 12 hours
        hours_ago = min(hours_ago, 72)  # Cap at 72 hours
        timestamp = now - timedelta(hours=hours_ago)
        
        event = {
            "id": str(uuid.uuid4()),
            "eventId": str(uuid.uuid4()),
            "changeType": change_type,
            "source": source,
            "status": random.choices(
                ["succeeded", "failed", "rolled_back"],
                weights=[0.85, 0.1, 0.05]
            )[0],
            "timestamp": timestamp.isoformat(),
            "serviceName": service["name"],
            "environment": service["namespace"],
            "namespace": service["namespace"],
        }
        
        # Add source-specific details
        if source == "github":
            event["git"] = {
                "repoUrl": f"https://github.com/org/{service['name']}",
                "repoName": f"org/{service['name']}",
                "commitSha": uuid.uuid4().hex[:12],
                "commitMessage": f"{change_type.replace('_', ' ').title()} for {service['name']}",
                "branch": random.choice(["main", "develop", "release/v1.2"]),
                "author": f"dev{random.randint(1, 10)}",
                "authorEmail": f"dev{random.randint(1, 10)}@company.com",
            }
        elif source == "terraform":
            event["terraform"] = {
                "workspace": f"{service['namespace']}-{service['name']}",
                "planId": f"plan-{uuid.uuid4().hex[:8]}",
                "applyId": f"apply-{uuid.uuid4().hex[:8]}",
                "runId": f"run-{uuid.uuid4().hex[:8]}",
                "organization": "company",
                "moduleAddresses": [f"module.{service['name']}"],
            }
        elif source == "kubernetes":
            event["kubernetesChanges"] = [{
                "resource": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "namespace": service["namespace"],
                    "name": service["name"],
                },
                "operation": random.choice(["CREATE", "UPDATE", "PATCH"]),
                "diff": {"replicas": {"before": 3, "after": 5}},
            }]
        
        # Add pipeline context
        event["pipelineName"] = f"github/{service['name']}"
        event["pipelineRunId"] = f"run-{uuid.uuid4().hex[:8]}"
        event["pipelineUrl"] = f"https://github.com/org/{service['name']}/actions/runs/{uuid.uuid4().hex[:8]}"
        
        if change_type == "code_deployment":
            event["deploymentId"] = f"deploy-{uuid.uuid4().hex[:8]}"
            event["deploymentStrategy"] = random.choice(["rolling", "canary", "blue-green"])
            event["rolloutPercentage"] = random.choice([10, 25, 50, 100])
            event["previousVersion"] = f"v1.{random.randint(0, 5)}.{random.randint(0, 10)}"
            event["newVersion"] = f"v1.{random.randint(0, 5)}.{random.randint(0, 10)}"
        
        events.append(event)
    
    events.sort(key=lambda x: x["timestamp"], reverse=True)
    return events


async def generate_incidents(count: int = 20) -> List[Dict[str, Any]]:
    """Generate incidents with ground truth for evaluation."""
    incidents = []
    now = datetime.utcnow()
    
    # Some incidents have known root causes (for evaluation)
    fault_scenarios = [
        {
            "fault_type": "pod_failure",
            "target_service": "payment-service",
            "root_cause_service": "payment-service",
            "root_cause_change_type": "code_deployment",
        },
        {
            "fault_type": "cpu_pressure",
            "target_service": "fraud-service",
            "root_cause_service": "fraud-service",
            "root_cause_change_type": "code_deployment",
        },
        {
            "fault_type": "network_latency",
            "target_service": "order-service",
            "root_cause_service": "payment-service",
            "root_cause_change_type": "config_change",
        },
        {
            "fault_type": "memory_pressure",
            "target_service": "inventory-service",
            "root_cause_service": "inventory-service",
            "root_cause_change_type": "infrastructure_change",
        },
    ]
    
    for i in range(count):
        if i < len(fault_scenarios):
            # Known fault scenario
            scenario = fault_scenarios[i]
            affected_service = scenario["target_service"]
            root_cause_service = scenario["root_cause_service"]
            root_cause_type = scenario["root_cause_change_type"]
            fault_type = scenario["fault_type"]
        else:
            # Random incident
            affected_service = random.choice(SERVICES)["name"]
            root_cause_service = random.choice(SERVICES)["name"]
            root_cause_type = random.choice(CHANGE_TYPES)
            fault_type = random.choice(["pod_failure", "cpu_pressure", "memory_pressure", "network_latency"])
        
        detected_at = now - timedelta(hours=random.uniform(1, 48))
        started_at = detected_at - timedelta(minutes=random.uniform(5, 30))
        
        # Generate candidates (including the true cause)
        candidates = []
        for svc in SERVICES:
            if svc["name"] == root_cause_service:
                # True cause - high confidence
                confidence = random.uniform(0.75, 0.95)
            elif svc["name"] == affected_service:
                # Affected service itself - medium confidence
                confidence = random.uniform(0.4, 0.7)
            else:
                # Other services - low confidence
                confidence = random.uniform(0.05, 0.35)
            
            candidates.append({
                "changeEventId": str(uuid.uuid4()),
                "serviceName": svc["name"],
                "changeType": root_cause_type if svc["name"] == root_cause_service else random.choice(CHANGE_TYPES),
                "source": random.choice(SOURCES),
                "timestamp": (detected_at - timedelta(hours=random.uniform(0.5, 4))).isoformat(),
                "confidenceScore": confidence,
                "evidence": {
                    "graphDistance": 0 if svc["name"] == affected_service else random.randint(1, 3),
                    "timeDeltaHours": random.uniform(0.5, 4),
                }
            })
        
        candidates.sort(key=lambda x: x["confidenceScore"], reverse=True)
        
        incident = {
            "id": str(uuid.uuid4()),
            "incidentId": f"INC-{detected_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "title": f"{fault_type.replace('_', ' ').title()} in {affected_service}",
            "description": f"SLO breach detected in {affected_service} due to {fault_type}",
            "severity": random.choice(["sev1", "sev2", "sev3"]),
            "status": random.choice(["resolved", "closed", "verifying"]),
            "affectedService": affected_service,
            "affectedNamespace": "production",
            "sloName": "availability",
            "errorBudgetBurnRate": random.uniform(5, 50),
            "detectedAt": detected_at.isoformat(),
            "startedAt": started_at.isoformat(),
            "resolvedAt": (detected_at + timedelta(minutes=random.uniform(30, 120))).isoformat(),
            "candidates": candidates,
            "topCandidateId": candidates[0]["changeEventId"] if candidates else None,
            "topCandidateConfidence": candidates[0]["confidenceScore"] if candidates else 0,
            "groundTruth": {
                "changeEventId": next((c["changeEventId"] for c in candidates if c["serviceName"] == root_cause_service), None),
                "confirmed": True,
                "confirmedAt": (detected_at + timedelta(hours=2)).isoformat(),
                "confirmedBy": "chaos-validation",
                "faultType": fault_type,
            } if i < len(fault_scenarios) else None,
            "remediationAction": random.choice(["rollback_deployment", "restart_workload"]),
            "remediationStatus": "completed",
            "labels": {
                "fault_type": fault_type,
                "validation": "chaos" if i < len(fault_scenarios) else "production",
            }
        }
        incidents.append(incident)
    
    return incidents


async def main():
    """Main entry point."""
    print("Generating demo data for ChangeTrace...")
    
    graph = await generate_dependency_graph()
    changes = await generate_change_events(150)
    incidents = await generate_incidents(25)
    
    output_dir = "demo_data"
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    with open(f"{output_dir}/dependency_graph.json", "w") as f:
        json.dump(graph, f, indent=2)
    
    with open(f"{output_dir}/change_events.json", "w") as f:
        json.dump(changes, f, indent=2, default=str)
    
    with open(f"{output_dir}/incidents.json", "w") as f:
        json.dump(incidents, f, indent=2, default=str)
    
    with open(f"{output_dir}/slos.json", "w") as f:
        json.dump(SLOS, f, indent=2)
    
    print(f"Generated demo data in {output_dir}/")
    print(f"  - {len(graph['vertices'])} services, {len(graph['edges'])} dependencies")
    print(f"  - {len(changes)} change events")
    print(f"  - {len(incidents)} incidents ({sum(1 for i in incidents if i['groundTruth'])}) with ground truth")


if __name__ == "__main__":
    asyncio.run(main())