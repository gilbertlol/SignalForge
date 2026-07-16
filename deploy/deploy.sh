#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: deploy.sh RELEASE_DIR IMAGE_TAG" >&2
    exit 2
fi

release_dir="$(cd "$1" && pwd)"
image_tag="$2"
deploy_root="$(cd "${release_dir}/../.." && pwd)"
shared_env="${deploy_root}/shared/.env"
current_link="${deploy_root}/current"
compose_file="deploy/docker-compose.production.yml"
previous_release=""

if [[ ! -f "$shared_env" ]]; then
    echo "Missing ${shared_env}; create it from deploy/.env.production.example" >&2
    exit 1
fi

if [[ -L "$current_link" ]]; then
    previous_release="$(readlink -f "$current_link")"
fi

ln -sfn "$shared_env" "${release_dir}/.env"
printf 'IMAGE_TAG=%s\n' "$image_tag" >"${release_dir}/.release-env"

compose() {
    COMPOSE_PROJECT_NAME=signalforge IMAGE_TAG="$image_tag" \
        docker compose --project-directory . --env-file .env -f "$compose_file" "$@"
}

rollback() {
    echo "Deployment failed; attempting rollback." >&2
    if [[ -n "$previous_release" && -f "${previous_release}/.release-env" ]]; then
        previous_tag="$(sed -n 's/^IMAGE_TAG=//p' "${previous_release}/.release-env")"
        cd "$previous_release"
        COMPOSE_PROJECT_NAME=signalforge IMAGE_TAG="$previous_tag" \
            docker compose --project-directory . --env-file .env \
                -f "$compose_file" up -d --remove-orphans
        ln -sfn "$previous_release" "$current_link"
    fi
}
trap rollback ERR

cd "$release_dir"
compose build --pull web
compose up -d db redis
compose run --rm web python manage.py migrate --noinput
compose run --rm web python manage.py collectstatic --noinput
compose run --rm web python manage.py operational_bootstrap
compose up -d --remove-orphans

for _ in {1..30}; do
    if compose exec -T web curl -fsS http://localhost:8000/health/ready >/dev/null; then
        ln -sfn "$release_dir" "$current_link"
        trap - ERR
        find "${deploy_root}/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
            | sort -nr | tail -n +6 | cut -d' ' -f2- | xargs -r rm -rf
        echo "SignalForge ${image_tag} deployed successfully."
        exit 0
    fi
    sleep 2
done

echo "Readiness check did not pass." >&2
exit 1
