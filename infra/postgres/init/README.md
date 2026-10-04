# PostgreSQL initial initialization

This directory is not the source of Action Gate's domain migrations. The schema is applied by a separate `migrate` job in Compose through the [runner](../../../app/action_gate/migrate.py); the API and MCP ingress wait for this job to complete successfully; the composition of the six SQL migrations, the locking and the constraints are described in the [main reference](../../../app/migrations/README.md).

To continue the work, add migrations under `app/migrations/`. Do not delete the volume or live data in order to apply new SQL. The database parameters are set by [Compose](../../../compose.yaml); before Docker actions, check the separate project name and port against the [README](../../../README.md).
