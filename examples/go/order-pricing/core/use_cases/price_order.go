package use_cases

import (
	"example.com/pricing/core/model"
	"example.com/pricing/core/ports"
)

type PriceOrder struct {
	Catalog ports.CatalogPort
	Clock   ports.ClockPort
}

func (p PriceOrder) Price(order model.Order) (model.PricingResult, error) {
	var subtotalCents int64
	currency := "USD"
	for _, line := range order.Lines {
		price, err := p.Catalog.UnitPrice(line.SKU)
		if err != nil {
			return model.PricingResult{}, err
		}
		subtotalCents += price.Cents * line.Quantity
		currency = price.Currency
	}

	var discountCents int64
	if order.CustomerTier == "gold" {
		discountCents = subtotalCents / 10
	}
	discountedCents := subtotalCents - discountCents
	taxCents := (discountedCents*8 + 50) / 100
	var shippingCents int64
	if discountedCents < 5000 {
		shippingCents = 500
	}
	totalCents := discountedCents + taxCents + shippingCents

	amount := func(cents int64) model.Money {
		return model.Money{Cents: cents, Currency: currency}
	}
	return model.PricingResult{
		Subtotal: amount(subtotalCents),
		Discount: amount(discountCents),
		Tax:      amount(taxCents),
		Shipping: amount(shippingCents),
		Total:    amount(totalCents),
		PricedAt: p.Clock.Now(),
	}, nil
}
