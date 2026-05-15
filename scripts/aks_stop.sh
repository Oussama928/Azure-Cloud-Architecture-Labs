#!/usr/bin/env bash
# aks_stop.sh - Stop AKS cluster to save costs
# Usage: ./scripts/aks_stop.sh [resource-group] [cluster-name]
# If no arguments provided, reads from terraform outputs

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values (can be overridden by terraform outputs or arguments)
RESOURCE_GROUP="${1:-}"
CLUSTER_NAME="${2:-}"

# If not provided as arguments, try to get from terraform outputs
if [[ -z "$RESOURCE_GROUP" || -z "$CLUSTER_NAME" ]]; then
    if [[ -d "terraform" ]]; then
        cd terraform
        if [[ -z "$RESOURCE_GROUP" ]]; then
            RESOURCE_GROUP=$(terraform output -raw resource_group_name 2>/dev/null || echo "")
        fi
        if [[ -z "$CLUSTER_NAME" ]]; then
            CLUSTER_NAME=$(terraform output -raw aks_cluster_name 2>/dev/null || echo "")
        fi
        cd ..
    fi
fi

# Fallback to environment variables
RESOURCE_GROUP="${RESOURCE_GROUP:-${AZURE_RESOURCE_GROUP:-}}"
CLUSTER_NAME="${CLUSTER_NAME:-${AKS_CLUSTER_NAME:-}}"

if [[ -z "$RESOURCE_GROUP" || -z "$CLUSTER_NAME" ]]; then
    echo -e "${RED}Error: Resource group and cluster name must be provided${NC}"
    echo "Usage: $0 [resource-group] [cluster-name]"
    echo "Or set AZURE_RESOURCE_GROUP and AKS_CLUSTER_NAME environment variables"
    echo "Or run from terraform directory with outputs configured"
    exit 1
fi

echo -e "${YELLOW}Stopping AKS cluster: $CLUSTER_NAME in resource group: $RESOURCE_GROUP${NC}"

# Check if cluster exists and get current state
CLUSTER_STATE=$(az aks show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CLUSTER_NAME" \
    --query "powerState.code" \
    -o tsv 2>/dev/null || echo "NotFound")

if [[ "$CLUSTER_STATE" == "NotFound" ]]; then
    echo -e "${RED}Cluster not found: $CLUSTER_NAME${NC}"
    exit 1
fi

if [[ "$CLUSTER_STATE" == "Stopped" ]]; then
    echo -e "${GREEN}Cluster is already stopped${NC}"
    exit 0
fi

echo "Current cluster state: $CLUSTER_STATE"
echo -e "${YELLOW}Stopping cluster... (this may take a few minutes)${NC}"

# Stop the cluster
az aks stop \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CLUSTER_NAME" \
    --no-wait

echo -e "${GREEN}Stop command issued. Cluster is stopping in the background.${NC}"
echo "Run 'az aks show --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME --query powerState.code -o tsv' to check status"
echo ""
echo -e "${YELLOW}Note: Stopped clusters still incur minimal costs for attached resources (disks, IPs, etc.)${NC}"
echo "To fully eliminate costs, consider deleting the resource group when not needed for extended periods."