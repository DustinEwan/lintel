package model

import "time"

type Money struct {
	Cents    int64
	Currency string
}

type Line struct {
	SKU      string
	Quantity int64
}

type Order struct {
	Lines        []Line
	CustomerTier string
	Country      string
}
type PricingResult struct {
	Subtotal Money
	Discount Money
	Tax      Money
	Shipping Money
	Total    Money
	PricedAt time.Time
}
