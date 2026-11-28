from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Money:
    cents: int
    currency: str = "USD"


@dataclass(frozen=True)
class Line:
    sku: str
    quantity: int


@dataclass(frozen=True)
class Order:
    lines: tuple[Line, ...]
    customer_tier: str
    country: str


@dataclass(frozen=True)
class PricingResult:
    subtotal: Money
    discount: Money
    tax: Money
    shipping: Money
    total: Money
    priced_at: datetime
