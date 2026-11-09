# forceupdate

L'outil s'appelle `forceupdate` (nom PyPI, paquet Python et commande). Le dossier
du projet garde son nom, `update-checker`.

Outil avec une interface web, qui tourne sur l'ordinateur de la personne. Il
prend du code (un dossier, un fichier, ou tous les dépôts GitHub, GitLab et
Bitbucket d'une personne), repère les langages et les dépendances, dit ce qui doit
être mis à jour, et sait faire ces mises à jour : en local il réécrit les
fichiers, sur une forge il ouvre une PR.

## État

**Livré : la 1.1.0 est sur PyPI** (session 38 ; la 1.0.0 à la session 37). Reste l'étape E38,
l'entretien (un test instable, le clavier de « Parcourir… » sous macOS).
L'avancement est dans [PLAN.md](PLAN.md) (tableau « Vue d'ensemble »). L'idée et les
décisions prises sont dans [docs/BRIEF.md](docs/BRIEF.md).

## Travail par sessions (règle obligatoire)

Le projet se construit étape par étape, en suivant [PLAN.md](PLAN.md).

1. **Au début de la session** : lire [PROCHAINE_SESSION.md](PROCHAINE_SESSION.md),
   le prompt préparé par la session d'avant, puis l'étape visée dans PLAN.md. Ne
   pas passer à une autre étape sans l'accord de l'utilisateur.
2. **Pendant** : une session = une étape. Les décisions prises en route et les
   écarts au plan sont notés sous l'étape, dans une rubrique « Notes ».
3. **À la fin de chaque session, toujours, même si l'étape n'est pas finie** :
   - mettre à jour PLAN.md : cases cochées, statut dans « Vue d'ensemble », une
     ligne dans « Journal des sessions » ;
   - **rédiger le prompt de la session suivante** dans PROCHAINE_SESSION.md, en
     remplaçant le précédent, sur le « Modèle de prompt de session » de PLAN.md.
     Il vise l'étape suivante du plan, ou la même étape si elle n'est pas finie,
     en disant ce qui reste ;
   - recopier ce prompt dans le dernier message à l'utilisateur.
4. **Le plan couvre 100 % du livrable.** Du travail non prévu s'ajoute au plan
   (nouvelle étape, ou étape découpée), il n'est jamais laissé de côté. Quand
   toutes les étapes sont faites et toutes les cases de « Le livrable » cochées,
   le projet est livrable, et le dernier prompt le dit.
5. **Pas de commit sans l'accord de l'utilisateur** : en fin de session, le
   proposer.

## Structure

