export interface Money {
  cents: number;
  currency: string;
}

export interface Line {
  sku: string;
  quantity: number;
}

export interface Order {
  lines: Line[];
  customerTier: string;
  country: string;
}

export interface PricingResult {
  subtotal: Money;
  discount: Money;
  tax: Money;
  shipping: Money;
  total: Money;
  pricedAt: Date;
}
