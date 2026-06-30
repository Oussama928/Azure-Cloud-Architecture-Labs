#!/usr/bin/env python3
"""
Seed Cosmos DB Gremlin with demo data for ChangeTrace.

Creates service vertices, dependency edges, change events, and incidents.
"""

import asyncio
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta

from gremlin_python.driver import client as gremlin_client, serializer
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.shared.cosmos import get_cosmos_config_from_env, create_gremlin_client

SERVICES = [
    {"name": "api-gateway", "criticality": "high", "namespace": "production"},
    {"name": "auth-service", "criticality": "high", "namespace": "production"},
    {"name": "payment-service", "criticality": "critical", "namespace": "production"},
    {"name": "fraud-service", "criticality": "high", "namespace": "production"},
    {"name": "order-service", "criticality": "high", "namespace": "production"},
    {"name": "inventory-service", "criticality": "medium", "namespace": "production"},
    {"name": "notification-service", "criticality": "medium", "namespace": "production"},
]

DEPENDENCIES = [
    ("api-gateway", "auth-service"),
    ("api-gateway", "payment-service"),
    ("api-gateway", "order-service"),
    ("order-service", "payment-service"),
    ("order-service", "inventory-service"),
    ("payment-service", "auth-service"),
    ("payment-service", "fraud-service"),
]

SLOS = {
    "api-gateway": 99.9, "auth-service": 99.95, "payment-service": 99.99,
    "fraud-service": 99.9, "order-service": 99.9, "inventory-service": 99.9,
    "notification-service": 99.5,
}

CHANGE_TYPES = ["code_deployment", "config_change", "infrastructure_change", "release", "rollback"]
SOURCES = ["github", "terraform", "kubernetes", "azure_resource_graph"]


def run_query(client, query: str, bindings: dict | None = None):
    """Run a Gremlin query synchronously with retry/backoff on Cosmos throttling."""
    import time
    for attempt in range(8):
        try:
            rs = client.submit(query, bindings or {})
            return rs.all().result()
        except Exception as exc:
            if attempt == 7:
                raise
            time.sleep(min(2 ** attempt, 10))


def seed_demo_data():
    cfg = get_cosmos_config_from_env()
    endpoint = cfg["endpoint"]
    key = cfg["key"]
    database = cfg["database"]

    if not endpoint or not key:
        print("ERROR: COSMOS_DB_ENDPOINT and COSMOS_DB_KEY must be set")
        sys.exit(1)

    print(f"Connecting to {endpoint}")
    print(f"Database: {database}")
    print()

    client = gremlin_client.Client(
        endpoint,
        "g",
        username=f"/dbs/{database}/colls/dependency-graph",
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )

    remote_conn = DriverRemoteConnection(
        endpoint,
        "g",
        username=f"/dbs/{database}/colls/dependency-graph",
        password=key,
    )
    g = traversal().withRemote(remote_conn)

    try:
        # Step 1: Drop existing data
        print("Dropping existing data...")
        run_query(client, "g.V().drop()")
        print("  Done")

        # Step 2: Create service vertices
        print(f"\nCreating {len(SERVICES)} service vertices...")
        for svc in SERVICES:
            run_query(client, """
                g.addV('Service')
                 .property('id', svc_id)
                 .property('serviceName', svc_id)
                 .property('criticality', criticality)
                 .property('namespace', namespace)
                 .property('partitionKey', svc_id)
            """, {
                "svc_id": svc["name"],
                "criticality": svc["criticality"],
                "namespace": svc["namespace"],
            })
        print("  Done")

        # Step 3: Create dependency edges
        print(f"\nCreating {len(DEPENDENCIES)} dependency edges...")
        for src, dst in DEPENDENCIES:
            run_query(client, """
                def src = g.V().has('serviceName', src_name).next()
                def dst = g.V().has('serviceName', dst_name).next()
                g.V(src).addE('depends_on').to(dst)
                  .property('type', 'runtime')
                  .property('latencyP99', latency)
                  .next()
            """, {
                "src_name": src,
                "dst_name": dst,
                "latency": random.randint(5, 100),
            })
        print("  Done")

        # Step 4: Create change events
        now = datetime.utcnow()
        print(f"\nCreating change events...")
        for i in range(100):
            svc_name = random.choice(SERVICES)["name"]
            change_type = random.choice(CHANGE_TYPES)
            source = random.choice(SOURCES)
            hours_ago = min(random.expovariate(1/12), 72)
            ts = now - timedelta(hours=hours_ago)
            event_id = str(uuid.uuid4())
            status = random.choices(
                ["succeeded", "failed", "rolled_back"],
                weights=[0.85, 0.1, 0.05]
            )[0]

            run_query(client, """
                g.addV('ChangeEvent')
                 .property('id', event_id)
                 .property('eventId', event_id)
                 .property('changeType', change_type)
                 .property('source', source)
                 .property('status', status)
                 .property('timestamp', ts)
                 .property('serviceName', svc_name)
                 .property('partitionKey', svc_name)
            """, {
                "event_id": event_id,
                "change_type": change_type,
                "source": source,
                "status": status,
                "ts": ts.isoformat(),
                "svc_name": svc_name,
            })
        print(f"  Created 100 change events")

        # Step 5: Create incidents
        print(f"\nCreating 20 incidents...")
        fault_scenarios = [
            ("pod_failure", "payment-service", "payment-service"),
            ("cpu_pressure", "fraud-service", "fraud-service"),
            ("network_latency", "order-service", "payment-service"),
            ("memory_pressure", "inventory-service", "inventory-service"),
        ]

        for i in range(20):
            if i < len(fault_scenarios):
                fault_type, affected, root_cause = fault_scenarios[i]
            else:
                affected = random.choice(SERVICES)["name"]
                root_cause = random.choice(SERVICES)["name"]
                fault_type = random.choice(["pod_failure", "cpu_pressure", "memory_pressure", "network_latency"])

            detected_at = now - timedelta(hours=random.uniform(1, 48))
            incident_id = f"INC-{detected_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

            run_query(client, """
                g.addV('Incident')
                 .property('id', inc_id)
                 .property('incidentId', inc_id)
                 .property('title', title)
                 .property('severity', severity)
                 .property('status', status)
                 .property('affectedService', affected)
                 .property('detectedAt', detected_at)
                 .property('partitionKey', affected)
            """, {
                "inc_id": incident_id,
                "title": f"{fault_type.replace('_', ' ').title()} in {affected}",
                "severity": random.choice(["sev1", "sev2", "sev3"]),
                "status": random.choice(["resolved", "closed"]),
                "affected": affected,
                "detected_at": detected_at.isoformat(),
            })
        print("  Done")

        print("\n Demo data seeded successfully!")
        print(f"  - {len(SERVICES)} services")
        print(f"  - {len(DEPENDENCIES)} dependencies")
        print("  - 100 change events")
        print("  - 20 incidents")

    finally:
        client.close()
        remote_conn.close()


if __name__ == "__main__":
    seed_demo_data()