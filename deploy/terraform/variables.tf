variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "zone" {
  type    = string
  default = "asia-south1-c"
}

variable "instance_name" {
  type    = string
  default = "nyayalens"
}

variable "machine_type" {
  type    = string
  default = "e2-medium"
}

variable "domain_name" {
  type    = string
  default = "nyayalens.abhi07.xyz"
}

variable "cloudflare_api_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "cloudflare_zone_id" {
  type    = string
  default = ""
}

variable "ssh_source_ranges" {
  description = "IAP TCP forwarding ranges by default. Add a trusted public CIDR only if direct SSH is required."
  type        = list(string)
  default     = ["35.235.240.0/20"]
}
