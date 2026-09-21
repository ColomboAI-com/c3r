# C3R domain context

C3R controls the next computation, not the authoritative outcome. Learned components may
propose and rank actions, but they cannot grant permissions, select their own authoritative
verifier, or commit consequential effects.

The public behavioral seams are:

1. `StateCompiler.compile` creates a bounded, provenance-bearing state or returns an explicit
   unsafe-to-compress result.
2. `CandidateCompiler.compile` applies hard policy masks before bounded candidate selection and
   always represents the absence of a safe action.
3. `RobustCvocController.select` chooses only candidates with a positive conservative lower bound.
4. `VerifierFirewall.verify` runs policy-selected checks that proposals cannot replace or suppress.
5. `TrustedCommitGateway.commit` completely mediates external effects and requires independent
   authorization and successful verification.

