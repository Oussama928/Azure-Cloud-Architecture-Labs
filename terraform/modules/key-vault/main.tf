# Key Vault module for ChangeTrace - Secrets management

# Key Vault (Standard tier)
resource "azurerm_key_vault" "main" {
  name                       = "changetrace-${var.environment}-${random_string.suffix.result}-kv"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
  enable_rbac_authorization  = true

  # Network ACLs - allow from Azure services
  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }

  tags = var.common_tags
}

# Random suffix for unique naming
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
  number  = true
}

# Access policy for current user (development)
resource "azurerm_key_vault_access_policy" "current_user" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions      = ["Get", "List", "Set", "Delete", "Recover", "Backup", "Restore"]
  key_permissions         = ["Get", "List", "Create", "Delete", "Recover", "Backup", "Restore"]
  certificate_permissions = ["Get", "List", "Create", "Delete", "Recover", "Backup", "Restore"]
}

# Access policy for Function App managed identity
resource "azurerm_key_vault_access_policy" "function_app" {
  count = var.function_app_identity_id != "" ? 1 : 0

  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = var.function_app_identity_id

  secret_permissions      = ["Get", "List"]
  key_permissions         = ["Get", "List"]
  certificate_permissions = ["Get", "List"]
}

# Access policy for AKS managed identity 
resource "azurerm_key_vault_access_policy" "aks_identity" {
  count = var.aks_identity_id != "" ? 1 : 0

  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = var.aks_identity_id

  secret_permissions      = ["Get", "List"]
  key_permissions         = ["Get", "List"]
  certificate_permissions = ["Get", "List"]
}

# Key Vault secrets for application configuration
# These are created as empty placeholders - actual values set by deployment scripts

resource "azurerm_key_vault_secret" "cosmos_connection" {
  name         = "cosmos-db-connection-string"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.cosmos_connection_string != "" ? var.cosmos_connection_string : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "cosmos_key" {
  name         = "cosmos-db-primary-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.cosmos_primary_key != "" ? var.cosmos_primary_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_cicd_endpoint" {
  name         = "eventgrid-cicd-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_cicd_endpoint != "" ? var.eventgrid_cicd_endpoint : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_cicd_key" {
  name         = "eventgrid-cicd-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_cicd_key != "" ? var.eventgrid_cicd_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_git_endpoint" {
  name         = "eventgrid-git-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_git_endpoint != "" ? var.eventgrid_git_endpoint : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_git_key" {
  name         = "eventgrid-git-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_git_key != "" ? var.eventgrid_git_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_alert_endpoint" {
  name         = "eventgrid-alert-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_alert_endpoint != "" ? var.eventgrid_alert_endpoint : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_alert_key" {
  name         = "eventgrid-alert-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_alert_key != "" ? var.eventgrid_alert_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_argo_endpoint" {
  name         = "eventgrid-argo-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_argo_endpoint != "" ? var.eventgrid_argo_endpoint : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "eventgrid_argo_key" {
  name         = "eventgrid-argo-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.eventgrid_argo_key != "" ? var.eventgrid_argo_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "appinsights_key" {
  name         = "appinsights-instrumentation-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.appinsights_key != "" ? var.appinsights_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "appinsights_connection_string" {
  name         = "appinsights-connection-string"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.appinsights_connection_string != "" ? var.appinsights_connection_string : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "github_webhook_secret" {
  name         = "github-webhook-secret"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.github_webhook_secret != "" ? var.github_webhook_secret : "PLACEHOLDER-GENERATE-AND-SET"
}

resource "azurerm_key_vault_secret" "github_app_id" {
  name         = "github-app-id"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.github_app_id != "" ? var.github_app_id : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "github_app_private_key" {
  name         = "github-app-private-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.github_app_private_key != "" ? var.github_app_private_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "approval_webhook_secret" {
  name         = "approval-webhook-secret"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.approval_webhook_secret != "" ? var.approval_webhook_secret : "PLACEHOLDER-GENERATE-AND-SET"
}

resource "azurerm_key_vault_secret" "argo_api_token" {
  name         = "argo-api-token"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.argo_api_token != "" ? var.argo_api_token : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

resource "azurerm_key_vault_secret" "azure_ml_workspace_key" {
  name         = "azure-ml-workspace-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.azure_ml_workspace_key != "" ? var.azure_ml_workspace_key : "PLACEHOLDER-SET-BY-DEPLOYMENT"
}

# Data source for current client config
data "azurerm_client_config" "current" {}

# Outputs
output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

output "key_vault_id" {
  value = azurerm_key_vault.main.id
}