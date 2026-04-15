---
source_file: "business_needed_solutions/hooks.py"
type: "code"
community: "GL Entry"
location: "L342-L346"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/GL_Entry
---

# hooks.scheduler_events.daily -> scheduled_squareoff_run

## Connections
- [[Rationale daily tick is cheap because scheduled_squareoff_run short-circuits on schedulelast_run; lets operators change cadence without restart]] - `rationale_for` [EXTRACTED]
- [[hooks.py_1]] - `implements` [EXTRACTED]
- [[scheduled_squareoff_run()_1]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/GL_Entry