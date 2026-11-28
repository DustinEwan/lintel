use std::env;
use std::fs;
use std::process::ExitCode;

use order_pricing::adapters::catalog::{JsonFileCatalog, MemoryCatalog};
use order_pricing::adapters::clock::SystemClock;
use order_pricing::adapters::presenter::TerminalPresenter;
use order_pricing::core::model::{Line, Order};
use order_pricing::core::ports::{CatalogPort, PresenterPort};
use order_pricing::core::price_order::PriceOrder;

fn usage() {
    println!("usage: price --order <path> [--catalog <path>]");
    println!("options: --order, --catalog, --help");
}

fn field_after<'a>(text: &'a str, key: &str) -> Result<&'a str, String> {
    let marker = format!("\"{}\"", key);
    let start = text
        .find(&marker)
        .ok_or_else(|| format!("missing {}", key))?;
    let rest = &text[start + marker.len()..];
    let colon = rest
        .find(':')
        .ok_or_else(|| format!("missing colon after {}", key))?;
    Ok(rest[colon + 1..].trim_start())
}

fn string_field(text: &str, key: &str) -> Result<String, String> {
    let after = field_after(text, key)?;
    let body = after
        .strip_prefix('"')
        .ok_or_else(|| format!("{} is not a string", key))?;
    let end = body
        .find('"')
        .ok_or_else(|| format!("unterminated {}", key))?;
    Ok(String::from(&body[..end]))
}

fn integer_field(text: &str, key: &str) -> Result<i64, String> {
    let after = field_after(text, key)?;
    let end = after
        .find(|ch: char| !(ch.is_ascii_digit() || ch == '-'))
        .unwrap_or(after.len());
    after[..end]
        .parse::<i64>()
        .map_err(|_| format!("invalid {}", key))
}
fn parse_order(text: &str) -> Result<Order, String> {
    let after = field_after(text, "lines")?;
    let open = after
        .find('[')
        .ok_or_else(|| String::from("lines is not an array"))?;
    let body = &after[open + 1..];
    let close = body
        .find(']')
        .ok_or_else(|| String::from("unterminated lines"))?;

    let mut lines = Vec::new();
    for item in body[..close].split('}') {
        if !item.contains('{') {
            continue;
        }
        let start = item.find('{').unwrap_or(0);
        let object = &item[start..];
        lines.push(Line {
            sku: string_field(object, "sku")?,
            quantity: integer_field(object, "quantity")?,
        });
    }

    Ok(Order {
        lines,
        customer_tier: string_field(text, "customer_tier")?,
        country: string_field(text, "country")?,
    })
}

fn run(order_path: &str, catalog_path: Option<&str>) -> Result<(), String> {
    let text = fs::read_to_string(order_path).map_err(|error| error.to_string())?;
    let order = parse_order(&text)?;

    let memory_catalog = MemoryCatalog::new();
    let file_catalog = match catalog_path {
        Some(path) => Some(JsonFileCatalog::from_path(path)?),
        None => None,
    };
    let catalog: &dyn CatalogPort = match file_catalog.as_ref() {
        Some(value) => value,
        None => &memory_catalog,
    };

    let clock = SystemClock;
    let presenter = TerminalPresenter;
    let price_order = PriceOrder {
        catalog,
        clock: &clock,
    };
    let result = price_order.price(&order)?;
    presenter.present(&result);
    Ok(())
}

fn main() -> ExitCode {
    let mut order_path: Option<String> = None;
    let mut catalog_path: Option<String> = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--help" | "-h" => {
                usage();
                return ExitCode::SUCCESS;
            }
            "--order" => order_path = args.next(),
            "--catalog" => catalog_path = args.next(),
            other => {
                eprintln!("unknown option: {}", other);
                usage();
                return ExitCode::from(2);
            }
        }
    }

    let Some(order_path) = order_path else {
        usage();
        return ExitCode::from(2);
    };
    let catalog_path = catalog_path.or_else(|| env::var("PRICING_CATALOG").ok());
    match run(&order_path, catalog_path.as_deref()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("error: {}", message);
            ExitCode::from(2)
        }
    }
}