```
update-checker/             ← dossier du projet ; l'outil s'appelle forceupdate
├── CLAUDE.md               ← ce fichier
├── PLAN.md                 ← le plan complet, étape par étape, et le journal des sessions
├── PROCHAINE_SESSION.md    ← le prompt de la prochaine session (réécrit à chaque session)
├── README.md               ← aussi la page PyPI : liens et images en adresses absolues (GitHub)
├── CHANGELOG.md            ← les versions publiées sur PyPI
├── LICENSE                 ← MIT, « Copyright (c) 2026 Pauzzle »
├── pyproject.toml          ← le paquet, ses dépendances, la config ruff et pytest ; la version (une seule fois)
├── uv.lock                 ← les versions figées des dépendances (versionné)
├── .gitattributes          ← tout en LF, même sous Windows (E35 : les tests comparent des octets)
├── .github/workflows/      ← ci.yml : ruff + pytest (Ubuntu, Windows, macOS ; Python 3.11 et 3.14), et le
│                             front sous Ubuntu et Windows (types, lint, Vitest, Playwright) ; network.yml :
│                             les tests network chaque lundi et à la demande, vrais outils installés ;
│                             publish.yml : PyPI à une étiquette v*, front compris ; picker.yml :
│                             « Parcourir… » avec une vraie fenêtre (macOS, Linux), à la demande (E37)
├── design-system/          ← produit à E13 avec le skill ui-ux-pro-max
│   ├── MASTER.md           ← les règles de l'interface : tokens, typo, composants, accessibilité
│   ├── ECRANS.md           ← les 9 écrans : contenu, appels à l'API, états, adresses
│   ├── pages/              ← les écarts au MASTER, par écran
│   └── mockups/            ← maquettes HTML statiques (ouvrir index.html), tokens de référence
├── docs/
│   ├── BRIEF.md            ← l'idée, les décisions prises, les pièges, les sources de données
│   ├── USAGE.md            ← la doc utilisateur (E35) : interface, commandes, configuration,
│   │                         écosystèmes et leurs limites, registres privés, réseau, robustesse
│   ├── FORGES.md           ← la doc des forges (E35) : connexion, droits, PR, application à soi
│   ├── JSON_FORMAT.md      ← le format du rapport JSON (scan --format json), et l'API de ui
│   └── images/             ← les captures du README (E35 : le serveur de tests/e2e_server.py, 1440 px)
├── reference/              ← code repris d'Argos, à piocher (voir reference/README.md)
├── frontend/               ← l'interface : React + TypeScript + Vite + Tailwind 4 + shadcn/ui (E14)
│   ├── src/api/            ← schema.d.ts (généré depuis openapi.json), client.ts, types.ts
│   ├── src/styles/         ← tokens.css (ceux de MASTER), app.css (Tailwind, polices)
│   ├── src/components/ui/  ← les composants shadcn/ui, habillés par les tokens ; sheet.tsx, dialog.tsx : <dialog> natif
│   ├── src/screens/        ← les écrans (Home, Choose, ScanProgress, report/…, update/ : l'écran 5,
│   │                         accounts/ : l'écran 6, repositories/ : l'écran 7, proposals/ : l'écran 8,
│   │                         settings/ : l'écran 9, Réglages) ;
│   │                         tests *.test.tsx à côté
│   ├── src/test/           ← mise en place de Vitest, fetch et EventSource simulés, rapport d'exemple
│   └── e2e/                ← tests Playwright (vrai serveur, front construit, CSP, axe-core) ;
│                             helpers.ts : copie d'un mini-projet dans un dossier temporaire ;
│                             forges.spec.ts : écrans 6, 7 et 8, GitHub, GitLab et Bitbucket, en série
│                             (comptes du serveur partagés) ; code.spec.ts : un fichier de code (E28),
│                             déposé sur la page (un vrai événement « drop ») ; settings.spec.ts : l'écran 9
│                             (les réglages du serveur sont partagés : rien qui change les autres rapports)
├── src/forceupdate/        ← le code de l'outil (architecture cible : PLAN.md)
│   ├── processes.py        ← lancer un outil (npm, uv, git, gh…) sans shell, et tuer tout son arbre à
│   │                         son délai, à Ctrl+C ou à l'arrêt du serveur (E30 : taskkill /T, killpg)
│   ├── config.py           ← la configuration d'un projet (E29) : forceupdate.toml ou [tool.forceupdate]
│   │                         (ignore, exclude, include-tests, [selection]) ; les règles ignore
│   ├── preferences.py      ← les réglages de la personne (E29) : forceupdate.toml de son dossier de
│   │                         configuration (platformdirs), mêmes clés + dépôts exclus, délais, Rust
│   ├── userfiles.py        ← les fichiers de configuration de la personne et son environnement (E33) :
│   │                         ~/.npmrc, GOENV, auth.json, settings.xml, NuGet.Config, pip.ini, uv.toml,
│   │                         .netrc ; tout passe par lui (home, config_home, environ, read, expand)
│   ├── net/                ← le client HTTP (http.py), le cache (cache.py), les identifiants des
│   │                         registres privés (auth.py, E33 : chacun lié à son adresse, jamais ailleurs)
│   ├── routing/            ← à quel registre demander chaque paquet (E33) : le public, un miroir, des
│   │                         registres en plus, ou celui d'un paquet privé par son nom (jamais le public
│   │                         ni OSV) ; un module par écosystème (npm et .yarnrc.yml, go, netrc, composer,
│   │                         nuget, python, maven pour Maven et Gradle, ruby : les serveurs de gems et la
│   │                         configuration de Bundler, cargo : [registries] et credentials.toml, E34) ;
│   │                         Clients : la chaîne
│   ├── advisories/         ← les failles : osv.py (OSV), packagist.py (les avis de Packagist, FriendsOfPHP
│   │                         compris, ajoutés à ceux d'OSV pour PHP, E34), cvss.py
│   ├── managed.py          ← les versions Maven gérées par un parent ou un BOM distant : leur pom lu au
│   │                         dépôt (E34), comme Maven construit son modèle
│   ├── checks/             ← les constats : outdated.py, vulns.py, deprecated.py, eol.py (fins de vie, E27 :
│   │                         la table des frameworks, le cycle d'une version, le cycle conseillé),
│   │                         runtimes.py (les versions que le runtime du projet ne fait pas tourner)
│   ├── endoflife.py        ← le client d'endoflife.date (/api/v1/products/{produit}, cache 24 h)
│   ├── forges/             ← interface Forge et OAuthFlow (base.py), GitHub (github.py : REST, dépôts,
│   │                         arborescence, fichiers, OAuth, device flow, gh, clone, branche, push, PR),
│   │                         GitLab (gitlab.py : gitlab.com ou une instance, projets, arborescence
│   │                         paginée, fichiers, OAuth PKCE et refresh token, clone, branche, MR), Bitbucket
│   │                         Cloud (bitbucket.py : workspaces puis dépôts, arborescence en largeur, fichiers,
│   │                         OAuth avec secret et refresh token, token d'API Atlassian, clone, branche dont
│   │                         l'arbre est lu par git, PR), git (git.py : token par un credential helper
│   │                         éphémère, donné au seul hôte de l'adresse, insteadOf de la personne
│   │                         neutralisé, clone superficiel, commit, push avec bail, arbre d'une branche
│   │                         distante, dossier de travail, cancel), comptes connectés (accounts.py : tokens dans le
│   │                         trousseau, keyring, en morceaux s'ils sont longs, un compte par forge et par
│   │                         hôte, renouvellement)
│   ├── parsers/            ← un module par écosystème : python.py, npm.py, rust.py (Cargo.toml, Cargo.lock,
│   │                         workspaces), go.py (go.mod et go.work : un lexer comme celui de modfile),
│   │                         php.py (composer.json, composer.lock), ruby.py (Gemfile et gems.rb lus par
│   │                         motifs, jamais exécutés ; .gemspec ; Gemfile.lock ; gems path:), java.py
│   │                         (Maven, puis Gradle), maven.py (pom.xml : propriétés, parents du dépôt,
│   │                         dependencyManagement, BOM, plugins), gradle.py (libs.versions.toml,
│   │                         build.gradle(.kts) lus en jetons, jamais exécutés, gradle.properties) ;
│   │                         nuget.py (packages.config, .csproj/.fsproj/.vbproj, Directory.Build.props
│   │                         et Directory.Packages.props, packages.lock.json, SDK de projet, TargetFramework ;
│   │                         MSBuild jamais lancé) ; runtimes.py (la version des runtimes : manifestes,
│   │                         .python-version, .nvmrc, global.json, Dockerfile… ; E27 ; la CI : workflows de
│   │                         GitHub, .gitlab-ci.yml, bitbucket-pipelines.yml, E32) ;
│   │                         code.py (un fichier de code seul, E28 : le bloc PEP 723 d'un script, lu par
│   │                         python.py, sinon ses imports ; la table import → paquet, les modules
│   │                         intégrés de Node), imports.py (ast pour Python, un lexer pour JS/TS et Go :
│   │                         jamais exécutés) ;
│   │                         lockfiles.py (lien manifeste ↔ lockfile), *_spans.py (positions ;
│   │                         ruby_spans.py, gradle_spans.py : des lexers ; xml_spans.py : expat, le
│   │                         texte et les attributs) ;
│   │                         versions/ et registries/ de même
│   │                         (cargo.py, crates.py : l'index « sparse » ; go.py, goproxy.py :
│   │                         proxy.golang.org, plusieurs requêtes par module ; composer.py, réécrit
│   │                         d'après composer/semver, packagist.py : les métadonnées p2 minifiées ;
│   │                         rubygems.py, réécrit d'après Gem::Version, rubygems.py : l'index compact ;
│   │                         maven.py, réécrit d'après ComparableVersion et VersionRange, maven.py :
│   │                         maven-metadata.xml de Maven Central, Google Maven et du portail Gradle ;
│   │                         nuget.py, réécrit d'après NuGet.Versioning : NuGet prend la plus basse
│   │                         version qui convient ; nuget.py : l'API « registration » et ses pages) ;
│   │                         un registre déclaré (E33) : registries.declared, la même classe à une autre
│   │                         adresse, ou composer.py (ComposerRepository : packages.json), NuGetFeed
│   │                         (l'index de services), SimpleIndex de pypi.py (l'API « simple » en HTML)
│   ├── sources/            ← d'où vient le code : local.py (dossier, fichier ; un fichier de code : le
│   │                         projet trouvé en remontant les dossiers, E28), forge.py (un dépôt lu par
│   │                         l'API : seuls les fichiers que lisent les parseurs sont téléchargés ; un
│   │                         clone superficiel si l'arborescence est tronquée)
│   ├── update/             ← planner, writers/, lockfiles (une majeure refusée retirée, le reste fait : `_retry`, session 37), local.py (mise à jour d'un dossier), forge.py
│   │                         (une PR par dépôt : clone, mise à jour, commit, push, PR), project_npm.py (le
│   │                         npm qu'attend le projet, E32 : régénéré par npx -y npm@10, relu par npm ci),
│   │                         blockers.py (E37 : ce que demandent les autres paquets, lu dans les lockfiles
│   │                         ou aux registres : une version retenue ou que l'outil refusera, et la
│   │                         version du parent qui l'accepterait ; après planner.plan et audit)
│   └── web/                ← le serveur de ui (FastAPI) ; repositories.py : les dépôts des comptes et leurs
│                             analyses groupées ; proposals.py : le récapitulatif des PR et leur envoi ;
│                             preferences.py : les réglages côté serveur (routes/settings.py : écran 9) ;
│                             workdirs.py : le dossier de travail du serveur (forceupdate-ui-*, verrouillé,
│                             effacé à l'arrêt ; ceux d'un arrêt brutal, au démarrage) ;
│                             openapi.json, exporté, donne les types du front ;
│                             static/ : le front construit (npm run build), ignoré par git, livré dans le paquet
└── tests/                  ← les tests ; conftest.py gère le marqueur network
    ├── picker_desktop.py   ← pas un test de la suite : l'essai de picker.yml (une vraie fenêtre de choix)
    ├── e2e_server.py       ← le serveur de ui hors ligne pour Playwright (npm, uv, gh, GitHub, GitLab
    │                         et une instance, Bitbucket, leurs dépôts, trousseau simulés ; des dépôts
    │                         « bare » où git pousse), et les
    │                         rapports d'exemple du front
    ├── fake_forge.py       ← GitHub simulé pour les dépôts (liste, arborescence, fichiers, organisations,
    │                         branches, comparaison, PR) ; make_remote : un dépôt « bare » local par dépôt
    ├── fake_gitlab.py      ← GitLab simulé (gitlab.com ou une instance : projets, arborescence paginée,
    │                         fichiers, branches, comparaison, MR, OAuth avec refresh token)
    ├── fake_bitbucket.py   ← Bitbucket Cloud simulé (workspaces, droits, dépôts, arborescence en largeur,
    │                         fichiers, branches, commits propres, PR, OAuth : Basic, refresh token renouvelé)
    ├── fake_bundler.py     ← bundle lock simulé (FakeTools.handlers["bundle"]), comme le vrai Bundler 4.0
    ├── fixtures/           ← réponses HTTP enregistrées (NuGet : compressées ; endoflife/ : endoflife.date ;
    │                         tls/ : une autorité de test, son certificat public seul ; maven/poms/ : des
    │                         pom de parents, de BOM et de dernières versions, E34 ;
    │                         packagist-advisories.json : les avis de Packagist, E34) ;
    │                         record.py les ré-enregistre, RECORDED_ON : le jour des fins de vie des tests
    └── projects/           ← mini-projets par outil, lockfiles produits par les vrais outils ; eol/ : E27 ;
                              scripts/ : E28 (des fichiers de code seuls ; locked.py.lock de uv lock --script) ;
                              exports/ : E32 (requirements.txt de uv export, poetry export, pdm export,
                              pip-compile pyproject.toml)
```

