output "instance_id" {
  description = "EC2 instance ID (use with: aws ssm start-session --target <id>)."
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Public IP of the instance."
  value       = aws_instance.app.public_ip
}

output "app_url" {
  description = "Open this in a browser once the instance has booted (~2 min)."
  value       = "http://${aws_instance.app.public_dns}"
}

output "health_url" {
  description = "Health endpoint, handy for curl checks."
  value       = "http://${aws_instance.app.public_dns}/health"
}
