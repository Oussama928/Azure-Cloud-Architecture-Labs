# Cosmos DB Module Outputs
# Note: Most outputs are defined in main.tf.
# This file contains additional outputs with resource IDs.

output "cosmosdb_account_id" {
  description = "Cosmos DB Account Resource ID"
  value       = azurerm_cosmosdb_account.main.id
}

output "cosmosdb_account_endpoint" {
  description = "Cosmos DB Account Endpoint"
  value       = azurerm_cosmosdb_account.main.endpoint
}

output "gremlin_database_id" {
  description = "Gremlin Database Resource ID"
  value       = azurerm_cosmosdb_gremlin_database.main.id
}

output "dependency_graph_id" {
  description = "Dependency Graph Resource ID"
  value       = azurerm_cosmosdb_gremlin_graph.dependency_graph.id
}

output "change_history_graph_id" {
  description = "Change History Graph Resource ID"
  value       = azurerm_cosmosdb_gremlin_graph.change_history.id
}

output "incidents_graph_id" {
  description = "Incidents Graph Resource ID"
  value       = azurerm_cosmosdb_gremlin_graph.incidents.id
}
