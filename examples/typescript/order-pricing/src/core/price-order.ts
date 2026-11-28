import type { Money, Order, PricingResult } from "./model.js";
import type { CatalogPort, ClockPort } from "./ports.js";

export class PriceOrder {
  constructor(
    private readonly catalog: CatalogPort,
    private readonly clock: ClockPort,
  ) {}

  price(order: Order): PricingResult {
    let subtotalCents = 0;
    let currency = "USD";
    for (const line of order.lines) {
      const price = this.catalog.unitPrice(line.sku);
      subtotalCents += price.cents * line.quantity;
      currency = price.currency;
    }

    const discountCents =
      order.customerTier === "gold" ? Math.trunc(subtotalCents / 10) : 0;
    const discountedCents = subtotalCents - discountCents;
    const taxCents = Math.trunc((discountedCents * 8 + 50) / 100);
    const shippingCents = discountedCents < 5000 ? 500 : 0;
    const totalCents = discountedCents + taxCents + shippingCents;

    const amount = (cents: number): Money => ({ cents, currency });
    return {
      subtotal: amount(subtotalCents),
      discount: amount(discountCents),
      tax: amount(taxCents),
      shipping: amount(shippingCents),
      total: amount(totalCents),
      pricedAt: this.clock.now(),
    };
  }
}
