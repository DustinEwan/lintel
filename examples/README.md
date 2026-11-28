# Examples

Small inward-architecture teaching projects. Each `order-pricing` example reads an order, applies a few pricing rules, and prints a total.

| Language | Example | Role |
| --- | --- | --- |
| Python | [order-pricing](python/order-pricing/README.md) | Canonical readable reference |
| Go | [order-pricing](go/order-pricing/README.md) | Same domain with Go packages and interfaces |
| Rust | [order-pricing](rust/order-pricing/README.md) | Same domain with Rust modules and traits |
| TypeScript | [order-pricing](typescript/order-pricing/README.md) | Same domain with ES modules and TypeScript interfaces |

Check one example from the repository root:

```sh
python3 lintel/cli/main.py --root examples/<language>/order-pricing check
```

The repository root assigns `examples/**` to the excluded `example` scope. Each example is therefore checked from its own root, with its own `lintel.toml`, `lintel.lock`, and `lintel.baseline.json`.

Clean examples need no decision provider. A new semantic review finding needs a configured provider for the initial proposal; after `lintel review` records an accepted decision, subsequent checks run offline.

For full command behavior and the decision model, see [usage](../docs/usage.md), [semantic decisions](../docs/semantic-decisions.md), and [semantic scenarios](../SEMANTIC_SCENARIOS.md).
