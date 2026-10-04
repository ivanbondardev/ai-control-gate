# Session log

## 2026-10-04 — initialization of the standalone directory

**Fact of the instruction:** the owner asked to prepare a copy for manual transfer.
**Done:** code and materials were copied selectively; README, AGENTS,
context and decisions were added. The composition and boundaries are in [transfer](transfer.md).
**Decision:** a new Compose project name, without transferring live state or keys.
**Unverified:** the new Docker run, browser and paid model scenarios.

**Checks:** 224 tests passed, 72 skipped; 14 assertion tests — OK;
53 fixtures valid; Compose, shell syntax and copy integrity were checked.
Details and boundaries are in [transfer](transfer.md).

## 2026-10-04 — documentation inventory and structure

**Fact of the instruction:** find and structure all the workspace documentation, prepare cleanup candidates.

**Done:** 46 documentation files were inventoried (41 Markdown, 2 PDF, 2 JSON indexes, 1 log) and grouped by purpose and status in the [documentation map](00-documentation-map.md). [10 groups of candidates](09-documentation-cleanup.md) were prepared: archiving three historical pitch drafts, updating outdated technical/competition summaries, removing duplication and clarifying navigation. A link from the README, a decision entry and a question about the invocation contract version were added.

**Decision:** structure the navigation in place. Do not delete or move existing documents as part of preparing candidates. Preserve the primary sources, translations, historical reports and the initial transfer manifest. All C01–C10 actions remain proposals.

**Checks:** before the changes, 221 records of the transfer manifest matched SHA-256; among the 46 documentation files there are no byte-identical duplicates; 168 initial local Markdown links have existing targets. The map contains exactly 46 unique rows and covers the entire initial documentation composition. After adding this entry, 277 local links in 43 Markdown files were checked: there are no missing targets. The code, configuration, scripts and sources are unchanged; the editorial changes to the initial files are limited to the README and three logs in docs/.

**Unverified:** anchors and external URLs, re-extraction of the PDFs and the accuracy of the translations, full correspondence of the contracts with the runtime, Docker/UI/integration and model checks. This is a documentation review with spot-checking of the code, not a new product readiness report.

## 2026-10-04 — documentation cleanup completed

**Fact of the instruction:** the owner approved the execution of the prepared cleanup list.

**Done:** C01–C10 executed, the result is the [report](09-documentation-cleanup.md). Three pitch drafts were moved to a dated archive with the text preserved and the links corrected; the previous judging is preserved separately. The module map, migrations, criteria, scenario statuses and navigation were updated. Duplicated extraction metadata was removed, the paid-subscription wording was clarified, and the invocation heading question was closed. The [map](00-documentation-map.md) now contains all 50 documentation files.

**Decision:** the historical materials are separated from the working references; the initial manifest and the archive references index were not rewritten. The code, configuration, data and product scope are unchanged.

**Checks:** all local Markdown links have existing targets; the 50 unique registry entries match the document composition exactly. All non-Markdown files were compared with the start of the session: unchanged. The SHA-256 of 16 preserved primary sources/historical files was checked separately (PDF, extracts, translations, reports, log, manifest, archive index, transfer and changelog). 53 scenario IDs were verified against cases.json: 39 for the model input, 14 MCP. `git diff --check` — no errors. Runtime tests were not run because the changes are documentation-only.

**Unverified:** anchors and external URLs, the runtime of the new stack, the UI, real model invocations, re-verification of the translations against the PDFs. Historical results were not relabelled as new PASS.

## 2026-10-04 — documentation translated into English

**Fact of the instruction:** the owner asked to translate all project documentation into English, including `sources/**` and the `*.uk.md` organizer-task files, and approved updating the language rule in `AGENTS.md`.

