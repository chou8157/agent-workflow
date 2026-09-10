# Do not automatically migrate existing workflow directories

We decided that initialization must not silently delete, rename, or migrate existing workflow directories such as `agent_docs/`. The skill should detect them, summarize their contents, and propose how they could map into `.agent-workflow/`; migration or consolidation happens only after user confirmation. If old content is used as source material, the generated documents must preserve that source trace.
