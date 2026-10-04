# Staging deployment — ai-control-gate.ivbon.dev

## Scope and prerequisites

Prepared configuration, not a completed deployment. The requested hostname is
`ai-control-gate.ivbon.dev`. The previously prepared server is `95.217.5.223`, with
application directory `/opt/action-gate` (see the session log); reconfirm the target
before transferring or starting anything. No server changes or DNS changes are made
by preparation.

Use Docker Compose >= 2.24.4, Docker Buildx, Python >= 3.10, and Bash. The server
must have outbound access to container registries and Let's Encrypt. Point the DNS
A record to the target server. With DNS-only records, publish an AAAA record only if
origin IPv6 is configured; proxied Cloudflare IPv6 answers are edge addresses.
Ports TCP 80 and 443 must be available and reachable. Do not start this stack beside
another service already using those ports. Only Traefik publishes ports; PostgreSQL,
Redis and dummy MCP services remain internal.

The staging application uses real TLS certificates, even though the application is
called staging. Traefik requests and renews them using HTTP-01 and stores ACME state
in the project's `staging_acme` volume. HTTP redirects to HTTPS. Routing is restricted
to the configured hostname, including `/mcp`.


### Cloudflare proxy

**Source fact:** the owner's 2026-10-04 screenshot shows an A record for
`ai-control-gate.ivbon.dev` pointing to `95.217.5.223` with **Proxied** enabled.
It does not show SSL/TLS mode or prove origin reachability.

