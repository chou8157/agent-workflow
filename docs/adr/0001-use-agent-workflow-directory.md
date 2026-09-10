# Use `.agent-workflow/` as the project workflow directory

We decided that the core artifact is a layered `.agent-workflow/` directory, with `AGENTS.md` acting only as the root entry and enforcement hook. This keeps Agent-specific workflow material discoverable without turning `AGENTS.md` into a long project encyclopedia, and leaves room for progressive project understanding through directories such as `10-project/`, `15-modules/`, `20-gates/`, and `30-records/`.
