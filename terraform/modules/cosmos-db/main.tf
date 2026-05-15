# Cosmos DB module for ChangeTrace - Gremlin API with free tier

resource "azurerm_cosmosdb_account" "main" {
  name                = "changetrace-${var.environment}-${random_string.suffix.result}-cosmos"
  location            = var.location
  resource_group_name = var.resource_group_name
  
  offer_type = "Standard"
  

  free_tier_enabled = var.free_tier_enabled
  
  # Gremlin API for graph database
  capabilities {
    name = "EnableGremlin"
  }
  
  # Consistency policy
  consistency_policy {
    consistency_level       = "Session"
    max_interval_in_seconds = 5
    max_staleness_prefix    = 100
  }
  
  # Geo-redundancy (disabled for free tier)
  geo_redundancy_enabled = false
  
  backup_policy {
    type = "Periodic"
    periodic_mode_properties {
      backup_interval_in_minutes = 240
      backup_retention_interval_in_hours = 8
    }
  }
  
  public_network_access_enabled = true
  
  # Disable local auth (will use managed identity)
  disable_local_auth = true
  
  tags = var.common_tags
}

# Gremlin database
resource "azurerm_cosmosdb_gremlin_database" "main" {
  name                = "changetrace-graph"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  
  # Throughput , using autoscale for free tier
  autoscale_settings {
    max_throughput = 4000  
  }
}

# Gremlin graph for dependency graph
resource "azurerm_cosmosdb_gremlin_graph" "dependency_graph" {
  name                = "dependency-graph"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.main.name
  
  partition_key_path = "/serviceName"
  
  # Indexing policy for graph queries
  indexing_policy {
    automatic = true
    indexing_mode = "Consistent"
    
    included_path {
      path = "/*"
    }
    
    excluded_path {
      path = "/_etag/?"
    }
  }
  
}

# Gremlin graph for change history
resource "azurerm_cosmosdb_gremlin_graph" "change_history" {
  name                = "change-history"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.main.name
  
  partition_key_path = "/timestamp"
  
  indexing_policy {
    automatic = true
    indexing_mode = "Consistent"
    
    included_path {
      path = "/*"
    }
    
    excluded_path {
      path = "/_etag/?"
    }
  }
}

# Gremlin graph for incidents
resource "azurerm_cosmosdb_gremlin_graph" "incidents" {
  name                = "incidents"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.main.name
  
  partition_key_path = "/incidentId"
  
  indexing_policy {
    automatic = true
    indexing_mode = "Consistent"
    
    included_path {
      path = "/*"
    }
    
    excluded_path {
      path = "/_etag/?"
    }
  }
}

# Random string for unique naming
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
  number  = true
}

# Outputs
output "cosmos_db_account_name" {
  value = azurerm_cosmosdb_account.main.name
}

output "cosmos_db_gremlin_endpoint" {
  value = azurerm_cosmosdb_account.main.gremlin_endpoint
}

output "cosmos_db_primary_connection_string" {
  value     = azurerm_cosmosdb_account.main.primary_connection_string
  sensitive = true
}

output "cosmos_db_primary_key" {
  value     = azurerm_cosmosdb_account.main.primary_key
  sensitive = true
}

output "gremlin_database_name" {
  value = azurerm_cosmosdb_gremlin_database.main.name
}

output "dependency_graph_name" {
  value = azurerm_cosmosdb_gremlin_graph.dependency_graph.name
}

output "change_history_graph_name" {
  value = azurerm_cosmosdb_gremlin_graph.change_history.name
}

output "incidents_graph_name" {
  value = azurerm_cosmosdb_gremlin_graph.incidents.name
}