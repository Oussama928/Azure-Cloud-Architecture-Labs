# TLS Setup Module Outputs

output "ingress_certificate_uri" {
  description = "Key Vault URI of the ingress TLS certificate"
  value       = var.enable_tls && var.key_vault_id != "" ? azurerm_key_vault_certificate.ingress[0].secret_id : ""
}

output "api_certificate_uri" {
  description = "Key Vault URI of the API TLS certificate"
  value       = var.enable_tls && var.key_vault_id != "" ? azurerm_key_vault_certificate.api[0].secret_id : ""
}

output "ingress_certificate_version" {
  description = "Version of the ingress TLS certificate"
  value       = var.enable_tls && var.key_vault_id != "" ? azurerm_key_vault_certificate.ingress[0].version : ""
}

output "api_certificate_version" {
  description = "Version of the API TLS certificate"
  value       = var.enable_tls && var.key_vault_id != "" ? azurerm_key_vault_certificate.api[0].version : ""
}