## Commandes

```bash
uv sync                          # installe l'outil et ses dépendances dans .venv
uv run forceupdate --version     # lance l'outil (ui, scan, update)
uv run forceupdate scan <chemin> # analyse ; --format json|md, --output, --offline, --fail-on…
uv run forceupdate update <chemin>  # le plan, le diff, puis la réécriture des manifestes et
                                    # la régénération des lockfiles (npm, uv… s'ils sont là) ;
                                    # --dry-run, --yes, --force, --level, --security-only…
uv run forceupdate ui --no-browser  # le serveur local (127.0.0.1), l'adresse avec le jeton ; Ctrl+C
uv run python -m forceupdate.web.openapi  # réexporte web/openapi.json (un test vérifie qu'il est à jour)
uv run pytest                    # tests hors ligne ; reference/ n'est jamais ramassé
uv run pytest --run-network      # avec en plus les tests marqués network (vrai réseau)
uv run ruff check                # lint
uv run ruff format               # formatage ; la CI vérifie avec --check
uv run python tests/fixtures/record.py   # ré-enregistre les réponses des registres et d'OSV
uv run python tests/fixtures/record.py pypi:jinja2   # un seul paquet (déclaré dans PACKAGES)
uv run python tests/fixtures/record.py maven-poms   # les pom que lisent les mini-projets maven et gradle
uv run python tests/fixtures/record.py packagist-advisories   # les avis de Packagist des paquets PHP

# le front (node 24 ; dans frontend/, après « npm ci »)
npm run build                    # construit le front dans src/forceupdate/web/static/ (servi par ui)
npm test                         # tests de composants (Vitest + Testing Library), sans réseau
npm run typecheck                # types (tsc) ; npm run lint : oxlint, sans avertissement
npm run test:e2e                 # construit, puis Playwright : vrai serveur hors ligne (tests/e2e_server.py)
npm run gen:api                  # régénère src/api/schema.d.ts depuis openapi.json (un test le vérifie)
FORCEUPDATE_URL=<adresse de « forceupdate ui »> npm run dev   # Vite, /api passé au serveur, jeton compris

# une autre version de Python que celle de .venv (la CI teste 3.11 et 3.14)
uv run --isolated --python 3.11 --group dev pytest

# tests de reference/, avec le Python du système (qui a loguru et pytest-asyncio)
cd reference && python -m pytest argos_sca_parsers_tests.py
```

