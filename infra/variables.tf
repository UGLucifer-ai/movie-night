variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Tag value so everyone knows who owns these resources."
  type        = string
  default     = "Uday Charan Gopi"
}

variable "instance_type" {
  description = "EC2 size. t3.micro is Free Tier eligible on many accounts."
  type        = string
  default     = "t3.micro"
}

variable "container_image" {
  description = "Image published by the CD workflow, e.g. ghcr.io/<github-user>/movie-night:latest (package must be public)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9./_-]+(:[A-Za-z0-9._-]+)?$", var.container_image))
    error_message = "container_image must look like registry/owner/name:tag in lowercase."
  }
}

variable "allowed_cidr" {
  description = "Who may reach the app on port 80. Narrow this to your own IP (x.x.x.x/32) for a demo."
  type        = string
  default     = "0.0.0.0/0"

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0))
    error_message = "allowed_cidr must be a valid CIDR block, e.g. 203.0.113.10/32."
  }
}

variable "root_volume_size_gb" {
  description = "Disk size for the instance (GB)."
  type        = number
  default     = 30
}
