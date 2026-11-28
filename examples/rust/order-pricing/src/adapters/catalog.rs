use std::collections::HashMap;

use crate::core::model::Money;
use crate::core::ports::CatalogPort;

pub struct MemoryCatalog {
    prices: HashMap<String, i64>,
}

impl MemoryCatalog {
    pub fn new() -> Self {
        let mut prices = HashMap::new();
        prices.insert(String::from("A100"), 1250);
        prices.insert(String::from("B200"), 2400);
        prices.insert(String::from("C300"), 899);
        Self { prices }
    }
}

impl CatalogPort for MemoryCatalog {
    fn unit_price(&self, sku: &str) -> Result<Money, String> {
        let cents = self
            .prices
            .get(sku)
            .ok_or_else(|| format!("unknown sku: {}", sku))?;
        Ok(Money {
            cents: *cents,
            currency: String::from("USD"),
        })
    }
}

pub struct JsonFileCatalog {
    prices: HashMap<String, i64>,
}

impl JsonFileCatalog {
    pub fn from_path(path: &str) -> Result<Self, String> {
        let text = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
        Ok(Self {
            prices: parse_prices(&text)?,
        })
    }
}

impl CatalogPort for JsonFileCatalog {
    fn unit_price(&self, sku: &str) -> Result<Money, String> {
        let cents = self
            .prices
            .get(sku)
            .ok_or_else(|| format!("unknown sku: {}", sku))?;
        Ok(Money {
            cents: *cents,
            currency: String::from("USD"),
        })
    }
}

fn object_after_key<'a>(text: &'a str, key: &str) -> Result<&'a str, String> {
    let marker = format!("\"{}\"", key);
    let start = text
        .find(&marker)
        .ok_or_else(|| format!("missing {}", key))?;
    let rest = &text[start + marker.len()..];
    let colon = rest
        .find(':')
        .ok_or_else(|| format!("missing colon after {}", key))?;
    let after = rest[colon + 1..].trim_start();
    let open = after
        .find('{')
        .ok_or_else(|| format!("{} is not an object", key))?;
    let body = &after[open + 1..];
    let close = body
        .find('}')
        .ok_or_else(|| format!("unterminated {}", key))?;
    Ok(&body[..close])
}

fn parse_prices(text: &str) -> Result<HashMap<String, i64>, String> {
    let mut prices = HashMap::new();
    for pair in object_after_key(text, "prices")?.split(',') {
        let pair = pair.trim();
        if pair.is_empty() {
            continue;
        }
        let mut parts = pair.splitn(2, ':');
        let sku_field = parts.next().unwrap_or("").trim();
        let cents_field = parts
            .next()
            .ok_or_else(|| String::from("invalid price entry"))?
            .trim();
        let sku = sku_field
            .strip_prefix('"')
            .and_then(|value| value.strip_suffix('"'))
            .ok_or_else(|| String::from("invalid sku"))?;
        let cents: i64 = cents_field
            .parse()
            .map_err(|_| String::from("invalid cents"))?;
        prices.insert(String::from(sku), cents);
    }
    Ok(prices)
}
