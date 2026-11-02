# Session 32 — Étape E32 : Mise à jour : le npm du projet, Python, NuGet, Go

Contexte : E01 à E31 sont faites. E31 (forges : robustesse) a fait `web/workdirs.py` (le dossier
de travail du serveur, `forceupdate-ui-*`, verrouillé, effacé à l'arrêt ; ceux d'un arrêt brutal,
au démarrage), l'arrêt immédiat d'un envoi de PR (git reçoit `cancel` : `Forge.cancel`,
`Jobs.stopping`), la PR fermée sans fusion signalée au récapitulatif (`Forge.closed_request`,
pas cochée), `url.<base>.insteadOf` neutralisé et le token donné au seul hôte de l'adresse, les
sous-modules d'un dépôt dits (`Tree.submodules`), le `fetch` de Bitbucket mesuré et évité quand
il est inutile. Les décisions de l'utilisateur sont dans les notes de E31 (trousseau sous Linux :
la doc seulement). 4 789 tests Python verts (plus 21 réseau), 164 Vitest, 71 Playwright.
**E31 n'est pas commitée : à proposer d'abord.**

Lis CLAUDE.md, puis l'étape E32 de PLAN.md (toutes ses cases), les notes de E11 (lockfiles,
`npm update`, la relecture), de E22 (Go, `vendor/`), de E23 (Composer, `--no-blocking`), de E26
(NuGet : la plus basse version qui convient), de E27 (`Project.runtimes`,
`checks.runtimes.project_runtime`) et de E29 (la décision « `npx npm@10` coché d'office »), et
`docs/BRIEF.md` (décision n°11 ; « Pièges connus »). Puis le code qui sert de modèle :
`update/lockfiles.py` (`plan`, `regenerate`, `_poetry_major`, `Tools`, `_Context`), `update/local.py`
(`prepare`, `apply`), `update/planner.py` (`manual`), `parsers/python.py` (requirements),
`parsers/nuget.py` et `update/writers/` (la réécriture, insérer un élément), `processes.py`. Si
l'interface change (une case dans le plan de l'écran 5, un avertissement), charger d'abord le
skill `ui-ux-pro-max` et lire `design-system/MASTER.md`, l'écran 5 dans `design-system/ECRANS.md`
et `design-system/pages/mise-a-jour.md`.

À faire :
- le npm du projet : lire la version attendue (`packageManager`, `devEngines.packageManager`,
  `engines.npm`, puis la version de Node du projet, puis `actions/setup-node` des workflows),
  la comparer à la majeure du npm installé, le dire dans le plan et régénérer par `npx -y npm@10`
  (une case cochée d'office), vérifier par `npx -y npm@10 ci --dry-run --ignore-scripts` ; pnpm et
  Yarn (corepack) ; les PR des forges (le clone a la CI du dépôt) ; un test qui reproduit le cas et
  un test `network` avec les deux vrais npm ;
- le workspace npm : une indirecte d'un membre retenue par une version forcée de la racine, sur un
  vrai workspace ;
- les `requirements.txt` générés sans `.in` (`uv export`, `poetry export`, `pdm export`,
  `pip-compile pyproject.toml`) : les reconnaître et les traiter comme des lockfiles ;
- une ligne de `requirements` à empreintes (`--hash`) : l'option `manual` dès l'analyse ;
- NuGet : appliquer l'option « à la main » d'une indirecte en faille (`PackageReference`, ou
  `PackageVersion` et `CentralPackageTransitivePinningEnabled`), relue comme les autres ;
- Go : proposer `go mod vendor` après `go mod tidy`, avec de quoi remettre `vendor/` ;
- Composer 2.9 : dire `config.audit.block-insecure` dans le plan.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E31 (message « E31 : forges : robustesse »,
  un résumé comme pour E29 et E30).
- Vérifier en vrai avant d'écrire, comme à E27–E31 : la table Node → npm sur nodejs.org (Node 22
  et 24 aujourd'hui), ce que fait `npx -y npm@10` (le cache de npx : dans le scratchpad,
  `npm_config_cache`), `npm ci --dry-run` sur un lockfile écrit par npm 11, `corepack` pour pnpm et
  Yarn (`corepack yarn@4.18.1`), les en-têtes des `requirements.txt` de `uv export`, `uvx poetry
  export`, `uvx pdm export` et `uvx --from pip-tools pip-compile`, `dotnet restore` après l'ajout
  d'une `PackageReference`, `go mod vendor`, Composer 2.9 si on peut l'avoir à côté (sinon le
  dire). Toujours sur une copie dans le scratchpad, jamais dans `tests/projects/` (les outils
  réécrivent les lockfiles) ; les PATH des outils sont dans CLAUDE.md.
- Une case de plan nouvelle change l'API (`openapi.json`, `npm run gen:api`) et l'écran 5.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache,
  le trousseau, les réglages ni le dossier temporaire de l'utilisateur (huit garde-fous de
  `conftest.py`, dont `server_temp` depuis E31) ; dans un test, jamais `monkeypatch.undo()`.
- Le dossier temporaire de l'utilisateur : les 773 dossiers `forceupdate-*` d'avant E31 ont été
  effacés avec son accord (session 31) ; les `forceupdate-e2e-*` que laisse le serveur des tests
  de bout en bout restent (case de E35).
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc (il mange
  les barres obliques inverses : encore vu à la session 31) ; l'outil d'écriture change un
  `\uXXXX` en caractère ; `python -I` ignore `PYTHONIOENCODING` (`-X utf8`) ; un argument qui
  commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1` ; une suppression : un chemin écrit en
  entier (le contrôle de l'outil refuse `rm -rf "$VAR/x"`).

Fini quand : sur une copie d'un projet dont la CI est en Node 22, une mise à jour faite avec
npm 11 installé donne un lockfile que `npm@10 ci` accepte ; les autres cases ont leurs tests et
sont vérifiées avec le vrai outil. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
