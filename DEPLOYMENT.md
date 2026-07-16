# Deploy SignalForge to signalforge.dev2share.com

The production stack runs Django behind Gunicorn with PostgreSQL, Redis, Celery worker and
scheduler containers. It can either manage HTTPS through Caddy or sit behind an existing host
reverse proxy. Every push to `master` must pass CI before the deployment job can run.

## 1. Point DNS at the server

Create an `A` record for `signalforge.dev2share.com` pointing to the public IPv4 address of the
server. Add an `AAAA` record only when the server has working public IPv6. DNS must resolve before
Caddy can issue a TLS certificate.

## 2. Prepare the server

Install Docker Engine with the Compose plugin. The deployment user must be able to run Docker
without an interactive password and write to `/opt/signalforge`:

```bash
sudo mkdir -p /opt/signalforge/shared /opt/signalforge/releases
sudo chown -R "$USER":"$USER" /opt/signalforge
cp deploy/.env.production.example /opt/signalforge/shared/.env
chmod 600 /opt/signalforge/shared/.env
```

Edit `/opt/signalforge/shared/.env` and replace every placeholder. Generate independent Django
and provider-encryption secrets; never reuse the database password. The owner password must have
at least 12 characters.

For a server where ports 80 and 443 are free, leave `COMPOSE_PROFILES=edge`. Caddy will request and
renew the certificate automatically. Open inbound TCP 80/443 and UDP 443 in the host/cloud
firewall.

If dev2share.com already uses Nginx, Caddy, Traefik, or another edge proxy, leave
`COMPOSE_PROFILES` blank. Configure that existing proxy to send HTTPS traffic for
`signalforge.dev2share.com` to `http://127.0.0.1:8000`. Do not start two services on ports 80/443.

After the first successful deployment, remove `SIGNALFORGE_OWNER_PASSWORD` and
`SIGNALFORGE_OWNER_EMAIL` from the server environment. The owner remains in the database and
later deployments will not reset its password.

## 3. Create a deployment SSH key

Create a dedicated key locally and authorize it for the deployment user:

```bash
ssh-keygen -t ed25519 -f signalforge_deploy -C signalforge-deploy
ssh-copy-id -i signalforge_deploy.pub deploy-user@server-address
ssh-keyscan -H server-address
```

Restrict server access and protect the private key. The deployment user needs Docker access, but
should not be root and should not accept password-based SSH login.

## 4. Configure the GitHub production environment

In the GitHub repository, open **Settings → Environments → New environment**, create
`production`, and optionally require manual approval. Add these environment secrets:

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | Server hostname or IP used by SSH |
| `DEPLOY_USER` | Non-root deployment user |
| `DEPLOY_SSH_KEY` | Complete private Ed25519 key, including header/footer |
| `DEPLOY_KNOWN_HOSTS` | Exact `ssh-keyscan -H` output verified by the server administrator |

Add the environment variable `DEPLOY_ENABLED` with value `true` only after the server, DNS, `.env`,
and SSH secrets are ready. Until then, pushes run CI but safely skip deployment. Optionally add
`DEPLOY_PATH`; it defaults to `/opt/signalforge`.

## 5. Deploy

Push to `master` or run **SignalForge CI/CD** manually from GitHub Actions. The workflow:

1. lints, checks formatting and migrations, runs Django checks, and executes the full test suite;
2. uploads an immutable release directory to the server;
3. builds a production image tagged with the Git commit SHA;
4. starts dependencies, migrates the database, collects static files, and bootstraps operations;
5. switches the stack only after `/health/ready` passes;
6. rolls back to the previous release when deployment or readiness fails.

Verify after deployment:

```bash
curl -fsS https://signalforge.dev2share.com/health/ready
```

On the server, inspect status and logs with:

```bash
cd /opt/signalforge/current
COMPOSE_PROJECT_NAME=signalforge docker compose --project-directory . \
  --env-file .env -f deploy/docker-compose.production.yml ps
COMPOSE_PROJECT_NAME=signalforge docker compose --project-directory . \
  --env-file .env -f deploy/docker-compose.production.yml logs --tail=200 web worker beat
```

PostgreSQL, Redis, static/media data, and Caddy certificates use stable named volumes and survive
release changes. Keep independent off-server backups of the PostgreSQL and media volumes; release
rollback is not a database backup.
