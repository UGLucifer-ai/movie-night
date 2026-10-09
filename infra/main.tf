# Minimal, cheap AWS deploy: ONE EC2 instance running the app container.
# No load balancer, no NAT gateway, no RDS - those cost money every hour.
# The app uses its SQLite fallback on the instance's disk.

# Use the account's default VPC so we don't have to build networking.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Latest Amazon Linux 2023 image, looked up through AWS's public SSM parameter.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_security_group" "app" {
  name_prefix = "movie-night-"
  description = "Movie Night: HTTP in, everything out"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP to the app"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    description = "Allow outbound (pull image, OS updates)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# IAM role so we can open a shell with AWS Systems Manager Session Manager
# instead of opening SSH (port 22) to the internet.
resource "aws_iam_role" "ec2" {
  name_prefix = "movie-night-ec2-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name_prefix = "movie-night-"
  role        = aws_iam_role.ec2.name
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  # cloud-init script: install Docker and start the container on first boot.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    container_image = var.container_image
  })
  user_data_replace_on_change = true

  # Require IMDSv2 (token-based metadata) - a common security baseline.
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = "movie-night"
  }
}
