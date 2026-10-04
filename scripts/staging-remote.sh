#!/usr/bin/env bash
# Invoked over SSH by deploy-staging.py, from the verified GitHub commit.
set -euo pipefail
sha=${1:?Commit required}
email=${2:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
root=/opt/action-gate
mkdir -p "$root/releases" "$root/shared"
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
# Confirm the Docker target and reject unrelated listeners before any Docker mutation.
[[ "$(docker context show)" == default ]] || { echo 'Expected server default Docker context.' >&2; exit 1; }
docker compose ls
for port in 80 443; do
    if [[ -n "$(ss -H -lnt "sport = :$port")" ]]; then
        owner=$(docker ps --filter "publish=$port" --format '{{.Label "com.docker.compose.project"}}' | sort -u)
        [[ "$owner" == action-gate-staging ]] || { echo "Port $port belongs to another service." >&2; exit 1; }
    fi
done
release="$root/releases/$sha"
if [[ ! -d "$release" ]]; then
    staging=$(mktemp -d "$root/releases/.extract-XXXXXX")
    trap 'rm -rf "$staging"' EXIT
    tar -xzf "$root/incoming/$sha.tar.gz" -C "$staging"
    mv "$staging" "$release"
    trap - EXIT
fi
cd "$release"
if [[ ! -f "$root/shared/.env.staging" ]]; then
    [[ -n "$email" ]] || { echo 'First deploy requires --email for ACME.' >&2; exit 2; }
    python3 scripts/staging-init.py --directory "$root/shared" --email "$email"
fi
ln -sfn "$root/shared/.env.staging" .env.staging
ln -sfn "$root/shared/secrets" secrets
./scripts/staging.sh config
./scripts/staging.sh up
if [[ ! -f "$root/shared/bootstrap-complete" ]]; then
    ./scripts/staging.sh bootstrap
    touch "$root/shared/bootstrap-complete"
fi
# Validate the origin certificate independently of Cloudflare's edge certificate.
# Certificate issuance can take time. Never bypass certificate validation.
check_ready() {
    curl --fail --silent --show-error --location --max-redirs 3 \
        --retry 12 --retry-delay 5 --retry-all-errors \
        --connect-timeout 5 --max-time 15 "$@" \
        https://ai-control-gate.ivbon.dev/health/ready |
        python3 -c 'import json,sys; data=json.load(sys.stdin); sys.exit(0 if data.get("ready") is True else 1)'
}
check_ready --noproxy '*' --resolve ai-control-gate.ivbon.dev:443:127.0.0.1
check_ready
curl --fail --silent --show-error --location --max-redirs 3 --output /dev/null \
    --connect-timeout 5 --max-time 15 https://ai-control-gate.ivbon.dev/control/
ln -sfn "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf '%s\n' "$sha" > "$root/shared/deployed-commit"
printf '\nDeployed %s at https://ai-control-gate.ivbon.dev/control/\n' "$sha"
