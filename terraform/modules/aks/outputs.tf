output "aks_server_fully_qualified_domain_name" {
  description = "AKS cluster server fully qualified domain name"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].fqdn : ""
}

output "aks_node_resource_group" {
  description = "Auto-generated resource group for AKS node resources"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].node_resource_group : ""
}

output "aks_api_server_endpoint" {
  description = "AKS API server endpoint"
  value       = var.enable_aks ? azurerm_kubernetes_cluster.main[0].fqdn : ""
}
