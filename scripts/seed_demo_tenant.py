#!/usr/bin/env python3
"""
Enrich the live demo tenant in Cosmos DB Gremlin with the full demo dataset.

Adds rich dashboard data without touching the live service graph.
"""

import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from gremlin_python.driver import client as gremlin_client, serializer
from gremlin_python.driver.protocol import GremlinServerError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.shared.cosmos import get_cosmos_config_from_env

SERVICES = [
    {"name": "api-gateway",       "criticality": "high",     "namespace": "production", "slo": 99.9},
    {"name": "auth-service",      "criticality": "high",     "namespace": "production", "slo": 99.95},
    {"name": "payment-service",   "criticality": "critical", "namespace": "production", "slo": 99.99},
    {"name": "fraud-service",     "criticality": "high",     "namespace": "production", "slo": 99.9},
    {"name": "order-service",     "criticality": "high",     "namespace": "production", "slo": 99.9},
    {"name": "inventory-service", "criticality": "medium",   "namespace": "production", "slo": 99.9},
    {"name": "notification-service", "criticality": "medium", "namespace": "production", "slo": 99.5},
]

CHANGE_TYPES = ["code_deployment", "config_change", "infrastructure_change", "release", "rollback", "scale_event"]
SOURCES = ["github", "terraform", "kubernetes", "azure_resource_graph", "argocd"]
AUTHORS = ["alice@co.com", "bob@co.com", "charlie@co.com", "diana@co.com", "evan@co.com"]
VERSIONS = ["v2.3.1", "v2.3.2", "v2.4.0", "v3.0.0-rc1", "v1.9.8", "v2.5.0-beta"]

FAULT_SCENARIOS = [
    {"fault": "pod_failure",       "target": "payment-service",  "root": "payment-service",  "type": "code_deployment"},
    {"fault": "cpu_pressure",      "target": "fraud-service",    "root": "fraud-service",    "type": "code_deployment"},
    {"fault": "network_latency",   "target": "order-service",    "root": "payment-service",  "type": "config_change"},
    {"fault": "memory_pressure",   "target": "inventory-service", "root": "inventory-service", "type": "infrastructure_change"},
    {"fault": "dns_failure",       "target": "api-gateway",      "root": "api-gateway",      "type": "config_change"},
    {"fault": "disk_io",           "target": "payment-service",  "root": "payment-service",  "type": "infrastructure_change"},
]

TENANT_ID = os.getenv("CHANGETRACE_DEMO_TENANT", "demo-tenant")

SVC_MAP = {s["name"]: s for s in SERVICES}


def q(v: str) -> str:
    return v.replace("'", "\\'")


def ts(dt: datetime) -> str:
    return dt.isoformat()


def rand_svc() -> dict:
    return random.choice(SERVICES)


def run(client, query: str, retries=5):
    for attempt in range(retries):
        try:
            return client.submit(query).all().result()
        except GremlinServerError as e:
            if "429" in str(e) or "RequestRateTooLarge" in str(e) or "TooManyRequests" in str(e):
                wait = min(2 ** attempt * 2, 60)
                print(f"  [429] retry in {wait}s (attempt {attempt + 1}/{retries}) …")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Query failed after {retries} retries:\n{query[:200]}")


def count_for(client, label: str) -> int:
    r = run(client, f"g.V().hasLabel('{label}').has('tenantId','{TENANT_ID}').count()")
    return r[0] if r else 0


