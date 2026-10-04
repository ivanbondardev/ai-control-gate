# Clean project transfer — 2026-10-04

**Provenance fact:** the copy was created from the working files
`/Users/ivbon/projects/deepseek/hackyeah-2026`, including the required
uncommitted files. It is a standalone copy, not a worktree and not a symlink.
The original directory remains an archive; it is not needed for launching.

**Composition fact:** app/, infra/, launch, client and check scripts,
root build files, the primary task, selected implementation reports,
criteria, open questions, scenarios and historical pitch drafts.
The source files are preserved in content, but references to removed materials
are marked as archive reference; the index is archive-references.json.

**Exclusion fact:** talks/, jitsu/, the original ai-control-layer/,
independent reviews, the general preparation log, caches, dependencies, UI snapshots,
the old Git history, .env, secrets/ and Docker volumes were not copied. The original panel is already
integrated: [source](../sources/original-panel-integration-2026-10-03.md).

**Transfer boundary:** this is code and bootstrap configuration, not a backup copy of a
live system. A new launch will not have the current policies from the DB, audit history,
budget counters and receipts of the old demo. Preserving such state
requires a separate agreed transfer of the DB, service volumes and local secrets.
make demo-mcp-up generates new secrets for the dummy services. A real model
provider requires separate local configuration.

**Proposal, high confidence:** transfer the whole folder, start a new chat
with README.md and AGENTS.md, check a fresh launch and only then update the
pitch for the verified scenario. The source documents contain historical results;
they do not confirm the new runtime. The full raw evidence is left in the archive.

## Checks on this copy


**Copy check fact:** Python 3.14.7 — 296 tests in discovery, 224 passed,
72 skipped due to optional dependencies/environment conditions; no errors.
[Log](../sources/export-unit-tests.log). Additionally 14 assertion tests — OK,
53 fixtures valid without sending requests; docker compose config --quiet — OK,
syntax of all shell scripts — OK. 171 code/configuration/script files
match the original byte-for-byte; Markdown and the root .env.example have the
described editorial changes. No broken local clickable Markdown links
and no symlinks found.

**Boundaries:** the initial launch on system Python 3.9 is incompatible with the code;
local HTTP tests required sandbox permission for localhost. The final
run was performed successfully on Python 3.14.7. The new Docker stack, integration,
browser and real model checks were not run. The old runtime was not changed.
Git was initialized on the codex/standalone branch, without a remote and without commits.

