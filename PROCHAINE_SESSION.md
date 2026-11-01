# Session 27 — Étape E27 : Fin de vie des runtimes et frameworks

Contexte : E01 à E26 sont faites ; la phase F est finie, les huit écosystèmes sont gérés en analyse
et en mise à jour, dans l'interface et en ligne de commande. E26 a ajouté .NET : `versions/nuget.py`
(NuGet.Versioning 7.9.0 réécrit, aucun écart sur 17 866 versions et 30 189 vérifications), les
projets MSBuild, `Directory.Build.props`, la gestion centrale, `packages.config`,
`packages.lock.json`, l'API « registration » de nuget.org, le pilote `dotnet restore` (vérifié avec
le SDK .NET 10.0.403) ; NuGet prend la plus basse version qui convient (`VersionScheme.lowest`,
`reaches`, `chosen`). 4268 tests Python verts (plus 20 réseau), 141 Vitest, 49 Playwright. **E26
n'est pas commitée : à proposer d'abord.** E27 ajoute le type 3 du brief : la fin de vie.

Lis CLAUDE.md, puis l'étape E27 de PLAN.md (et ses cases « Depuis E23 », « Depuis E24 »,
« Depuis E26 »), les notes de E26 et de E25 (comment un comportement a été vérifié en vrai avant
d'être écrit), et `docs/BRIEF.md` : décisions n°1, 2, 8 et 12, le tableau « Ce que « besoin de mise
à jour » veut dire » (type 3), « Sources de données » (endoflife.date). Puis le code qui sert de
modèle : `checks/` (`deprecated.py`, `outdated.py`, `base.py`, `priority.py`), `models.py`
(`FindingKind.EOL`, `Finding.dependency` à `None` pour un runtime), `engine.check`, un client de
registre (`registries/base.py`, `registries/packagist.py`) et le cache (`net/cache.py`, ses
`CacheKind`) ; `report/` (terminal, JSON, Markdown) et `docs/JSON_FORMAT.md`. **L'écran 4 change**
(les fins de vie dans le rapport) : charger d'abord le skill `ui-ux-pro-max`, puis lire
`design-system/MASTER.md`, l'écran 4 dans `design-system/ECRANS.md` et
`design-system/pages/` s'il en a une.

À faire :
- Détecter la version de chaque runtime, sans rien exécuter : Python (`requires-python`,
  `.python-version`, `runtime.txt`), Node (`engines.node`, `.nvmrc`, `.node-version`), Go
  (directive `go` de `go.mod`, `toolchain`), Ruby (`.ruby-version`, `ruby "…"` du `Gemfile`,
  `RUBY VERSION` du `Gemfile.lock`), PHP (`require.php`, `config.platform.php` de
  `composer.json`), Java (`maven.compiler.release`, `java.version`, toolchain Gradle), .NET
  (`TargetFramework`, `TargetFrameworks` des projets MSBuild, le SDK de `global.json`), et les
  `FROM` des `Dockerfile` (`python`, `node`, `ruby`, `php`, `golang`, `eclipse-temurin`,
  `mcr.microsoft.com/dotnet/…`). Une contrainte (`>=3.8`) n'est pas une version : sa borne basse,
  approximative (décision n°2).
- Frameworks : une table dépendance → produit endoflife.date (`django`, `rails`, `spring-boot`,
  `laravel`, `symfony`, `angular`, `vue`, `nuxt`, `electron`, `dotnet`/`aspnetcore`…), la version
  utilisée de la dépendance donnant le cycle.
- Client endoflife.date (`https://endoflife.date/api/v1/products/{produit}` : vérifier le format
  en vrai, et l'ancienne forme `/api/{produit}.json`), cache 24 h, réponses enregistrées
  (`record.py`), hors ligne. Constat `EOL` dans deux cas : fin de vie passée, ou dans moins de 6
  mois ; il donne la date et le cycle conseillé. Un runtime est signalé seulement (pas de mise à
  jour automatique) ; un framework monte comme toute autre dépendance (type 1).
- Les cases « Depuis E23 / E24 » : les versions qu'un PHP ou un Ruby du projet ne peut pas faire
  tourner (`require.php` des métadonnées `p2`, `ruby:` de l'index compact) : le dire, ou les écarter ;
  de même pour Node (`engines.node`, case de E07) ; la case « Depuis E26 » : les SDK de projet
  MSBuild venus de NuGet.
- Interface : les fins de vie dans le rapport (écran 4), avec la date et le cycle conseillé ;
  `openapi.json` et `schema.d.ts` régénérés si l'API change.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E26 (message « E26 : .NET (NuGet) », un résumé
  comme pour E23 à E25).
- endoflife.date : vérifier en vrai les noms des produits et les champs (dates `eol` qui peuvent
  être un booléen, cycles `latest`, `lts`) avant d'écrire ; un produit inconnu ; une erreur réseau
  donne un « non concluant », jamais un faux constat.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache
  de l'utilisateur ; `reference/` n'est jamais importé par `src/`. Les dates de fin de vie bougent :
  dans les tests, une date « aujourd'hui » injectée, pas l'horloge.
- Les SDK et outils sont hors du `PATH` des outils (`~/sdk/dotnet-sdk-10.0.403`, Ruby, Go, PHP,
  Composer, cargo) : la ligne de CLAUDE.md pour les tests `network`.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture (un heredoc a encore avalé une
  barre oblique à E26) ; `python -I` ignore `PYTHONIOENCODING` (`-X utf8`) ; jamais `node -e "…"`
  avec des accents graves ; un argument qui commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1`.
  Pour piloter la vraie interface : un script Playwright en `.cjs` dans le scratchpad, qui
  `require` le Playwright de `frontend/node_modules` (`ui --no-browser` en arrière-plan, l'adresse
  lue dans sa sortie, le serveur arrêté ensuite par son port) ; attendre le titre exact du rapport
  (`exact: true`).

Fini quand : un projet Python 3.8 + Django 3.2 + Node 16 sort trois constats datés et justes, dans
l'interface (écran 4) et en ligne de commande. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` ; à la main, `uv run forceupdate scan` sur un tel projet dans le scratchpad, et
`uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
