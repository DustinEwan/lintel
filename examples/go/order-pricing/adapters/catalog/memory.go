package catalog

import (
	"fmt"

	"example.com/pricing/core/model"
)

type MemoryCatalog struct {
	prices map[string]int64
}

func NewMemoryCatalog() *MemoryCatalog {
	return &MemoryCatalog{
		prices: map[string]int64{
			"A100": 1250,
			"B200": 2400,
			"C300": 899,
		},
	}
}

func (c *MemoryCatalog) UnitPrice(sku string) (model.Money, error) {
	cents, ok := c.prices[sku]
	if !ok {
		return model.Money{}, fmt.Errorf("unknown sku: %s", sku)
	}
	return model.Money{Cents: cents, Currency: "USD"}, nil
}
