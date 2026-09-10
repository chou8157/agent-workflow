# Create a standard `AGENTS.md` first, then integrate workflow rules

We decided that a project should not receive a thin, workflow-only `AGENTS.md`. If the file is missing, the skill should first create a complete standard `AGENTS.md` entry point and only then integrate the three project-specific additions: workflow navigation, highest-priority constraints, and the project workflow directory path. If the file already exists, the skill should preserve the existing structure and only supplement those additions.
