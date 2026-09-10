# Separate project workflow improvements from global skill improvements

We decided that improve mode may directly update the current project's `.agent-workflow/`, but changes to the master skill's templates or global rules must be explicitly identified as global changes and confirmed by the user before writing. This prevents one project's special case from silently contaminating the reusable workflow system.
