#!/usr/bin/env bash
# aks_start.sh - Start AKS cluster for development/demo
# Usage: ./scripts/aks_start.sh [resource-group] [cluster-name]
# If no arguments provided, reads from terraform outputs

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' 

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

echo -e "${YELLOW}Starting AKS cluster: $CLUSTER_NAME in resource group: $RESOURCE_GROUP${NC}"

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

if [[ "$CLUSTER_STATE" == "Running" ]]; then
    echo -e "${GREEN}Cluster is already running${NC}"
    
    # Get credentials for kubectl
    echo "Fetching credentials..."
    az aks get-credentials \
        --resource-group "$RESOURCE_GROUP" \
        --name "$CLUSTER_NAME" \
        --overwrite-existing
    exit 0
fi

echo "Current cluster state: $CLUSTER_STATE"
echo -e "${YELLOW}Starting cluster... (this may take a few minutes)${NC}"

# Start the cluster
az aks start \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CLUSTER_NAME" \
    --no-wait

echo -e "${GREEN}Start command issued. Cluster is starting in the background.${NC}"
echo "Run 'az aks show --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME --query powerState.code -o tsv' to check status"
echo ""
echo -e "${YELLOW}Waiting for cluster to be ready...${NC}"

# Wait for cluster to be running
while true; do
    STATE=$(az aks show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$CLUSTER_NAME" \
        --query "powerState.code" \
        -o tsv 2>/dev/null || echo "Error")
    
    if [[ "$STATE" == "Running" ]]; then
        echo -e "${GREEN}Cluster is now running!${NC}"
        break
    elif [[ "$STATE" == "Error" ]]; then
        echo -e "${RED}Error checking cluster state${NC}"
        exit 1
    fi
    
    echo "Current state: $STATE (waiting...)"
    sleep 30
done

# Get credentials
echo "Fetching kubectl credentials..."
az aks get-credentials \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CLUSTER_NAME" \
    --overwrite-existing

echo -e "${GREEN}AKS cluster is ready!${NC}"
echo ""
echo -e "${YELLOW}  IMPORTANT: Remember to run './scripts/aks_stop.sh' when done to avoid unnecessary costs!${NC}"
echo "Estimated cost while running: ~\$0.10/hour for the cluster + node pool costs"