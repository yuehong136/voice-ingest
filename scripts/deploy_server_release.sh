#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <git-commit-or-tag>" >&2
    exit 2
fi

requested_ref=$1
app_repo=${VOICE_APP_REPO:-/opt/voice-ingest/app}
current_link=${VOICE_CURRENT_LINK:-/opt/voice-ingest/current}
release_root=${VOICE_RELEASE_ROOT:-/opt/voice-ingest/releases}
backup_root=${VOICE_BACKUP_ROOT:-/var/backups/voice-ingest}
env_file=${VOICE_ENV_FILE:-/etc/voice-ingest/voice-ingest.env}
project=${VOICE_COMPOSE_PROJECT:-voice-ingest}
state_root=$(dirname "$current_link")

if [[ ! -d "$app_repo/.git" || ! -f "$env_file" ]]; then
    echo "Missing server checkout or deployment environment file" >&2
    exit 1
fi
if [[ -n "$(git -C "$app_repo" status --porcelain)" ]]; then
    echo "Server base checkout is dirty; preserve or remove those changes before release" >&2
    exit 1
fi

api_port=$(sed -n 's/^VOICE_API_PORT=//p' "$env_file" | tail -n 1)
api_port=${api_port:-18080}
if [[ ! "$api_port" =~ ^[0-9]+$ ]]; then
    echo "VOICE_API_PORT must be numeric" >&2
    exit 1
fi

git -C "$app_repo" fetch --prune origin
target_commit=$(git -C "$app_repo" rev-parse --verify "${requested_ref}^{commit}")
current_source=$(readlink -f "$current_link")
current_commit=$(git -C "$current_source" rev-parse HEAD)
if [[ "$target_commit" == "$current_commit" ]]; then
    echo "Already deployed: $target_commit"
    exit 0
fi

install -d -m 755 "$release_root"
release_dir="$release_root/$target_commit"
if [[ ! -e "$release_dir/.git" ]]; then
    git -C "$app_repo" worktree add --detach "$release_dir" "$target_commit"
fi

target_compose=(
    docker compose
    --project-name "$project"
    --env-file "$env_file"
    -f "$release_dir/deploy/compose.yaml"
    -f "$release_dir/deploy/compose.web.yaml"
)
current_compose=(
    docker compose
    --project-name "$project"
    --env-file "$env_file"
    -f "$current_source/deploy/compose.yaml"
    -f "$current_source/deploy/compose.web.yaml"
)

"${target_compose[@]}" config --quiet
"${target_compose[@]}" build

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 700 "$backup_root"
backup_dir="$backup_root/${timestamp}-${current_commit:0:12}-to-${target_commit:0:12}"
python3 "$current_source/scripts/deployment_snapshot.py" backup \
    --project "$project" \
    --env-file "$env_file" \
    --directory "$backup_dir"

"${current_compose[@]}" stop --timeout 180 web api worker
"${target_compose[@]}" run --rm --no-deps migrate
"${target_compose[@]}" run --rm --no-deps storage-init
"${target_compose[@]}" up -d

for _ in $(seq 1 30); do
    if curl --fail --silent --show-error "http://127.0.0.1:${api_port}/v1/health/ready" >/dev/null; then
        ln -sfn "$release_dir" "$current_link"
        printf '%s\n' "$target_commit" > "$state_root/deployed-commit"
        echo "Deployment healthy: $target_commit"
        echo "Pre-upgrade snapshot: $backup_dir"
        exit 0
    fi
    sleep 2
done

echo "Deployment did not become ready. Writers may be stopped or unhealthy." >&2
echo "Inspect Compose logs; snapshot is available at $backup_dir." >&2
echo "Do not downgrade the database automatically." >&2
exit 1
