# Production deployment

The deployment uses the GCP Compute Engine and Cloudflare pattern from the existing N8N-Agent Terraform setup. This project has its own Terraform state and resources; it does not alter the N8N project. The source path supplied has a trailing space: `/home/manav/dev_ws/N8N-Agent /terraform`.

FastAPI, Next.js, and Caddy run in Docker Compose. Only Caddy publishes ports. Caddy provides HTTPS, streams SSE without buffering, and forwards WebSockets. API keys remain in `backend/.env` on the server. Separate persistent SQLite volumes hold the graph checkpoints and lawyer accounts. The database service applies the Prisma schema before the web service starts. Keep a single backend worker because running calls and analysis subscriptions live in that worker.

## Prepare

1. Copy `backend/.env.example` to `backend/.env` and set the real provider keys.
2. Copy `deploy/.env.example` to `deploy/.env`; set the ACME contact email and a long random JWT secret.
3. Copy `deploy/terraform/terraform.tfvars.example` to `deploy/terraform/terraform.tfvars`; set the project and Cloudflare zone.
4. Supply Cloudflare credentials as `TF_VAR_cloudflare_api_token` in the shell. Credentials never belong in committed files.

## Provision

```bash
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform plan -out=nyaya.plan
terraform -chdir=deploy/terraform apply nyaya.plan
```

Review the plan before applying. The module creates a dedicated VM, network, static address, and optional DNS A record. Configure the DNS record with proxying disabled until the origin certificate is issued; proxying can then be enabled in Cloudflare with Full (strict) SSL.

## Upload and launch

```bash
bash deploy/publish.sh YOUR_GCP_PROJECT nyayalens asia-south1-c
```

The script uploads the current working tree, including local uncommitted application changes, but excludes Git history, caches, dependencies, databases and secrets. It uploads the two required environment files separately over SSH. It builds and starts the containers on the VM. The initial package and image downloads can take several minutes.

IAP is the default SSH transport. If IAP access is unavailable, add only your trusted public `/32` to `ssh_source_ranges`, review and apply that firewall update, and prefix the publish command with `NYAYA_DIRECT_SSH=1`. Do not open SSH to the world.

For an existing server with Docker Compose, copy this project and environment files to `/opt/nyayalens`, then run:

```bash
docker compose --env-file deploy/.env up -d --build
docker compose --env-file deploy/.env ps
docker compose --env-file deploy/.env logs --tail=100
```

Do not use `down --volumes`; it deletes the persistent case store. For rollback, upload a previously verified source revision and run the same Compose command.

## Verify

```bash
curl --fail https://nyayalens.abhi07.xyz/health
curl --fail --head https://nyayalens.abhi07.xyz/
```

Test microphone permission, an actual client turn, document upload, case acceptance, SSE progress, and packet/chat in a browser. Microphone access requires HTTPS. A Cloudflare 525 response means the origin TLS handshake is failing; check the DNS target, Caddy logs, and SSL mode.
