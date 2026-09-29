# Incident Investigator

The application owns a bounded investigation loop. Groq can select one registered,
read-only tool per iteration or return a typed proposed diagnosis. Arguments are
validated by the registry, execution has a deadline, and every result is persisted as
evidence. The default maximum is eight iterations.

The provider sees current incident context, normalized evidence, tool names, and the
system safety policy. It never receives database access or credentials. Its response
contains categorical confidence, evidence IDs, contradictions, uncertainties, historical
precedent, and an allowlisted recommendation. It never returns hidden reasoning.

`FakeProvider` is deterministic and is used only by standard tests and offline evaluation.
Live Groq is opt-in with `RUN_GROQ_INTEGRATION_TESTS=1`.
