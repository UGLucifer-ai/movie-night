terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # State is kept locally for this demo. In a team you would use a remote
  # backend (e.g. S3 + DynamoDB locking) so state is shared and locked.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "movie-night"
      Owner     = var.owner
      ManagedBy = "terraform"
    }
  }
}
