# Go order-pricing example

A small Go CLI with the same domain and inward dependency shape as the Python reference.

## Domain and rules

Accepted order shape:

```json
{ "customer_tier": "regular", "country": "US", "lines": [{ "sku": "A100", "quantity": 1 }] }
```

- Subtotal is the sum of `unit_price(sku) * quantity`, in `int64` cents.
- Discount is 10% of subtotal for `gold`; otherwise zero.
- Tax is 8% of `subtotal - discount`, rounded to the nearest cent.
- Shipping is 500 cents when the discounted subtotal is below 5000 cents; otherwise zero.
- Total is `subtotal - discount + tax + shipping`.
- Unknown SKU returns an error.

## Directory meaning

- `core/model`: plain data in cents.
- `core/ports`: core-owned interfaces.
- `core/use_cases`: pricing rules, depending only on core model and ports.
- `adapters`: catalog, clock, and terminal implementations.
- `entrypoints/price`: flag/env parsing, composition, output, and exit status.

See the [shared examples README](../../README.md) for the other languages.

## Run

```sh
go run ./entrypoints/price --help
go run ./entrypoints/price --order order.json [--catalog prices.json]
```

`--catalog` falls back to `PRICING_CATALOG`. Without either, the in-memory catalog is used.

## Check

From the repository root:

```sh
python3 lintel/cli/main.py --root examples/go/order-pricing check --stages deterministic --format json
python3 lintel/cli/main.py --root examples/go/order-pricing check --format json
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
| Go: import a new CLI framework in an adapter | no finding; Go boundary-token analysis is deterministic only |
| TypeScript: write `/process\.argv/` as a regex literal in an adapter | no finding; replace it with real `process.argv` use → `adapter_cli_concern` |
| Change the source after accepting a semantic review | the new finding is not in the accepted baseline → `baseline_violation`; no additional rule ID is claimed for a removed accepted entry |

Use [usage](../../../docs/usage.md) and [semantic decisions](../../../docs/semantic-decisions.md) for the command and decision-model contracts.
