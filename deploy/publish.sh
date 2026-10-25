#!/usr/bin/env bash
set -euo pipefail

project=${1:?Usage: bash deploy/publish.sh PROJECT [INSTANCE] [ZONE]}
instance=${2:-nyayalens}
zone=${3:-asia-south1-c}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
gcloud_bin=${GCLOUD_BIN:-gcloud}
if ! command -v "$gcloud_bin" >/dev/null 2>&1; then
  if [[ -x /home/manav/google-cloud-sdk/bin/gcloud ]]; then
    gcloud_bin=/home/manav/google-cloud-sdk/bin/gcloud
  else
    echo "gcloud is required. Set GCLOUD_BIN to its absolute path." >&2
    exit 1
  fi
fi
[[ -f "$repo_dir/backend/.env" ]] || { echo "backend/.env is missing" >&2; exit 1; }
[[ -f "$script_dir/.env" ]] || { echo "deploy/.env is missing" >&2; exit 1; }

stage_dir=$(mktemp -d -t nyayalens-release.XXXXXX)
cleanup() {
  [[ -f "$stage_dir/source.tar.gz" ]] && rm -- "$stage_dir/source.tar.gz"
  rmdir -- "$stage_dir"
}
trap cleanup EXIT
tar -czf "$stage_dir/source.tar.gz" -C "$repo_dir" \
  --exclude=.git --exclude=node_modules --exclude=.next --exclude=venv --exclude=.venv \
  --exclude=__pycache__ --exclude='*.pyc' --exclude='*.db*' --exclude='*.sqlite3*' --exclude='.env' \
  --exclude='.env.*' --exclude=.terraform --exclude='*.tfstate*' --exclude='*.tfvars' \
  --exclude='*.plan' --exclude='*.tsbuildinfo' --exclude=.codex --exclude=.agents \
  --exclude='*.pem' --exclude='*.key' --exclude='*.p12' --exclude=.npmrc .

transport_args=(--tunnel-through-iap)
if [[ ${NYAYA_DIRECT_SSH:-0} == 1 ]]; then
  transport_args=()
fi
ssh_args=("$instance" --project="$project" --zone="$zone" "${transport_args[@]}" --quiet)
"$gcloud_bin" compute ssh "${ssh_args[@]}" --command='sudo install -d -m 0750 /opt/nyayalens; install -d -m 0700 /tmp/nyayalens-upload'
"$gcloud_bin" compute scp --project="$project" --zone="$zone" "${transport_args[@]}" --quiet \
  "$stage_dir/source.tar.gz" "$instance:/tmp/nyayalens-upload/source.tar.gz"
"$gcloud_bin" compute scp --project="$project" --zone="$zone" "${transport_args[@]}" --quiet \
  "$repo_dir/backend/.env" "$instance:/tmp/nyayalens-upload/backend.env"
"$gcloud_bin" compute scp --project="$project" --zone="$zone" "${transport_args[@]}" --quiet \
  "$script_dir/.env" "$instance:/tmp/nyayalens-upload/deploy.env"
"$gcloud_bin" compute ssh "${ssh_args[@]}" --command='set -eu; sudo tar -xzf /tmp/nyayalens-upload/source.tar.gz -C /opt/nyayalens; sudo install -m 0600 /tmp/nyayalens-upload/backend.env /opt/nyayalens/backend/.env; sudo install -m 0600 /tmp/nyayalens-upload/deploy.env /opt/nyayalens/deploy/.env; sudo bash -c "cd /opt/nyayalens && docker compose --env-file deploy/.env up -d --build && docker compose --env-file deploy/.env ps"; rm /tmp/nyayalens-upload/source.tar.gz /tmp/nyayalens-upload/backend.env /tmp/nyayalens-upload/deploy.env; rmdir /tmp/nyayalens-upload'
