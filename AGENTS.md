# Working rules — Action Gate

Before your first action, read README.md and docs/transfer.md.

The owner is Ivan. The goal is to continue the competition project AI Control Layer.
The owner decides on the direction, the team and the submission.

- Notes, plans and documentation — in English. The repository README, UI,
  code comments, messages, pitch and submission texts — in English.
  Prepare mentor questions in Ukrainian and English.
- Separate source facts (references to code, sources/ or a specific URL)
  from hypotheses and proposals (with a confidence level). Do not invent criteria,
  probabilities, partner availability, budgets, pilots or hiring.
- Code — app/, launch — infra/ and root files, scripts — scripts/,
  submission texts — pitch/. Do not bring a general research library back here.
- Record new decisions in docs/01-decision.md, questions — docs/07-open-questions.md.
  After each session add an entry to docs/08-session-log.md: date,
  what was done, decisions, checks and unverified items. Do not rewrite history.
- Do not publish, do not submit to the competition, do not register, do not write to partners,
  do not spend money without a direct instruction. Do not add real third-party
  integrations or keys without a separate instruction; the existing proxy is not permission
  for paid calls. Do not commit secrets.
- The task source is sources/goldman-task/. Deadline and criteria weight
  discrepancies are preserved in docs/07-open-questions.md. Do not plan artifacts
  for the last hour. Old pitch drafts are not a description of the current product.
- Do not touch the archive workspace stack. The new Compose project has a separate name.
  Before Docker actions check the target and port. Do not reset live data for tests;
  MCP acceptance creates an isolated project by default.
