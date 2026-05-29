# Chaos Studio module for ChangeTrace - Fault injection for validation

# Chaos Studio workspace
resource "azurerm_chaos_studio_workspace" "main" {
  name                = "changetrace-${var.environment}-${random_string.suffix.result}-chaos"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.common_tags
}

# Random suffix for unique naming
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
  number  = true
}

# Chaos Studio target for AKS cluster
resource "azurerm_chaos_studio_target" "aks" {
  count = var.aks_cluster_id != "" ? 1 : 0

  name                = "changetrace-${var.environment}-aks-target"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  target_resource_id = var.aks_cluster_id

  # Capabilities for AKS
  capability {
    name = "Microsoft-Agent"
    type = "Agent"
  }

  capability {
    name = "Service-Direct"
    type = "ServiceDirect"
  }
}

# Chaos Studio experiment: Pod failure
resource "azurerm_chaos_studio_experiment" "pod_failure" {
  name                = "changetrace-${var.environment}-pod-failure"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  identity {
    type = "SystemAssigned"
  }

  # Experiment steps
  step {
    name = "inject-pod-failure"

    branch {
      name = "pod-failure-branch"

      action {
        name = "kill-pod"
        type = "Continuous"

        # This would be configured with the actual fault parameters
        # For AKS pod kill, we use the Microsoft-Agent capability
        parameters = jsonencode({
          faultType = "PodKill"
          selector = {
            namespaces = ["default"]
            labelSelectors = {
              app = var.target_service_label
            }
          }
          duration = "PT1M"
        })
      }
    }
  }

  tags = var.common_tags
}

# Chaos Studio experiment: CPU pressure
resource "azurerm_chaos_studio_experiment" "cpu_pressure" {
  name                = "changetrace-${var.environment}-cpu-pressure"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  identity {
    type = "SystemAssigned"
  }

  step {
    name = "inject-cpu-pressure"

    branch {
      name = "cpu-pressure-branch"

      action {
        name = "cpu-stress"
        type = "Continuous"

        parameters = jsonencode({
          faultType = "CPUPressure"
          selector = {
            namespaces = ["default"]
            labelSelectors = {
              app = var.target_service_label
            }
          }
          cpuCount = 1
          load     = 80
          duration = "PT5M"
        })
      }
    }
  }

  tags = var.common_tags
}

# Chaos Studio experiment: Memory pressure
resource "azurerm_chaos_studio_experiment" "memory_pressure" {
  name                = "changetrace-${var.environment}-memory-pressure"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  identity {
    type = "SystemAssigned"
  }

  step {
    name = "inject-memory-pressure"

    branch {
      name = "memory-pressure-branch"

      action {
        name = "memory-stress"
        type = "Continuous"

        parameters = jsonencode({
          faultType = "MemoryPressure"
          selector = {
            namespaces = ["default"]
            labelSelectors = {
              app = var.target_service_label
            }
          }
          memoryConsumption = "80%"
          duration          = "PT5M"
        })
      }
    }
  }

  tags = var.common_tags
}

# Chaos Studio experiment: Network latency
resource "azurerm_chaos_studio_experiment" "network_latency" {
  name                = "changetrace-${var.environment}-network-latency"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  identity {
    type = "SystemAssigned"
  }

  step {
    name = "inject-network-latency"

    branch {
      name = "network-latency-branch"

      action {
        name = "network-delay"
        type = "Continuous"

        parameters = jsonencode({
          faultType = "NetworkLatency"
          selector = {
            namespaces = ["default"]
            labelSelectors = {
              app = var.target_service_label
            }
          }
          latency  = "200ms"
          jitter   = "50ms"
          duration = "PT5M"
        })
      }
    }
  }

  tags = var.common_tags
}

# Chaos Studio experiment: DNS failure
resource "azurerm_chaos_studio_experiment" "dns_failure" {
  name                = "changetrace-${var.environment}-dns-failure"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  identity {
    type = "SystemAssigned"
  }

  step {
    name = "inject-dns-failure"

    branch {
      name = "dns-failure-branch"

      action {
        name = "dns-fault"
        type = "Continuous"

        parameters = jsonencode({
          faultType = "DNSFailure"
          selector = {
            namespaces = ["default"]
            labelSelectors = {
              app = var.target_service_label
            }
          }
          duration = "PT2M"
        })
      }
    }
  }

  tags = var.common_tags
}

# Chaos Studio experiment: Disk I/O pressure
resource "azurerm_chaos_studio_experiment" "disk_io_pressure" {
  name                = "changetrace-${var.environment}-disk-io-pressure"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_chaos_studio_workspace.main.id

  identity {
    type = "SystemAssigned"
  }

  step {
    name = "inject-disk-io-pressure"

    branch {
      name = "disk-io-pressure-branch"

      action {
        name = "io-stress"
        type = "Continuous"

        parameters = jsonencode({
          faultType = "DiskPressure"
          selector = {
            namespaces = ["default"]
            labelSelectors = {
              app = var.target_service_label
            }
          }
          duration = "PT5M"
        })
      }
    }
  }

  tags = var.common_tags
}

# Outputs
output "chaos_studio_workspace_id" {
  value = azurerm_chaos_studio_workspace.main.id
}

output "chaos_studio_workspace_name" {
  value = azurerm_chaos_studio_workspace.main.name
}

output "pod_failure_experiment_id" {
  value = azurerm_chaos_studio_experiment.pod_failure.id
}

output "cpu_pressure_experiment_id" {
  value = azurerm_chaos_studio_experiment.cpu_pressure.id
}

output "memory_pressure_experiment_id" {
  value = azurerm_chaos_studio_experiment.memory_pressure.id
}

output "network_latency_experiment_id" {
  value = azurerm_chaos_studio_experiment.network_latency.id
}

output "dns_failure_experiment_id" {
  value = azurerm_chaos_studio_experiment.dns_failure.id
}

output "disk_io_pressure_experiment_id" {
  value = azurerm_chaos_studio_experiment.disk_io_pressure.id
}