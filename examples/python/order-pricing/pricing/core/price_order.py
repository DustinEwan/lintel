from .model import Money, Order, PricingResult
from .ports import CatalogPort, ClockPort


class PriceOrder:
    def __init__(self, catalog: CatalogPort, clock: ClockPort) -> None:
        self.catalog = catalog
        self.clock = clock

    def price(self, order: Order) -> PricingResult:
        subtotal_cents = 0
        currency = "USD"
        for line in order.lines:
            price = self.catalog.unit_price(line.sku)
            subtotal_cents += price.cents * line.quantity
            currency = price.currency

        discount_cents = subtotal_cents // 10 if order.customer_tier == "gold" else 0
        discounted_cents = subtotal_cents - discount_cents
        tax_cents = (discounted_cents * 8 + 50) // 100
        shipping_cents = 500 if discounted_cents < 5000 else 0
        total_cents = discounted_cents + tax_cents + shipping_cents

        def amount(cents: int) -> Money:
            return Money(cents, currency)

        return PricingResult(
            subtotal=amount(subtotal_cents),
            discount=amount(discount_cents),
            tax=amount(tax_cents),
            shipping=amount(shipping_cents),
            total=amount(total_cents),
            priced_at=self.clock.now(),
        )
