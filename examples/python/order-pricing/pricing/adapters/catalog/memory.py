from ...core.model import Money


class MemoryCatalog:
    def __init__(self) -> None:
        self._prices = {"A100": 1250, "B200": 2400, "C300": 899}

    def unit_price(self, sku: str) -> Money:
        if sku not in self._prices:
            raise ValueError(f"unknown sku: {sku}")
        return Money(self._prices[sku])
