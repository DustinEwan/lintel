package presenter

import (
	"fmt"

	"example.com/pricing/core/model"
)

type TerminalPresenter struct{}

func (TerminalPresenter) Present(result model.PricingResult) {
	fmt.Printf(
		"total: %d %s (priced at %v)\n",
		result.Total.Cents,
		result.Total.Currency,
		result.PricedAt,
	)
}
