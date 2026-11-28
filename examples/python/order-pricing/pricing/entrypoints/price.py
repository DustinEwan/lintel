import argparse
import json
import os
import sys
from pathlib import Path

from pricing.adapters.catalog.json_file import JsonFileCatalog
from pricing.adapters.catalog.memory import MemoryCatalog
from pricing.adapters.clock.system import SystemClock
from pricing.adapters.presenter.terminal import TerminalPresenter
from pricing.core.model import Line, Order
from pricing.core.price_order import PriceOrder


def _read_order(path: str) -> Order:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Order(
        lines=tuple(
            Line(sku=item["sku"], quantity=int(item["quantity"]))
            for item in data["lines"]
        ),
        customer_tier=data["customer_tier"],
        country=data["country"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="price", description="Price an order.")
    parser.add_argument("--order", required=True, help="path to order JSON file")
    parser.add_argument("--catalog", help="path to catalog JSON file")
    args = parser.parse_args()

    catalog_path = args.catalog or os.environ.get("PRICING_CATALOG")
    try:
        catalog = JsonFileCatalog(catalog_path) if catalog_path else MemoryCatalog()
        order = _read_order(args.order)
        result = PriceOrder(catalog, SystemClock()).price(order)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    TerminalPresenter().present(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
