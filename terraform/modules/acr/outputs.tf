# ACR Module Outputs
# Note: Most outputs are defined in main.tf.
# This file contains additional outputs only.

output "container_registry_identity_principal_id" {
  description = "Container Registry Managed Identity Principal ID"
  value       = var.enable_acr ? azurerm_container_registry.main[0].identity[0].principal_id : ""
}