**Done:** 33 documentation files with Ukrainian prose were translated UK→EN in place; a further file (`infra/postgres/init/README.md`) was missed by the first pass and translated afterwards. Quoted Ukrainian phrases inside the English documents were rendered in English, marked as translated. The language rule in [AGENTS.md](../AGENTS.md) now states that documentation is in English. The `*.uk.md` files were made self-consistent: "unofficial English translation", `language: en`, `method: translation-to-en`, with the existing file names kept so that links and archive references keep working.

**Decision:** English is the documentation language of this workspace. Two categories stay in Ukrainian on purpose: the functional test fixtures `scripts/gate-scenarios/cases.json` and `scripts/gate-scenarios/requests/*.json` (the Ukrainian payloads are the test data for Ukrainian input handling), and the `archive reference` anchors that point at headings of archived files (`CHANGELOG.md`, `docs/archive-references.json`), where translating the fragment would break the reference. The organizers' PDFs and the exact English extractions were not altered.

**Checks:** every translated file was compared against the pre-translation copy for line count, headings, tables, code spans and link targets; the Markdown link check reports 0 broken links in 45 files, the same as before the translation. A full-repository Cyrillic scan is clean apart from the intentional cases above. Code, configuration, SQL, runtime and the Compose stack were not touched; no commits were made.

**Unverified:** the quality of the translation as judged by a native reviewer; anchors and external URLs; the runtime of the stack, the UI and real model invocations. The pre-translation originals are kept at `.translation-backup/uk-originals-2026-10-04.tar.gz` (not part of the documentation set).

## 2026-10-04 — remote deployment prerequisites

**Fact of the instruction:** prepare the fresh instance at `95.217.5.223` using the owner's supplied SSH key path. Source evidence: direct SSH inspection and command output from this session.

**Done:** inspected host `it-nomads-server` (Ubuntu 26.04.1 LTS, x86_64, approximately 2 GB RAM, no swap); installed Docker 29.1.3, Compose 2.40.3, Buildx 0.30.1, Make and jq, and ensured Git, rsync, curl and CA certificates are present. Enabled and started Docker; created `/opt/action-gate`. Available disk after installation: approximately 34 GB. No application source, private key, provider credentials or database state was transferred.

**Decision:** prepare prerequisites only; retain the project separation and loopback HTTP binding. Automatic approval review rejected the combined OS/security command before execution; a narrower dependency installation completed. Requested separate approval for SSH/firewall changes. SSH, UFW, swap, daemon log settings and automatic-update configuration remain unchanged; no full OS upgrade was performed.

**Checks:** fresh SSH connections succeeded; Docker is active and enabled; registry pull and `hello-world` execution passed with no container network and no published ports, and the temporary container was removed. The project's Compose template, including the demo profile, passed `config --quiet` in a temporary server directory that was subsequently removed. No failed systemd units or reboot-required marker were reported. Before the Docker smoke test, the daemon had no containers and HTTP/HTTPS ports were unused.

**Unverified:** application build/start, migrations, integration/UI/MCP acceptance, sustained memory use, public DNS/TLS, backup/restore and real model calls. UFW was inactive and SSH password authentication enabled at inspection; root password login was already prohibited. Public deployment remains a separate task.

## 2026-10-04 — first local runtime verification

**Fact of the instruction:** perform the first local test launch; the owner explicitly requested port 80 and the previous project name after stopping the old stack.

**Done:** built and bootstrapped this workspace as `ai-control-proxy` on `127.0.0.1:80`; migrations completed, all eight long-running services reported healthy, and `/health/ready` returned ready with PostgreSQL and Redis available. Opened `http://ai-control-proxy.localhost/control/` and verified operator login and live policy v2 in the browser. Left the application running and the panel open.

**Decision:** use fresh `action-gate-export-first-run-*` volumes and the ignored `compose.first-run.local` override; archived `ai-control-proxy_*` volumes were not reset. Existing `.env` was preserved; provider settings are overridden to empty in the running API. The repeat-launch command and the reason to retain the overrides are recorded in [decisions](01-decision.md).

