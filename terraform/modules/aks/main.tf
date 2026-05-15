# AKS module for ChangeTrace - Only enable when needed as it costs quite a bit

resource "azurerm_kubernetes_cluster" "main" {
  count = var.enable_aks ? 1 : 0
  
  name                = "changetrace-${var.environment}-${random_string.suffix.result}-aks"
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = "changetrace-${var.environment}-${random_string.suffix.result}"
  
  # Use managed identity
  identity {
    type = "SystemAssigned"
  }
  
  local_account_disabled = false
  
  # Network profile
  network_profile {
    network_plugin     = "azure"
    network_policy     = "calico"
    load_balancer_sku  = "standard"
    dns_service_ip     = "10.0.0.10"
    service_cidr       = "10.0.0.0/16"
    docker_bridge_cidr = "172.17.0.1/16"
  }
  
  # Default node pool
  default_node_pool {
    name           = "system"
    vm_size        = var.node_vm_size
    enable_auto_scaling = true
    min_count      = var.min_node_count
    max_count      = var.max_node_count
    node_count     = var.node_count
    os_disk_size_gb = 30
    os_disk_type   = "Ephemeral"
    type           = "VirtualMachineScaleSets"
    availability_zones = var.availability_zones
    
    # Labels for system pods
    node_labels = {
      "workload-type" = "system"
    }
    
    # Taints for system pool
    node_taints = [
      "CriticalAddonsOnly=true:NoSchedule"
    ]
  }
  
  # Additional node pool for workloads
  node_pool {
    name           = "workload"
    vm_size        = var.workload_vm_size
    enable_auto_scaling = true
    min_count      = var.workload_min_count
    max_count      = var.workload_max_count
    node_count     = var.workload_node_count
    os_disk_size_gb = 30
    os_disk_type   = "Ephemeral"
    type           = "VirtualMachineScaleSets"
    availability_zones = var.availability_zones
    
    node_labels = {
      "workload-type" = "application"
    }
  }
  
  oidc_issuer_enabled = true
  
  workload_identity_enabled = true
  
  # Azure Policy (disabled for dev to save cost)
  azure_policy_enabled = var.environment == "prod"
  
  # Private cluster (disabled for dev to save cost)
  private_cluster_enabled = var.environment == "prod"
  
  # API server authorized IP ranges (for security)
  api_server_authorized_ip_ranges = var.api_server_authorized_ip_ranges
  
  tags = var.common_tags
}

# User-assigned managed identity for workload identity
resource "azurerm_user_assigned_identity" "workload_identity" {
  count = var.enable_aks ? 1 : 0
  
  name                = "changetrace-${var.environment}-${random_string.suffix.result}-wi"
  location            = var.location
  resource_group_name = var.resource_group_name
  
  tags = var.common_tags
}

# Federated identity credential for GitHub Actions
resource "azurerm_federated_identity_credential" "github_actions" {
  count = var.enable_aks && var.github_repository != "" ? 1 : 0
  
  name                = "github-actions-main"
  resource_group_name = var.resource_group_name
  parent_id           = azurerm_user_assigned_identity.workload_identity[0].id
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_repository}:ref:refs/heads/main"
  audiences           = ["api://AzureADTokenExchange"]
}

resource "azurerm_federated_identity_credential" "github_actions_pr" {
  count = var.enable_aks && var.github_repository != "" ? 1 : 0
  
  name                = "github-actions-pr"
  resource_group_name = var.resource_group_name
  parent_id           = azurerm_user_assigned_identity.workload_identity[0].id
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_repository}:pull_request"
  audiences           = ["api://AzureADTokenExchange"]
}

# Role assignment for workload identity to access Key Vault
resource "azurerm_role_assignment" "workload_identity_keyvault" {
  count = var.enable_aks && var.key_vault_id != "" ? 1 : 0
  
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload_identity[0].principal_id
}

# Role assignment for workload identity to access Cosmos DB
resource "azurerm_role_assignment" "workload_identity_cosmos" {
  count = var.enable_aks && var.cosmos_db_id != "" ? 1 : 0
  
  scope                = var.cosmos_db_id
  role_definition_name = "Cosmos DB Built-in Data Contributor"
  principal_id         = azurerm_user_assigned_identity.workload_identity[0].principal_id
}

# Role assignment for workload identity to access ACR
resource "azurerm_role_assignment" "workload_identity_acr" {
  count = var.enable_aks && var.acr_id != "" ? 1 : 0
  
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.workload_identity[0].principal_id
}

# Outputs
output "aks_cluster_name" {
  description = "AKS cluster name"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].name : ""
}

output "aks_cluster_id" {
  description = "AKS cluster resource ID"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].id : ""
}

output "aks_kube_config" {
  description = "AKS kubeconfig (sensitive)"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].kube_config_raw : ""
  sensitive   = true
}

output "aks_identity_id" {
  description = "AKS managed identity object ID"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].identity[0].principal_id : ""
}

output "workload_identity_id" {
  description = "Workload identity client ID"
  value       = var.enable_aks ? azurerm_user_assigned_identity.workload_identity[0].client_id : ""
}

output "workload_identity_principal_id" {
  description = "Workload identity principal ID"
  value       = var.enable_aks ? azurerm_user_assigned_identity.workload_identity[0].principal_id : ""
}