# Variables for Chaos Studio module

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "aks_cluster_id" {
  description = "AKS cluster resource ID for Chaos Studio target"
  type        = string
  default     = ""
}

variable "target_service_label" {
  description = "Kubernetes label selector for target service (e.g., 'app=payments')"
  type        = string
  default     = "app=payments"
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}