use std::time::SystemTime;

pub struct Money {
    pub cents: i64,
    pub currency: String,
}

pub struct Line {
    pub sku: String,
    pub quantity: i64,
}

pub struct Order {
    pub lines: Vec<Line>,
    pub customer_tier: String,
    pub country: String,
}

pub struct PricingResult {
    pub subtotal: Money,
    pub discount: Money,
    pub tax: Money,
    pub shipping: Money,
    pub total: Money,
    pub priced_at: SystemTime,
}