**Checks:** host suite: 296 tests, 224 passed and 72 skipped; container suite: all 296 passed, no skips; PostgreSQL integration: 21 passed in a dedicated scratch database; HTTP acceptance: 145 passed, 0 failed. MCP acceptance completed with no failed phase, including service receipt correlation, lost-response reconciliation, restart persistence, fencing, reset and rate refusal. It ran in its own temporary project with random loopback port, no external providers and separate volumes; its containers, networks and volumes were removed automatically. Initial sandboxed host tests could not open sockets; the rerun with local socket access passed. `git diff --check` passed.

**Evidence:** local ignored logs in `evidence/first-local-run-2026-10-04/`; MCP phase JSON and service snapshots in the `evidence/demo-mcp-*` directory named in the saved MCP log. Source tests: `app/tests/`, `scripts/acceptance.sh`, `scripts/demo-mcp-test.sh`. No code changes were required.

**Unverified:** real provider calls (intentionally disabled), full browser interaction coverage, sustained load, public deployment and backup/restore. Browser verification covered panel loading and operator connection only.

## 2026-10-04 — staging deployment scripts prepared

**Instruction:** prepare staging for `ai-control-gate.ivbon.dev`, using SSH key `~/.ssh/grisha_htz_id_ed25519` and target `root@95.217.5.223`; deploy remote GitHub HEAD only after checking local changes are committed and pushed.

**Done:** added `compose.staging.yaml`, hostname-specific Traefik HTTPS routes, server-local secret initialization, explicit staging Compose wrapper, SSH deployment orchestrator and remote deployment script. Git verification rejects dirty/untracked files, mismatched local/remote commits, a different branch and a remote HEAD race. The archive and remote script come from the verified commit. Added deployment lock, release directories, shared secrets, first-run-only bootstrap, strict host-key checks and public HTTPS postchecks. Added [staging runbook](staging.md) and README navigation. No local secrets are included in the deployment source paths.

**Decisions:** default branch HEAD is resolved from GitHub rather than assumed to be main. Staging uses a separate project and persistent data, random tokens instead of fixture tokens, and disabled external model providers. No automatic commit/push, data reset or database rollback. The earlier working-tree packaging draft was replaced by the Git-only SSH workflow.

**Checks:** Bash syntax passed; five offline deployment guard tests passed; real `--check` correctly refused the current dirty checkout before any network/SSH action. Temporary secret-generation checks verified distinct random tokens, private environment-file permissions and refusal to overwrite existing configuration. Docker Compose rendered successfully without starting containers; assertions verified ports 80/443 only on Traefik, correct secret/policy mounts, separate staging project and empty external provider settings. `git diff --check` passed. Official Docker merge and Traefik documentation were consulted and linked in the runbook.

**Unverified:** clean-checkout live GitHub verification and SSH deployment end to end, server DNS/firewall/ports, live TLS issuance, authenticated public API/MCP behavior, and backup recovery. No server connection or mutation, certificate request, commit or push was performed. ACME email and DNS readiness remain open questions. The previous local stack was not changed.

## 2026-10-04 — supplied staging contact and DNS evidence applied

**Done:** set the owner's email `ivan.bondar.dev@gmail.com` as the default ACME contact. Recorded the screenshot's proxied A record to `95.217.5.223`. Updated the runbook for Cloudflare Full (strict), HTTP-01 challenge routing and independent origin/edge verification. Enhanced deployment postchecks to validate the origin certificate via loopback with hostname/SNI and require JSON readiness on both routes.

**Checks:** Bash syntax, Python compilation and the five deployment guard tests passed; `git diff --check` passed. Documentation guidance was checked against official Cloudflare documentation. The dirty-checkout guard remains in force.

**Unverified:** origin/public network reachability, Cloudflare TLS mode/rules, certificate issuance and deployment. No server or Cloudflare mutation, commit or push was performed.

