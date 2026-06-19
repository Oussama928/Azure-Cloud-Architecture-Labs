# Cosmos DB Module Outputs

output "cosmosdb_account_id" {
  description = "Cosmos DB Account Resource ID"
  value       = azurerm_cosmosdb_account.main.id
}

output "cosmosdb_account_name" {
  description = "Cosmos DB Account Name"
  value       = azurerm_cosmosdb_account.main.name
}

output "cosmosdb_account_endpoint" {
  description = "Cosmos DB Account Endpoint"
  value       = azurerm_cosmosdb_account.main.endpoint
}

output "cosmosdb_primary_key" {
  description = "Cosmos DB Primary Key"
  value       = azurerm_cosmosdb_account.main.primary_key
  sensitive   = true
}

output "cosmosdb_primary_connection_string" {
  description = "Cosmos DB Primary Connection String"
  value       = azurerm_cosmosdb_account.main.primary_connection_string
  sensitive   = true
}

output "gremlin_database_id" {
  description = "Gremlin Database Resource ID"
  value       = azurerm_cosmosdb_gremlin_database.graph.id
}

output "gremlin_database_name" {
  description = "Gremlin Database Name"
  value       = azurerm_cosmosdb_gremlin_database.graph.name
}

output "dependencies_graph_id" {
  description = "Dependencies Graph Resource ID"
  value       = azurerm_cosmosdb_gremlin_graph.dependencies.id
}

output "changes_graph_id" {
  description = "Changes Graph Resource ID"
  value       = azurerm_cosmosdb_gremlin_graph.changes.id
}

output "incidents_graph_id" {
  description = "Incidents Graph Resource ID"
  value       = azurerm_cosmosdb_gremlin_graph.incidents.id
}