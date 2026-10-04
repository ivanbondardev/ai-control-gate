# Decisions

## 2026-10-04 — separate project directory

**Fact of the owner's instruction:** create a directory with a copy of everything necessary;
the owner will move it manually into the new workspace.

**Decision within the scope of the instruction:** the current code was transferred with its structure preserved,
along with the infrastructure, scripts, the primary task and the selected context. The source of the composition is the
[transfer description](transfer.md). The direction and the product scope were not changed.

## 2026-10-04 — documentation navigation and cleanup candidates

**Fact of the instruction:** find and structure all the workspace documentation and prepare cleanup candidates.

**Decision within the scope of the instruction:** a [full map](00-documentation-map.md) and a [list of candidates](09-documentation-cleanup.md) were added; the map was included in the root README. The navigation was structured without moving or deleting existing files. Archiving, trimming and updating from the list are proposals, not approved product decisions. The initial transfer manifest is kept as a historical snapshot.

## 2026-10-04 — execution of the documentation cleanup

**Fact of the instruction:** the owner approved the execution of the prepared list: "OK. do the cleanup" (translated from the owner's Ukrainian wording).

**Decision and execution:** C01–C10 from the [report](09-documentation-cleanup.md) were implemented. The historical pitch drafts and the previous prototype assessment were separated from the working navigation. The primary sources, the evidence and the initial transfer indexes are preserved. The invocation contract heading was corrected to release scope 0.2.0 under the explicit rule of the contracts index; there is no new release or API change. The project direction and the submission decision were not changed.

## 2026-10-04 — English as the documentation language

**Fact of the instruction:** the owner asked to translate all project documentation into English, including `sources/**` and the `*.uk.md` organizer-task files, and approved updating the language rule.

**Decision:** documentation in this workspace is written in English, and the language rule in [AGENTS.md](../AGENTS.md) was updated to match. Notes, plans, the repository README, UI text, code comments, messages, pitch and submission texts are all in English; mentor questions are still prepared in Ukrainian and English. Ukrainian is kept only where it is functional rather than documentary: the test fixtures `scripts/gate-scenarios/cases.json` and `scripts/gate-scenarios/requests/*.json`, whose Ukrainian payloads exercise Ukrainian input handling, and the archived-heading anchors in `CHANGELOG.md` and `docs/archive-references.json`.

**Boundaries:** the organizers' PDFs and the exact English extractions were not altered. The `*.uk.md` files keep their names for link stability although their content is now an unofficial English translation. The pre-translation originals are stored outside the documentation set at `.translation-backup/uk-originals-2026-10-04.tar.gz`. Code, configuration and runtime were not changed.

## 2026-10-04 — server deployment prerequisites

**Fact of the instruction:** the owner supplied SSH access to `root@95.217.5.223` and requested preparation of the fresh instance for this project.

**Decision and execution:** install Docker, Compose, Buildx and deployment utilities from the configured Ubuntu repositories; enable Docker at boot; reserve `/opt/action-gate` for the application. Preparation does not publish or launch the application. The existing Compose loopback binding and separate project name remain the deployment baseline.

**Boundary:** automatic approval review rejected the initial combined OS/security configuration command before execution. A narrower dependency installation was approved and completed. SSH/firewall changes require the requested explicit approval; no OS-wide upgrade, swap configuration, Docker log configuration or automatic-update configuration was applied.

## 2026-10-04 — first local launch

**Fact of the owner's instruction:** run the application locally, explicitly retaining port 80 and the previous Compose project name `ai-control-proxy` after the previous stack was stopped. This supersedes the separate-project-name rule for this local launch.

**Decision and execution:** recreate that project's containers from this workspace, with fresh named volumes `action-gate-export-first-run-{postgres,documents,outbox,tickets}`. The four archived `ai-control-proxy_*` volumes are retained untouched. Local overrides in ignored `compose.first-run.local` disable external provider configuration without changing the existing `.env`. No paid model calls are authorized by this launch.

**Repeat launch:** from the repository root, run `COMPOSE_FILE=compose.yaml:compose.first-run.local COMPOSE_PROJECT_NAME=ai-control-proxy TRAEFIK_HTTP_PORT=80 make demo-mcp-up`. Keep these overrides for this runtime: plain `make up` would select the old volumes and provider configuration from `.env`. Do not pass this override to `make demo-mcp-test`, whose default isolated project must retain its own temporary volumes.

## 2026-10-04 — staging deployment preparation

**Fact of the owner's instruction:** prepare staging for `ai-control-gate.ivbon.dev`; deploy through SSH with `~/.ssh/grisha_htz_id_ed25519` to `root@95.217.5.223`; use GitHub repository HEAD and check that local changes are committed and pushed before deployment.

**Implementation decision:** resolve `origin`'s default-branch HEAD, require a clean local checkout on that branch at the exact advertised commit, and create a Git archive from the fetched commit. The configured repository is `ivanbondardev/ai-control-gate` (source: local Git remote configuration). The server receives that archive via SCP and deployment logic from the same commit. No GitHub credentials are copied to the server. Deployment does not commit or push automatically.

**Configuration:** dedicated `action-gate-staging` Compose project, public Traefik ports 80/443 with hostname-specific HTTPS routing and HTTP redirect, ACME certificate storage, server-generated principal/service/database secrets and persistent volumes. Providers remain disabled. Releases and shared configuration live under `/opt/action-gate`; subsequent deploys do not reapply bootstrap policy. See [the runbook](staging.md).

**Boundary:** this session prepares and checks scripts locally. No server deployment, DNS change, certificate registration, commit or push was performed. Local development runtime remains unchanged.

## 2026-10-04 — ACME contact and Cloudflare proxy

**Owner input:** use `ivan.bondar.dev@gmail.com`; the supplied DNS screenshot shows `ai-control-gate.ivbon.dev` pointing at `95.217.5.223`, proxied by Cloudflare.

**Implementation:** default the deploy email to the supplied address. Verify the origin certificate and JSON readiness directly through loopback with hostname/SNI, then verify public readiness through Cloudflare. Document Full (strict) and challenge-path requirements. The screenshot confirms record configuration only; Cloudflare TLS settings and live reachability remain unverified. No Cloudflare settings were changed.

## 2026-10-04 — owner authorized staging publication

**Direct instruction:** commit and push the local changes, then perform the staging deployment. This authorizes publication of the reviewed repository changes and the application deployment through the prepared SSH script. Existing restrictions on real provider calls, partner integrations and spending remain in force.

## 2026-10-04 — architecture review document

**Owner instruction:** create an architecture review in a separate file and follow ASD-STE100 as closely as possible.

**Documentation decision:** keep the English review in [architecture-review.md](architecture-review.md). Use current source code and contracts as evidence. Separate risk hypotheses and proposals from implementation facts. State the limits of the language and runtime checks.

**Boundary:** this is a documentation decision. The review does not approve a new product direction, policy unification, storage redesign, or deployment.

## 2026-10-04 — staging detector provider configuration

**Owner instruction:** use the local `DETECTOR_PROVIDER_BASE_URL`, `DETECTOR_PROVIDER_API_KEY` and `DETECTOR_PROVIDER_MODEL` on staging.

**Decision:** remove the staging Compose overrides that forced those three settings empty, and transfer their resolved local values over the authorized SSH connection into the private server `.env.staging`. Values and secrets are not written to tracked files or logs. This is configuration authorization; verification does not issue paid provider requests or change the active detector policy/profile.
