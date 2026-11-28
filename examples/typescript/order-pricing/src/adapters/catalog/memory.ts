import type { Money } from "../../core/model.js";
import type { CatalogPort } from "../../core/ports.js";

export class MemoryCatalog implements CatalogPort {
  private readonly prices: Record<string, number> = {
    A100: 1250,
    B200: 2400,
    C300: 899,
  };

  unitPrice(sku: string): Money {
    const cents = this.prices[sku];
    if (cents === undefined) {
      throw new Error(`unknown sku: ${sku}`);
    }
    return { cents, currency: "USD" };
  }
}
