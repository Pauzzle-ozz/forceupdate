module example.com/forceupdate/demo

go 1.21

require (
	example.com/forceupdate/localmod v0.0.0
	github.com/BurntSushi/toml v1.2.0
	github.com/go-chi/chi v1.5.4
	github.com/golang-jwt/jwt/v4 v4.4.0
	github.com/google/uuid v1.3.0
	github.com/stretchr/testify v1.7.0
	golang.org/x/text v0.3.7
)

require (
	github.com/davecgh/go-spew v1.1.0 // indirect
	github.com/pmezard/go-difflib v1.0.0 // indirect
	gopkg.in/yaml.v3 v3.0.0-20200313102051-9f266ea9e77c // indirect
)

replace example.com/forceupdate/localmod => ./third_party/localmod

// uuid est figé par un replace : c'est sa version qui compte.
replace github.com/google/uuid => github.com/google/uuid v1.4.0

exclude github.com/BurntSushi/toml v1.6.0

retract v0.1.0 // Publiée par erreur.
