import json
from pathlib import Path

from ...core.model import Money


class JsonFileCatalog:
    def __init__(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._prices = {sku: int(cents) for sku, cents in data["prices"].items()}

    def unit_price(self, sku: str) -> Money:
        if sku not in self._prices:
            raise ValueError(f"unknown sku: {sku}")
        return Money(self._prices[sku])
