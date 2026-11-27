# Lintel architecture rules

- Keep source dependencies pointing inward: entrypoints -> adapters -> core.
- `core` owns facts, policy, rules, ports, and use cases. It must not own argv,
  environment access, filesystem access, subprocesses, or JSON I/O.
- Language-specific source syntax belongs in an analyzer registered by suffix.
- Run `lintel --root . check` after each edit and before declaring work complete.
- New violations fail. Baseline entries cover debt only; config errors, contract
  drift, unparsed source, and baseline errors cannot be accepted away.
- `lintel --root . review` records semantic judgments by fingerprint with a reason.
- Use `lintel --root . hook <event>` for editor and harness integration.