## 2026-10-04 — authorized commit, push and staging deployment started

**Instruction:** commit and push local changes, then deploy staging.

**Preflight facts:** SSH reached `it-nomads-server` at the approved address; Docker context is `default`, Compose is 2.40.3, no Compose projects are running, TCP ports 80/443 are free and approximately 34 GB of disk is available. Five deployment guard tests, Bash syntax and `git diff --check` passed. `.env` and `secrets/` are not tracked. Deployment outcome will be appended after the run.

### Deployment retry — shared image build

The first authorized deployment of `c506084` reached the server and generated staging configuration, but stopped during BuildKit image export: multiple services exporting the shared `action-gate-api:0.2.0` tag raced (`image already exists`). Changed the staging wrapper to build the API image once and start all services with `--no-build`. No data reset or credential regeneration is needed. Bash syntax passed; the fix is committed and pushed before retrying through the same GitHub-HEAD deployment guard.

### Deployment retry — SSH script input isolation

The `a8b3567` release started all eight services healthy and completed bootstrap; direct origin HTTPS readiness passed with certificate validation. The SSH invocation exited without creating the final deployment marker. The remote script had been streamed on stdin shared with child commands. Changed the orchestrator to pass the verified remote script as a quoted `bash -c` argument and close stdin, preventing Compose/child commands from consuming the remaining deployment script. Existing credentials, data and bootstrap marker are retained on retry. A transient GitHub "repository disabled" response cleared on a read-only retry; GitHub then advertised the expected HEAD.

### Successful staging deployment and public checks

Release `bdb3ecc7e83c785020eb1402bdb831b91b8e786e` completed deployment through the GitHub-HEAD guard. All eight long-running services are healthy; migrations succeeded and bootstrap completed. Direct-origin HTTPS certificate validation and public Cloudflare readiness both passed. Public panel returned HTTP 200; anonymous panel API and MCP returned 401; the known local development operator token returned 401; the generated staging operator token returned 200; authenticated MCP initialization returned 200. Tokens were not printed or copied into the repository.

Automatic approval review initially rejected public authenticated checks because of token transmission through Cloudflare. The owner explicitly approved this check, after which it completed successfully. No provider/model calls were made. Bootstrap reported the existing labelled baseline mismatch `t10`, with no new failures; this is not a claim of perfect semantic classification. Full browser interaction coverage, load and backup restoration remain unverified.

The deployment record is committed and pushed, then the same deployment script is run again so staging follows the final documentation-inclusive GitHub HEAD. Existing secrets, volumes and bootstrap state are retained.

## 2026-10-04 — static architecture review

**Work:** read the entry documents, implementation modules, contracts, SQL structure, and deployment configuration. Added [architecture-review.md](architecture-review.md) with a component diagram, four execution paths, policy ownership, data boundaries, failure behavior, and architectural assessments. Added a navigation link and recorded follow-up questions.

**Decisions:** keep the review in English and follow ASD-STE100 principles as closely as practical. Label facts, risk hypotheses, proposals, and confidence. No implementation proposal was approved or applied.

**Checks:** local links in the review resolve. An approximate prose check found no descriptive sentence above 25 words. Reviewed paragraph length and terminology. Documentation whitespace checks passed. No application code changed.

**Unverified:** complete ASD-STE100 dictionary compliance; direct official source retrieval returned HTTP 403, although search exposed relevant rules. No new application tests, container actions, provider calls, live deployment checks, or load measurements ran. Historical verification remains separate. The Mermaid diagram was checked as source, not in a rendered preview.

## 2026-10-04 — staging detector settings update

**Instruction:** reuse the three local detector provider settings on staging. Removed their forced-empty staging Compose overrides and updated the runbook. Transfer uses SSH into server-private configuration; verification compares the running container settings without printing values. Active detector policy/profile remains unchanged and no provider request is used for verification. Outcome follows below.
