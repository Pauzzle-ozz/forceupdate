# Session 33 — Étape E33 : Registres et dépôts privés

Contexte : E01 à E32 sont faites. E32 (mise à jour : le npm du projet, Python, NuGet, Go) a fait
`update/project_npm.py` (le npm qu'attend le projet : `packageManager`, `devEngines`, `engines`, le
plus ancien Node choisi, la CI ; régénéré par `npx -y npm@10`, case cochée d'office, relu par
`npm ci --dry-run`), la CI lue comme un runtime (`parsers/runtimes.py` : workflows de GitHub,
`.gitlab-ci.yml`, `bitbucket-pipelines.yml`), les `requirements.txt` générés sans `.in` traités en
lockfiles (et refaits après le leur), `Dependency.manual` pour une ligne à `--hash`, l'indirecte
NuGet ajoutée au projet (`EditKind.REFERENCE`, une réécriture qui insère), `go mod vendor` (case
cochée d'office, `vendor/` remis sur un échec), Composer 2.9 dit dans le plan, et le message d'une
version forcée npm par référence (`$x`). Détail et décisions dans les notes de E32.
4 864 tests Python verts (plus 23 réseau), 167 Vitest, 72 Playwright.
**E32 n'est pas commitée : à proposer d'abord.**

Lis CLAUDE.md, puis l'étape E33 de PLAN.md (toutes ses cases), et ce qu'elle cite : les notes de
E22 (Go : `GOPRIVATE`, le proxy, OSV), de E23 (Composer : les dépôts de `repositories`, `auth.json`,
`COMPOSER_AUTH`), de E25 (Maven et Gradle : les dépôts déclarés), de E26 (NuGet : `nuget.config`,
l'API « registration »), de E28 (uv : `[tool.uv] index` d'un script), et de E06 (le client HTTP,
le cache, « une requête par paquet et par session »). Puis le code qui sert de modèle :
`registries/` (un client par registre, `PackageInfo`), `net/http.py` (`HttpClient`, l'hôte
injoignable abandonné), `net/cache.py`, `advisories/osv.py` (ce qui part chez OSV), `engine.check`
(qui demande quoi, à quel registre), `parsers/npm.py`, `parsers/go.py`, `parsers/php.py`,
`parsers/maven.py`, `parsers/gradle.py`, `parsers/nuget.py`, `parsers/python.py` (les index).

À faire :
- Go : un module privé (`GOPRIVATE`, `GONOPROXY`, de l'environnement et de `go env -w`) n'est
  demandé ni au proxy public ni à OSV : « module privé : non vérifié », comme `go` ; npm : un
  paquet d'un registre privé (`.npmrc`, `@scope:registry`) de même, ou demandé à ce registre ;
- Composer : un dépôt `composer` de `repositories` (Satis, Private Packagist) : ses paquets
  demandés à ce dépôt (son `packages.json`, `metadata-url`), avec `auth.json` ;
- Maven et Gradle : les dépôts déclarés (`<repositories>`, miroirs de `~/.m2/settings.xml`,
  `repositories { }`) lus, avec leurs identifiants ;
- NuGet : les sources de `nuget.config` et leurs identifiants, pour les versions publiées ;
- Python : `[tool.uv] index` d'un script ; `[[tool.uv.index]]` d'un projet, `--index-url` d'un
  `requirements` (à vérifier).

Attention :
- **Demander à l'utilisateur** d'abord le commit de E32 (message « E32 : mise à jour : le npm du
  projet, Python, NuGet, Go », un résumé comme pour E30 et E31).
- **Lui demander aussi** comment traiter les identifiants des registres privés : les lire dans les
  fichiers de la personne (`.npmrc`, `auth.json`, `settings.xml`, `nuget.config`, `netrc`…) et les
  envoyer à ce registre seul, ou s'en tenir à « privé : non vérifié » sans jamais rien lire. C'est
  une décision de sécurité (un token qui partirait ailleurs, ou dans un log) : ne pas la prendre
  seul. Quoi qu'il décide : jamais un identifiant dans le cache, un rapport, l'API, ni le
  navigateur ; jamais un paquet privé demandé au registre public (un homonyme serait une attaque
  par confusion de dépendances).
- Vérifier en vrai avant d'écrire : `go env GOPRIVATE`, `go env -w` (le fichier `GOENV`), ce que
  fait le proxy pour un module privé ; `npm config get @scope:registry`, la forme de `.npmrc` ; un
  dépôt `composer` (un `packages.json` servi en local suffit) ; `nuget.config` et `dotnet nuget list
  source` ; uv et ses index (`uv lock` avec `[[tool.uv.index]]`). Maven et Gradle ne sont pas
  installés (choix de l'utilisateur) : lire les formats d'après leur documentation, le dire.
  Toujours dans le scratchpad, jamais dans `tests/projects/`.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil, ni le cache, le trousseau, les
  réglages ou le dossier temporaire de la personne (huit garde-fous de `conftest.py`) ; **les
  fichiers de configuration de la personne** (`~/.npmrc`, `~/.m2/settings.xml`, le `nuget.config`
  de son profil, `auth.json` de `COMPOSER_HOME`, le fichier `GOENV`) ne doivent jamais être lus par
  un test : un neuvième garde-fou s'il en faut un. Un registre privé se simule (respx).
- E32 a rendu la CI « runtime » du projet : une CI en Node 18 écarte maintenant les versions qui
  demandent Node 20 ; si un test de E33 en est surpris, c'est voulu (notes de E32).
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc (il mange
  les barres obliques inverses) ; `python -I` ignore `PYTHONIOENCODING` (`-X utf8`) ; un argument
  qui commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1` ; une suppression : un chemin écrit en
  entier (le contrôle de l'outil refuse `rm -rf "$VAR/x"`, et tout `rm -rf` d'un lecteur).
- Si l'interface change (« privé : non vérifié » dans le rapport), charger d'abord le skill
  `ui-ux-pro-max` et lire `design-system/MASTER.md` et l'écran concerné.

Fini quand : pour chaque écosystème, un paquet d'un registre privé déclaré est demandé à ce
registre (testé avec un registre simulé), ou dit « privé : non vérifié » ; jamais au registre
public. Vérifier avec : `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans
`frontend/` : `npm test`, `npm run typecheck`, `npm run lint`, `npm run test:e2e`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
