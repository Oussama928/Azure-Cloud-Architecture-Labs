# Monitor Module Outputs

output "log_analytics_workspace_id" {
  description = "Log Analytics Workspace Resource ID"
  value       = azurerm_log_analytics_workspace.main.id
}

output "log_analytics_workspace_name" {
  description = "Log Analytics Workspace Name"
  value       = azurerm_log_analytics_workspace.main.name
}

output "application_insights_id" {
  description = "Application Insights Resource ID"
  value       = azurerm_application_insights.main.id
}

output "application_insights_name" {
  description = "Application Insights Name"
  value       = azurerm_application_insights.main.name
}

output "application_insights_instrumentation_key" {
  description = "Application Insights Instrumentation Key"
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}

output "application_insights_connection_string" {
  description = "Application Insights Connection String"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "action_group_id" {
  description = "Action Group Resource ID"
  value       = azurerm_monitor_action_group.main.id
}

output "action_group_name" {
  description = "Action Group Name"
  value       = azurerm_monitor_action_group.main.name
}