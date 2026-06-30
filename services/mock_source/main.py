"""Dynamic mock ChangeEvent source server that generates a fresh batch of
synthetic ChangeEvents on every poll so the collector continuously creates
new change vertices during a live demo."""

import json
import os
import random
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

SERVICES = {
    "api-gateway": {"ci": "acme/gateway-ci", "deps": ["auth-service", "payment-service", "order-service"]},
    "auth-service": {"ci": "acme/auth-ci", "deps": []},
    "payment-service": {"ci": "acme/payments-ci", "deps": ["api-gateway", "order-service", "fraud-service"]},
    "order-service": {"ci": "acme/orders-ci", "deps": ["payment-service", "inventory-service"]},
    "inventory-service": {"ci": "acme/inventory-ci", "deps": []},
    "fraud-service": {"ci": "acme/fraud-terraform", "deps": ["payment-service"]},
    "notification-service": {"ci": "acme/notifications-infra", "deps": []},
}

PORT = int(os.getenv("MOCK_SOURCE_PORT", "8099"))
BATCH_SIZE = int(os.getenv("MOCK_SOURCE_BATCH_SIZE", "3"))
FAIL_RATE = float(os.getenv("MOCK_SOURCE_FAIL_RATE", "0.10"))

_lock = threading.Lock()
_versions = {name: 1.0 for name in SERVICES}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_version(service: str) -> tuple[str, str]:
    """Return (new_version, previous_version) for a service's next deploy."""
    with _lock:
        old = _versions[service]
        _versions[service] = round(old + 0.1, 1)
        return f"v{_versions[service]:.1f}", f"v{old:.1f}"


def _pick_change() -> tuple[str, str, str]:
    """Return (change_type, source, status) sampled from realistic ratios."""
    roll = random.random()
    if roll < 0.05:
        return "rollback", "github", "rolled_back"
    if roll < 0.15:
        return "scale_event", "kubernetes", random.choices(["succeeded", "failed"], [0.9, 0.1])[0]
    if roll < 0.30:
        return "config_change", random.choice(["terraform", "azure_resource_graph"]), random.choices(["succeeded", "failed"], [0.9, 0.1])[0]
    if roll < 0.45:
        return "infrastructure_change", random.choice(["kubernetes", "argo_rollouts", "azure_resource_graph"]), random.choices(["succeeded", "failed"], [0.9, 0.1])[0]
    status = random.choices(["succeeded", "failed"], [1 - FAIL_RATE, FAIL_RATE])[0]
    return "code_deployment", "github", status


def _build_event() -> dict:
    service = random.choice(list(SERVICES.keys()))
    cfg = SERVICES[service]
    change_type, source, status = _pick_change()
    new_ver, prev_ver = _next_version(service)
    deployment_id = f"dep-acme-{random.randint(100000, 999999)}"
    authors = ["ci-bot", "deploy-bot", "sre-bot", "platform-bot", "dev-team"]
    descriptions = {
        "code_deployment": f"Deploy {service} {new_ver}",
        "config_change": f"Update {service} config to {new_ver}",
        "infrastructure_change": f"Scale {service} replicas to {random.randint(3, 12)}",
        "rollback": f"Rollback {service} to {prev_ver} after SLO breach",
        "scale_event": f"Autoscale {service} to {random.randint(2, 10)}",
    }
    return {
        "serviceName": service,
        "changeType": change_type,
        "source": source,
        "status": status,
        "environment": "production",
        "author": random.choice(authors),
        "description": descriptions[change_type],
        "pipelineName": cfg["ci"],
        "deploymentId": deployment_id,
        "newVersion": new_ver,
        "previousVersion": prev_ver,
        "blastRadiusServices": cfg["deps"],
        "timestamp": _now(),
        "eventId": str(uuid.uuid4()),
    }


def _build_events() -> list[dict]:
    return [_build_event() for _ in range(BATCH_SIZE)]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"events": _build_events()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
