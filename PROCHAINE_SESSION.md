# Session 22 — Étape E22 : Go

Contexte : E01 à E21 sont faites. Rust (crates.io) marche de bout en bout comme Python et npm :
parseurs (`workspace = true`, plateformes, renommages, membres et `exclude`), versions Cargo
(26 choix de cargo reproduits), index « sparse », failles OSV, réécriture de `Cargo.toml` (la
racine d'un workspace comme un catalogue pnpm), `Cargo.lock` régénéré par le vrai cargo (installé
à E21). 2377 tests Python verts (plus 11 réseau), 139 Vitest, 49 Playwright. E21 n'est pas
commitée : à proposer d'abord. Go est le deuxième écosystème de la phase F.

Lis CLAUDE.md, puis dans PLAN.md l'introduction de la phase F (et son paragraphe « Depuis E21 »),
les notes de E21 (le modèle le plus proche : ce qui a été vérifié en vrai, et comment) et l'étape
E22 ; `reference/README.md` (Go : `parse_go_mod`, `go.sum` ; limites : `// indirect` pas
distingué, `replace` ignoré, `go.sum` garde des versions plus utilisées) et leurs tests dans
`reference/argos_sca_parsers_tests.py` ; `docs/BRIEF.md` (décisions n°2, 3, 4, 11 et 12, « Versions
et fichiers » : pseudo-versions, `go.sum`, « Go, majeur ≥ 2 » ; « Sources de données » : le proxy
Go) ; puis le code de E21 qui sert de modèle : `parsers/rust.py`, `versions/cargo.py`,
`registries/crates.py`, `update/writers/rust.py`, le pilote `_Cargo` de `update/lockfiles.py`,
`tests/test_rust_projects.py`, et `detect/manifests.py` (`go.mod`, `go.sum` y sont ; `go.work`
non). Pas d'interface à toucher en principe : si un écran change, charger d'abord le skill
`ui-ux-pro-max`.

À faire :
- Parseurs : reprendre `parse_go_mod` et ses tests ; `require` (en ligne et en bloc) avec
  l'emplacement exact de chaque version, `// indirect` → `direct=False` ; `replace` vers un chemin
  local → non vérifiable, vers un autre module → c'est lui qu'on vérifie ; `exclude`, `retract` ;
  `go.sum` n'est plus une source de versions (depuis Go 1.17, `go.mod` liste les modules qu'il
  faut, à la version choisie : à vérifier) ; `go.work` et `go.work.sum` à reconnaître dans
  `detect/manifests.py` (workspaces Go, `use`).
- Versions Go : une `VersionScheme` (`v` devant, pseudo-versions `v0.0.0-20230101…-abcdef`
  comparées par date, `+incompatible`) dans `versions._SCHEMES`. Une version de `go.mod` est un
  minimum (sélection de version minimale), pas une plage : en tirer `satisfies`, `lower_bound`,
  `exact`, et les styles de `update/constraints.py`.
- Registre : `proxy.golang.org` (`/@v/list`, `/@latest`, chemins à majuscules encodées
  `!minuscule`) ; les `retract` et le `// Deprecated:` du `go.mod` de la dernière version
  (`/@v/<version>.mod`) ; 404 et 410 ; cache ; réponses enregistrées (`record.py`, `PACKAGES`).
- Failles : OSV `Go`, le nom est le chemin du module ; vérifier si OSV veut les versions avec
  ou sans `v` (ses avis Go les écrivent sans), et qu'un avis `GO-…` donne la bonne version
  corrigée ; `stdlib` et `toolchain` relèvent de E27.
- Changer de majeur (v2 et plus) change le chemin du module : proposé, jamais appliqué
  (`manual`, avec la raison).
- Réécriture de `go.mod` (`writers`) ; régénération : `go mod tidy` (`go.sum`, et les `require`
  que la sélection minimale fait monter), ou `go get <module>@<version>` (qui réécrit lui-même
  `go.mod` : à trancher). Un `LockKind` et son pilote.
- Un mini-projet `tests/projects/go` (et un workspace `go.work` s'il le faut) aux fichiers faits
  par le vrai `go` ; vérifier l'analyse et la mise à jour dans l'interface et en ligne de commande.

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E21 ; puis **`go` n'est pas installé** :
  l'installer (`winget install GoLang.Go`, quelques minutes) pour faire `go.sum` et vérifier
  `go mod tidy` / `go get` en vrai, ou simuler la commande (la phase F le permet, « et c'est
  noté ») ; sans `go`, les fichiers des mini-projets doivent venir d'un vrai projet public, jamais
  écrits à la main.
- **Vérifier en vrai**, comme à E21 pour cargo : ce que garde `go mod tidy` d'une version écrite à
  la main, s'il touche à la directive `go` ou `toolchain`, ce qu'il télécharge ; **la directive
  `toolchain` (et `GOTOOLCHAIN`) fait télécharger et lancer une autre version de Go**, comme
  `rust-toolchain.toml` pour rustup (E21) : la neutraliser (`GOTOOLCHAIN=local` ?) ou le dire
  dans le plan ; `GOFLAGS`, `GOPROXY`, `GOPRIVATE` hérités de l'environnement ; un module privé
  (404/410 du proxy) ; `go` lance-t-il du code du projet (`go generate` non, les directives
  `tool` ?). Le simulé doit répondre comme le vrai.
- Les tests qui prenaient Go pour « pas encore géré » (`test_checks_vulns.py`, `test_cli.py`,
  `test_lockfiles.py`, `test_parsers_python.py`, `test_registries.py`) : les passer à Packagist.
- cargo est dans `~/.cargo/bin`, hors du `PATH` des outils : `export PATH="$HOME/.cargo/bin:$PATH"`
  pour les tests `network` de Rust (CLAUDE.md) ; `go` sera sans doute dans `C:\Program Files\Go\bin`,
  à vérifier de même.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil de lockfile (`FakeTools`),
  jamais le cache de l'utilisateur ; `reference/` n'est jamais importé par `src/` ; on ne modifie
  pas `reference/` (copier, adapter, reprendre les tests). Ré-enregistrer OSV (`record.py osv`)
  réécrit le texte des avis déjà là : remettre ceux dont le contenu n'a pas changé (E21).
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : écrire les scripts dans le scratchpad avec l'outil d'écriture (un heredoc abîme les
  accents et les `\\`, encore vu à E21) ; jamais `node -e "…"` avec des accents graves ; un argument
  qui commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1`. Pour piloter la vraie interface, un
  script Playwright en `.cjs` dans le scratchpad, qui `require` le Playwright de
  `frontend/node_modules` (fait à E21).

Fini quand : sur un mini-projet Go, l'analyse et la mise à jour donnent un résultat juste, dans
l'interface et en ligne de commande (si `go` n'est pas installé, la régénération est testée avec
une commande simulée, et c'est noté). Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` ; à la main, `uv run forceupdate scan` et `update` sur une copie du mini-projet
dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
