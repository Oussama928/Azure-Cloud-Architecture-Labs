# Terraform configuration for ChangeTrace - cost effective Azure infrastructure

terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
  
  backend "azurerm" {
    # Configured via command line
  }
}

provider "azurerm" {
  features {}
  
  # Use Azure CLI authentication
  # For CI/CD, will use OIDC with GitHub Actions
}

# Random suffix for globally unique names
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Resource group for all resources
resource "azurerm_resource_group" "main" {
  name     = "changetrace-${random_string.suffix.result}-rg"
  location = var.location
  
  tags = var.common_tags
}

# Log Analytics Workspace (free tier)
resource "azurerm_log_analytics_workspace" "main" {
  name                = "changetrace-${random_string.suffix.result}-law"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  
  tags = var.common_tags
}

# Application Insights (free tier)
resource "azurerm_application_insights" "main" {
  name                = "changetrace-${random_string.suffix.result}-ai"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id
  
  # Daily data cap (100MB free tier limit)
  daily_data_cap_in_gb = var.app_insights_daily_cap_gb
  
  # Sampling to stay within free tier
  sampling_percentage = var.app_insights_sampling_percentage
  
  tags = var.common_tags
}

# Key Vault (Standard tier)
resource "azurerm_key_vault" "main" {
  name                        = "changetrace-${random_string.suffix.result}-kv"
  location                    = azurerm_resource_group.main.location
  resource_group_name         = azurerm_resource_group.main.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  purge_protection_enabled    = false
  soft_delete_retention_days  = 7
  
  enable_rbac_authorization = true
  
  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }
  
  tags = var.common_tags
}

# Key Vault access policy for the current user (for development)
resource "azurerm_key_vault_access_policy" "current_user" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id
  
  secret_permissions = ["Get", "List", "Set", "Delete", "Recover", "Backup", "Restore"]
  key_permissions    = ["Get", "List", "Create", "Delete", "Recover", "Backup", "Restore"]
  certificate_permissions = ["Get", "List", "Create", "Delete", "Recover", "Backup", "Restore"]
}

# Cosmos DB Account (Free tier)
resource "azurerm_cosmosdb_account" "main" {
  name                = "changetrace-${random_string.suffix.result}-cosmos"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  
  free_tier_enabled = var.cosmos_db_free_tier
  
  # Gremlin API for graph database
  capabilities {
    name = "EnableGremlin"
  }
  
  consistency_policy {
    consistency_level       = "Session"
    max_interval_in_seconds = 5
    max_staleness_prefix    = 100
  }
  
  # Public network access (will be restricted in production)
  public_network_access_enabled = true
  
  # Required geo_location block
  geo_location {
    location          = azurerm_resource_group.main.location
    failover_priority = 0
  }
  
  backup {
    type              = "Periodic"
    interval_in_minutes = 240
    retention_in_hours  = 8
  }
  
  tags = var.common_tags
}

resource "azurerm_cosmosdb_gremlin_database" "graph" {
  name                = "changetrace-graph"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  autoscale_settings {
    max_throughput = 1000
  }
}

# Cosmos DB Gremlin Graph - Dependencies
resource "azurerm_cosmosdb_gremlin_graph" "dependencies" {
  name                = "dependencies"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.graph.name
  partition_key_path  = "/serviceName"
  throughput          = 400
}

# Cosmos DB Gremlin Graph - Changes
resource "azurerm_cosmosdb_gremlin_graph" "changes" {
  name                = "changes"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.graph.name
  partition_key_path  = "/serviceName"
  throughput          = 400
}

# Cosmos DB Gremlin Graph - Incidents
resource "azurerm_cosmosdb_gremlin_graph" "incidents" {
  name                = "incidents"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.graph.name
  partition_key_path  = "/serviceName"
  throughput          = 400
}

# Event Grid Custom Topic for CI/CD events
resource "azurerm_eventgrid_topic" "cicd_events" {
  name                = "changetrace-${random_string.suffix.result}-cicd-events"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  
  tags = var.common_tags
}

# Event Grid Custom Topic for Git events
resource "azurerm_eventgrid_topic" "git_events" {
  name                = "changetrace-${random_string.suffix.result}-git-events"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  
  tags = var.common_tags
}

# Event Grid Custom Topic for Alert events
resource "azurerm_eventgrid_topic" "alert_events" {
  name                = "changetrace-${random_string.suffix.result}-alert-events"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  
  tags = var.common_tags
}

# Event Grid Custom Topic for Argo Rollouts events
resource "azurerm_eventgrid_topic" "argo_events" {
  name                = "changetrace-${random_string.suffix.result}-argo-events"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  
  tags = var.common_tags
}

# Storage Account for Function App and Terraform state
resource "azurerm_storage_account" "main" {
  name                     = "changetrace${random_string.suffix.result}sa"
  location                 = azurerm_resource_group.main.location
  resource_group_name      = azurerm_resource_group.main.name
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  
  # Enable blob versioning for state file protection
  blob_properties {
    versioning_enabled = true
  }
  
  tags = var.common_tags
}

