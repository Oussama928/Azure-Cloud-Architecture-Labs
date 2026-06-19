# Key Vault Module Outputs

output "key_vault_id" {
  description = "Key Vault Resource ID"
  value       = azurerm_key_vault.main.id
}

output "key_vault_name" {
  description = "Key Vault Name"
  value       = azurerm_key_vault.main.name
}

output "key_vault_uri" {
  description = "Key Vault URI"
  value       = azurerm_key_vault.main.vault_uri
}

output "key_vault_identity_principal_id" {
  description = "Key Vault Managed Identity Principal ID"
  value       = azurerm_key_vault.main.identity[0].principal_id
}