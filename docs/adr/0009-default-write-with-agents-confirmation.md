# Write workflow files by default, but confirm major `AGENTS.md` rewrites

We decided that initialization and recording should write directly to the target project's `AGENTS.md` and `.agent-workflow/` files by default. However, if the skill needs to overwrite or substantially rewrite an existing `AGENTS.md`, it must first present a change plan or diff and wait for user confirmation. This keeps normal setup efficient while protecting the most authoritative project instruction file.
