# Chaos Studio Module Outputs
# Note: Workspace outputs are defined in main.tf.
# This file contains experiment-specific outputs.

output "pod_failure_experiment_id" {
  description = "Pod Failure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.pod_failure.id
}

output "network_latency_experiment_id" {
  description = "Network Latency Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.network_latency.id
}

output "cpu_pressure_experiment_id" {
  description = "CPU Pressure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.cpu_pressure.id
}

output "memory_pressure_experiment_id" {
  description = "Memory Pressure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.memory_pressure.id
}

output "disk_io_pressure_experiment_id" {
  description = "Disk I/O Pressure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.disk_io_pressure.id
}

output "dns_failure_experiment_id" {
  description = "DNS Failure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.dns_failure.id
}
