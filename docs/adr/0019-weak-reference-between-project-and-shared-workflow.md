# Link project workflows to shared workflows with weak references

We decided that a project participating in a shared workflow should reference the shared directory from its own `.agent-workflow/README.md` or `10-project/dependencies.md`, but should not copy shared rules into the project workflow. This keeps each project aware of the chain it belongs to while avoiding duplicated or conflicting governance content.
