output "instance_ip" {
  value = google_compute_address.app.address
}

output "instance_name" {
  value = google_compute_instance.app.name
}

output "app_url" {
  value = "https://${var.domain_name}"
}
