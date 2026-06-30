# Private Endpoints Module Outputs

output "cosmos_private_endpoint_id" {
  description = "Cosmos DB Private Endpoint ID"
  value       = var.enable_private_endpoints && var.cosmos_db_id != "" ? azurerm_private_endpoint.cosmos[0].id : ""
}

output "acr_private_endpoint_id" {
  description = "ACR Private Endpoint ID"
  value       = var.enable_private_endpoints && var.acr_id != "" ? azurerm_private_endpoint.acr[0].id : ""
}

output "key_vault_private_endpoint_id" {
  description = "Key Vault Private Endpoint ID"
  value       = var.enable_private_endpoints && var.key_vault_id != "" ? azurerm_private_endpoint.key_vault[0].id : ""
}

output "cosmos_private_dns_zone_id" {
  description = "Cosmos DB Private DNS Zone ID"
  value       = var.enable_private_endpoints ? azurerm_private_dns_zone.cosmos[0].id : ""
}

output "acr_private_dns_zone_id" {
  description = "ACR Private DNS Zone ID"
  value       = var.enable_private_endpoints ? azurerm_private_dns_zone.acr[0].id : ""
}

output "key_vault_private_dns_zone_id" {
  description = "Key Vault Private DNS Zone ID"
  value       = var.enable_private_endpoints ? azurerm_private_dns_zone.key_vault[0].id : ""
}
