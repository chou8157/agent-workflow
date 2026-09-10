# Store ADRs in the workflow records unless the project already has an ADR location

We decided that ADRs created by this workflow should default to `.agent-workflow/30-records/adr/`. If the target project already has an established ADR location such as `docs/adr/`, the skill should use that existing location instead. This keeps workflow-managed decisions discoverable while respecting a project's existing documentation conventions.
