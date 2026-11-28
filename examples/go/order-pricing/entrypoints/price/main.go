package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"example.com/pricing/adapters/catalog"
	"example.com/pricing/adapters/clock"
	"example.com/pricing/adapters/presenter"
	"example.com/pricing/core/model"
	"example.com/pricing/core/ports"
	"example.com/pricing/core/use_cases"
)

type orderInput struct {
	CustomerTier string      `json:"customer_tier"`
	Country      string      `json:"country"`
	Lines        []lineInput `json:"lines"`
}

type lineInput struct {
	SKU      string `json:"sku"`
	Quantity int64  `json:"quantity"`
}

func readOrder(path string) (model.Order, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return model.Order{}, err
	}
	var input orderInput
	if err := json.Unmarshal(data, &input); err != nil {
		return model.Order{}, err
	}
	lines := make([]model.Line, 0, len(input.Lines))
	for _, line := range input.Lines {
		lines = append(lines, model.Line{SKU: line.SKU, Quantity: line.Quantity})
	}
	return model.Order{
		Lines:        lines,
		CustomerTier: input.CustomerTier,
		Country:      input.Country,
	}, nil
}

func run(orderPath string, catalogPath string) error {
	order, err := readOrder(orderPath)
	if err != nil {
		return err
	}

	var catalogPort ports.CatalogPort
	if catalogPath == "" {
		catalogPort = catalog.NewMemoryCatalog()
	} else {
		fileCatalog, err := catalog.NewJsonFileCatalog(catalogPath)
		if err != nil {
			return err
		}
		catalogPort = fileCatalog
	}

	priceOrder := use_cases.PriceOrder{Catalog: catalogPort, Clock: clock.SystemClock{}}
	result, err := priceOrder.Price(order)
	if err != nil {
		return err
	}

	terminal := presenter.TerminalPresenter{}
	terminal.Present(result)
	return nil
}

func main() {
	orderPath := flag.String("order", "", "path to order JSON file")
	catalogPath := flag.String("catalog", "", "path to catalog JSON file")
	flag.Parse()
	if *orderPath == "" {
		flag.Usage()
		os.Exit(2)
	}

	path := *catalogPath
	if path == "" {
		path = os.Getenv("PRICING_CATALOG")
	}
	if err := run(*orderPath, path); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(2)
	}
}