- **Vérifier une version publiée** : quelques minutes après `uv publish`, le CDN de PyPI peut encore
  servir l'ancien index, et `uv tool install forceupdate` donner une version plus ancienne (la
  0.1.0, session 37) : `--refresh`, et vérifier `--version`. Sous Linux, l'image
  `ghcr.io/astral-sh/uv` met les outils de uv dans `/usr/local/bin` : en utilisateur non root,
  `UV_TOOL_DIR` et `UV_TOOL_BIN_DIR` sous `HOME`.
- **La suite sous Linux, sans pousser** (E35 : elle y cassait sans qu'on le voie) : Docker
  Desktop est installé (le démarrer). Une archive fidèle du dépôt (`git -c core.autocrlf=false
  archive` de `git stash create`, sinon de `HEAD` : sans `-c`, `archive` applique l'`autocrlf`
  de Windows), dépliée dans `ghcr.io/astral-sh/uv:python3.14-bookworm` lancé en utilisateur non
  root (`--user 1000:1000`, `HOME` et `UV_CACHE_DIR` dans `/tmp`), puis `uv sync --locked` et
  `uv run pytest`. Monter le dossier avec `MSYS_NO_PATHCONV=1` sous Git Bash. macOS ne se teste
  que par la CI.
- Sous Windows, uv prévient parfois « Failed to hardlink files » : sans effet sur
  le résultat, `UV_LINK_MODE=copy` le fait taire.
- Sous Windows, une sortie redirigée (tube, fichier) est écrite en cp1252 par
  défaut, pas en UTF-8. `forceupdate scan` repasse la sienne en UTF-8 (E07) ; pour
  un autre script, `PYTHONIOENCODING=utf-8`. Un script passé à Python par l'entrée
  standard (heredoc) abîme les accents, et l'outil Bash réduit `\\` à `\` dans un heredoc :
  l'écrire dans un fichier (outil d'écriture), puis le lancer. `python -I` ignore
  `PYTHONIOENCODING` : `python -I -X utf8`.
