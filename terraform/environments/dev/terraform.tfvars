# Development environment configuration for ChangeTrace


location    = "swedencentral"
environment = "dev"

common_tags = {
  Project     = "ChangeTrace"
  Environment = "dev"
  Owner       = "internship-project"
  CostCenter  = "engineering"
  ManagedBy   = "terraform"
}

# Enable AKS (set to true only when ready to deploy and test - costs money!)
enable_aks = false

# AKS configuration (only used if enable_aks = true)
aks_node_count   = 1
aks_node_vm_size = "Standard_B2s"

# GitHub repository for OIDC federation (owner/repo)
github_repository = ""

# Email for alerts
alert_email = ""

# Cosmos DB free tier - DISABLED (1 per subscription limit, already used)
cosmos_db_free_tier = false

# Application Insights daily cap (100MB free tier)
app_insights_daily_cap_gb = 0.1

# Application Insights sampling (10% = 10)
app_insights_sampling_percentage = 10

# GitHub Actions Service Principal Object ID (for Key Vault access in CI/CD)
github_actions_sp_object_id = "335fcb5b-836f-4113-86fd-588d280f6012"