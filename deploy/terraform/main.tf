resource "google_compute_network" "app" {
  name                    = "${var.instance_name}-network"
  auto_create_subnetworks = true
}

resource "google_compute_firewall" "web" {
  name    = "${var.instance_name}-web"
  network = google_compute_network.app.name
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.instance_name]
}

resource "google_compute_firewall" "ssh" {
  name    = "${var.instance_name}-ssh"
  network = google_compute_network.app.name
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = var.ssh_source_ranges
  target_tags   = [var.instance_name]
}

resource "google_compute_address" "app" {
  name = "${var.instance_name}-ip"
}

resource "google_compute_instance" "app" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone
  tags         = [var.instance_name]
  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 30
      type  = "pd-balanced"
    }
  }
  network_interface {
    network = google_compute_network.app.name
    access_config {
      nat_ip = google_compute_address.app.address
    }
  }
  metadata_startup_script   = file("${path.module}/startup.sh")
  allow_stopping_for_update = true
}

resource "cloudflare_record" "app" {
  count           = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id         = var.cloudflare_zone_id
  name            = var.domain_name
  content         = google_compute_address.app.address
  type            = "A"
  proxied         = false
  allow_overwrite = true
}
