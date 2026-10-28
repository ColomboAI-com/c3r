# v0.1.0 integration candidate

This is a source integration record, not production qualification or a release tag.
The integration branch starts at reviewed readiness commit `54eeb54`.
Neither existing branch is force-updated.

The five PR #6 commits were inspected individually. Each records its reviewed local
source; those local sources already occur in the readiness ancestry:

| PR commit | Existing reviewed source | Change retained |
| --- | --- | --- |
| `ab9344f` | `f1c4cbb` | Self-hosted provider/launcher and qualification configuration |
| `a9e91f9` | `9adf275` | CPU build and three-image Cloud Build qualification |
| `e8b82c3` | `a7acb8c` | Serialized security scans |
| `197b026` | `5a06bc7` | Compiler headers/probe and failed-image regression |
| `0333653` | `45f2a864` | Launcher test import ordering |

`git diff 45f2a864 0333653` is empty. Both trees are
`ce5646e8266df911e03322cfc1c2073550340d4f`. Thus the missing commits introduce
no missing final source change. Reapplying their patches would duplicate changes
or regress subsequent readiness work. A deliberate ancestry-only merge preserves
the reviewed readiness source while recording both histories.

Preserved additions after the identical production tree include the authenticated
loopback-only internal-readiness channel, local artifact verification, API-worker
liveness checks, shutdown revocation, and readiness HTTP regressions.

PR #6 remains unmerged. API engineering may continue here, but public traffic,
production labeling and an immutable release require the separate host, runtime,
API and independent-review gates. `/v1/c3r/execute` remains disabled.
