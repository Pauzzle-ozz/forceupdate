// Un fichier Go seul : forceupdate lit ses imports et les rattache à leur module.
package main

import (
	"fmt"
	"net/http"

	"github.com/google/uuid"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
)

func main() {
	fmt.Println(http.StatusOK, uuid.New(), cases.Title(language.French).String("forceupdate"))
}
