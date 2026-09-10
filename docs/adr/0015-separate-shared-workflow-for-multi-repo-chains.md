# Use a separate shared workflow for multi-repo chains

We decided that each project should own only its own `.agent-workflow/`, while cross-project or multi-repo chains should be governed by a separate shared workflow directory. This keeps project facts local, avoids overloading one repository with global responsibilities, and gives contract handoffs, change manifests, and downstream consumption records a clear home.
