# Session 34 — Étape E34 : Compléments d'analyse

Contexte : E01 à E33 sont faites. E33 (registres et dépôts privés) a fait `routing/` (à quel
registre demander chaque paquet : le public, un miroir, des registres en plus, ou celui d'un paquet
privé par son nom, jamais demandé au public ni à OSV ; npm et `.yarnrc.yml`, Go, Composer, NuGet,
Python, Maven et Gradle, la source globale d'un `Gemfile`), `net/auth.py` (un identifiant lié à son
adresse, jamais ailleurs), `userfiles.py` (les fichiers de la personne) et le neuvième garde-fou des
tests (`user_files`). Décision de l'utilisateur, docs/BRIEF.md n° 24. Détail dans les notes de E33.
4 987 tests Python verts (plus 23 réseau), 167 Vitest, 72 Playwright.
**E33 n'est pas commitée : à proposer d'abord.**

Lis CLAUDE.md, puis l'étape E34 de PLAN.md (toutes ses cases), et les notes qu'elle cite : E21
(Rust), E22 (Go), E23 (PHP), E24 (Ruby), E25 (Java), E26 (.NET), E27 (fins de vie), E28 (fichier de
code isolé), E32 (la CI comme runtime), E33 (registres privés : les règles des identifiants).

**E34 est grosse** (sept cases, une vingtaine de points, huit écosystèmes) : **proposer d'abord à
l'utilisateur de la découper**, comme E29 l'a été en cinq étapes, par exemple : Ruby et Rust privés
avec les autres cases Rust, Go et PHP ; Java et .NET ; fins de vie et fichiers de code. La
documentation (E35) et la recette (E36) seraient décalées d'autant. Ne pas découper seul ; une
session = une étape.

À faire (les cases de E34) :
- depuis E33 : Ruby (la source globale d'un `Gemfile` et ses blocs `source … do` : l'index compact
  du serveur, avec les identifiants de Bundler) ; Rust (`registry = "…"` : `.cargo/config.toml`,
  `[registries]`, l'index « sparse », `credentials.toml`) ;
- depuis E21 (Rust) : le `rust-version` des versions (résolveur 3) ;
- depuis E22 (Go) : la version construite dans un workspace `go.work` ; la majeure suivante d'un
  module à `+incompatible` ;
- depuis E23 (PHP) : les avis de Packagist (FriendsOfPHP) réunis à ceux d'OSV ; `prefer-stable` et
  `minimum-stability` ;
- depuis E25 (Java) : le `pom` d'un parent ou d'un BOM distant ; `<relocation>` ; `gradle.lockfile` ;
  `settings.gradle(.kts)`, `buildSrc`, les versions riches ; la version corrigée de la variante
  utilisée (Guava `-jre`) ;
- depuis E26 (.NET) : `Directory.Build.targets` (`PackageReference Update=`) ;
- depuis E27 : ce qui n'est pas lu (images non officielles, `mise.toml`, `required_ruby_version`…),
  les tests `network` des tables tenues à la main (produits d'endoflife.date, LTS de Node,
  `NODE_NPM`), les autres `actions/setup-*` des workflows ;
- depuis E28 : Deno (`npm:`, `jsr:`), `tsconfig.json` (`paths`), `.ipynb`, `.vue`, `.svelte`,
  `importlib`, un paquet d'espace de noms local, `exclude-newer`, le test `network` de
  `IMPORT_PACKAGES`.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E33 (message « E33 : registres et dépôts
  privés », un résumé comme pour E31 et E32), puis le découpage de E34.
- Les registres privés de Ruby et de Rust suivent les règles de E33 (BRIEF n° 24) : les
  identifiants de Bundler (`BUNDLE_<HÔTE>`, `~/.bundle/config`) sont liés à leur hôte ; ceux de
  Cargo (`credentials.toml`) à un *nom* de registre : seulement vers l'adresse qu'un fichier de la
  personne donne à ce nom. Un nouveau fichier de la personne passe par `userfiles` (le garde-fou
  des tests le couvre alors) ; un module de `routing/` par écosystème.
- Vérifier en vrai avant d'écrire : Bundler 4.0.20 (`bundle config`, un serveur de gems local à
  index compact), cargo (un registre « sparse » local : `config.json` et l'index), `composer audit`
  contre OSV, le SDK .NET (`Directory.Build.targets`), endoflife.date ; Maven et Gradle ne sont pas
  installés (choix de l'utilisateur) : d'après leur documentation, le dire. Toujours dans le
  scratchpad, jamais dans `tests/projects/` ; pour un essai qui lit des fichiers de la personne, un
  dossier personnel factice (`USERPROFILE`, `HOME`, `APPDATA`, voir CLAUDE.md).
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc ni par
  `python -c` avec des `\n` dans une chaîne (l'outil Bash les transforme) ; `python -I -X utf8`.
- Si l'interface change (une dépréciation par `<relocation>`, par exemple), charger d'abord le
  skill `ui-ux-pro-max` et lire `design-system/MASTER.md` et l'écran concerné.

Fini quand : chaque case de l'étape (telle que découpée avec l'utilisateur) a ses tests et a été
vérifiée en vrai ; les limites qui restent sont écrites, pour la documentation. Vérifier avec :
`uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
