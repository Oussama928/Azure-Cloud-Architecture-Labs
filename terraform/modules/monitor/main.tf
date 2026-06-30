# Monitor module for ChangeTrace - Log Analytics, Application Insights, Alerts

# Log Analytics Workspace (free tier 5GB/month)
resource "azurerm_log_analytics_workspace" "main" {
  name                = "changetrace-${var.environment}-${random_string.suffix.result}-law"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = var.common_tags
}

# Application Insights (free tier)
resource "azurerm_application_insights" "main" {
  name                = "changetrace-${var.environment}-${random_string.suffix.result}-ai"
  location            = var.location
  resource_group_name = var.resource_group_name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id

  # Daily data cap (100MB free tier)
  daily_data_cap_in_gb = var.daily_data_cap_gb

  # Sampling to stay within free tier
  sampling_percentage = var.sampling_percentage

  tags = var.common_tags
}

# Action Group for alerts
resource "azurerm_monitor_action_group" "main" {
  name                = "changetrace-${var.environment}-alerts"
  resource_group_name = var.resource_group_name
  short_name          = "CTAlerts"

  email_receiver {
    name                    = "admin"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }

  webhook_receiver {
    name                    = "webhook"
    service_uri             = var.webhook_url
    use_common_alert_schema = true
  }

  tags = var.common_tags
}

# Metric alert for Application Insights availability
resource "azurerm_monitor_metric_alert" "app_insights_availability" {
  name                 = "changetrace-${var.environment}-availability-alert"
  resource_group_name  = var.resource_group_name
  scopes               = [azurerm_application_insights.main.id]
  description          = "Alert when availability test fails"
  severity             = 2
  enabled              = true
  evaluation_frequency = "PT1M"
  window_size          = "PT5M"

  criteria {
    metric_namespace = "Microsoft.Insights/components"
    metric_name      = "availabilityResults/availabilityPercentage"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 99.0

    dimension {
      name     = "result"
      operator = "Exclude"
      values   = ["Success"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = var.common_tags
}

# Metric alert for Application Insights server response time
resource "azurerm_monitor_metric_alert" "app_insights_response_time" {
  name                 = "changetrace-${var.environment}-response-time-alert"
  resource_group_name  = var.resource_group_name
  scopes               = [azurerm_application_insights.main.id]
  description          = "Alert when server response time exceeds threshold"
  severity             = 3
  enabled              = true
  evaluation_frequency = "PT1M"
  window_size          = "PT5M"

  criteria {
    metric_namespace = "Microsoft.Insights/components"
    metric_name      = "requests/duration"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 5000 # 5 seconds
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = var.common_tags
}

# Metric alert for Application Insights failed requests
resource "azurerm_monitor_metric_alert" "app_insights_failed_requests" {
  name                 = "changetrace-${var.environment}-failed-requests-alert"
  resource_group_name  = var.resource_group_name
  scopes               = [azurerm_application_insights.main.id]
  description          = "Alert when failed request rate exceeds threshold"
  severity             = 2
  enabled              = true
  evaluation_frequency = "PT1M"
  window_size          = "PT5M"

  criteria {
    metric_namespace = "Microsoft.Insights/components"
    metric_name      = "requests/failed"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 10
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = var.common_tags
}

# Log alert for error budget burn rate (SLO alert)
resource "azurerm_monitor_log_alert" "error_budget_burn" {
  name                 = "changetrace-${var.environment}-error-budget-burn"
  resource_group_name  = var.resource_group_name
  scopes               = [azurerm_log_analytics_workspace.main.id]
  description          = "Alert when error budget burn rate exceeds threshold"
  severity             = 1
  enabled              = true
  evaluation_frequency = "PT5M"
  window_size          = "PT15M"

  criteria {
    query = <<-QUERY
      requests
      | where timestamp > ago(15m)
      | summarize totalRequests = count(), failedRequests = countif(success == false)
      | extend errorRate = failedRequests * 100.0 / totalRequests
      | where errorRate > 2.0  // 2% error rate threshold
      | project errorRate, totalRequests, failedRequests
    QUERY

    metric_measure_column = "errorRate"
    operator              = "GreaterThan"
    threshold             = 2.0

    dimension {
      name     = "errorRate"
      operator = "Include"
      values   = ["*"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }

  tags = var.common_tags
}

# Diagnostic settings for Key Vault
resource "azurerm_monitor_diagnostic_setting" "key_vault" {
  count = var.key_vault_id != "" ? 1 : 0

  name                       = "changetrace-${var.environment}-kv-diagnostics"
  target_resource_id         = var.key_vault_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  log {
    category = "AuditEvent"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }

  metric {
    category = "AllMetrics"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }
}

# Diagnostic settings for Cosmos DB
resource "azurerm_monitor_diagnostic_setting" "cosmos_db" {
  count = var.cosmos_db_id != "" ? 1 : 0

  name                       = "changetrace-${var.environment}-cosmos-diagnostics"
  target_resource_id         = var.cosmos_db_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  log {
    category = "DataPlaneRequests"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }

  log {
    category = "QueryRuntimeStatistics"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }

  metric {
    category = "AllMetrics"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }
}

# Diagnostic settings for Function App
resource "azurerm_monitor_diagnostic_setting" "function_app" {
  count = var.function_app_id != "" ? 1 : 0

  name                       = "changetrace-${var.environment}-func-diagnostics"
  target_resource_id         = var.function_app_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  log {
    category = "FunctionAppLogs"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }

  metric {
    category = "AllMetrics"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }
}

# Diagnostic settings for Event Grid topics
resource "azurerm_monitor_diagnostic_setting" "eventgrid_cicd" {
  count = var.eventgrid_cicd_topic_id != "" ? 1 : 0

  name                       = "changetrace-${var.environment}-eventgrid-cicd-diagnostics"
  target_resource_id         = var.eventgrid_cicd_topic_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  log {
    category = "DeliverySuccess"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }

  log {
    category = "DeliveryFailure"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }

  metric {
    category = "AllMetrics"
    enabled  = true

    retention_policy {
      enabled = true
      days    = 30
    }
  }
}

# Random suffix for unique naming
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
  number  = true
}

# Outputs
output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.main.id
}

output "log_analytics_workspace_key" {
  value     = azurerm_log_analytics_workspace.main.primary_shared_key
  sensitive = true
}

output "application_insights_id" {
  value = azurerm_application_insights.main.id
}

output "application_insights_name" {
  value = azurerm_application_insights.main.name
}

output "application_insights_instrumentation_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "action_group_id" {
  value = azurerm_monitor_action_group.main.id
}