# Storage container for function app
resource "azurerm_storage_container" "function_app" {
  name                  = "changetrace-functions"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# Consumption plan for Function App
resource "azurerm_service_plan" "consumption" {
  name                = "changetrace-${random_string.suffix.result}-plan"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = "Y1"  # Consumption plan
  tags = var.common_tags
}

# Key Vault secrets for Function App configuration
resource "azurerm_key_vault_secret" "cosmos_connection" {
  name         = "cosmos-db-connection-string"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_cosmosdb_account.main.connection_strings[0]
}

resource "azurerm_key_vault_secret" "eventgrid_cicd_endpoint" {
  name         = "eventgrid-cicd-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.cicd_events.endpoint
}

resource "azurerm_key_vault_secret" "eventgrid_cicd_key" {
  name         = "eventgrid-cicd-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.cicd_events.primary_access_key
}

resource "azurerm_key_vault_secret" "eventgrid_git_endpoint" {
  name         = "eventgrid-git-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.git_events.endpoint
}

resource "azurerm_key_vault_secret" "eventgrid_git_key" {
  name         = "eventgrid-git-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.git_events.primary_access_key
}

resource "azurerm_key_vault_secret" "eventgrid_alert_endpoint" {
  name         = "eventgrid-alert-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.alert_events.endpoint
}

resource "azurerm_key_vault_secret" "eventgrid_alert_key" {
  name         = "eventgrid-alert-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.alert_events.primary_access_key
}

resource "azurerm_key_vault_secret" "eventgrid_argo_endpoint" {
  name         = "eventgrid-argo-endpoint"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.argo_events.endpoint
}

resource "azurerm_key_vault_secret" "eventgrid_argo_key" {
  name         = "eventgrid-argo-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_eventgrid_topic.argo_events.primary_access_key
}

resource "azurerm_key_vault_secret" "appinsights_key" {
  name         = "appinsights-instrumentation-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_application_insights.main.instrumentation_key
}

resource "azurerm_key_vault_secret" "appinsights_connection_string" {
  name         = "appinsights-connection-string"
  key_vault_id = azurerm_key_vault.main.id
  value        = azurerm_application_insights.main.connection_string
}

# Function App (Consumption plan - free tier)
resource "azurerm_linux_function_app" "main" {
  name                = "changetrace-${random_string.suffix.result}-func"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  storage_account_name = azurerm_storage_account.main.name
  service_plan_id     = azurerm_service_plan.consumption.id
  
  site_config {
    application_stack {
      python_version = "3.12"
    }
    
    cors {
      allowed_origins = ["*"]
    }
  }
  
  identity {
    type = "SystemAssigned"
  }
  
  # Application settings with Key Vault references
  app_settings = {
    "COSMOS_DB_CONNECTION_STRING" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.cosmos_connection.name}/)"
    "EVENTGRID_CICD_ENDPOINT"     = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_cicd_endpoint.name}/)"
    "EVENTGRID_CICD_KEY"          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_cicd_key.name}/)"
    "EVENTGRID_GIT_ENDPOINT"      = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_git_endpoint.name}/)"
    "EVENTGRID_GIT_KEY"           = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_git_key.name}/)"
    "EVENTGRID_ALERT_ENDPOINT"    = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_alert_endpoint.name}/)"
    "EVENTGRID_ALERT_KEY"         = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_alert_key.name}/)"
    "EVENTGRID_ARGO_ENDPOINT"     = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_argo_endpoint.name}/)"
    "EVENTGRID_ARGO_KEY"          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.eventgrid_argo_key.name}/)"
    "APPINSIGHTS_INSTRUMENTATIONKEY" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.appinsights_key.name}/)"
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/${azurerm_key_vault_secret.appinsights_connection_string.name}/)"
    "PYTHON_ENABLE_WORKER_EXTENSIONS" = "1"
    "FUNCTIONS_WORKER_RUNTIME" = "python"
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
  }
  
  tags = var.common_tags
}

# Grant Function App access to Key Vault
resource "azurerm_key_vault_access_policy" "function_app" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_linux_function_app.main.identity[0].principal_id
  
  secret_permissions = ["Get", "List"]
}

# Container Registry (Basic tier)
resource "azurerm_container_registry" "main" {
  name                = "changetrace${random_string.suffix.result}acr"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Basic"
  admin_enabled       = false
  
  # Enable managed identity
  identity {
    type = "SystemAssigned"
  }
  
  tags = var.common_tags
}

# Grant Function App access to ACR
resource "azurerm_role_assignment" "function_app_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

# Data sources
data "azurerm_client_config" "current" {}

output "function_app_name" {
  value = azurerm_linux_function_app.main.name
}

output "function_app_default_hostname" {
  value = azurerm_linux_function_app.main.default_hostname
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "container_registry_name" {
  value = azurerm_container_registry.main.name
}

output "container_registry_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "application_insights_name" {
  value = azurerm_application_insights.main.name
}

output "application_insights_instrumentation_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.main.id
}

output "log_analytics_workspace_name" {
  value = azurerm_log_analytics_workspace.main.name
}
