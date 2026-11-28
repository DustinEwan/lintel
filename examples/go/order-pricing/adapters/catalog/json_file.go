package catalog

import (
	"encoding/json"
	"fmt"
	"os"

	"example.com/pricing/core/model"
)

type catalogFile struct {
	Prices map[string]int64 `json:"prices"`
}

type JsonFileCatalog struct {
	prices map[string]int64
}

func NewJsonFileCatalog(path string) (*JsonFileCatalog, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var file catalogFile
	if err := json.Unmarshal(data, &file); err != nil {
		return nil, err
	}
	return &JsonFileCatalog{prices: file.Prices}, nil
}

func (c *JsonFileCatalog) UnitPrice(sku string) (model.Money, error) {
	cents, ok := c.prices[sku]
	if !ok {
		return model.Money{}, fmt.Errorf("unknown sku: %s", sku)
	}
	return model.Money{Cents: cents, Currency: "USD"}, nil
}
