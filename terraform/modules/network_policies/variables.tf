variable "enable_network_policies" {
  description = "Enable network security group and service endpoint creation"
  type        = bool
  default     = false
}

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

variable "subnet_id" {
  description = "Subnet ID for NSG association and service endpoints"
  type        = string
  default     = ""
}

variable "allowed_source_addresses" {
  description = "Allowed source IP ranges for internal traffic"
  type        = list(string)
  default     = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
}

variable "common_tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default     = {}
}
