import type { PricingResult } from "../../core/model.js";
import type { PresenterPort } from "../../core/ports.js";

export class TerminalPresenter implements PresenterPort {
  present(result: PricingResult): void {
    console.log(
      `total: ${result.total.cents} ${result.total.currency} ` +
        `(priced at ${result.pricedAt.toISOString()})`,
    );
  }
}
