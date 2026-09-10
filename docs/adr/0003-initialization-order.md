# Preserve AGENTS.md first, then build `.agent-workflow/`

We decided that project onboarding should always check and preserve the root `AGENTS.md` before creating or extending the `.agent-workflow/` directory. This keeps the Agent entry point authoritative, avoids duplicating governance rules across files, and makes it safe to integrate the workflow into both existing and new projects without rewriting the project's top-level instructions.
