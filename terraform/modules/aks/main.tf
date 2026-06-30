# AKS module for ChangeTrace - AzureRM v4 compatible

resource "azurerm_kubernetes_cluster" "main" {
  count = var.enable_aks ? 1 : 0

  name                = "changetrace-${var.environment}-aks"
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = "changetrace-${var.environment}-aks"

  identity {
    type = "SystemAssigned"
  }

  local_account_disabled = false

  default_node_pool {
    name            = "system"
    vm_size         = var.node_vm_size
    node_count      = var.node_count
    os_disk_size_gb = 30
    os_disk_type    = "Managed"
    zones           = var.availability_zones
    node_labels = {
      "workload-type" = "system"
    }
  }

  network_profile {
    network_plugin    = "azure"
    network_policy    = "calico"
    load_balancer_sku = "standard"
    dns_service_ip    = "10.0.0.10"
    service_cidr      = "10.0.0.0/16"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  azure_policy_enabled      = false
  private_cluster_enabled   = false

  tags = var.common_tags
}

resource "azurerm_kubernetes_cluster_node_pool" "workload" {
  count = var.enable_aks ? 1 : 0

  name                  = "workload"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main[0].id
  vm_size               = var.workload_vm_size
  node_count            = var.workload_node_count
  os_disk_size_gb       = 30
  os_disk_type          = "Managed"
  zones                 = var.availability_zones
  node_labels = {
    "workload-type" = "application"
  }
}

resource "azurerm_user_assigned_identity" "workload_identity" {
  count = var.enable_aks ? 1 : 0

  name                = "changetrace-${var.environment}-aks-wi"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.common_tags
}

resource "azurerm_federated_identity_credential" "github_actions" {
  count = var.enable_aks && var.github_repository != "" ? 1 : 0

  name      = "changetrace-${var.environment}-github-actions"
  parent_id = azurerm_user_assigned_identity.workload_identity[0].id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = "https://token.actions.githubusercontent.com"
  subject   = "repo:${var.github_repository}:environment:${var.environment}"
}

resource "azurerm_role_assignment" "workload_identity_keyvault" {
  count = var.enable_aks && var.key_vault_id != "" ? 1 : 0

  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload_identity[0].principal_id
}

resource "azurerm_role_assignment" "workload_identity_cosmos" {
  count = var.enable_aks && var.cosmos_db_id != "" ? 1 : 0

  scope                = var.cosmos_db_id
  role_definition_name = "DocumentDB Account Contributor"
  principal_id         = azurerm_user_assigned_identity.workload_identity[0].principal_id
}

resource "azurerm_role_assignment" "workload_identity_acr" {
  count = var.enable_aks && var.acr_id != "" ? 1 : 0

  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.workload_identity[0].principal_id
}

output "aks_cluster_name" {
  value = var.enable_aks ? azurerm_kubernetes_cluster.main[0].name : ""
}

output "aks_cluster_id" {
  value = var.enable_aks ? azurerm_kubernetes_cluster.main[0].id : ""
}

output "aks_kube_config" {
  value     = var.enable_aks ? azurerm_kubernetes_cluster.main[0].kube_config_raw : ""
  sensitive = true
}

output "aks_identity_id" {
  value = var.enable_aks ? azurerm_kubernetes_cluster.main[0].identity[0].principal_id : ""
}

output "workload_identity_id" {
  value = var.enable_aks ? azurerm_user_assigned_identity.workload_identity[0].client_id : ""
}

output "workload_identity_principal_id" {
  value = var.enable_aks ? azurerm_user_assigned_identity.workload_identity[0].principal_id : ""
}