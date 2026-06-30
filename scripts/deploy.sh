#!/usr/bin/env bash
# ChangeTrace Azure Deployment Script
#
# Prerequisites:
#   - Azure CLI (az) logged in
#   - kubectl installed
#   - Docker installed
#   - Terraform 1.5+
#   - Python 3.12+
#
# Usage:
#   ./scripts/deploy.sh [--tf-only] [--image-only] [--k8s-only] [--seed-only]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Parse args
TF_ONLY=false
IMAGE_ONLY=false
K8S_ONLY=false
SEED_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tf-only)   TF_ONLY=true; shift ;;
    --image-only) IMAGE_ONLY=true; shift ;;
    --k8s-only)  K8S_ONLY=true; shift ;;
    --seed-only) SEED_ONLY=true; shift ;;
    *)           err "Unknown arg: $1"; exit 1 ;;
  esac
done

# Step 0: Prerequisites check
check_prereqs() {
  for cmd in az kubectl docker terraform python3; do
    if ! command -v "$cmd" &>/dev/null; then
      err "$cmd not found. Please install it."
      exit 1
    fi
  done

  if ! az account show &>/dev/null; then
    err "Not logged into Azure. Run 'az login' first."
    exit 1
  fi

  SUBSCRIPTION_ID=$(az account show --query id -o tsv)
  log "Azure subscription: $SUBSCRIPTION_ID"
}

# Step 1: Terraform - provision Azure infrastructure
run_terraform() {
  log "=== Step 1: Provisioning Azure infrastructure ==="

  cd "$PROJECT_ROOT/terraform"

  if [ ! -f terraform.tfvars ]; then
    if [ -f environments/dev/terraform.tfvars ]; then
      ln -sf environments/dev/terraform.tfvars terraform.tfvars
    else
      warn "No terraform.tfvars found. Creating default..."
      cat > terraform.tfvars <<-TFEOF
environment               = "demo"
location                  = "eastus"
enable_aks                = true
aks_node_count            = 1
aks_node_vm_size          = "Standard_B2s"
cosmos_db_free_tier       = true
app_insights_daily_cap_gb = 0.1
app_insights_sampling_percentage = 10
common_tags = {
  Project     = "ChangeTrace"
  Environment = "demo"
  Owner       = "changetrace-demo"
  CostCenter  = "engineering"
}
TFEOF
    fi
  fi

  terraform init -upgrade
  terraform apply -auto-approve

  # Capture outputs as env vars
  export COSMOS_DB_ENDPOINT="wss://$(terraform output -raw cosmos_account_name).gremlin.cosmos.azure.com:443/"
  export COSMOS_DB_KEY="$(terraform output -raw cosmos_primary_key)"
  export ACR_NAME="$(terraform output -raw container_registry_name)"
  export ACR_LOGIN_SERVER="$(terraform output -raw container_registry_login_server)"
  export LOG_ANALYTICS_WORKSPACE_ID="$(terraform output -raw log_analytics_workspace_name)"
  export RESOURCE_GROUP="$(terraform output -raw resource_group_name)"

  log "Terraform apply complete"
  info "  Cosmos DB endpoint: $COSMOS_DB_ENDPOINT"
  info "  ACR: $ACR_LOGIN_SERVER"

  cd "$PROJECT_ROOT"
}

# Step 2: Build and push Docker images to ACR
build_and_push_images() {
  log "=== Step 2: Building and pushing Docker images ==="

  # Get ACR credentials
  if [ -z "${ACR_NAME:-}" ] || [ -z "${ACR_LOGIN_SERVER:-}" ]; then
    info "Getting ACR info from Terraform state..."
    cd "$PROJECT_ROOT/terraform"
    ACR_NAME="$(terraform output -raw container_registry_name)"
    ACR_LOGIN_SERVER="$(terraform output -raw container_registry_login_server)"
    cd "$PROJECT_ROOT"
  fi

  az acr login --name "$ACR_NAME"
  IMAGE_TAG="${IMAGE_TAG:-demo-$(date +%Y%m%d-%H%M)}"

  services=(
    "dashboard_api:changetrace-dashboard-api"
    "collector:changetrace-collector"
    "correlation_engine:changetrace-correlation-engine"
    "graph_builder:changetrace-graph-builder"
    "risk_engine:changetrace-risk-engine"
    "postmortem_generator:changetrace-postmortem-generator"
  )

  for entry in "${services[@]}"; do
    src="${entry%%:*}"
    img="${entry##*:}"
    log "Building $src -> $ACR_LOGIN_SERVER/$img:$IMAGE_TAG"
    docker build \
      -f "services/$src/Dockerfile" \
      -t "$ACR_LOGIN_SERVER/$img:$IMAGE_TAG" \
      -t "$ACR_LOGIN_SERVER/$img:latest" \
      .
    docker push "$ACR_LOGIN_SERVER/$img:$IMAGE_TAG"
    docker push "$ACR_LOGIN_SERVER/$img:latest"
    log "  Pushed $img"
  done

  # Build dashboard
  DASHBOARD_API_URL="${DASHBOARD_API_URL:-http://changetrace-dashboard-api}"
  log "Building dashboard -> $ACR_LOGIN_SERVER/changetrace-dashboard:$IMAGE_TAG"
  docker build \
    -f dashboard/Dockerfile \
    --build-arg VITE_API_BASE="$DASHBOARD_API_URL" \
    -t "$ACR_LOGIN_SERVER/changetrace-dashboard:$IMAGE_TAG" \
    -t "$ACR_LOGIN_SERVER/changetrace-dashboard:latest" \
    dashboard
  docker push "$ACR_LOGIN_SERVER/changetrace-dashboard:$IMAGE_TAG"
  docker push "$ACR_LOGIN_SERVER/changetrace-dashboard:latest"

  export IMAGE_TAG
  log "All images built and pushed with tag: $IMAGE_TAG"
}

