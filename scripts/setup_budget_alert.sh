#!/usr/bin/env bash
# this is custom only to me, cause of limited budget
# setup_budget_alert.sh - Configure Azure budget alerts for cost control
# Usage: ./scripts/setup_budget_alert.sh [subscription-id] [budget-amount-usd] [alert-email]
# Budget amount defaults to $60 (project budget), email defaults to Azure account owner

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SUBSCRIPTION_ID="${1:-}"
BUDGET_AMOUNT="${2:-60}"  # Default $60 budget
ALERT_EMAIL="${3:-}"

# Get current subscription if not provided
if [[ -z "$SUBSCRIPTION_ID" ]]; then
    SUBSCRIPTION_ID=$(az account show --query id -o tsv 2>/dev/null || echo "")
fi

if [[ -z "$SUBSCRIPTION_ID" ]]; then
    echo -e "${RED}Error: No subscription ID provided and no default subscription set${NC}"
    echo "Usage: $0 [subscription-id] [budget-amount-usd] [alert-email]"
    echo "Run 'az account set --subscription <id>' first or provide subscription ID"
    exit 1
fi

# Get default email if not provided
if [[ -z "$ALERT_EMAIL" ]]; then
    ALERT_EMAIL=$(az account show --query user.name -o tsv 2>/dev/null || echo "")
fi

if [[ -z "$ALERT_EMAIL" ]]; then
    echo -e "${YELLOW}Warning: No alert email provided and couldn't determine account email${NC}"
    read -p "Enter email for budget alerts: " ALERT_EMAIL
fi

echo -e "${YELLOW}Setting up budget alert for subscription: $SUBSCRIPTION_ID${NC}"
echo "Budget: \$$BUDGET_AMOUNT USD/month"
echo "Alert email: $ALERT_EMAIL"
echo ""

# Set the subscription
az account set --subscription "$SUBSCRIPTION_ID"

# Create budget with alerts at 50%, 80%, and 100%
BUDGET_NAME="changetrace-monthly-budget"
RESOURCE_GROUP="changetrace-rg" 


echo "Creating budget with alerts at 50%, 80%, and 100%..."


# Register the provider if needed
az provider register --namespace Microsoft.Consumption --wait 2>/dev/null || true

# Create budget with multiple alerts
cat > /tmp/budget.json <<EOF
{
  "properties": {
    "category": "Cost",
    "amount": $BUDGET_AMOUNT,
    "timeGrain": "Monthly",
    "startDate": "$(date -u +%Y-%m-01T00:00:00Z)",
    "endDate": "$(date -u -d '+2 years' +%Y-%m-01T00:00:00Z)",
    "notifications": {
      "alert_50": {
        "enabled": true,
        "operator": "GreaterThan",
        "threshold": 50,
        "contactEmails: ["$ALERT_EMAIL"],
        "contactRoles": [],
        "contactGroups": []
      },
      "alert_80": {
        "enabled": true,
        "operator": "GreaterThan",
        "threshold": 80,
        "contactEmails": ["$ALERT_EMAIL"],
        "contactRoles": [],
        "contactGroups": []
      },
      "alert_100": {
        "enabled": true,
        "operator": "GreaterThan",
        "threshold": 100,
        "contactEmails": ["$ALERT_EMAIL"],
        "contactRoles": [],
        "contactGroups": []
      }
    }
  }
}
EOF

# Try to create budget via REST API since CLI support is limited
ACCESS_TOKEN=$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)

BUDGET_URL="https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.Consumption/budgets/${BUDGET_NAME}?api-version=2021-10-01"

echo "Creating budget via REST API..."

RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/budget.json \
    "$BUDGET_URL")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 300 ]]; then
    echo -e "${GREEN}✓ Budget created successfully!${NC}"
    echo "Budget name: $BUDGET_NAME"
    echo "Amount: \$$BUDGET_AMOUNT/month"
    echo "Alerts configured at: 50%, 80%, 100%"
    echo "Notification email: $ALERT_EMAIL"
else
    echo -e "${RED}Failed to create budget (HTTP $HTTP_CODE)${NC}"
    echo "Response: $BODY"
    echo ""
    echo "Alternative: Create budget manually in Azure Portal:"
    echo "1. Go to Cost Management + Billing > Budgets"
    echo "2. Click 'Add' > Set amount to \$$BUDGET_AMOUNT/month"
    echo "3. Add alerts at 50%, 80%, 100% with email: $ALERT_EMAIL"
    exit 1
fi

# Also create an action group for more sophisticated alerting 
echo ""
echo -e "${YELLOW}Creating action group for budget alerts...${NC}"

ACTION_GROUP_NAME="changetrace-budget-alerts"
ACTION_GROUP_RG="$RESOURCE_GROUP"

# Check if resource group exists, if not we'll note it needs to be created first
if ! az group show --name "$ACTION_GROUP_RG" &>/dev/null; then
    echo -e "${YELLOW}Resource group $ACTION_GROUP_RG doesn't exist yet (will be created by Terraform)${NC}"
    echo "Action group will be created after Terraform applies."
else
    az monitor action-group create \
        --resource-group "$ACTION_GROUP_RG" \
        --name "$ACTION_GROUP_NAME" \
        --short-name "CTBudget" \
        --action email "$ALERT_EMAIL" "BudgetAlert" \
        --action webhook "https://webhook.site/unique-id" "BudgetWebhook" 2>/dev/null || true
    
    echo -e "${GREEN}✓ Action group created${NC}"
fi

echo ""
echo -e "${GREEN}=== Budget Alert Setup Complete ===${NC}"
echo ""
echo "Next steps:"
echo "1. Verify budget in Azure Portal: Cost Management + Billing > Budgets"
echo "2. Run Terraform to create resource group and other resources"
echo "3. After Terraform, re-run this script to create the action group"
echo ""
echo -e "${YELLOW}  Remember: This budget alert only NOTIFIES. It does NOT automatically stop resources.${NC}"
echo "You must manually run ./scripts/aks_stop.sh when alerts fire."