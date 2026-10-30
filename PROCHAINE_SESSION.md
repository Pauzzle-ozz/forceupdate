# Session 23 — Étape E23 : PHP (Composer)

Contexte : E01 à E22 sont faites. Go marche de bout en bout comme Python, npm et Rust : `go.mod`
et `go.work` lus par un lexer comme celui de `modfile` (`// indirect`, `replace`, `exclude`,
`retract`), versions Go (pseudo-versions, `+incompatible`, chemins de majeure), proxy Go
(retraits et dépréciation du `go.mod` de la dernière, majeure suivante sous son chemin), failles
OSV, réécriture de `go.mod`, `go mod tidy` par le vrai `go` (installé à E22, dans `~/sdk`). 2551
tests Python verts (plus 13 réseau), 141 Vitest, 49 Playwright. E22 n'est pas commitée : à
proposer d'abord. PHP est le troisième écosystème de la phase F.

Lis CLAUDE.md, puis dans PLAN.md l'introduction de la phase F (et ses paragraphes « Depuis E21 »
et « Depuis E22 » : les points d'extension `written`, `unlisted`, `moved`, `not_found_statuses`,
`_complete`, `Dependency.excluded`, `_versions_path`), les notes de E22 et de E21 (ce qui a été
vérifié en vrai, et comment) et l'étape E23 ; `reference/README.md` (PHP : `parse_composer_json`,
`parse_composer_lock` ; limite : tout est `pinned=True` dans `composer.lock`, branches comprises)
et leurs tests dans `reference/argos_sca_parsers_tests.py` ; `docs/BRIEF.md` (décisions n°2, 3,
4, 11 et 12 ; « Versions et fichiers » ; « Sources de données » : Packagist `p2`) ; puis le code
de E21 et E22 qui sert de modèle : `parsers/rust.py` et `parsers/go.py`, `versions/cargo.py` et
`versions/go.py`, `registries/crates.py` et `registries/goproxy.py`, `update/writers/rust.py`,
les pilotes `_Cargo` et `_Go` de `update/lockfiles.py`, `tests/test_rust_projects.py` et
`tests/test_go_projects.py`. Pas d'interface à toucher en principe : si un écran change, charger
d'abord le skill `ui-ux-pro-max` (fait à E22 pour deux libellés de l'écran 5).

À faire :
- Parseurs : reprendre `parse_composer_json`, `parse_composer_lock` et leurs tests ; `require` et
  `require-dev` (scope `dev`) avec l'emplacement exact de chaque contrainte (`json_spans.py`) ;
  `dev-master`, `dev-…` et autres branches, `*@dev` : non vérifiables ; `php`, `ext-*`, `lib-*`,
  `composer-plugin-api` mis de côté (E27 pour PHP) ; `replace`, `provide`, `conflict` ;
  `repositories` (`path`, `vcs`, un autre dépôt Composer : non vérifiables) ; `composer.lock`
  (`packages`, `packages-dev`, la version installée, `source`/`dist`), lié au `composer.json` ; les
  dépendances d'un paquet figé (`require`) pour le graphe des transitives.
- Versions Composer : une `VersionScheme` (`v` toléré, quatre nombres possibles, stabilités
  `-alpha`, `-beta`, `-RC`, `-patch`/`-p`, `-dev` et leur ordre) dans `versions._SCHEMES` ; les
  contraintes : `^`, `~` (« prochaine version significative » : `~1.2` veut dire `>=1.2,<2.0`,
  pas comme npm), `||` et `|`, `-` (intervalle), `*` et `1.2.*`, espaces et virgules (ET),
  `@dev`/`@beta` (stabilité), `minimum-stability` et `prefer-stable` du `composer.json` ; en tirer
  `satisfies`, `lower_bound`, `exact`, et les styles de `update/constraints.py` (opérateurs,
  séparateurs, un tableau de cas).
- Registre : Packagist `p2` (`https://repo.packagist.org/p2/{vendor}/{paquet}.json`, et
  `~dev.json` pour les branches) ; le format « minifié » (chaque version ne garde que ce qui
  change) à reconstruire ; `abandoned` (`true` ou le paquet de remplacement) → constat
  « déprécié » ; `time` ; 404 ; cache ; réponses enregistrées (`record.py`, `PACKAGES`).
