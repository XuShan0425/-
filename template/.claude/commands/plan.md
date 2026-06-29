---
description: Plan a requirement into EPIC + task files via the orchestrator
---

Plan the following requirement and create task files, using the orchestrator in
autopilot mode.

Requirement: $ARGUMENTS

Run the planner:

```bash
python orchestrator/agent-team.py plan "$ARGUMENTS"
```

Then run `python orchestrator/agent-team.py status` and summarize: the EPIC id,
the task files created, their branches, and the recommended execution order.
Do not implement any task — planning only.
