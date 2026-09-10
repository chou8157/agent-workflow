# Use progressive loading during normal project work

We decided that use mode should always read the project entry points `AGENTS.md`, `.agent-workflow/README.md`, and `30-records/current-status.md`, then progressively load only the documents relevant to the task. Gates, module indexes, risk logs, architecture notes, and conventions are read according to task type and affected area. This protects context budget while keeping the agent anchored in the workflow.
