// Mini-projet de forceupdate : des dépendances Go à mettre à jour.
package main

import (
	"fmt"

	"example.com/forceupdate/localmod"
	"github.com/BurntSushi/toml"
	"github.com/go-chi/chi"
	"github.com/golang-jwt/jwt/v4"
	"github.com/google/uuid"
	"golang.org/x/text/language"
)

func main() {
	var config map[string]any
	_, _ = toml.Decode("a = 1", &config)
	fmt.Println(localmod.Name, chi.NewRouter() != nil, jwt.SigningMethodHS256.Alg(), uuid.New(), language.French, config)
}