- Failles : OSV `Packagist`, le nom est `vendor/paquet` (en minuscules ?) ; vérifier qu'un avis
  donne la bonne version corrigée (et si ses versions ont un `v`).
- Réécriture de `composer.json` (`writers`) ; régénération : `composer update <nom>
  --no-install --no-scripts --no-plugins` (ou `--lock` seul : à vérifier), et l'épinglage le temps
  d'un passage si Composer ignore la version visée (comme npm, Cargo) ; `--with`
  (`composer update x --with x:1.2.3`) à essayer. Un `LockKind` et son pilote.
- Un mini-projet `tests/projects/composer` aux fichiers faits par le vrai Composer ; vérifier
  l'analyse et la mise à jour dans l'interface et en ligne de commande.

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E22 ; puis **ni PHP ni Composer ne sont
  installés** : les installer pour faire `composer.lock` et vérifier `composer update` en vrai,
  ou simuler la commande (la phase F le permet, « et c'est noté ») ; sans eux, les fichiers du
  mini-projet doivent venir d'un vrai projet public, jamais écrits à la main. À E22, `winget` a
  échoué (code 1618 : une autre installation Windows en cours) : l'archive officielle, vérifiée
  par sa somme SHA-256 et dépliée dans `~/sdk`, a fait l'affaire (PHP : windows.php.net ;
  Composer : le `composer.phar` de getcomposer.org et sa somme, pas `composer-setup.php`).
- **Vérifier en vrai**, comme à E21 et E22 : ce que garde `composer update` d'une version écrite
  à la main, s'il sait viser une version sans toucher au manifeste, ce qu'il réécrit de
  `composer.json` (il peut le reformater) ; **Composer exécute du code du projet** : les plugins
  (`--no-plugins`), les scripts (`--no-scripts`), et les plugins déjà autorisés
  (`config.allow-plugins`) ; `config.platform` (la version de PHP visée) ; `COMPOSER_*` hérités
  de l'environnement (`COMPOSER_HOME`, `COMPOSER_AUTH`, `COMPOSER_ALLOW_SUPERUSER`) ; un dépôt
  privé (`repositories`, `auth.json`). Le simulé doit répondre comme le vrai.
- Les tests qui prenaient Packagist pour « pas encore géré » (`test_checks_vulns.py`,
  `test_cli.py`, `test_lockfiles.py`, `test_parsers_python.py`, `test_registries.py`,
  `test_versions.py`) : les passer à RubyGems (`Gemfile`, `Gemfile.lock`).
- `go` est dans `~/sdk/go1.27.3/bin` et cargo dans `~/.cargo/bin`, hors du `PATH` des outils :
  `export PATH="$HOME/sdk/go1.27.3/bin:$HOME/.cargo/bin:$PATH"` pour les tests `network` (CLAUDE.md).
- Les tests : jamais le réseau sans `network`, jamais un vrai outil de lockfile (`FakeTools`),
  jamais le cache de l'utilisateur ; `reference/` n'est jamais importé par `src/` ; on ne modifie
  pas `reference/` (copier, adapter, reprendre les tests). Ré-enregistrer OSV (`record.py osv`)
  réécrit le texte des avis déjà là : remettre ceux dont le contenu lu n'a pas changé (un script
  qui compare `parse_vuln` avant et après l'a fait à E22 : 33 remis).
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : écrire les scripts Python dans le scratchpad avec l'outil d'écriture (un heredoc
  passé à Python abîme les accents et réduit `\\` à `\`, encore vu à E22) ; jamais `node -e "…"`
  avec des accents graves ; un argument qui commence par `/` sous Git Bash :
  `MSYS_NO_PATHCONV=1`. Pour piloter la vraie interface, un script Playwright en `.cjs` dans le
  scratchpad, qui `require` le Playwright de `frontend/node_modules` (fait à E21 et E22 :
  `ui --no-browser` en arrière-plan, l'adresse lue dans sa sortie).

Fini quand : sur un mini-projet PHP, l'analyse et la mise à jour donnent un résultat juste, dans
l'interface et en ligne de commande (si Composer n'est pas installé, la régénération est testée
avec une commande simulée, et c'est noté). Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run
lint`, `npm run test:e2e` ; à la main, `uv run forceupdate scan` et `update` sur une copie du
mini-projet dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
