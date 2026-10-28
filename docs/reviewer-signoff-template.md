# Independent C3R review record — template

Use this for an actual review, not for accepting the reviewer role or confirming
CI. The reviewer should submit the completed record as a PR review or a dated
reply from the approved ColomboAI work address. Do not attach credentials,
private trace rows, raw prompts, or customer/product records. A blank or
unsubstantiated approval is not a release sign-off.

**Reviewer:**
**Date and time (UTC):**
**Reviewed commit SHA:**
**Scope and independence/conflicts:**
**Evidence links and immutable hashes:**

For each gate, choose **approve / needs changes / reject / not reviewed** and
record what was inspected, a finding, and any limitation. Approval is limited
to the exact artifact revision and population reviewed.

| Gate | Decision | Evidence inspected | Findings / limitations |
| --- | --- | --- | --- |
| C3R-controlled task source, rights and source registry | | | |
| Independent outcome labels and sealed split integrity | | | |
| Redaction, field allowlist and leakage tests | | | |
| Effective storage IAM, encryption, read/export audit | | | |
| Daily age-based deletion, backups/replicas and failure alert | | | |
| Independent ledger-head anchoring and tamper detection | | | |
| Kill switch, verifier/commit isolation and unsafe-action tests | | | |
| Trained weights, raw predictions and held-out calibration | | | |
| Paired baselines, provider outages, latency/cost and canary evidence | | | |
| Proposed de-identified public rows and release claims | | | |

**Overall decision for collection:** approve / needs changes / reject / not reviewed

**Overall decision for public standalone launch:** approve / needs changes / reject / not reviewed

**Required changes before reconsideration:**

No row marked “approve” permits collection or publication by itself. The
release owner must also verify the deployed controls and approve the exact
release separately. MC-1 remains outside this standalone scope, not complete
under the original directive.