- Les tests ne touchent jamais le réseau sans le marqueur `network` (donc jamais le vrai
  GitHub), ni le cache de l'utilisateur, ni un vrai outil de lockfile (npm, uv…), ni le
  trousseau du système ni `gh`, ne lancent git que vers des dépôts locaux, et n'ouvrent jamais
  le navigateur, ni les réglages de la personne (`user_settings` : un fichier propre au test),
  ni le dossier temporaire de la personne par le serveur (`server_temp` : son dossier de travail
  et son balayage au démarrage), ni ses fichiers de configuration et son environnement
  (`user_files` : `~/.npmrc`, `GOPRIVATE`… ; un dossier personnel et un environnement vides, propres
  au test, que le test remplit ; lire hors des dossiers des tests échoue) : neuf garde-fous
  automatiques de `tests/conftest.py` y veillent
  (celui de git ignore les valeurs de `-c`, où est la règle `insteadOf` de l'adresse). Les tests des
  PR clonent et poussent pour de vrai, vers des dépôts « bare » du dossier du test
  (`fake_forge.make_remote`, `github.GIT_URL` vers `remotes_url(…)`). Dans un test, jamais
  `monkeypatch.undo()` : il défait aussi ces garde-fous (`monkeypatch.context()`). GitLab se simule avec
  `fake_gitlab.FakeGitLab` (`gitlab.GIT_URL` vers `remotes_url(…)` pour git), Bitbucket avec
  `fake_bitbucket.FakeBitbucket` (`bitbucket.GIT_URL` de même). Le trousseau des tests refuse,
  comme Windows, un secret de plus de 1 280 caractères. La fixture `recorded` simule PyPI, npm,
  crates.io, le proxy Go, Packagist, RubyGems, Maven (Central, Google, portail Gradle), nuget.org,
  OSV et endoflife.date avec les
  réponses de `tests/fixtures/` (pour Go, toutes celles d'un module dans un fichier :
  `goproxy/<module>.json` ; pour NuGet, l'index et ses pages : `nuget/<id>.json.gz` ; pour Maven,
  `:` s'écrit `__` dans le nom). Une fin de vie se juge à la date du jour : tous les tests (et le
  serveur de `e2e_server.py`) se placent au jour de l'enregistrement d'endoflife.date
  (`record.RECORDED_ON`, fixture `_fixed_today`), à changer avec un nouvel enregistrement ;
  `fake_tools("npm", "uv")`
  simule les outils (`FakeTools` ; `fake_bundler.FakeBundler` pour `bundle`) ; `keychain` est le
  trousseau en mémoire du test ; `api` est le
  serveur de `ui` (client de test de FastAPI, jeton compris), `finished` attend la fin
  d'une tâche. GitHub se simule avec respx (`tests/test_web_accounts.py`, `FakeGitHub` pour les
  comptes ; `tests/fake_forge.py`, `FakeGitHubRepos`, pour les dépôts, faits des mini-projets).
  respx remplace une route qui a le même motif qu'une autre : une route ajoutée à
  `recorded_responses(ajout)` pour changer une réponse enregistrée prend un autre motif
  (`url__regex=`). Les tables tenues à la main (`FRAMEWORKS`, `NODE_CODENAMES`, `NODE_NPM`,
  `IMPORT_PACKAGES`) ont des tests `network` (`tests/test_tables_network.py`, E34).
