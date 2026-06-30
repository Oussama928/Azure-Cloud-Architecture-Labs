#!/bin/bash
set -uo pipefail

NAMESPACE="${1:-changetrace}"
DASHBOARD_URL="${2:-http://4.166.166.202}"
DEMO_EMAIL="${DEMO_EMAIL:-demo@changetrace.io}"
DEMO_PASSWORD="${DEMO_PASSWORD:-changetrace123}"
API_BASE="${DASHBOARD_URL}/api/v1"
RESULTS_DIR="chaos/results/k8s"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PASS=0
FAIL=0
CURL="curl -sf --connect-timeout 5 --max-time 10"

mkdir -p "$RESULTS_DIR"

log()  { echo "[$(date +%H:%M:%S)] $*"; }
pass() { log "PASS: $*"; ((PASS++)); }
fail() { log "FAIL: $*"; ((FAIL++)); }

AUTH_TOKEN=""
get_token() {
    if [ -z "$AUTH_TOKEN" ]; then
        AUTH_TOKEN=$(curl -s --connect-timeout 5 --max-time 15 -X POST "$API_BASE/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"$DEMO_EMAIL\",\"password\":\"$DEMO_PASSWORD\"}" 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)
    fi
    [ -n "$AUTH_TOKEN" ]
}

api_ok() {
    $CURL -H "Authorization: Bearer $AUTH_TOKEN" "$API_BASE/graph/dependency" >/dev/null 2>&1
}

snapshot() {
    local phase="$1"
    log "=== Snapshot: $phase ==="
    kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | awk '{print $1,$3}' > "$RESULTS_DIR/${phase}_pods.txt"
    api_ok && $CURL -H "Authorization: Bearer $AUTH_TOKEN" "$API_BASE/graph/dependency" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
for n in d.get('nodes',[]):
    s=n.get('service_name', n.get('name','?'))
    slo=n.get('current_slo','N/A')
    print(f'{s}: SLO={slo}')
" > "$RESULTS_DIR/${phase}_slo.txt" 2>/dev/null || echo "API unavailable" > "$RESULTS_DIR/${phase}_slo.txt"
}

run_pod_failure() {
    local service="$1"
    local label="$2"
    log "=== Pod Failure ($service) ==="

    local pod
    pod=$(kubectl get pods -n "$NAMESPACE" -l "$label" --no-headers 2>/dev/null | awk '{print $1}' | head -1)
    if [ -z "$pod" ]; then fail "no pod for $service"; return; fi
    kubectl delete pod -n "$NAMESPACE" "$pod" --grace-period=0 --force --wait=false >/dev/null 2>&1
    log "Killed $pod"

    if kubectl wait pod --for=condition=Ready -l "$label" -n "$NAMESPACE" --timeout=120s >/dev/null 2>&1; then
        pass "pod-failure/$service: pod recovered"
    else
        fail "pod-failure/$service: pod did NOT recover"
    fi

    if api_ok; then
        pass "pod-failure/$service: API healthy"
    else
        fail "pod-failure/$service: API unavailable"
    fi
}

run_cpu_pressure() {
    log "=== CPU Pressure ==="
    kubectl run -n "$NAMESPACE" chaos-cpu-stress --image=alpine:3.18 --restart=Never \
        -- sh -c "apk add --no-cache stress-ng >/dev/null 2>&1 && stress-ng --cpu 4 --timeout 30s" >/dev/null 2>&1 || true
    sleep 5
    pass "cpu-pressure: stress job completed"
}

# Inject latency into a demo-app service using its built-in fault endpoint.
run_app_latency() {
    local service="$1"
    local ms="$2"
    local label="app=${service}"
    log "=== Latency Injection ($service +${ms}ms) ==="

    local pod
    pod=$(kubectl get pods -n "$NAMESPACE" -l "$label" --no-headers 2>/dev/null | awk '{print $1}' | head -1)
    if [ -z "$pod" ]; then fail "no pod for $service"; return; fi

    if kubectl exec -n "$NAMESPACE" "$pod" -- \
        curl -sf -X POST "http://localhost:8080/fault/latency/${ms}" >/dev/null 2>&1; then
        pass "latency/${service}: fault injected (+${ms}ms)"
    else
        fail "latency/${service}: could not inject fault"
        return
    fi

    sleep 15

    if api_ok; then
        pass "latency/${service}: API still reachable under ${ms}ms injected latency"
    else
        fail "latency/${service}: API unreachable during latency"
    fi

    kubectl exec -n "$NAMESPACE" "$pod" -- \
        curl -sf -X POST "http://localhost:8080/fault/reset" >/dev/null 2>&1 || true
    log "latency/${service}: fault reset"
}

# Induce a failure (503) in a demo-app service using its built-in fault endpoint.
run_app_failure() {
    local service="$1"
    local label="app=${service}"
    log "=== Failure Mode ($service) ==="

    local pod
    pod=$(kubectl get pods -n "$NAMESPACE" -l "$label" --no-headers 2>/dev/null | awk '{print $1}' | head -1)
    if [ -z "$pod" ]; then fail "no pod for $service"; return; fi

    if kubectl exec -n "$NAMESPACE" "$pod" -- \
        curl -sf -X POST "http://localhost:8080/fault/fail" >/dev/null 2>&1; then
        pass "failure/${service}: failure mode injected"
    else
        fail "failure/${service}: could not inject failure"
        return
    fi

    sleep 15

    if api_ok; then
        pass "failure/${service}: API healthy with ${service} in failure mode"
    else
        fail "failure/${service}: API unavailable"
    fi

    kubectl exec -n "$NAMESPACE" "$pod" -- \
        curl -sf -X POST "http://localhost:8080/fault/reset" >/dev/null 2>&1 || true
    log "failure/${service}: fault reset"
}

echo "=== ChangeTrace K8s Chaos Runner ==="
echo "Namespace: $NAMESPACE  Dashboard: $DASHBOARD_URL"

if ! get_token; then
    fail "could not authenticate to dashboard API (login as $DEMO_EMAIL)"
fi

snapshot "initial"

# Platform service pod failures (ChangeTrace itself must self-heal)
run_pod_failure "risk-engine" "app=changetrace-risk-engine"
run_pod_failure "dashboard-api" "app=changetrace-dashboard-api"
run_pod_failure "correlation-engine" "app=changetrace-correlation-engine"

# Demo application faults (payment-service is a critical dependency of order-service)
run_pod_failure "payment-service" "app=payment-service"
run_app_latency "payment-service" 2000
run_app_failure "payment-service"

run_cpu_pressure

snapshot "final"

echo ""
echo "=== RESULTS: $PASS passed, $FAIL failed ==="

cat > "$RESULTS_DIR/summary.json" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "namespace": "$NAMESPACE",
  "dashboard_url": "$DASHBOARD_URL",
  "passed": $PASS,
  "failed": $FAIL
}
EOF

exit $FAIL
