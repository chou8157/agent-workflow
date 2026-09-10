# Add an explicit migrate mode for existing workflow directories

We decided that migration from existing workflow directories such as `agent_docs/` or `stack-workflow/` should be handled by an explicit `migrate` mode, not by default initialization. Migrate mode must scan the old structure, propose a mapping into the new workflow layout, wait for confirmation, and preserve source traces during consolidation.
