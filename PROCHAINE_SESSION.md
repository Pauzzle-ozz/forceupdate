# Session 24 — Étape E24 : Ruby (Bundler)

Contexte : E01 à E23 sont faites. PHP marche de bout en bout comme Python, npm, Rust et Go :
`composer.json` et `composer.lock` lus (branches, dépôts `path`, `replace`, `conflict`), versions
Composer réécrites d'après composer/semver (aucun écart sur 1 282 versions et 99 contraintes, 22
choix de `composer update` reproduits), Packagist `p2` (minifié, `abandoned`), OSV `Packagist`,
réécriture de `composer.json`, `composer update x:V… -W --no-install --no-scripts --no-plugins` par
le vrai Composer (installé à E23, dans `~/sdk`). 2838 tests Python verts (plus 15 réseau), 141
Vitest, 49 Playwright. E23 n'est pas commitée : à proposer d'abord. Ruby est le quatrième
écosystème de la phase F.

Lis CLAUDE.md, puis dans PLAN.md l'introduction de la phase F (et ses paragraphes « Depuis E21 »,
« Depuis E22 » et « Depuis E23 » : `written`, `unlisted`, `moved`, `not_found_statuses`,
`_complete`, `Dependency.excluded` qui tient des contraintes, `is_excluded`, `_versions_path`), les
notes de E23 et de E22 (ce qui a été vérifié en vrai, et comment : un oracle lancé par l'outil
lui-même, des témoins pour ce que l'outil exécute) et l'étape E24 ; `reference/README.md` (Ruby :
`parse_gemfile_lock` ; `Gemfile` repéré mais pas lu) et ses tests dans
`reference/argos_sca_parsers_tests.py` ; `docs/BRIEF.md` (décisions n°2, 3, 4, 11 et 12 ;
« Versions et fichiers », dont « Régénérer un lockfile peut exécuter du code du projet » : le
`Gemfile` est du Ruby ; « Sources de données » : RubyGems) ; puis le code de E23 qui sert de modèle :
`parsers/php.py`, `versions/composer.py`, `registries/packagist.py`, `update/writers/php.py`, le
pilote `_Composer` de `update/lockfiles.py`, `tests/test_php_projects.py` et
`tests/test_versions_composer.py`. Pas d'interface à toucher en principe : si un écran change,
charger d'abord le skill `ui-ux-pro-max`.

À faire :
- Parseurs : reprendre `parse_gemfile_lock` et ses tests (`GEM` / `specs:`, les dépendances de
  chaque gem pour le graphe, `GIT` et `PATH` : non vérifiables, `PLATFORMS`, `DEPENDENCIES` (le `!`
  d'une source à part), `BUNDLED WITH`, les versions à plateforme `nokogiri (1.16.0-x86_64-linux)`) ;
  ajouter le `Gemfile`, lu par motifs sans l'exécuter : `gem "nom", "~> 1.2", ">= 1.2.3"` (plusieurs
  contraintes), `group :development, :test do … end` et `group:` en option (scope `dev`),
  `require: false`, `git:`, `github:`, `path:` (non vérifiables), `source "…" do … end` (un autre
  serveur), `platforms`, `gemspec` (les dépendances du `.gemspec`, `add_dependency` et
  `add_development_dependency`), `eval_gemfile` (une remarque), et l'emplacement exact de chaque
  contrainte ; ce qui n'est pas lisible par motifs (une variable, une condition) : une remarque, pas
  une erreur.
- Versions RubyGems : une `VersionScheme` (`Gem::Version` : segments, `.pre`, `.rc1`, `1.0.a`, une
  lettre fait une pré-version, `1.0` égale `1.0.0`) et les contraintes (`~>` : `~> 1.2` veut dire
  `>= 1.2, < 2.0`, `~> 1.2.3` veut dire `>= 1.2.3, < 1.3`, `=`, `!=`, `>`, `<`, plusieurs
  contraintes en ET) ; `satisfies`, `lower_bound`, `exact`, les styles de `update/constraints.py`
  (`~>` ressemble à `~=` : un tableau de cas). Vérifier contre le vrai `Gem::Version` et
  `Gem::Requirement` (un oracle lancé par Ruby, comme composer/semver à E23).
- Registre : RubyGems (`/api/v1/versions/{nom}.json` : `number`, `prerelease`, `created_at`,
  `platform` ; les versions retirées, « yanked », y sont-elles ?) ; un paquet inconnu ; le cache ;
  réponses enregistrées (`record.py`, `PACKAGES`).
- Failles : OSV `RubyGems`, vérifier le nom et la version corrigée d'un avis (versions à plateforme).
- Réécriture du `Gemfile` (`writers`) ; régénération : `bundle lock --update <nom>` (garde-t-il les
  autres ? sait-il viser une version, `--conservative`, `--patch`/`--minor`, ou faut-il épingler
  le temps d'un passage comme npm et Cargo ?). Un `LockKind` et son pilote. Bundler **évalue le
  `Gemfile`** (du Ruby du projet) : le dire dans le plan (`_RUNS_CODE`), et voir ce qu'il exécute
  d'autre (plugins de Bundler, `.bundle/config`, `BUNDLE_*` hérités de l'environnement).
- Un mini-projet `tests/projects/bundler` aux fichiers faits par le vrai Bundler ; vérifier l'analyse
  et la mise à jour dans l'interface et en ligne de commande.

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E23 ; puis **ni Ruby ni Bundler ne sont
  installés** : les installer pour faire `Gemfile.lock` et vérifier `bundle lock` en vrai, ou simuler
  la commande (la phase F le permet, « et c'est noté ») ; sans eux, les fichiers du mini-projet
  doivent venir d'un vrai projet public, jamais écrits à la main. À E22 et E23, l'archive officielle
  vérifiée par sa somme SHA-256 et dépliée dans `~/sdk` a fait l'affaire (winget avait échoué : code
  1618). Pour Ruby sous Windows : RubyInstaller (rubyinstaller.org, l'archive 7z « without devkit »
  et sa somme) ; Bundler vient avec Ruby.
- **Vérifier en vrai**, comme à E21-E23 : ce que garde `bundle lock --update x` d'une version écrite à
  la main, s'il sait viser une version sans toucher au `Gemfile`, ce qu'il réécrit (`Gemfile.lock`
  seulement ?), ce qu'il exécute (le `Gemfile` est évalué : un témoin qui écrit un fichier le
  montrera), `BUNDLE_GEMFILE`, `BUNDLE_FROZEN`, `BUNDLE_DEPLOYMENT` hérités, les plateformes
  (`bundle lock --add-platform`) ; le simulé doit répondre comme le vrai.
- Les tests qui prenaient RubyGems pour « pas encore géré » (`test_checks_vulns.py`, `test_cli.py`,
  `test_lockfiles.py`, `test_parsers_python.py`, `test_registries.py`, `test_versions.py`) : les passer
  à Maven (`pom.xml`).
- `go` (`~/sdk/go1.27.3/bin`), cargo (`~/.cargo/bin`), PHP et Composer (`~/sdk/php-8.5.12`,
  `~/sdk/composer-2.11.0`) sont hors du `PATH` des outils : la ligne de CLAUDE.md pour les tests
  `network`.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil de lockfile (`FakeTools`),
  jamais le cache de l'utilisateur ; `reference/` n'est jamais importé par `src/` ; on ne modifie
  pas `reference/` (copier, adapter, reprendre les tests). Pour OSV, n'ajouter à `queries.json` que
  les versions du nouveau mini-projet (fait à E23 par un script : la requête de `record.py osv` pour
  ce projet seul), pour ne rien changer aux autres.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : écrire les scripts dans le scratchpad avec l'outil d'écriture (un heredoc a encore cassé à
  E23) ; jamais `node -e "…"` avec des accents graves ; un argument qui commence par `/` sous Git
  Bash : `MSYS_NO_PATHCONV=1`. Pour piloter la vraie interface : un script Playwright en `.cjs` dans
  le scratchpad, qui `require` le Playwright de `frontend/node_modules` (fait à E21-E23 : `ui
  --no-browser` en arrière-plan, l'adresse lue dans sa sortie) ; attendre le titre exact du rapport
  (`exact: true`), sinon celui de la progression (« Analyse de … ») répond d'abord.

Fini quand : sur un mini-projet Ruby, l'analyse et la mise à jour donnent un résultat juste, dans
l'interface et en ligne de commande (si Bundler n'est pas installé, la régénération est testée avec
une commande simulée, et c'est noté). Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` ; à la main, `uv run forceupdate scan` et `update` sur une copie du mini-projet
dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
