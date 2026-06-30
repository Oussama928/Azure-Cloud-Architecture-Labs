#!/usr/bin/env python3
"""
Migrate the seeded ChangeTrace graph to multi-tenant.

Tags data vertices/edges with a tenantId and creates the demo login account.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.shared.cosmos import create_gremlin_client, get_cosmos_config_from_env

DEMO_TENANT = os.getenv("CHANGETRACE_DEMO_TENANT", "demo-tenant")
DEMO_EMAIL = os.getenv("CHANGETRACE_DEMO_EMAIL", "demo@changetrace.io")
DEMO_PASSWORD = os.getenv("CHANGETRACE_DEMO_PASSWORD", "ChangeTraceDemo!2026")

LABELS = ["Service", "ChangeEvent", "Incident", "SLOMetric", "RiskScore", "Candidate"]
EDGES = ["depends_on", "has_candidate"]


def submit(client, query: str):
    result = client.submit(query).all().result()
    return result


def main():
    config = get_cosmos_config_from_env()
    client = create_gremlin_client(
        config["endpoint"], config["key"], config["database"], config["graph"]
    )
    if not client:
        print("ERROR: Cosmos DB credentials not configured")
        sys.exit(1)

    print(f"Demo tenant: {DEMO_TENANT}")

    for label in LABELS:
        q = f"g.V().hasLabel('{label}').hasNot('tenantId').property('tenantId', '{DEMO_TENANT}').count()"
        try:
            n = submit(client, q)[0]
            print(f"  tagged {n} {label} vertices")
        except Exception as e:
            print(f"  ERROR tagging {label}: {e}")

    for edge in EDGES:
        q = f"g.E().hasLabel('{edge}').hasNot('tenantId').property('tenantId', '{DEMO_TENANT}').count()"
        try:
            n = submit(client, q)[0]
            print(f"  tagged {n} {edge} edges")
        except Exception as e:
            print(f"  ERROR tagging {edge}: {e}")

    # Create the demo showcase user (upsert by email)
    from services.dashboard_api.src.users import hash_password

    pw_hash = hash_password(DEMO_PASSWORD)
    q = (
        f"g.V().hasLabel('User').has('email', '{DEMO_EMAIL}')"
        f".fold().coalesce(unfold(), addV('User'))"
        f".property('userId', 'demo-user')"
        f".property('email', '{DEMO_EMAIL}')"
        f".property('name', 'Demo Showcase')"
        f".property('passwordHash', '{pw_hash}')"
        f".property('tenantId', '{DEMO_TENANT}')"
        f".property('serviceName', '{DEMO_EMAIL}')"
        f".property('roles', 'admin')"
    )
    try:
        submit(client, q)
        print(f"  demo user {DEMO_EMAIL} ready")
    except Exception as e:
        print(f"  ERROR creating demo user: {e}")

    print("Migration complete.")


if __name__ == "__main__":
    main()
