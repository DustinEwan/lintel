package app

import "example.com/app/internal/domain"

func Run() {
	domain.Handle(nil)
}
