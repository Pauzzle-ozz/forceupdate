# Session 21 — Étape E21 : Rust (crates.io)

Contexte : E01 à E20 sont faites ; la phase E (forges) est finie. GitHub, GitLab (et ses instances)
et Bitbucket Cloud marchent de bout en bout : connexion (OAuth, token collé), dépôts analysés sans
les cloner, une PR (MR) par dépôt, idempotente, lots et récapitulatifs à plusieurs forges.
Vérifié avec le vrai compte sur `pauzzle/forceupdate-demo` (Bitbucket) : PR #1 ouverte, relancée
sans rien pousser, puis refaite sur un `main` avancé. 2114 tests Python verts (plus 9 réseau),
138 Vitest, 49 Playwright. E20 n'est pas commitée : à proposer d'abord. La phase F commence :
Rust, le premier des six autres écosystèmes, de bout en bout comme Python et npm.

Lis CLAUDE.md, puis dans PLAN.md l'introduction de la phase F (ce que chaque écosystème doit faire,
et ce qui est vérifié) et l'étape E21 ; `reference/README.md` (Rust : `parse_cargo_toml`,
`parse_cargo_lock`, leurs limites : `workspace = true` donne une version vide) et leurs tests dans
`reference/argos_sca_parsers_tests.py` ; `docs/BRIEF.md` (décisions n°2, 3, 4, 11 et 12, « Versions
et fichiers » dans les pièges, crates.io dans « Sources de données » : User-Agent exigé, 1 requête
par seconde sur l'API, l'index « sparse ») ; puis le code qui sert de modèle, écosystème par
écosystème : `parsers/python.py` et `parsers/npm.py` (dépendances directes avec emplacement exact,
lockfiles en graphe de nœuds), `parsers/toml_spans.py` (positions dans un TOML),
`parsers/lockfiles.py` (lien manifeste ↔ lockfile), `detect/manifests.py` (`Cargo.toml` et
`Cargo.lock` y sont déjà, workspaces compris), `versions/` (`VersionScheme`, `pypi.py`, `npm.py`,
`_SCHEMES`), `registries/` (PyPI, npm), `checks/vulns.py` (`version_to_check`),
`update/constraints.py`, `update/writers/`, `update/lockfiles.py` (un `LockKind` et son pilote,
`_RUNS_CODE`), et `tests/projects/` (les mini-projets, leurs lockfiles faits par les vrais outils).
Pas d'interface à toucher en principe (l'écosystème s'y affiche déjà par son nom) : si un écran
change, charger d'abord le skill `ui-ux-pro-max`.

À faire :
- Parseurs : reprendre `parse_cargo_toml`, `parse_cargo_lock` et leurs tests ; corriger
  `workspace = true` (version lue dans `[workspace.dependencies]` à la racine :
  `Dependency.resolved_constraint`, comme `catalog:` de pnpm), `[target.'…'.dependencies]`, les
  dépendances renommées (`package = "…"`), `git` / `path` (non vérifiables), les membres de
  workspace (`[workspace] members` / `exclude` ; E02 rattache déjà le `Cargo.lock` du parent le plus
  proche) ; chaque contrainte avec son emplacement exact (`toml_spans`) ; les scopes (dev, build).
- Versions Cargo : une `VersionScheme` (`1.2` veut dire `^1.2`, `^` en 0.x comme npm, `=`, `~`,
  `*`, plusieurs bornes séparées par des virgules ; pré-versions semver), ajoutée à
  `versions._SCHEMES`.
- Registre : l'index « sparse » (`https://index.crates.io/…`, une ligne JSON par version, `yanked`)
  plutôt que l'API (1 requête par seconde) ; User-Agent ; cache ; réponses enregistrées dans
  `tests/fixtures/` (`record.py`, `PACKAGES`).
- Failles : vérifier le nom qu'OSV attend (`crates.io`) et la version corrigée d'un avis Rust.
- Mise à jour : les styles de contrainte de Cargo dans `update/constraints.py` (avec un tableau de
  cas), la réécriture de `Cargo.toml` (`writers`), et le lockfile par
  `cargo update -p <nom> --precise <version>` (sans scripts : `build.rs` ne tourne pas à
  `cargo update`, à vérifier ; `_RUNS_CODE` sinon).
- Un mini-projet `tests/projects/cargo` (et un workspace) au `Cargo.lock` fait par le vrai cargo ;
  vérifier l'analyse et la mise à jour dans l'interface et en ligne de commande.

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E20 ; puis **cargo n'est pas installé** sur la
  machine (ni `rustc`) : l'installer (rustup, quelques minutes) pour faire les `Cargo.lock` des
  mini-projets et vérifier `cargo update --precise` en vrai, ou simuler la commande (la phase F le
  permet, « et c'est noté ») ; sans cargo, les lockfiles des mini-projets doivent venir d'ailleurs
  (un vrai projet public), jamais écrits à la main.
- **Vérifier en vrai** : l'index sparse (format d'une ligne, `yanked`, noms en minuscules et leur
  chemin `1/`, `2/`, `3/a/`, `ab/cd/`), une contrainte Cargo contre l'outil (la version que choisit
  cargo est la référence, comme `npm-pick-manifest` pour npm à E07) ; le simulé doit répondre comme
  le vrai.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil de lockfile (`FakeTools`),
  jamais le cache de l'utilisateur ; `reference/` n'est jamais importé par `src/` ; on ne modifie
  pas `reference/` (copier, adapter, reprendre les tests).
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : écrire les scripts dans le scratchpad avec l'outil d'écriture (un heredoc abîme les
  accents et les `\\`) ; jamais `node -e "…"` avec des accents graves ; un argument qui commence par
  `/` sous Git Bash : `MSYS_NO_PATHCONV=1`.

Fini quand : sur un mini-projet Cargo, l'analyse et la mise à jour donnent un résultat juste,
dans l'interface et en ligne de commande (si cargo n'est pas installé, la régénération du
lockfile est testée avec une commande simulée, et c'est noté). Vérifier avec : `uv run pytest`,
`uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; à la main, `uv run forceupdate scan` et
`update` sur une copie du mini-projet dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
