package ports

import (
	"time"

	"example.com/pricing/core/model"
)

type CatalogPort interface {
	UnitPrice(sku string) (model.Money, error)
}

type ClockPort interface {
	Now() time.Time
}

type PresenterPort interface {
	Present(result model.PricingResult)
}