- Les retours d'OAuth (`/oauth/github/callback`, `/oauth/gitlab/callback`,
  `/oauth/bitbucket/callback`) sont les seules adresses que le garde du serveur laisse passer
  sans jeton : ne pas en ajouter d'autre sans la même protection (`state`).
  L'essayer pour de vrai : `forceupdate ui`, par l'adresse `127.0.0.1` (pas `localhost`) ;
  le compte connecté va dans le vrai trousseau (Gestionnaire d'identification de Windows), et
  l'écran Réglages écrit le vrai fichier `%LOCALAPPDATA%\forceupdate\forceupdate.toml` (le même que
  la ligne de commande : l'effacer après un essai s'il n'existait pas) ; « Vider le cache » vide
  le vrai cache de l'utilisateur (dans un essai, annuler le dialogue).
- Un registre privé se simule avec respx, dans `recorded_responses(ajout)` de `conftest.py` (ses
  routes passent avant celles qui répondent 404) : voir `tests/test_routing_*.py`. Pour l'essayer
  en vrai sans toucher aux fichiers de la personne : un dossier personnel factice dans le
  scratchpad (`USERPROFILE`, `HOME` et `APPDATA` pour la commande : `Path.home()` suit
  `USERPROFILE` sous Windows) et des registres servis sur `127.0.0.1` (un identifiant peut y partir
  en http : rien ne quitte la machine).
- Un test qui lance une vraie commande `ui` (sans `serve` simulé) bloque la suite :
  le serveur attend Ctrl+C.
- Le front construit (`src/forceupdate/web/static/`) n'est pas versionné : sans lui, `ui`
  sert une ligne de texte. `npm run build` d'abord ; la publication (`publish.yml`) le fait
  avant `uv build`, et hatchling l'embarque (`artifacts`). Les tests Python ne lancent
  jamais node ; ceux du front ont leurs commandes (ci-dessus).
- Front : TypeScript 5.9, pas 7 (openapi-typescript a besoin de l'API JavaScript de
  TypeScript, que la 7 n'a pas). Playwright télécharge son Chromium une fois
  (`npx playwright install chromium`). Le serveur Vite de dev n'a pas la CSP : vérifier le
  front construit, servi par `ui` (les tests e2e échouent sur toute erreur de console).
- CSP du serveur (`default-src 'self'`) : rien d'un CDN, pas d'URL `data:`, pas de
  `<style>` ni de script en ligne (les styles posés par React passent). Radix Dialog et
  Sonner injectent un `<style>` : refusés ; le panneau et les dialogues sont des
  `<dialog>` natifs (`components/ui/sheet.tsx`, `dialog.tsx`), « Copié » s'annonce par une
  région `aria-live` (`components/Command.tsx`).
- Les tests e2e qui écrivent travaillent sur une copie (`e2e/helpers.ts`, `copyProject`) ;
  le serveur de test est partagé entre les tests : ses chemins récents s'accumulent.
- Pour essayer les PR en vrai : le dépôt de test `Pauzzle-ozz/forceupdate-demo` (privé, créé à
  E18, copie de `tests/projects/vulnerable`) sur GitHub, le projet du même nom sur gitlab.com
  (privé, créé à E19) pour les MR, et `pauzzle/forceupdate-demo` sur Bitbucket (privé, créé à
  E20 par l'utilisateur, workspace `pauzzle`) ; gardés pour la recette (E36) ; jamais un autre
  dépôt sans l'accord de l'utilisateur.
- Un script qui prend un chemin d'API en argument (`/user/…`) sous Git Bash : `MSYS_NO_PATHCONV=1`,
  sinon Git Bash le réécrit en chemin Windows (`C:/Program Files/Git/user/…`).
- Pour essayer `forceupdate update` en vrai : sur une copie dans le scratchpad, jamais
  dans `tests/projects/` (les outils réécrivent les lockfiles). yarn, poetry, pdm,
  pipenv et pip-compile ne sont pas installés (choix de l'utilisateur) : `npx yarn@1`,
  `corepack yarn@4.18.1`, `uvx poetry`, `uvx pdm`, `uvx pipenv`,
  `uvx --from pip-tools pip-compile`. pipenv crée un virtualenv dans `~/.virtualenvs`
  (le retirer avec `uvx pipenv --rm`), et prend le `.venv` activé si `VIRTUAL_ENV` est
  défini. Pour qu'un `forceupdate update` les trouve, un lanceur dans un dossier du scratchpad mis
  en tête du `PATH` (`pdm.cmd` : `@echo off` puis `uvx pdm %*` ; de même `uvx --with
  poetry-plugin-export poetry %*`, E32). Un outil qui range ses fichiers sous le scratchpad peut
  dépasser les 260 caractères de chemin de Windows (pnpm, E32) : un lecteur `subst` vers le
  scratchpad, retiré ensuite (`subst Q: /d`).
- cargo est installé par rustup (E21, toolchain stable MSVC) dans `~/.cargo/bin`, qui n'est pas
  dans le `PATH` des outils Bash et PowerShell : `export PATH="$HOME/.cargo/bin:$PATH"` avant
  `forceupdate update`, `ui` ou `pytest --run-network`. rustup installe tout seul la chaîne
  d'outils que demande un `rust-toolchain.toml` : la retirer ensuite
  (`rustup toolchain uninstall …`).
- go 1.27.3 est dans `~/sdk/go1.27.3/bin` (E22 : l'archive officielle de go.dev, winget étant
  bloqué), hors du `PATH` : `export PATH="$HOME/sdk/go1.27.3/bin:$PATH"` avant `forceupdate update`,
  `ui` ou `pytest --run-network`. Pour un essai à la main, mettre les modules dans le scratchpad
  (`GOMODCACHE`, `GOCACHE`, `GOFLAGS=-modcacherw` pour pouvoir les effacer) plutôt que dans
  `~/go` ; forceupdate passe lui-même `GOTOOLCHAIN=local` et `GOFLAGS=-mod=mod`. `go build ./...`
  laisse un programme dans un module à `package main` : ne pas le copier dans `tests/projects/`.
- PHP 8.5.12 est dans `~/sdk/php-8.5.12` (E23 : l'archive NTS x64 de windows.php.net, son
  `php.ini` charge openssl, curl, mbstring, zip et fileinfo) et Composer 2.11.0 dans
  `~/sdk/composer-2.11.0` (le `composer.phar` de getcomposer.org, et un `composer.bat` comme celui
  de son installateur), hors du `PATH` : `export PATH="$HOME/sdk/php-8.5.12:$HOME/sdk/composer-2.11.0:$PATH"`
  avant `forceupdate update`, `ui` ou `pytest --run-network`. Sous Git Bash, lancer `composer.bat`
  (`which composer` ne le trouve pas ; `shutil.which` si). Pour un essai à la main, mettre
  `COMPOSER_HOME` et `COMPOSER_CACHE_DIR` dans le scratchpad ; pour fabriquer un lockfile
  volontairement vulnérable, `--no-blocking` (Composer refuse sinon les versions à faille).
- Ruby 4.0.9 (RubyGems et Bundler 4.0.20) est dans `~/sdk/ruby-4.0.9` (E24 : l'archive 7z « without
  devkit » de RubyInstaller, dépliée par le `tar` de Windows), hors du `PATH` :
  `export PATH="$HOME/sdk/ruby-4.0.9/bin:$PATH"` avant `forceupdate update`, `ui` ou
  `pytest --run-network`. Sous Windows, `bundle` est le `bundle.bat` de RubyInstaller (`shutil.which`
  le trouve). Pour un essai à la main, mettre `BUNDLE_USER_HOME`, `GEM_HOME` et `GEM_SPEC_CACHE`
  dans le scratchpad. `bundle lock` exécute le `Gemfile` et les `.gemspec` : jamais sur un projet
  inconnu ; cloner une gem `git:` d'un dépôt externe n'a pas été permis.
- Java : ni Maven ni Gradle ne sont installés (choix de l'utilisateur, E25) : pas de lockfile Java en
  V1, et forceupdate ne lance jamais Gradle (un script est un programme). Java 8 n'est qu'un JRE (pas de
  `javac`) ; l'oracle des versions Maven était `~/sdk/maven-artifact/maven-artifact-3.9.16.jar`
  (effacé à la session 36, à la demande de l'utilisateur : le reprendre de Maven Central,
  `org.apache.maven:maven-artifact:3.9.16`, s'il faut revérifier), lancé par Nashorn : `"/c/Program Files/Java/jre1.8.0_481/bin/jjs.exe" -cp <jar> script.js -- <args>`
  (`ComparableVersion`, `VersionRange` ; voir les notes de E25). `ComparableVersion` n'est pas
  transitif : ne pas trier un corpus avec `Collections.sort` (il refuse), comparer deux à deux.
- Le SDK .NET 10.0.403 est dans `~/sdk/dotnet-sdk-10.0.403` (E26 : l'archive zip officielle,
  vérifiée), hors du `PATH` : `export PATH="$HOME/sdk/dotnet-sdk-10.0.403:$PATH"` avant
  `forceupdate update`, `ui` ou `pytest --run-network`. Le `dotnet` de `C:\Program Files\dotnet`
  n'a que des runtimes : sans SDK, forceupdate le tient pour absent. Pour un essai à la main,
  `DOTNET_CLI_HOME` et `NUGET_PACKAGES` dans le scratchpad ; `dotnet restore` écrit `obj/` dans
  chaque projet (ne pas le copier dans `tests/projects/`). L'oracle des versions NuGet était
  `~/sdk/nuget-versioning-7.9.0/lib/net472/NuGet.Versioning.dll` (effacé à la session 36 : le
  paquet `NuGet.Versioning` 7.9.0 de nuget.org, s'il faut revérifier), chargé par PowerShell 5.1
  (`[Reflection.Assembly]::LoadFrom`) ; `[NuGet.Versioning.NuGetVersion]::TryParse` y prend la
  surcharge stricte héritée de `SemanticVersion` : `Parse` dans un `try`.
- Un fichier de code (E28) s'analyse à travers le projet trouvé en remontant les dossiers : dans
  le dépôt, `tests/projects/scripts/imports.py` le serait via le `pyproject.toml` de forceupdate.
  Les tests copient ces fichiers dans leur dossier et fixent le dossier personnel, où la remontée
  s'arrête (`monkeypatch.setattr(local, "_home", …)`) ; à la main, les copier dans le scratchpad.
- Pour tous les tests `network` d'un coup :
  `export PATH="$HOME/sdk/dotnet-sdk-10.0.403:$HOME/sdk/ruby-4.0.9/bin:$HOME/sdk/php-8.5.12:$HOME/sdk/composer-2.11.0:$HOME/sdk/go1.27.3/bin:$HOME/.cargo/bin:$PATH"`.

## Interface

- **Avant d'écrire ou de modifier quoi que ce soit dans l'interface, charger le
  skill `ui-ux-pro-max`**
  (source : https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), puis lire
  `design-system/MASTER.md`, l'écran dans `design-system/ECRANS.md` et, s'il existe,
  `design-system/pages/<écran>.md`. Les maquettes (`design-system/mockups/`) donnent le
  rendu attendu et les tokens exacts (`mockups/assets/mockups.css`).
- Le skill sous Windows : ses dossiers `scripts/` et `data/` sont des liens git non
  résolus ; lancer `python ~/.claude/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py`
  (avec `PYTHONIOENCODING=utf-8`).
- L'interface et la ligne de commande ne contiennent pas de logique métier : elles
  appellent le moteur.
- Les tokens des forges ne vont jamais au navigateur.

## Règles pour `reference/`

- C'est une **réserve de morceaux à copier puis adapter** dans `src/`. Le code de
  `src/` n'importe jamais `reference/`.
- L'outil ne dépend **jamais** d'Argos (`sechunter`) : il doit tourner seul.
- Avant d'écrire un parseur de fichier de dépendances, regarder s'il existe déjà
  dans `reference/argos_sca_parsers.py` et lire ses limites dans
  `reference/README.md`.
- `reference/` est une copie figée (commit `52c714b7` d'Argos) : on ne la modifie
  pas. Quand on reprend un morceau, on l'adapte dans `src/` et on reprend aussi
  ses tests depuis `reference/argos_sca_parsers_tests.py`.
- Les trois dépendances à Argos à couper sont marquées `ARGOS (n)` dans le code.
- Le dépôt Argos d'origine est dans `~/Desktop/the good guy`, si besoin de
  remonter à la source. Pour la partie GitHub (clone avec token, PR), il a du code
  qui n'est pas dans `reference/` : voir [docs/BRIEF.md](docs/BRIEF.md), « Ce
  qu'on a déjà ».

## Langue

Français.
