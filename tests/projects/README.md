# Mini-projets de test

Un dossier par outil. Les lockfiles ont été produits par les vrais outils, puis
figés : ne pas les régénérer sans mettre à jour les tests qui en dépendent.

| Dossier | Outil | Lockfile produit avec |
|---|---|---|
| `pip/` | pip : `-r`, `-c`, dépendance git, `-e` local | (pas de lockfile) |
| `pip-tools/` | pip-tools : `.in` compilés en `.txt` | `pip-compile` |
| `poetry/` | Poetry 1.8 : `poetry.lock` sans `category` ni `groups` | `poetry lock` (1.8.5) |
| `uv/` | workspace uv : un membre, un exclu, un projet hors workspace | `uv lock` |
| `pipenv/` | Pipfile | `pipenv lock` |
| `setuptools/` | `setup.cfg`, et un `setup.py` qui n'est pas lu | (pas de lockfile) |
| `npm/` | npm : chaque forme de plage, alias `npm:`, `file:`, pair, facultative, version imbriquée | `npm install` (npm 11.6, lockfile v3) |
| `yarn1/` | Yarn 1 : le même `package.json` que `npm/` | `yarn install` (1.22.22) |
| `yarn4/` | workspace Yarn 4 : la racine et un membre, `typescript` et `fsevents` patchés d'office | `yarn install --mode=update-lockfile` (4.18.1) |
| `pnpm9/` | workspace pnpm 9 : deux membres reliés par `workspace:*`, un exclu par `!packages/excluded` | `pnpm install --lockfile-only` (9.15.9) |
| `npm-workspace/` | workspace npm : deux membres, un conflit de versions entre eux, un dossier hors workspace | `npm install` (npm 11.6) |
| `pnpm-catalog/` | workspace pnpm à catalogues : `catalog:`, `catalog:default`, `catalog:legacy` (sous `catalogs:`), un alias `npm:` dans le catalogue | `pnpm install --lockfile-only --ignore-scripts` (12.15.0) |
| `cargo/` | un crate : chaîne, table en ligne, `[dependencies.x]`, renommage (`package =`), facultative, git, `path` (vers `vendor/local-crate`), plateforme (`[target.'cfg(windows)']`), dev, build ; `regex` `=1.5.4`, `time` 0.1 et `anyhow` 1.0.75 en faille | `cargo generate-lockfile`, puis `cargo update -p x --precise V` (serde 1.0.150, anyhow 1.0.75, log 0.4.14) (cargo 1.99) |
| `cargo-workspace/` | workspace Cargo : racine virtuelle, `members = ["crates/*"]`, un membre exclu (`exclude`), `[workspace.dependencies]` repris par `workspace = true`, une dépendance `path` entre membres, `smallvec` `=1.6.0` en faille | idem (serde 1.0.160, anyhow 1.0.75, log 0.4.17) |
| `go/` | un module Go (`go 1.21`) : `golang-jwt/jwt/v4` v4.4.0 retirée et en faille, `x/text` v0.3.7 en faille, `go-chi/chi` v1.5.4 dépréciée (la v5 est un autre module), `BurntSushi/toml` (majuscules ; v1.6.0 exclue), `uuid` remplacé par lui-même en v1.4.0 (`replace`), un module local (`replace … => ./third_party/localmod`), `testify` v1.7.0 et ses indirectes, dont `yaml.v3` en pseudo-version et en faille | `go mod tidy` (Go 1.27.3) |
| `go-workspace/` | workspace `go.work` : `app` et `lib` (`use`), `app` qui requiert `lib` (`replace … => ../lib`), un `replace` de `x/text` dans `go.work`, `tools` hors du workspace avec une ligne `toolchain` | `go mod tidy` dans chaque module, `go build` du workspace pour `go.work.sum` (Go 1.27.3) |
| `composer/` | un projet Composer (`config.platform.php` 8.1.30) : version exacte (`guzzlehttp/guzzle` 7.4.0, treize failles), `^`, `~5.4` (jusqu'à 6.0), joker `3.4.*` (`twig/twig`, quinze failles), union `^1.1 \|\| ^2.0`, branche `dev-master`, dépôt `path` (vers `third_party/acme-tools`), deux paquets abandonnés (`php-http/message-factory`, `doctrine/cache` en `require-dev`), `conflict` (`monolog/monolog` 2.11.*), `replace` de polyfills, un script `post-update-cmd` témoin (il écrirait `script-ran.txt`) ; `guzzlehttp/psr7` 2.1.0 indirecte en faille | `composer update --no-install --no-scripts --no-plugins --no-blocking --with x:V…` (Composer 2.11.0, PHP 8.5.12) |
| `bundler/` | un projet Bundler : `~> 2.2.3` (`rack` 2.2.3, 32 failles), deux contraintes (`nokogiri` `>= 1.19.0", "< 1.20`, à plateforme dans le lockfile : `1.19.0-x86_64-linux-gnu`), version exacte (`puma` 5.6.4), guillemets simples, `require: false`, `platforms: %i[windows jruby]` sans contrainte (`tzinfo-data`), un bloc `group :development, :test`, `group:` en option, `gemspec` (`demo.gemspec` : `add_dependency`, `add_runtime_dependency`, `add_development_dependency`), une gem `path:` (`helper/`, son `.gemspec` résolu dans le `Gemfile.lock` de la racine) ; `PLATFORMS` `x64-mingw-ucrt` et `x86_64-linux` | `bundle lock --add-platform x86_64-linux` d'un `Gemfile` aux versions épinglées (`= V`), puis `bundle lock` du vrai `Gemfile`, qui les garde (Bundler 4.0.20, Ruby 4.0.9) |
| `maven/` | un build Maven à trois `pom.xml` : la racine (parent distant `org.apache:apache` 23, `<modules>`, `<properties>` dont `log4j.version` 2.14.1 partagée par log4j-api et log4j-core, `dependencyManagement` avec un BOM importé et junit en `test`, `pluginManagement`), `lib` (versions gérées par le parent, guava `30.1-jre`, une plage `[1.9,2.0)` pour commons-text) et `app` (`${project.version}` d'un module, une version du BOM, une propriété du module, `provided`, `<optional>`, plugins avec et sans version) ; un peu de Java pour les langages | (pas de lockfile en V1) |
| `gradle/` | un build Gradle : `gradle/libs.versions.toml` (`version.ref` partagée par okhttp et logging-interceptor, `group`/`name`, un plugin), `build.gradle.kts` (bloc `plugins`, `alias(libs.plugins…)`, `libs.x`, une variable `val`, `platform(…)`, une dépendance sans version), `gradle.properties`, et `app/build.gradle` en Groovy (`libs.x`, `$variable` de `gradle.properties`, Google Maven, notation en carte) | (pas de lockfile en V1) |
| `vulnerable/` | des failles connues (E08) : `lodash` 4.17.15, `flask` 0.12 et ses dépendances de fin 2018 (jinja2 2.10, werkzeug 0.14.1) | `npm install --package-lock-only --ignore-scripts` (npm 11.6) ; `uv pip compile requirements.in -o requirements.txt --python-version 3.7 --exclude-newer 2019-01-01` (uv 0.10) |

Les lockfiles npm ont été produits avec `--ignore-scripts`, dans un dossier à part,
puis copiés ici sans `node_modules/`. `vendor/local-lib/` (cible du `file:` de `npm/`
et `yarn1/`) est rangé dans `vendor/` exprès : ce dossier est écarté, il ne fait pas
un projet de plus ; `vendor/local-crate/` de `cargo/` de même, et `third_party/localmod/` de
`go/` (pas `vendor/` : pour `go`, un `vendor/` est celui de `go mod vendor`). Les `Cargo.lock` ont été
faits dans un dossier à part (cargo ne crée pas de `target/` pour résoudre) ; les `go.sum` aussi,
copiés sans le programme que `go build` laisse. Le `composer.lock` aussi (`--no-install` : ni
`vendor/` ni script lancé) ; `third_party/acme-tools/` est la cible de son dépôt `path`, écartée comme
`third_party/localmod/`. Le `Gemfile.lock` de `bundler/` a été fait dans un dossier à part, ses gems
et le cache de Bundler hors du dossier de l'utilisateur (`bundle lock` n'installe rien) ; ses versions
anciennes acceptent Ruby 4.0 (Bundler résout pour le Ruby qui tourne : minitest 5.26.1, pas 5.15).
Sous Windows, Yarn écrit `yarn.lock` en CRLF.

Ce dossier est rangé sous `tests/` : `forceupdate scan` sur forceupdate lui-même
l'écarte (voir E02 dans `PLAN.md`). Pour l'analyser, choisir un mini-projet
directement : `forceupdate scan tests/projects/uv`.
