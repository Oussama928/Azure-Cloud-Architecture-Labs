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

variable "enable_aks" {
  description = "Enable AKS cluster creation (costs money!)"
  type        = bool
  default     = false
}

variable "node_vm_size" {
  description = "VM size for system node pool"
  type        = string
  default     = "Standard_B2s"
}

variable "workload_vm_size" {
  description = "VM size for workload node pool"
  type        = string
  default     = "Standard_B2s"
}

variable "node_count" {
  description = "Initial node count for system pool"
  type        = number
  default     = 1
}

variable "min_node_count" {
  description = "Minimum node count for system pool"
  type        = number
  default     = 1
}

variable "max_node_count" {
  description = "Maximum node count for system pool"
  type        = number
  default     = 3
}

variable "workload_node_count" {
  description = "Initial node count for workload pool"
  type        = number
  default     = 0
}

variable "workload_min_count" {
  description = "Minimum node count for workload pool"
  type        = number
  default     = 0
}

variable "workload_max_count" {
  description = "Maximum node count for workload pool"
  type        = number
  default     = 5
}

variable "availability_zones" {
  description = "Availability zones for node pools"
  type        = list(string)
  default     = ["1", "2", "3"]
}

variable "api_server_authorized_ip_ranges" {
  description = "Authorized IP ranges for API server access"
  type        = list(string)
  default     = []
}

variable "github_repository" {
  description = "GitHub repository for OIDC federation (owner/repo)"
  type        = string
  default     = ""
}

variable "key_vault_id" {
  description = "Key Vault resource ID for workload identity access"
  type        = string
  default     = ""
}

variable "cosmos_db_id" {
  description = "Cosmos DB resource ID for workload identity access"
  type        = string
  default     = ""
}

variable "acr_id" {
  description = "Container Registry resource ID for workload identity access"
  type        = string
  default     = ""
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}