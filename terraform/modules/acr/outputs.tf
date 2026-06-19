# ACR Module Outputs

output "container_registry_id" {
  description = "Container Registry Resource ID"
  value       = azurerm_container_registry.main.id
}

output "container_registry_name" {
  description = "Container Registry Name"
  value       = azurerm_container_registry.main.name
}

output "container_registry_login_server" {
  description = "Container Registry Login Server"
  value       = azurerm_container_registry.main.login_server
}

output "container_registry_identity_principal_id" {
  description = "Container Registry Managed Identity Principal ID"
  value       = azurerm_container_registry.main.identity[0].principal_id
}