# Event Grid Module Outputs

output "cicd_events_topic_id" {
  description = "CI/CD Events Topic Resource ID"
  value       = azurerm_eventgrid_topic.cicd_events.id
}

output "cicd_events_topic_endpoint" {
  description = "CI/CD Events Topic Endpoint"
  value       = azurerm_eventgrid_topic.cicd_events.endpoint
}

output "git_events_topic_id" {
  description = "Git Events Topic Resource ID"
  value       = azurerm_eventgrid_topic.git_events.id
}

output "git_events_topic_endpoint" {
  description = "Git Events Topic Endpoint"
  value       = azurerm_eventgrid_topic.git_events.endpoint
}

output "alert_events_topic_id" {
  description = "Alert Events Topic Resource ID"
  value       = azurerm_eventgrid_topic.alert_events.id
}

output "alert_events_topic_endpoint" {
  description = "Alert Events Topic Endpoint"
  value       = azurerm_eventgrid_topic.alert_events.endpoint
}

output "argo_events_topic_id" {
  description = "Argo Events Topic Resource ID"
  value       = azurerm_eventgrid_topic.argo_events.id
}

output "argo_events_topic_endpoint" {
  description = "Argo Events Topic Endpoint"
  value       = azurerm_eventgrid_topic.argo_events.endpoint
}