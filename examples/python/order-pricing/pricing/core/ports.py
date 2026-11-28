from datetime import datetime
from typing import Protocol

from .model import Money, PricingResult


class CatalogPort(Protocol):
    def unit_price(self, sku: str) -> Money: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class PresenterPort(Protocol):
    def present(self, result: PricingResult) -> None: ...
