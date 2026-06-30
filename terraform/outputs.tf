# Outputs for ChangeTrace Terraform configuration
# Note: Module outputs are defined in each module's outputs.tf
# Root-level outputs are defined in main.tf

output "resource_group_name" {
  description = "Resource group name"
  value       = azurerm_resource_group.main.name
}

output "cosmos_account_name" {
  description = "Cosmos DB account name (used to construct Gremlin WebSocket endpoint)"
  value       = azurerm_cosmosdb_account.main.name
}

output "cosmos_primary_key" {
  description = "Cosmos DB primary key"
  value       = azurerm_cosmosdb_account.main.primary_key
  sensitive   = true
}

output "cosmos_db_endpoint" {
  description = "Cosmos DB document endpoint"
  value       = azurerm_cosmosdb_account.main.endpoint
}

output "function_app_url" {
  description = "Function App URL"
  value       = "https://${azurerm_linux_function_app.main.default_hostname}"
}

output "aks_cluster_name" {
  description = "AKS cluster name"
  value       = module.aks.aks_cluster_name
}

output "acr_login_server" {
  description = "ACR login server"
  value       = azurerm_container_registry.main.login_server
}
