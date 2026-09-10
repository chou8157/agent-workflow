# Route natural language requests to internal workflow modes

We decided that users should not have to remember exact mode commands. The master skill should interpret natural language requests and route them to internal modes: onboarding or initialization to `init`, starting development to `use`, recording or archiving to `record`, rule changes to `improve`, and multi-project chain setup to `init shared`. This preserves a friendly interface while keeping agent behavior structured.
