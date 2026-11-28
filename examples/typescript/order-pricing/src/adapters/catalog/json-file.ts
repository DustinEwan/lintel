// @ts-expect-error Node type declarations are intentionally omitted.
import { readFileSync } from "node:fs";

import type { Money } from "../../core/model.js";
import type { CatalogPort } from "../../core/ports.js";

interface CatalogFile {
  prices: Record<string, number>;
}

export class JsonFileCatalog implements CatalogPort {
  private readonly prices: Record<string, number>;

  constructor(path: string) {
    const data = JSON.parse(readFileSync(path, "utf8")) as CatalogFile;
    this.prices = data.prices;
  }

  unitPrice(sku: string): Money {
    const cents = this.prices[sku];
    if (cents === undefined) {
      throw new Error(`unknown sku: ${sku}`);
    }
    return { cents, currency: "USD" };
  }
}
