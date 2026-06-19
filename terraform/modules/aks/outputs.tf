# AKS Module Outputs

output "aks_cluster_id" {
  description = "AKS Cluster Resource ID"
  value       = azurerm_kubernetes_cluster.main.id
}

output "aks_cluster_name" {
  description = "AKS Cluster Name"
  value       = azurerm_kubernetes_cluster.main.name
}

output "aks_cluster_fqdn" {
  description = "AKS Cluster FQDN"
  value       = azurerm_kubernetes_cluster.main.fqdn
}

output "aks_cluster_identity_principal_id" {
  description = "AKS Cluster Managed Identity Principal ID"
  value       = azurerm_kubernetes_cluster.main.identity[0].principal_id
}

output "aks_node_resource_group" {
  description = "AKS Node Resource Group Name"
  value       = azurerm_kubernetes_cluster.main.node_resource_group
}

output "aks_kube_config" {
  description = "AKS Kubeconfig (sensitive)"
  value       = azurerm_kubernetes_cluster.main.kube_config_raw
  sensitive   = true
}

output "aks_kube_admin_config" {
  description = "AKS Kubeconfig Admin (sensitive)"
  value       = azurerm_kubernetes_cluster.main.kube_admin_config_raw
  sensitive   = true
}