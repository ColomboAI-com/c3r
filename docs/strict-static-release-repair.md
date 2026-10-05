# Strict static release repair

Review baseline: `71bd6d30838f6fe7eafd9af7840b3fba31ac5bd4`.

The standalone release requires full strict static checks, not merely clean changed files. The baseline produced 461 Pyright diagnostics and 56 configured Ruff findings. Preserve the existing Pyright strict mode, full `c3r`/`tests` include set, Ruff configuration and runtime assertions: do not suppress diagnostics, introduce fake optional dependency stubs, remove tests or use blanket `Any`/unchecked schema casts.

Repair requirements:

- Type dataclass default factories and existing fixture/server/callback interfaces accurately.
- Keep untrusted JSON values as objects until actual structural validation, and preserve rejection messages and exception contracts.
- Express inference adapter metadata as read-only properties; implementations must not gain mutation or authority.
- Keep optional Laya dependencies lazy, missing-extra failures and immutable revision/license checks. Narrow only the documented SDK callable interfaces; injected fixture success is not live SDK qualification.
- Give shared canonical hashing and task admission explicit public interfaces without changing hash bytes, grant semantics or enabling collection. Preserve the historical private hash alias for compatibility.
- Preserve recommendation-only rejection, transport failure/stream cancellation tests, project isolation, generation-specific retention and timezone rejection. Use public transport boundaries instead of private socket/helper access where practical.
- Fix mechanical import, timezone, immutable-default and fixture-loop issues without changing supported Python versions or release scope.

Acceptance: full strict Pyright and configured Ruff pass, full existing suite including official Python/JS SDK fixtures passes with zero skips, and separate Standards/Spec review finds no unresolved correctness or requirements defects.

These repairs change the API source candidate. Existing exact-head `71bd6d3` image configurations and evidence remain historical; they cannot qualify the new candidate. Rebind API/retention qualification after code review and final source freeze. DeepSeek build-context equality must be checked before reusing its preserved artifact. No local static/test result clears host, CVE, cloud, registry, TLS, canary or Avori gates.
