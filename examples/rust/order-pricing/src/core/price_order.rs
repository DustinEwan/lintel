use crate::core::model::{Money, Order, PricingResult};
use crate::core::ports::{CatalogPort, ClockPort};

pub struct PriceOrder<'a> {
    pub catalog: &'a dyn CatalogPort,
    pub clock: &'a dyn ClockPort,
}

impl<'a> PriceOrder<'a> {
    pub fn price(&self, order: &Order) -> Result<PricingResult, String> {
        let mut subtotal_cents: i64 = 0;
        let mut currency = String::from("USD");
        for line in &order.lines {
            let price = self.catalog.unit_price(&line.sku)?;
            subtotal_cents += price.cents * line.quantity;
            currency = price.currency;
        }

        let discount_cents = if order.customer_tier == "gold" {
            subtotal_cents / 10
        } else {
            0
        };
        let discounted_cents = subtotal_cents - discount_cents;
        let tax_cents = (discounted_cents * 8 + 50) / 100;
        let shipping_cents = if discounted_cents < 5000 { 500 } else { 0 };
        let total_cents = discounted_cents + tax_cents + shipping_cents;

        let amount = |cents: i64| Money {
            cents,
            currency: currency.clone(),
        };
        Ok(PricingResult {
            subtotal: amount(subtotal_cents),
            discount: amount(discount_cents),
            tax: amount(tax_cents),
            shipping: amount(shipping_cents),
            total: amount(total_cents),
            priced_at: self.clock.now(),
        })
    }
}
