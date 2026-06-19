# Chaos Studio Module Outputs

output "chaos_studio_workspace_id" {
  description = "Chaos Studio Workspace Resource ID"
  value       = azurerm_chaos_studio_workspace.main.id
}

output "chaos_studio_workspace_name" {
  description = "Chaos Studio Workspace Name"
  value       = azurerm_chaos_studio_workspace.main.name
}

output "chaos_experiment_pod_failure_id" {
  description = "Pod Failure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.pod_failure.id
}

output "chaos_experiment_network_latency_id" {
  description = "Network Latency Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.network_latency.id
}

output "chaos_experiment_cpu_pressure_id" {
  description = "CPU Pressure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.cpu_pressure.id
}

output "chaos_experiment_memory_pressure_id" {
  description = "Memory Pressure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.memory_pressure.id
}

output "chaos_experiment_disk_io_id" {
  description = "Disk I/O Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.disk_io.id
}

output "chaos_experiment_dns_failure_id" {
  description = "DNS Failure Experiment Resource ID"
  value       = azurerm_chaos_studio_experiment.dns_failure.id
}