Use Cloudflare **Full (strict)** for TLS to the origin. Flexible sends HTTP to the
origin and conflicts with this stack's HTTPS redirect. See
[Cloudflare Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/)
and [redirect-loop guidance](https://developers.cloudflare.com/ssl/troubleshooting/too-many-redirects/).
Ensure rules allow `/.well-known/acme-challenge/` to reach Traefik on port 80 for
HTTP-01 issuance; do not challenge or cache that path. Avoid caching API and MCP
responses. Cloudflare settings are not modified by the deployment script.

Deployment verifies the origin over loopback with the real hostname/SNI and normal
certificate validation, then verifies the public Cloudflare route. Both readiness
responses must contain JSON `ready: true`; a redirect or challenge HTML page cannot
count as a passing health check.

## SSH deployment from GitHub HEAD

The deployment source is the default branch HEAD of
`git@github.com:ivanbondardev/ai-control-gate.git`. The script resolves GitHub's symbolic
HEAD, fetches that branch, and requires the local branch and commit to match it exactly.
A dirty working tree, any untracked file, unpushed commits, a stale checkout or a
concurrent HEAD change blocks deployment before any SSH connection. Ignored local
secrets and evidence are excluded from the Git archive.

```sh
# First review, commit and push all intended changes yourself.
python3 scripts/deploy-staging.py --check
# First deployment (after DNS is ready):
python3 scripts/deploy-staging.py
# Subsequent deployment:
python3 scripts/deploy-staging.py
```

SSH uses `~/.ssh/grisha_htz_id_ed25519` and `root@95.217.5.223`, with strict host-key
checking and batch mode. Verify and trust the server's host key through your normal
SSH setup first; the script never disables host verification. No GitHub private key
or agent forwarding is needed on the server: the local machine creates `git archive`
from the verified remote commit, uploads it by SCP, and runs the remote deployment
script from that same commit. No working-tree application files are packaged.

The server stores immutable source releases in `/opt/action-gate/releases/<commit>`
and environment/secrets in `/opt/action-gate/shared`. A deploy lock prevents concurrent
activation. Before starting containers it checks the Docker context and port owners.
First deployment initializes secrets and bootstraps the demo; later deploys preserve
credentials, volumes and the operator's policy. `current` and `shared/deployed-commit`
are updated only after public HTTPS checks succeed. A failure after container startup
can leave the new containers running even though `current` still names the old release;
inspect logs before recovery. No automatic database rollback is attempted.

The explicit runtime archive paths include application code, infrastructure and scripts.
Root `.env`, `.env.staging`, `secrets/`, local overrides, Git, evidence and data are
excluded. `.env.example` and synthetic policy fixtures are intentional; server-generated
credentials override the fixture tokens before first startup.

The owner supplied `ivan.bondar.dev@gmail.com` as the ACME contact; the deploy script
uses it by default. Use `--email` to override it. Initialization
refuses to overwrite existing configuration. It generates random database credentials,
a hash salt, service credentials and a token for every principal. `.env.staging` and
the host `secrets/` directory are private. Bind-mounted files are readable by the
non-root application UID 10001, through its read-only mount.

Open `https://ai-control-gate.ivbon.dev/control/`. Use principal `operator-local`
and its generated token from `secrets/staging/principals.json`, read privately on the
server. Never paste the token into logs, source control or a URL. The principal IDs
stay stable because policies refer to them; the known development tokens do not work
with a newly initialized staging database. MCP endpoint:
`https://ai-control-gate.ivbon.dev/mcp`.

The wrapper pins project `action-gate-staging`, both Compose files and `.env.staging`;
it clears inherited environment overrides. Always use this wrapper for staging.
Detector provider URL, API key and model are read from the server-only `.env.staging`.
On 2026-10-04 the owner authorized using the same three values as the local `.env`.
Fresh initialization still leaves them empty; never commit provider credentials.
This configuration does not switch the active detector policy away from its existing
profile. `MODEL_PROXY_DETECTOR_PROFILE` and the separate `OPENAI_API_KEY` remain empty;
the model proxy code can fall back to the detector key. Dummy Documents, Outbox and
Tickets remain synthetic.

## Verify and operate

```sh
cd /opt/action-gate/current
./scripts/staging.sh status
./scripts/staging.sh logs
curl --fail --show-error https://ai-control-gate.ivbon.dev/health/ready
curl --fail --show-error -o /dev/null https://ai-control-gate.ivbon.dev/control/
curl -I http://ai-control-gate.ivbon.dev/control/
```

Check HTTPS certificate validity, HTTP redirect, operator connection, service catalog
and one synthetic request in the panel. Health checks alone do not establish that DNS
or certificate issuance succeeded. Do not use `curl -k` to accept an invalid certificate.
The development acceptance scripts use known local tokens; do not run them against
staging or enable their in-place reset mode. Run them in an isolated local project.

For an update, retain the previous release, back up PostgreSQL, all three
service volumes, ACME state and server configuration, commit and push the new release, then run
`python3 scripts/deploy-staging.py` from the clean local checkout. Migrations run before the API starts. `bootstrap` is a
separate, first-launch operation because applying the demo policy can modify operator
configuration. Do not run it on every update. Initialization is not token rotation:
the active identity registry is persisted in PostgreSQL. Do not regenerate files to
rotate a deployed identity.

Use `./scripts/staging.sh stop` to stop without deleting data. Never use `down -v` on
staging. Rollback after schema migration requires a compatible release or restoration
of the coordinated backup; do not assume an older image is schema-compatible.
Backup/restore has not yet been rehearsed. Container images currently retain the
repository's version tags rather than digest pins.

## Configuration references and verification boundary

Compose merge behavior and `!override` version requirement:
[Docker documentation](https://docs.docker.com/reference/compose-file/merge/).
TLS entrypoints and HTTP redirection:
[Traefik 3.6 documentation](https://doc.traefik.io/traefik/v3.6/reference/install-configuration/entrypoints/).
Certificate challenge behavior:
[Traefik ACME documentation](https://doc.traefik.io/traefik/v3.2/reference/install-configuration/tls/certificate-resolvers/acme/).

Preparation checks cover secret generation, repeat-init refusal, Compose rendering,
mounts, ports, disabled providers and Git deployment guards and archive source. Live server startup, DNS,
certificate issuance, authenticated public HTTP/MCP access and backup recovery require
the actual deployment and are not claimed by these offline checks.
