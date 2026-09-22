# Runtime integration contracts

These contracts make production integration testable without treating a mocked request as a live
provider, MC-1, or Colibri deployment.

## Feature gates

`c3r.feature_flags.FeatureFlags` parses the directive's seven environment switches. Unknown
boolean values fail closed, `C3R_ENABLED=false` disables every learned/native control surface, and
`C3R_ONLINE_LEARNING=true` is rejected. A host still owns the deterministic path that runs when
C3R is disabled.

## Deliberative providers

The release default is DeepSeek V4.1 Flash. Canonical identifiers are:

- Hugging Face checkpoint: `deepseek-ai/DeepSeek-V4.1-Flash`
- OpenRouter: `deepseek/deepseek-v4.1-flash`
- DeepSeek API: `deepseek-flash`

This is a provider default, not execution authority and not a claim that the full checkpoint
fits the current GCP instance. `c3r.deliberative.default_provider_config` constructs either
hosted profile without embedding credentials. A self-hosted profile is enabled only after a
hardware manifest and live inference evidence demonstrate compatibility.

`c3r.adapters.providers.ProviderAdapter` supports four protocol shapes:

- OpenAI;
- Anthropic Messages;
- Gemini `generateContent`;
- OpenAI-compatible endpoints used by MC-1, Qwen, DeepSeek, vLLM, SGLang, and llama.cpp.

Remote endpoints must use HTTPS; plain HTTP is accepted only for loopback runtimes. Responses must
contain the five bounded arrays required by the Deliberative Envelope. The adapter limits response
bytes, array cardinality, individual strings, and aggregate structured content. Missing fields,
invalid JSON, oversize content, or non-success HTTP status fail closed. `ProviderController`
converts transport, outage, timeout, and malformed-response failures into the deterministic action
selected by host policy. API keys are supplied by the host and are absent from results and telemetry.

These are protocol-level contracts. A provider becomes release-qualified only after credentialed
tests capture model revision, region, latency, usage, failure, and fallback evidence.

## Colibri shadow control

`c3r.colibri.ColibriShadowController` consumes route trace, `.coli` usage, DSpark acceptance,
verification width, expert/cache/I/O/utilization, and context metrics. Its output is always marked
`authoritative=False`. Low draft acceptance recommends `TARGET_ONLY`; controller failure returns
`NATIVE_FALLBACK`. Native token acceptance and MoE routing remain authoritative.

Live completion still requires a compatible Colibri build, the dedicated public integration
repository, immutable build hashes, and captured shadow traces.

## Evidence ledger

`c3r.telemetry.trace_ledger.TraceLedger` canonicalizes decision traces and links them with SHA-256.
Replay rejects reordered, modified, non-canonical, or broken-chain records. The ledger supplies
an integrity check, not tamper proofing or empirical evidence by itself: evidence-grade use must
anchor or sign ledger heads in an independently controlled append-only store, and release traces
must still be governed, redacted, licensed, and independently reproducible.
