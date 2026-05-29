# Container Registry module for ChangeTrace

resource "azurerm_container_registry" "main" {
  count = var.enable_acr ? 1 : 0

  name                = "changetrace${var.environment}${random_string.suffix.result}acr"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = var.sku
  admin_enabled       = false

  # Enable managed identity
  identity {
    type = "SystemAssigned"
  }

  # Geo-replication (disabled for dev to save cost)
  georeplication_locations = var.environment == "prod" ? [var.geo_replication_location] : []

  # Network rules
  network_rule_set {
    default_action = var.environment == "prod" ? "Deny" : "Allow"

    ip_rule {
      action   = "Allow"
      ip_range = var.allowed_ip_range
    }

    virtual_network_subnet_id = var.subnet_id
  }

  # Retention policy for untagged manifests
  retention_policy {
    days    = 7
    enabled = true
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

# Grant Function App access to ACR
resource "azurerm_role_assignment" "function_app_acr_pull" {
  count = var.enable_acr && var.function_app_identity_id != "" ? 1 : 0

  scope                = azurerm_container_registry.main[0].id
  role_definition_name = "AcrPull"
  principal_id         = var.function_app_identity_id
}

# Grant AKS access to ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  count = var.enable_acr && var.aks_identity_id != "" ? 1 : 0

  scope                = azurerm_container_registry.main[0].id
  role_definition_name = "AcrPull"
  principal_id         = var.aks_identity_id
}

# Outputs
output "container_registry_name" {
  value = var.enable_acr ? azurerm_container_registry.main[0].name : ""
}

output "container_registry_login_server" {
  value = var.enable_acr ? azurerm_container_registry.main[0].login_server : ""
}

output "container_registry_id" {
  value = var.enable_acr ? azurerm_container_registry.main[0].id : ""
}

output "container_registry_identity_id" {
  value = var.enable_acr ? azurerm_container_registry.main[0].identity[0].principal_id : ""
}