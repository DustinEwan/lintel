use std::time::SystemTime;

use crate::core::model::{Money, PricingResult};

pub trait CatalogPort {
    fn unit_price(&self, sku: &str) -> Result<Money, String>;
}

pub trait ClockPort {
    fn now(&self) -> SystemTime;
}

pub trait PresenterPort {
    fn present(&self, result: &PricingResult);
}
