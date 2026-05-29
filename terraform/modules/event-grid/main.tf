# Event Grid module for ChangeTrace - Event backbone

# System topic for Azure resource events
resource "azurerm_eventgrid_system_topic" "resource_events" {
  name                = "changetrace-${var.environment}-resource-events"
  location            = var.location
  resource_group_name = var.resource_group_name
  source_type         = "Microsoft.Resources.ResourceGroups"

  tags = var.common_tags
}

# Custom topic for CI/CD events (deployments, builds)
resource "azurerm_eventgrid_topic" "cicd_events" {
  name                = "changetrace-${var.environment}-cicd-events"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "Custom"

  tags = var.common_tags
}

# Custom topic for Git events (commits, PRs, releases)
resource "azurerm_eventgrid_topic" "git_events" {
  name                = "changetrace-${var.environment}-git-events"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "Custom"

  tags = var.common_tags
}

# Custom topic for alert events (SLO breaches, etc.)
resource "azurerm_eventgrid_topic" "alert_events" {
  name                = "changetrace-${var.environment}-alert-events"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "Custom"

  tags = var.common_tags
}

# Custom topic for Argo Rollouts events
resource "azurerm_eventgrid_topic" "argo_events" {
  name                = "changetrace-${var.environment}-argo-events"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "Custom"

  tags = var.common_tags
}

# Event subscription for resource changes -> CI/CD topic
resource "azurerm_eventgrid_event_subscription" "resource_changes" {
  name  = "resource-changes-to-cicd-topic"
  scope = var.resource_group_id

  event_delivery_schema = "CloudEventSchemaV1_0"

  filter {
    included_event_types = [
      "Microsoft.Resources.ResourceWriteSuccess",
      "Microsoft.Resources.ResourceDeleteSuccess",
      "Microsoft.Resources.ResourceWriteFailure",
      "Microsoft.Resources.ResourceDeleteFailure"
    ]
    is_subject_case_sensitive = false
  }

  destination {
    type     = "EventGridTopic"
    endpoint = azurerm_eventgrid_topic.cicd_events.endpoint
  }

  retry_policy {
    max_delivery_attempts         = 30
    event_time_to_live_in_minutes = 1440
  }

  # Dead letter destination (storage account)
  dead_letter_destination {
    storage_blob {
      storage_account_id = var.storage_account_id
      container_name     = "eventgrid-deadletter"
    }
  }
}

# Event subscription for CI/CD topic -> Function App (for processing)
resource "azurerm_eventgrid_event_subscription" "cicd_to_function" {
  name  = "cicd-events-to-function"
  scope = azurerm_eventgrid_topic.cicd_events.id

  event_delivery_schema = "CloudEventSchemaV1_0"

  filter {
    included_event_types = [
      "DeploymentStarted",
      "DeploymentSucceeded",
      "DeploymentFailed",
      "BuildStarted",
      "BuildSucceeded",
      "BuildFailed",
      "ReleaseCreated",
      "ReleaseDeployed"
    ]
    is_subject_case_sensitive = false
  }

  destination {
    type = "AzureFunction"
    azure_function {
      function_app_id                   = var.function_app_id
      function_name                     = "ProcessCICDEvent"
      max_events_per_batch              = 10
      preferred_batch_size_in_kilobytes = 64
    }
  }

  retry_policy {
    max_delivery_attempts         = 30
    event_time_to_live_in_minutes = 1440
  }
}

# Event subscription for Git events -> Function App
resource "azurerm_eventgrid_event_subscription" "git_to_function" {
  name  = "git-events-to-function"
  scope = azurerm_eventgrid_topic.git_events.id

  event_delivery_schema = "CloudEventSchemaV1_0"

  filter {
    included_event_types = [
      "PullRequestMerged",
      "CommitPushed",
      "ReleasePublished",
      "TagCreated"
    ]
    is_subject_case_sensitive = false
  }

  destination {
    type = "AzureFunction"
    azure_function {
      function_app_id                   = var.function_app_id
      function_name                     = "ProcessGitEvent"
      max_events_per_batch              = 10
      preferred_batch_size_in_kilobytes = 64
    }
  }

  retry_policy {
    max_delivery_attempts         = 30
    event_time_to_live_in_minutes = 1440
  }
}

# Event subscription for Alert events -> Function App (triggers WF-1)
resource "azurerm_eventgrid_event_subscription" "alert_to_function" {
  name  = "alert-events-to-function"
  scope = azurerm_eventgrid_topic.alert_events.id

  event_delivery_schema = "CloudEventSchemaV1_0"

  filter {
    included_event_types = [
      "SLOAlertFired",
      "SLOAlertResolved",
      "ErrorBudgetBurnRateExceeded"
    ]
    is_subject_case_sensitive = false
  }

  destination {
    type = "AzureFunction"
    azure_function {
      function_app_id                   = var.function_app_id
      function_name                     = "ProcessAlertEvent"
      max_events_per_batch              = 1
      preferred_batch_size_in_kilobytes = 64
    }
  }

  retry_policy {
    max_delivery_attempts         = 30
    event_time_to_live_in_minutes = 1440
  }
}

# Event subscription for Argo events -> Function App (triggers WF-2)
resource "azurerm_eventgrid_event_subscription" "argo_to_function" {
  name  = "argo-events-to-function"
  scope = azurerm_eventgrid_topic.argo_events.id

  event_delivery_schema = "CloudEventSchemaV1_0"

  filter {
    included_event_types = [
      "RolloutStarted",
      "RolloutStepCompleted",
      "RolloutPaused",
      "RolloutAborted",
      "RolloutRolledBack",
      "CanaryAnalysisStarted",
      "CanaryAnalysisSucceeded",
      "CanaryAnalysisFailed"
    ]
    is_subject_case_sensitive = false
  }

  destination {
    type = "AzureFunction"
    azure_function {
      function_app_id                   = var.function_app_id
      function_name                     = "ProcessArgoEvent"
      max_events_per_batch              = 10
      preferred_batch_size_in_kilobytes = 64
    }
  }

  retry_policy {
    max_delivery_attempts         = 30
    event_time_to_live_in_minutes = 1440
  }
}

# Outputs
output "resource_events_topic_id" {
  value = azurerm_eventgrid_system_topic.resource_events.id
}

output "cicd_events_topic_endpoint" {
  value = azurerm_eventgrid_topic.cicd_events.endpoint
}

output "cicd_events_topic_key" {
  value     = azurerm_eventgrid_topic.cicd_events.primary_key
  sensitive = true
}

output "git_events_topic_endpoint" {
  value = azurerm_eventgrid_topic.git_events.endpoint
}

output "git_events_topic_key" {
  value     = azurerm_eventgrid_topic.git_events.primary_key
  sensitive = true
}

output "alert_events_topic_endpoint" {
  value = azurerm_eventgrid_topic.alert_events.endpoint
}

output "alert_events_topic_key" {
  value     = azurerm_eventgrid_topic.alert_events.primary_key
  sensitive = true
}

output "argo_events_topic_endpoint" {
  value = azurerm_eventgrid_topic.argo_events.endpoint
}

output "argo_events_topic_key" {
  value     = azurerm_eventgrid_topic.argo_events.primary_key
  sensitive = true
}