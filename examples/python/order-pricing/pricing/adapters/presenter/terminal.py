from ...core.model import PricingResult


class TerminalPresenter:
    def present(self, result: PricingResult) -> None:
        total = result.total
        print(
            f"total: {total.cents} {total.currency} "
            f"(priced at {result.priced_at.isoformat()})"
        )
