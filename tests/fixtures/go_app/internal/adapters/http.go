package httpadapter

import (
	"example.com/app/internal/app"
	"net/http"
)

func Serve(w http.ResponseWriter) {
	app.Run()
	_ = w
}
