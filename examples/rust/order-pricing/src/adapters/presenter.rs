use crate::core::model::PricingResult;
use crate::core::ports::PresenterPort;

pub struct TerminalPresenter;

impl PresenterPort for TerminalPresenter {
    fn present(&self, result: &PricingResult) {
        println!(
            "total: {} {} (priced at {:?})",
            result.total.cents, result.total.currency, result.priced_at
        );
    }
}
