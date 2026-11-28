# Python order-pricing example

Canonical readable reference for the inward architecture Lintel checks. The CLI reads an order, prices it in integer cents, and prints one total.

## Domain and rules

Accepted order shape:

```json
{ "customer_tier": "regular", "country": "US", "lines": [{ "sku": "A100", "quantity": 1 }] }
```

- Subtotal is the sum of `unit_price(sku) * quantity`.
- Discount is 10% of subtotal for `gold`; otherwise zero.
- Tax is 8% of `subtotal - discount`, rounded to the nearest cent.
- Shipping is 500 cents when the discounted subtotal is below 5000 cents; otherwise zero.
- Total is `subtotal - discount + tax + shipping`.
- Unknown SKU raises `ValueError`.

## Directory meaning

- `pricing/core`: plain data, rules, and core-owned ports. No argv, env, filesystem, or stdout.
- `pricing/adapters`: implementations of the ports. These own mechanism details.
- `pricing/entrypoints`: argv/env parsing, composition, stdout, and exit status. No pricing logic.

See the [shared examples README](../../README.md) for the other languages.

## Run

```sh
python3 -m pricing.entrypoints.price --help
python3 -m pricing.entrypoints.price --order order.json [--catalog prices.json]
```

`--catalog` falls back to `PRICING_CATALOG`. Without either, the in-memory catalog is used.

## Check

From the repository root:

```sh
python3 lintel/cli/main.py --root examples/python/order-pricing check --stages deterministic --format json
python3 lintel/cli/main.py --root examples/python/order-pricing check --format json
```

## Expected results

| Invocation | Expected `lintel check` rule IDs |
| --- | --- |
| Clean tree, deterministic stages | no findings; JSON output `[]` |
| Clean tree, default stages | no findings; JSON output `[]` |

## Drift in a temporary copy

Inject each change only in a temporary copy; keep the committed tree clean.

| Change made in a temporary copy | Expected rule IDs |
| --- | --- |
| Clean tree, deterministic check | no findings; JSON output `[]` |
| Add an import/use from `core` to `adapters` | `core_outward`, `edge_not_allowed`; with lock enabled also `baseline_violation` |
| Add argv parsing to an adapter | `adapter_cli_concern`; with lock enabled also `baseline_violation` |
| Add `print`/`console.log`/env access to core | `core_cli_concern`; with lock enabled also `baseline_violation` |
| Python: `import os as catalog`, rebind `catalog` from an unknown factory, then read `catalog.environ` | `semantic_review` and, with lock enabled, `baseline_violation`; accepted only after `lintel review` records a decision |
| TypeScript: write `/process\.argv/` as a regex literal in an adapter | no finding; replace it with real `process.argv` use → `adapter_cli_concern` |
| Change the source after accepting a semantic review | the new finding is not in the accepted baseline → `baseline_violation`; no additional rule ID is claimed for a removed accepted entry |

Use [usage](../../../docs/usage.md) and [semantic decisions](../../../docs/semantic-decisions.md) for the command and decision-model contracts.
