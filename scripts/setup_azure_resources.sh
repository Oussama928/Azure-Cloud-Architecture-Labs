#!/usr/bin/env bash
# setup_azure_resources.sh - Bootstrap Azure resources needed before Terraform
# This script creates the minimal resources needed to store Terraform state
# and sets up the Azure AD application for CI/CD

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
RESOURCE_GROUP="changetrace-tfstate-rg"
STORAGE_ACCOUNT="changetracetfstate$(date +%s | tail -c 6)"  # Must be globally unique
CONTAINER_NAME="tfstate"
LOCATION="${AZURE_LOCATION:-eastus}"
SUBSCRIPTION_ID="${1:-}"

# Get subscription if not provided
if [[ -z "$SUBSCRIPTION_ID" ]]; then
    SUBSCRIPTION_ID=$(az account show --query id -o tsv 2>/dev/null || echo "")
fi

if [[ -z "$SUBSCRIPTION_ID" ]]; then
    echo -e "${RED}Error: No subscription ID provided and no default subscription set${NC}"
    echo "Usage: $0 [subscription-id]"
    echo "Or run: az account set --subscription <id>"
    exit 1
fi

echo -e "${YELLOW}Setting up Azure resources for Terraform state storage${NC}"
echo "Subscription: $SUBSCRIPTION_ID"
echo "Resource Group: $RESOURCE_GROUP"
echo "Storage Account: $STORAGE_ACCOUNT"
echo "Location: $LOCATION"
echo ""

# Set subscription
az account set --subscription "$SUBSCRIPTION_ID"

# Check if resource group exists
if az group show --name "$RESOURCE_GROUP" &>/dev/null; then
    echo -e "${GREEN}Resource group $RESOURCE_GROUP already exists${NC}"
else
    echo "Creating resource group..."
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
    echo -e "${GREEN}✓ Resource group created${NC}"
fi

# Check if storage account exists
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    echo -e "${GREEN}Storage account $STORAGE_ACCOUNT already exists${NC}"
else
    echo "Creating storage account for Terraform state..."
    az storage account create \
        --name "$STORAGE_ACCOUNT" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --encryption-services blob \
        --https-only true \
        --min-tls-version TLS1_2 \
        --allow-blob-public-access false \
        --default-action Deny
    echo -e "${GREEN}✓ Storage account created${NC}"
fi

# Get storage account key
echo "Getting storage account key..."
ACCOUNT_KEY=$(az storage account keys list \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT" \
    --query "[0].value" -o tsv)

# Create container for Terraform state
echo "Creating blob container for Terraform state..."
az storage container create \
    --name "$CONTAINER_NAME" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$ACCOUNT_KEY" \
    --public-access off 2>/dev/null || echo "Container may already exist"

echo -e "${GREEN}✓ Terraform state storage configured${NC}"

# Enable versioning on the storage account for state protection
az storage account blob-service-properties update \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$ACCOUNT_KEY" \
    --enable-versioning true \
    --enable-delete-retention true \
    --delete-retention-days 30

echo -e "${GREEN}✓ Blob versioning and soft delete enabled${NC}"

# Create Azure AD application for GitHub Actions / CI/CD
echo ""
echo -e "${YELLOW}Setting up Azure AD application for CI/CD...${NC}"

APP_NAME="changetrace-cicd-$(date +%s)"
APP_EXISTS=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv 2>/dev/null || echo "")

if [[ -n "$APP_EXISTS" ]]; then
    echo -e "${GREEN}App registration already exists: $APP_EXISTS${NC}"
    APP_ID="$APP_EXISTS"
else
    echo "Creating Azure AD application..."
    APP_ID=$(az ad app create \
        --display-name "$APP_NAME" \
        --query appId -o tsv)
    echo -e "${GREEN}✓ App created: $APP_ID${NC}"
fi

# Create service principal
SP_EXISTS=$(az ad sp list --filter "appId eq '$APP_ID'" --query "[0].id" -o tsv 2>/dev/null || echo "")

