# Network Policies Module Outputs

output "network_security_group_id" {
  description = "Network Security Group ID"
  value       = var.enable_network_policies ? azurerm_network_security_group.main[0].id : ""
}

output "network_security_group_name" {
  description = "Network Security Group Name"
  value       = var.enable_network_policies ? azurerm_network_security_group.main[0].name : ""
}
