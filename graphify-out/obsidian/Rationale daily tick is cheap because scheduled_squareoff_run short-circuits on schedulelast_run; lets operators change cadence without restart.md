---
source_file: "business_needed_solutions/hooks.py"
type: "document"
community: "GL Entry"
location: "L338-L346"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/GL_Entry
---

# Rationale: daily tick is cheap because scheduled_squareoff_run short-circuits on schedule/last_run; lets operators change cadence without restart

## Connections
- [[hooks.scheduler_events.daily - scheduled_squareoff_run]] - `rationale_for` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/GL_Entry