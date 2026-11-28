import type { Money, PricingResult } from "./model.js";

export interface CatalogPort {
  unitPrice(sku: string): Money;
}

export interface ClockPort {
  now(): Date;
}

export interface PresenterPort {
  present(result: PricingResult): void;
}
