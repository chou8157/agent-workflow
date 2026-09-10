# Default initialization scans only the target project

We decided that initialization should read only the current target project by default. External materials such as other repositories, workflow examples, Wikis, or linked documents may be used only when the user explicitly provides them or the target project itself references them. This prevents accidental cross-project rule pollution and keeps project-specific workflow facts traceable to their sources.