def seed():
    cfg = get_cosmos_config_from_env()
    endpoint = cfg["endpoint"]
    key = cfg["key"]
    database = cfg["database"]

    if not endpoint or not key:
        print("ERROR: COSMOS_DB_ENDPOINT and COSMOS_DB_KEY must be set")
        sys.exit(1)

    print(f"Connecting to {endpoint}")
    print(f"Database: {database}")
    print(f"Tenant:   {TENANT_ID}\n")

    c = gremlin_client.Client(
        endpoint, "g",
        username=f"/dbs/{database}/colls/dependency-graph",
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )

    now = datetime.now(timezone.utc)

    try:
        existing_changes = count_for(c, "ChangeEvent")
        print(f"Existing ChangeEvents: {existing_changes}")
        target_changes = 120
        to_add = max(0, target_changes - existing_changes)
        print(f"Adding {to_add} ChangeEvents …\n")

        for i in range(to_add):
            svc = rand_svc()
            ctype = random.choice(CHANGE_TYPES)
            source = random.choice(SOURCES)
            author = random.choice(AUTHORS)
            hours_ago = min(random.expovariate(1 / 8), 72)
            event_ts = now - timedelta(hours=hours_ago)
            eid = str(uuid.uuid4())
            status = random.choices(["succeeded", "failed", "rolled_back", "in_progress"], [0.78, 0.10, 0.07, 0.05])[0]
            version = random.choice(VERSIONS)
            pipeline = random.choice(["main-ci", "release-2x", "canary-pipeline", "hotfix"])

            run(c, f"""g.addV('ChangeEvent')
.property('id','{eid}')
.property('eventId','{eid}')
.property('changeType','{ctype}')
.property('source','{source}')
.property('status','{status}')
.property('timestamp','{ts(event_ts)}')
.property('serviceName','{svc["name"]}')
.property('environment','{svc["namespace"]}')
.property('namespace','{svc["namespace"]}')
.property('author','{author}')
.property('description','{q(ctype.replace("_"," ").title() + " on " + svc["name"] + " by " + author.split("@")[0])}')
.property('deploymentId','deploy-{uuid.uuid4().hex[:8]}')
.property('newVersion','{version}')
.property('pipelineName','{pipeline}')
.property('tenantId','{TENANT_ID}')""")

            run(c, f"""g.V().has('ChangeEvent','eventId','{eid}').as('c')
.V().hasLabel('Service').has('serviceName','{svc["name"]}').as('s')
.addE('deployed_to').from('c').to('s')
.property('tenantId','{TENANT_ID}')""")

            if (i + 1) % 20 == 0:
                print(f"  Created {i + 1}/{to_add} events…")
        print()

        print("Creating SLO metric time-series …")
        slo_services = ["payment-service", "order-service", "fraud-service", "api-gateway", "inventory-service"]
        for svc_name in slo_services:
            base_slo = SVC_MAP[svc_name]["slo"]
            for h in range(48):
                point_ts = now - timedelta(hours=47 - h)
                dip = 0
                if 20 <= h <= 25:
                    dip = random.uniform(0.3, 2.0)
                elif 35 <= h <= 38:
                    dip = random.uniform(0.5, 1.5)
                actual = round(base_slo - dip - random.uniform(0, 0.1), 2)
                eb = max(0, round(100 - (h / 48) * 100 * random.uniform(0.8, 1.2), 1))
                br = round(dip / max(base_slo - actual + 0.01, 0.01), 2) if dip > 0 else round(random.uniform(0.2, 0.8), 2)
                mid = str(uuid.uuid4())

                run(c, f"""g.addV('SLOMetric')
.property('id','{mid}')
.property('serviceName','{svc_name}')
.property('service','{svc_name}')
.property('sloName','availability')
.property('target',{base_slo})
.property('actual',{actual})
.property('burnRate',{br})
.property('errorBudgetRemaining',{eb})
.property('timestamp','{ts(point_ts)}')
.property('tenantId','{TENANT_ID}')""")
            print(f"  Created 48 SLOMetric points for {svc_name}")
        print()

        print("Creating incidents …")
        existing_incidents = count_for(c, "Incident")
        print(f"Existing Incidents: {existing_incidents}")
        target_incidents = 25
        to_add = max(0, target_incidents - existing_incidents)
        print(f"Adding {to_add} Incidents …\n")

        for i in range(to_add):
            if i < len(FAULT_SCENARIOS):
                scenario = FAULT_SCENARIOS[i]
                affected = scenario["target"]
                root = scenario["root"]
                root_type = scenario["type"]
                fault = scenario["fault"]
                is_fault = True
            else:
                affected = rand_svc()["name"]
                root = rand_svc()["name"]
                root_type = random.choice(CHANGE_TYPES)
                fault = random.choice(["pod_failure", "cpu_pressure", "memory_pressure", "network_latency"])
                is_fault = False

            detected_at = now - timedelta(hours=random.uniform(1, 72))
            started_at = detected_at - timedelta(minutes=random.uniform(5, 30))
            resolved_at = detected_at + timedelta(minutes=random.uniform(20, 90))
            iid = f"INC-{detected_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            severity = "sev1" if is_fault else random.choices(["sev1", "sev2", "sev3", "sev4"], [0.20, 0.35, 0.30, 0.15])[0]
            status = "resolved" if is_fault else random.choices(
                ["open", "investigating", "root_cause_identified", "remediating", "verifying", "resolved", "closed"],
                [0.10, 0.10, 0.10, 0.10, 0.10, 0.35, 0.15])[0]
            title = fault.replace("_", " ").title() + " in " + affected

            run(c, f"""g.addV('Incident')
.property('id','{iid}')
.property('incidentId','{iid}')
.property('serviceName','{affected}')
.property('title','{q(title)}')
.property('description','SLO breach in {affected} due to {fault}')
.property('severity','{severity}')
.property('status','{status}')
.property('affectedService','{affected}')
.property('affectedNamespace','production')
.property('sloName','availability')
.property('errorBudgetBurnRate',{round(random.uniform(5,60),1)})
.property('detectedAt','{ts(detected_at)}')
.property('startedAt','{ts(started_at)}')
.property('resolvedAt','{ts(resolved_at)}')
.property('topCandidateConfidence',{round(random.uniform(0.72,0.96),2)})
.property('remediationAction','{random.choice(["rollback_deployment","restart_workload","scale_up","dns_failover"])}')
.property('remediationStatus','{random.choice(["completed","in_progress","failed"])}')
.property('rootCauseCandidate','{root}')
.property('trueCauseRank',{1 if is_fault else random.randint(1,5)})
.property('tenantId','{TENANT_ID}')""")

            for svc in SERVICES:
                conf = random.uniform(0.78, 0.95) if svc["name"] == root else random.uniform(0.40, 0.70) if svc["name"] == affected else random.uniform(0.05, 0.35)
                cid = str(uuid.uuid4())
                run(c, f"""g.V().has('Incident','incidentId','{iid}').as('i')
.addV('Candidate')
.property('id','{cid}')
.property('changeEventId','{cid}')
.property('serviceName','{svc["name"]}')
.property('changeType','{root_type if svc["name"] == root else random.choice(CHANGE_TYPES)}')
.property('source','{random.choice(SOURCES)}')
.property('timestamp','{ts(detected_at - timedelta(hours=random.uniform(0.5,4)))}')
.property('confidenceScore',{round(conf,2)})
.property('evidence','{{"graphDistance":{0 if svc["name"]==affected else random.randint(1,3)},"timeDeltaHours":{round(random.uniform(0.5,4),1)}}}')
.property('tenantId','{TENANT_ID}')
.addE('has_candidate').from('i')
.property('tenantId','{TENANT_ID}')""")

            print(f"  {iid} | {severity} | {title}  [{status}]")
        print()

        print("Creating risk score history …")
        risk_services = ["payment-service", "order-service", "fraud-service", "api-gateway", "inventory-service"]
        for svc_name in risk_services:
            base_risk = 0.7 if SVC_MAP[svc_name]["criticality"] == "critical" else 0.4
            for day_offset in range(14):
                point_ts = now - timedelta(days=13 - day_offset)
                score = round(min(1.0, base_risk + random.uniform(-0.15, 0.25) + (0.05 if 5 <= day_offset <= 8 else 0)), 2)
                rid = str(uuid.uuid4())
                run(c, f"""g.addV('RiskScore')
.property('id','{rid}')
.property('serviceName','{svc_name}')
.property('service','{svc_name}')
.property('riskScore',{score})
.property('timestamp','{ts(point_ts)}')
.property('deploymentId','deploy-{uuid.uuid4().hex[:8]}')
.property('changeSize',{round(random.uniform(0.1,0.9),2)})
.property('serviceCriticality',{0.4 if SVC_MAP[svc_name]["criticality"] == "medium" else 0.7 if SVC_MAP[svc_name]["criticality"] == "high" else 1.0})
.property('recentIncidents',{random.randint(0,2)})
.property('dependencyRisk',{round(random.uniform(0.1,0.8),2)})
.property('tenantId','{TENANT_ID}')""")
            print(f"  Created 14 RiskScore points for {svc_name}")
        print()

        print("Verifying data …")
        labels = ["Service", "ChangeEvent", "Incident", "SLOMetric", "RiskScore", "Candidate"]
        counts = {}
        for label in labels:
            counts[label] = count_for(c, label)
        ec = run(c, f"g.E().hasLabel('depends_on').has('tenantId','{TENANT_ID}').count()")
        dc = run(c, f"g.E().hasLabel('deployed_to').has('tenantId','{TENANT_ID}').count()")
        counts["depends_on"] = ec[0] if ec else 0
        counts["deployed_to"] = dc[0] if dc else 0

        print(f"  Services:       {counts.get('Service', 0)}")
        print(f"  Dependencies:   {counts.get('depends_on', 0)}")
        print(f"  Change Events:  {counts.get('ChangeEvent', 0)}")
        print(f"  Incidents:      {counts.get('Incident', 0)}")
        print(f"  Candidates:     {counts.get('Candidate', 0)}")
        print(f"  SLO Metrics:    {counts.get('SLOMetric', 0)}")
        print(f"  Risk Scores:    {counts.get('RiskScore', 0)}")
        print(f"  deployed_to:    {counts.get('deployed_to', 0)}")
        print()
        print("Demo tenant data seeded successfully!")

    finally:
        c.close()


if __name__ == "__main__":
    seed()