if [[ -n "$SP_EXISTS" ]]; then
    echo -e "${GREEN}Service principal already exists: $SP_EXISTS${NC}"
    SP_ID="$SP_EXISTS"
else
    echo "Creating service principal..."
    SP_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
    echo -e "${GREEN}✓ Service principal created: $SP_ID${NC}"
    
    # Wait for propagation
    echo "Waiting for service principal to propagate..."
    sleep 10
fi

# Assign Contributor role at subscription level (for Terraform)
echo "Assigning Contributor role to service principal..."
az role assignment create \
    --assignee "$APP_ID" \
    --role "Contributor" \
    --scope "/subscriptions/$SUBSCRIPTION_ID" \
    --description "ChangeTrace CI/CD deployment" 2>/dev/null || echo "Role assignment may already exist"

# Also assign User Access Administrator for role assignments
az role assignment create \
    --assignee "$APP_ID" \
    --role "User Access Administrator" \
    --scope "/subscriptions/$SUBSCRIPTION_ID" \
    --description "ChangeTrace CI/CD role management" 2>/dev/null || echo "Role assignment may already exist"

echo -e "${GREEN}✓ Role assignments created${NC}"

# Create federated identity credential for GitHub Actions (OIDC)
# This allows GitHub Actions to authenticate without secrets
echo ""
echo -e "${YELLOW}Setting up GitHub Actions OIDC federation...${NC}"
echo "You'll need to provide your GitHub repository (owner/repo) to configure this."
read -p "GitHub repository (e.g., owner/repo) [press Enter to skip]: " GITHUB_REPO

if [[ -n "$GITHUB_REPO" ]]; then
    # Create federated credential for main branch
    az ad app federated-credential create \
        --id "$APP_ID" \
        --parameters "{
            \"name\": \"github-actions-main\",
            \"issuer\": \"https://token.actions.githubusercontent.com\",
            \"subject\": \"repo:${GITHUB_REPO}:ref:refs/heads/main\",
            \"audiences\": [\"api://AzureADTokenExchange\"]
        }" 2>/dev/null || echo "Federated credential may already exist"
    
    # Create for pull requests
    az ad app federated-credential create \
        --id "$APP_ID" \
        --parameters "{
            \"name\": \"github-actions-pr\",
            \"issuer\": \"https://token.actions.githubusercontent.com\",
            \"subject\": \"repo:${GITHUB_REPO}:pull_request\",
            \"audiences\": [\"api://AzureADTokenExchange\"]
        }" 2>/dev/null || echo "Federated credential may already exist"
    
    echo -e "${GREEN}✓ GitHub Actions OIDC configured${NC}"
else
    echo -e "${YELLOW}Skipped OIDC setup. Configure manually later for passwordless GitHub Actions auth.${NC}"
fi

# Output summary
echo ""
echo -e "${GREEN}=== Azure Bootstrap Complete ===${NC}"
echo ""
echo "Add these to your GitHub repository secrets (Settings > Secrets > Actions):"
echo ""
echo "AZURE_CLIENT_ID: $APP_ID"
echo "AZURE_TENANT_ID: $(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID: $SUBSCRIPTION_ID"
echo ""
echo "For Terraform backend configuration, add to your terraform/backend.tf:"
echo ""
cat <<EOF
terraform {
  backend "azurerm" {
    resource_group_name  = "$RESOURCE_GROUP"
    storage_account_name = "$STORAGE_ACCOUNT"
    container_name       = "$CONTAINER_NAME"
    key                  = "changetrace.tfstate"
  }
}
EOF

echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Add the GitHub secrets above"
echo "2. Configure Terraform backend (see output above)"
echo "3. Run 'terraform init' in the terraform/ directory"
echo "4. Run 'terraform plan' to see what will be created"
echo "5. Run 'terraform apply' to provision infrastructure"
echo ""
echo -e "${YELLOW}Estimated monthly cost for these bootstrap resources: ~\$0.50 (storage account)${NC}"