# Step 3: Deploy to Azure Kubernetes Service
deploy_to_aks() {
  log "=== Step 3: Deploying to AKS ==="

  # Get AKS credentials
  if [ -z "${RESOURCE_GROUP:-}" ]; then
    cd "$PROJECT_ROOT/terraform"
    RESOURCE_GROUP="$(terraform output -raw resource_group_name)"
    cd "$PROJECT_ROOT"
  fi
  AKS_NAME="${AKS_NAME:-$(az aks list -g "$RESOURCE_GROUP" --query "[0].name" -o tsv)}"
  if [ -n "$AKS_NAME" ]; then
    az aks get-credentials --resource-group "$RESOURCE_GROUP" --name "$AKS_NAME" --overwrite-existing
    log "Connected to AKS cluster: $AKS_NAME"
  else
    warn "No AKS cluster found. Deploying to current kubectl context."
  fi

  # Collect Terraform outputs for K8s secret values
  if [ -z "${COSMOS_DB_ENDPOINT:-}" ]; then
    cd "$PROJECT_ROOT/terraform"
    COSMOS_DB_ENDPOINT="wss://$(terraform output -raw cosmos_account_name).gremlin.cosmos.azure.com:443/"
    COSMOS_DB_KEY="$(terraform output -raw cosmos_primary_key)"
    ACR_NAME="$(terraform output -raw container_registry_name)"
    LOG_ANALYTICS_WORKSPACE_ID="$(terraform output -raw log_analytics_workspace_name)"
    cd "$PROJECT_ROOT"
  fi

  export ACR_NAME
  export IMAGE_TAG="${IMAGE_TAG:-latest}"
  export DASHBOARD_API_HOST="changetrace-dashboard-api"
  export APPINSIGHTS_CONNECTION_STRING="${APPINSIGHTS_CONNECTION_STRING:-}"

  # Create namespace
  kubectl apply -f "$PROJECT_ROOT/k8s/namespace.yaml"

  # Create secrets
  kubectl delete secret changetrace-cosmos-secret -n changetrace 2>/dev/null || true
  kubectl create secret generic changetrace-cosmos-secret -n changetrace \
    --from-literal=cosmos-endpoint="$COSMOS_DB_ENDPOINT" \
    --from-literal=cosmos-key="$COSMOS_DB_KEY" \
    --from-literal=cosmos-connection-string="AccountEndpoint=${COSMOS_DB_ENDPOINT/wss:\/\//https:\/\/};AccountKey=${COSMOS_DB_KEY};" \
    --from-literal=log-analytics-workspace-id="$LOG_ANALYTICS_WORKSPACE_ID" \
    --from-literal=appinsights-connection-string="${APPINSIGHTS_CONNECTION_STRING:-}"

  # Internal auth token shared between collector and graph-builder (auto-generated
  # on first deploy, reused on subsequent runs).
  INTERNAL_AUTH_TOKEN="${INTERNAL_AUTH_TOKEN:-$(kubectl get secret changetrace-internal-secret -n changetrace -o jsonpath='{.data.internal-auth-token}' 2>/dev/null | base64 -d)}"
  if [ -z "$INTERNAL_AUTH_TOKEN" ]; then
    INTERNAL_AUTH_TOKEN="ct-$(openssl rand -hex 24)"
  fi
  kubectl delete secret changetrace-internal-secret -n changetrace 2>/dev/null || true
  kubectl create secret generic changetrace-internal-secret -n changetrace \
    --from-literal=internal-auth-token="$INTERNAL_AUTH_TOKEN"

  # Simple auth secret used for JWT signing/verification across services.
  SIMPLE_AUTH_SECRET="${SIMPLE_AUTH_SECRET:-$(kubectl get secret changetrace-simple-auth-secret -n changetrace -o jsonpath='{.data.simple-auth-secret}' 2>/dev/null | base64 -d)}"
  if [ -z "$SIMPLE_AUTH_SECRET" ]; then
    SIMPLE_AUTH_SECRET="changetrace-$(openssl rand -hex 24)"
  fi
  kubectl delete secret changetrace-simple-auth-secret -n changetrace 2>/dev/null || true
  kubectl create secret generic changetrace-simple-auth-secret -n changetrace \
    --from-literal=simple-auth-secret="$SIMPLE_AUTH_SECRET"

  export SIMPLE_AUTH_SECRET

  # Create ACR pull secret
  kubectl delete secret acr-pull-secret -n changetrace 2>/dev/null || true
  ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv 2>/dev/null || echo "")
  if [ -n "$ACR_PASSWORD" ]; then
    kubectl create secret docker-registry acr-pull-secret -n changetrace \
      --docker-server="$ACR_NAME.azurecr.io" \
      --docker-username="$ACR_NAME" \
      --docker-password="$ACR_PASSWORD"
  fi

  # Deploy ConfigMap
  kubectl apply -f "$PROJECT_ROOT/k8s/configmaps/"

  # Deploy all services with envsubst
  for manifest in "$PROJECT_ROOT"/k8s/deployments/*.yaml; do
    log "Applying $(basename "$manifest")"
    envsubst < "$manifest" | kubectl apply -f -
  done

  kubectl apply -f "$PROJECT_ROOT/k8s/services/"
  kubectl apply -f "$PROJECT_ROOT/k8s/ingress/"

  # Wait for all pods to be ready
  log "Waiting for pods to be ready..."
  kubectl wait --for=condition=Ready pods --all -n changetrace --timeout=300s 2>/dev/null || true

  # Show status
  kubectl get pods -n changetrace
  kubectl get svc -n changetrace

  log "AKS deployment complete"
}

# Step 4: Seed Cosmos DB with demo data
seed_demo_data() {
  log "=== Step 4: Seeding Cosmos DB with demo data ==="

  if [ -z "${COSMOS_DB_ENDPOINT:-}" ] || [ -z "${COSMOS_DB_KEY:-}" ]; then
    info "Getting Cosmos DB credentials from Terraform..."
    cd "$PROJECT_ROOT/terraform"
    COSMOS_ACCOUNT="$(terraform output -raw cosmos_account_name)"
    COSMOS_DB_ENDPOINT="wss://${COSMOS_ACCOUNT}.gremlin.cosmos.azure.com:443/"
    COSMOS_DB_KEY="$(terraform output -raw cosmos_primary_key)"
    cd "$PROJECT_ROOT"
  fi

  export COSMOS_DB_ENDPOINT COSMOS_DB_KEY
  python3 "$PROJECT_ROOT/scripts/seed_cosmos_db.py"
  log "Demo data seeded successfully"
}

# Main
main() {
  echo ""
  echo -e "${CYAN}============================================${NC}"
  echo -e "${CYAN}  ChangeTrace - Azure Deployment${NC}"
  echo -e "${CYAN}============================================${NC}"
  echo ""

  check_prereqs

  if ! $K8S_ONLY && ! $SEED_ONLY; then
    run_terraform
  fi

  if ! $TF_ONLY && ! $SEED_ONLY; then
    build_and_push_images
  fi

  if ! $TF_ONLY && ! $IMAGE_ONLY && ! $SEED_ONLY; then
    deploy_to_aks
  fi

  if ! $TF_ONLY && ! $IMAGE_ONLY && ! $K8S_ONLY; then
    seed_demo_data
  fi

  echo ""
  echo -e "${GREEN}============================================${NC}"
  echo -e "${GREEN}  Deployment Complete!${NC}"
  echo -e "${GREEN}============================================${NC}"
  echo ""
  info "To access the dashboard:"
  echo "  kubectl get svc -n changetrace changetrace-dashboard"
  echo ""
  info "To access any backend API:"
  echo "  kubectl port-forward -n changetrace svc/changetrace-dashboard-api 8002:8002"
  echo ""
  info "To run seed again:"
  echo "  ./scripts/deploy.sh --seed-only"
  echo ""
}

main "$@"
