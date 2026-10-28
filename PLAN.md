# Plan — forceupdate

Ce plan couvre **100 % du livrable** : quand toutes les étapes sont faites et
toutes les cases de « Le livrable » cochées, l'outil est livrable.

Une session = une étape. Les règles de suivi (mise à jour de ce fichier, prompt
de la session suivante) sont dans [CLAUDE.md](CLAUDE.md), section « Travail par
sessions ». L'idée et les décisions sont dans [docs/BRIEF.md](docs/BRIEF.md).

## Le livrable

Ce qui doit être vrai à la fin. Coché seulement à l'étape E31 (recette), après
vérification à la main.

- [ ] `uv tool install forceupdate` installe l'outil depuis PyPI, interface comprise (pas besoin de node pour l'utiliser), sous Windows et sous Linux.
- [ ] `forceupdate ui` ouvre l'interface web dans le navigateur. Dans l'interface, on peut :
  - choisir un dossier ou un fichier de l'ordinateur, ou glisser-déposer un fichier ;
  - voir les langages, les projets, les dépendances directes avec leur version installée, et les constats des 4 types (version plus récente, faille, fin de vie, déprécié ou retiré), du plus grave au moins grave ;
  - cocher les mises à jour (les sûres sont pré-cochées), voir le diff et appliquer : manifestes réécrits sans casser leur mise en forme, lockfiles régénérés quand l'outil natif est installé, commande à lancer indiquée sinon ;
  - connecter son compte GitHub, GitLab ou Bitbucket en quelques clics, et le déconnecter ;
  - voir tous ses dépôts, les analyser sans les cloner : un rapport par dépôt, plus une synthèse ;
  - ouvrir une PR (une MR sur GitLab) par dépôt à mettre à jour. Relancé, l'outil met à jour la même PR ; il ne pousse jamais sur la branche par défaut.
- [ ] L'interface suit `design-system/MASTER.md`. Elle est accessible (contraste, clavier), en clair et en sombre, en français.
- [ ] En ligne de commande, `forceupdate scan` (terminal, JSON, Markdown, `--fail-on`) et `forceupdate update` marchent sur un chemin local, pour les scripts et la CI.
- [ ] Les 8 écosystèmes (Python, JS/npm, Rust, Go, PHP, Ruby, Java, .NET) sont couverts en analyse et en mise à jour. Les limites restantes sont écrites dans la doc.
- [ ] Sans réseau, les tests passent. Une erreur réseau donne « non concluant », jamais un faux constat.
- [ ] La doc utilisateur est complète, la CI est verte, la version 1.0.0 est taguée.

## Architecture cible

```
src/forceupdate/
├── cli.py            commandes : ui, scan, update
├── engine.py         le moteur : enchaîne source → projets → dépendances → constats → rapport
├── models.py         Dependency, Finding, Project, Report, Language, Severity, FindingKind…
├── sources/          d'où vient le code : base.py (interface Source), local.py, forge.py
├── detect/           languages.py (langages), manifests.py (découverte, regroupement en projets)
├── parsers/          un module par écosystème : python, npm, rust, go, php, ruby, java, dotnet
├── versions/         comparer, classer l'écart, tester une contrainte : un module par écosystème
├── net/              http.py (client commun, retries, limites de débit), cache.py (cache disque)
├── registries/       un client par registre : pypi, npm, crates, goproxy, packagist, rubygems, maven, nuget
├── advisories/       osv.py (failles connues : querybatch, puis chaque avis), cvss.py (score d'un vecteur)
├── checks/           outdated.py, vulns.py (constats tirés d'OSV), deprecated.py, eol.py
├── update/           planner.py, writers/ (un par format), lockfiles.py
├── forges/           base.py (interface Forge), github.py, gitlab.py, bitbucket.py,
│                     git.py (clone, push), accounts.py (connexions, trousseau)
├── report/           terminal.py, json.py, markdown.py
└── web/              app.py (FastAPI), routes/, jobs.py (tâches de fond, progression),
                      security.py, static/ (le front construit)
frontend/             l'interface : React + TypeScript (Vite), construite dans web/static/
design-system/        MASTER.md, pages/*.md, mockups/ : produits avec le skill ui-ux-pro-max (E13)
tests/
├── fixtures/         réponses HTTP enregistrées (registres, OSV, forges, endoflife.date)
└── projects/         mini-projets de test, un par format
```

Le chemin des données :

- **analyse** : `Source` → `Project` → (parsers) `Dependency` → (registres + checks) `Finding` → `Report` ;
- **mise à jour** : `Finding` → (planner) sélection → (writers) manifestes → (lockfiles) lockfiles → (forges) PR / MR ;
- l'interface web (`web/` + `frontend/`) et la ligne de commande (`cli.py`) pilotent ce moteur. **Elles ne contiennent pas de logique métier.**

Une `Dependency` garde au moins :

- l'écosystème, le nom, la contrainte telle qu'écrite (`^4.18.0`) ;
- la version installée (lu dans le lockfile, sinon vide) ;
- directe ou non, et le scope (runtime, dev…) ;
- le fichier, et **l'emplacement exact de la contrainte** (ligne, colonnes) : c'est ce qui permet de la réécrire sans toucher au reste ;
- si elle est vérifiable : une dépendance git, `file:` ou `workspace:` ne l'est pas, et on garde la raison.

## Choix techniques

- Python ≥ 3.11, uv, layout `src/`.
- Dépendances prévues :
  - moteur : `httpx` (HTTP async), `packaging` (PEP 440), `pyyaml` (lockfiles pnpm et Yarn 2+), `platformdirs` (cache), `keyring` (tokens des forges) ;
  - interfaces : `fastapi` + `uvicorn` (serveur local), `typer` + `rich` (ligne de commande) ;
  - en dev : `pytest`, `respx` (simuler HTTP), `ruff`.

  Toute autre dépendance : la justifier dans les notes de l'étape.
- Front :
  - React + TypeScript + Vite + Tailwind + shadcn/ui, à confirmer à E13 ;
  - types TypeScript générés depuis le schéma OpenAPI de l'API ;
  - tests : Vitest + Testing Library, Playwright pour le bout en bout ;
  - node sert à développer et à construire le front, pas à utiliser l'outil.
- **Toute étape qui touche à l'interface charge d'abord le skill `ui-ux-pro-max`** et suit `design-system/MASTER.md`.
- Noms dans le code en anglais, docstrings et commentaires en français, comme dans `reference/`. Textes de l'interface en français.
- `logging` de la bibliothèque standard, pas `loguru`.
- Tests hors ligne par défaut : réponses HTTP enregistrées dans `tests/fixtures/`. Les tests qui touchent le vrai réseau sont marqués `network` et sautés par défaut.
- Toute commande externe (npm, uv, git, cargo…) : trouvée par `shutil.which`, lancée sans shell, avec un délai maximal, sans scripts du projet.

## Vue d'ensemble

Statuts : `à faire`, `en cours`, `fait`.

| Étape | Phase | Titre | Statut |
|---|---|---|---|
| E01 | A. Socle | Squelette du projet | fait |
| E02 | B. Analyse locale (Python + npm) | Source locale, langages, découverte des manifestes | fait |
| E03 | B | Parseurs Python, lien manifeste ↔ lockfile | fait |
| E04 | B | Parseurs npm (npm, Yarn, pnpm) | fait |
| E05 | B | Versions : comparer, classer l'écart, tester une contrainte | fait |
| E06 | B | Client HTTP, cache, registres PyPI et npm | fait |
| E07 | B | Constats « plus récente » et « retiré / déprécié », rapports, commande `scan` | fait |
| E08 | B | Failles (OSV) | fait |
| E09 | C. Mise à jour locale (Python + npm) | Planificateur et sélection des mises à jour | fait |
| E10 | C | Réécriture des manifestes, commande `update` | fait |
| E11 | C | Régénération des lockfiles | fait |
| E12 | D. Interface web | Serveur local et API | fait |
| E13 | D | Conception de l'interface (skill ui-ux-pro-max) | à faire |
| E14 | D | Front : socle et analyse locale | à faire |
| E15 | D | Front : mise à jour locale | à faire |
| E16 | E. Forges | Interface `Forge` commune, connexion GitHub | à faire |
| E17 | E | GitHub : dépôts et analyse sans cloner | à faire |
| E18 | E | GitHub : une PR par dépôt | à faire |
| E19 | E | GitLab | à faire |
| E20 | E | Bitbucket Cloud | à faire |
| E21 | F. Autres écosystèmes | Rust (crates.io) | à faire |
| E22 | F | Go | à faire |
| E23 | F | PHP (Composer) | à faire |
| E24 | F | Ruby (Bundler) | à faire |
| E25 | F | Java (Maven, Gradle) | à faire |
| E26 | F | .NET (NuGet) | à faire |
| E27 | G. Compléments | Fin de vie des runtimes et frameworks | à faire |
| E28 | G | Fichier de code isolé | à faire |
| E29 | H. Livraison | Configuration, page Réglages, robustesse | à faire |
| E30 | H | Documentation, packaging, CI | à faire |
| E31 | H | Recette finale | à faire |

**Jalons** :

- après E08, l'analyse locale Python + npm marche en ligne de commande ;
- après E15, l'interface web fait tout le parcours local pour Python + npm ;
- après E18, le parcours complet marche avec GitHub ;
- après E20, les trois forges sont là ;
- les phases F à H élargissent et finissent.

---

## Phase A — Socle

### E01 — Squelette du projet

**But** : un paquet Python installable, une commande qui répond, des tests et un
lint qui tournent.

- [x] Demander à l'utilisateur s'il veut `git init` maintenant (le dossier n'est pas encore un dépôt git).
- [x] `pyproject.toml` :
  - nom `forceupdate`, paquet `forceupdate` en layout `src/`, `requires-python = ">=3.11"`, build `hatchling` ;
  - commande `forceupdate = "forceupdate.cli:app"` ;
  - métadonnées prêtes pour PyPI : description, licence `MIT`, classifiers, URL du dépôt ;
  - dépendances de départ : `typer`, `rich`, `httpx`, `packaging` ; en dev : `pytest`, `respx`, `ruff` ;
  - `fastapi` et `uvicorn` viendront à E12.
- [x] `LICENSE` à la racine : texte MIT standard, année 2026. Demander à l'utilisateur le nom à mettre comme titulaire du copyright.
- [x] `uv sync`, `uv.lock` versionné.
- [x] `cli.py` : `--version`, et les commandes `ui`, `scan`, `update` présentes mais qui répondent « pas encore disponible ».
- [x] `models.py` : premières structures (voir « Architecture cible »), avec docstrings. `Severity` ici, il remplacera l'enum d'Argos (`ARGOS (1)`). Les modèles devront pouvoir sortir en JSON : c'est ce que l'API renverra au front.
- [x] Config `ruff` et `pytest` :
  - `testpaths = ["tests"]`, pour que `reference/` ne soit jamais ramassé ;
  - marqueur `network` sauté par défaut, lancé avec `--run-network` (via `conftest.py`).
- [x] `.github/workflows/ci.yml` : ruff + pytest, Ubuntu et Windows, Python 3.11 et 3.14. Il servira quand le dépôt sera sur GitHub.
- [x] CLAUDE.md : ajouter une section « Commandes » (`uv sync`, `uv run pytest`, `uv run ruff check`, lancer l'outil).

**Fini quand** :

- `uv run forceupdate --version` affiche la version ;
- `uv run pytest` et `uv run ruff check` passent ;
- les 31 tests de `reference/` passent toujours depuis `reference/`.

**Notes** (session 1) :

- Réponses de l'utilisateur : `git init` fait (branche `main`, aucun commit encore) ; copyright « Pauzzle » (aussi auteur dans `pyproject.toml`) ; URL du dépôt `https://github.com/Pauzzle-ozz/forceupdate`. Ce dépôt GitHub n'existe pas encore : sa création est ajoutée à E08, avant la publication sur PyPI.
- Version `0.1.0.dev0`, écrite seulement dans `pyproject.toml` ; `forceupdate.__version__` la lit dans les métadonnées du paquet installé.
- Licence au format PEP 639 (`license = "MIT"`, `license-files`, hatchling ≥ 1.27), donc pas de classifier « License :: » : les deux ensemble sont refusés. Le sdist ne prend que `src/` et `tests/` (plus `LICENSE`, `README.md`, `pyproject.toml`) : ni `reference/` ni les notes de travail.
- Une commande pas encore écrite affiche « forceupdate <commande> : pas encore disponible. » sur stderr et sort avec le code 2 (« erreur » dans la convention de E07). `scan` et `update` acceptent déjà un chemin (par défaut `.`).
- Modèles en dataclasses de la bibliothèque standard : pas de pydantic avant E12, et FastAPI sait renvoyer des dataclasses. Décisions prises :
  - chemins : chaînes POSIX relatives à la racine de la source (le dossier choisi, ou le dépôt), la même forme sous Windows, sous Linux et sur une forge ;
  - `Ecosystem` (ajouté) : les valeurs sont les noms d'écosystème d'OSV (`PyPI`, `npm`, `crates.io`…) ;
  - enums en `StrEnum`. Pour trier `Severity` et `Gap` (ajouté), utiliser `rank` : `<` comparerait des chaînes ;
  - `Location` (ajouté) : ligne à partir de 1, colonnes à partir de 0, comptées en caractères, fin exclue. `extract(text)` découpe les lignes sur `\n` seulement. **Les parseurs (E03, E04…) suivent cette convention** ;
  - `Scope` (ajouté) : `runtime`, `dev`, `optional`, `peer`, `build`, les valeurs de `reference/` plus `build` ;
  - `FindingKind` : `outdated`, `vulnerable`, `eol`, `yanked` et `deprecated` (le type 4 en deux), plus `unverifiable` et `inconclusive` ;
  - `Dependency`, `Finding` et `Location` sont figés ; `Project` et `Report` sont modifiables, parce qu'ils se remplissent au fil de l'analyse ;
  - `Finding` est minimal : E07, E08 et E27 ajoutent ce qui leur est propre (« la plus haute dans la contrainte », date de fin de vie…) ;
  - `to_dict(model)` donne du JSON simple. `schema_version` viendra avec `report/json.py` (E07).
- pytest : `-p pytester` dans `addopts`, pour que `tests/test_conftest.py` teste le marqueur `network` lui-même. Pas de `--strict-markers` dans la config : lancés depuis `reference/`, les tests d'Argos prennent aussi notre `pyproject.toml` comme config (pytest remonte jusqu'à lui) et utilisent le marqueur `asyncio`.
- ruff : `line-length = 100`, règles `E W F I UP B SIM RUF`, `reference/` exclu. La CI vérifie aussi `ruff format --check`.
- CI : `actions/checkout@v7`, `astral-sh/setup-uv@v10` (dernières versions le 2026-10-27), `uv sync --locked`. Pas encore lancée : le dépôt n'est pas sur GitHub.
- uv a pris Python 3.12 pour `.venv`. Vérifié : 25 tests verts sous 3.11, 3.12 et 3.14 ; `ruff check` et `ruff format --check` propres ; `uv build` et `twine check` passent, `LICENSE` est dans le wheel ; les 31 tests de `reference/` passent (les 5 tests OSV restent en `skip`, comme avant).
- Constaté : sous Windows, une sortie redirigée est écrite en cp1252. Case ajoutée à E07.

---

## Phase B — Analyse locale, Python + npm

### E02 — Source locale, langages, découverte des manifestes

**But** : à partir d'un chemin, savoir quels langages sont utilisés et quels
projets (manifestes + lockfiles) il contient.

- [x] `sources/base.py` : interface `Source`, qui produit des `Project` (racine, origine, fichiers). `sources/local.py` : un dossier ou un fichier.
- [x] `detect/languages.py` :
  - extension → langage (une quarantaine de langages courants) ;
  - poids en octets, comme GitHub Linguist ;
  - fichiers générés, minifiés ou vendorisés ignorés.

  Il travaille sur une liste de `(chemin, taille)`, sans lire les fichiers, pour servir aussi aux forges (E17).
- [x] `detect/manifests.py` :
  - reprendre `_IGNORE_DIRS_COMMON`, `is_test_path`, `safe_read_text`, `DEPENDENCY_MANIFESTS`, `discover_dependency_manifests`, `MANIFEST_LOCKFILES` ;
  - passer des noms exacts à des motifs : `requirements*.txt`, `requirements/*.txt`, `*.csproj` ;
  - ajouter les noms manquants : `uv.lock`, `Pipfile`, `build.gradle(.kts)`, `gradle/libs.versions.toml`, `*.csproj`, `Directory.Packages.props`, `packages.lock.json`.
- [x] Regroupement : un dossier qui contient un manifeste = un projet. Son lockfile est dans le même dossier, ou dans un dossier parent pour les workspaces.
- [x] Table langage → écosystème. Un langage sans gestionnaire reconnu (C, C++…) est listé comme tel.
- [x] `scan <chemin>` affiche, pour l'instant, les langages et les projets trouvés.
- [x] Ajouté en route : dans un dépôt git, la liste des fichiers suit `.gitignore` (voir les notes).

**À reprendre** : `reference/argos_sca_parsers.py` L51-185, L221-381, L1388-1401.

**Tests** :

- monorepo (`backend/` Python + `frontend/` npm) ;
- `node_modules` et `.venv` ignorés ;
- fichier unique ;
- dossier vide ;
- chemin inexistant.

**Fini quand** : `scan` sur un vrai dossier (par exemple `~/Desktop/the good guy`)
donne des langages et des projets justes, vérifiés à la main.

**Notes** (session 2) :

- **`.gitignore` respecté** (ajouté au plan) : sur le disque, `the good guy` a environ 64 000 fichiers, dont 48 000 dans `protocol/runs/` (des clones d'autres dépôts, ignorés par git). Sans `.gitignore`, `scan` y trouvait des dizaines de faux projets. Donc `sources/local.py` :
  - dans un dépôt git, liste les fichiers avec `git ls-files --cached --others --exclude-standard -z` (suivis, et nouveaux non ignorés) : c'est aussi ce que voit une forge (E17). git est trouvé par `shutil.which`, lancé sans shell, avec un délai de 60 s, avec `-c core.fsmonitor=false` (un dépôt peut sinon faire lancer un programme) et sans les variables `GIT_*` héritées ;
  - hors de git (ou sans git installé), parcourt le disque. Un dépôt rangé dans le dossier (un dossier avec `.git`) est listé par git, avec son propre `.gitignore`. Un dépôt dans le dépôt (sous-module, clone non ignoré) aussi ;
  - un dossier entièrement ignoré par git, choisi exprès, est parcouru quand même ;
  - `IGNORED_DIRS` s'applique dans tous les cas (un `vendor/` ou un `node_modules/` versionné reste écarté) ;
  - les liens symboliques ne sont pas suivis du tout (comme Linguist). Limite : les sous-modules non initialisés et les jonctions Windows ne sont pas traités (E29).
- **Projets dans des dossiers de tests (tranché)** : un manifeste ou un lockfile rangé dans un dossier de tests, de fixtures ou d'exemples (`is_test_path` sur le chemin **relatif à la source**) **ne fait pas un projet** par défaut. Ce sont des mini-projets de démonstration, souvent figés exprès sur de vieilles versions : `tests/projects/` de forceupdate aura `lodash 4.17.15` et `flask 0.12` (E08), on ne veut ni constats ni PR dessus. C'est aussi le réglage par défaut de Renovate (`**/test/**`, `**/tests/**`, `**/examples/**`…). Ils ne sont pas cachés : `Report.ignored_manifests` les liste, et `scan` les affiche. `engine.scan(include_tests=True)` les garde ; une option pour l'utilisateur viendra avec la configuration (E29). Choisir le dossier `tests/` lui-même les analyse, puisque le chemin relatif ne passe plus par `tests/`.
- **Modèles modifiés** :
  - `Report.languages` devient une liste de `Language(name, bytes, ecosystem)`, du plus lourd au plus léger, au lieu de `dict[str, int]` : le front doit savoir quel langage n'a pas de gestionnaire reconnu sans refaire la table (`ecosystem=None`) ;
  - `Project.ecosystems` (ajouté), dans l'ordre de `Ecosystem` ;
  - `Report.ignored_manifests` (ajouté).
- **`Source` ne fabrique pas les `Project` elle-même** : elle donne `origin`, `files()` (des `SourceFile(path, size)`, qui sont des tuples `(chemin, taille)`) et `read_text(path)`. Le regroupement est dans `detect/manifests.py` (`find_projects`), commun au local et aux forges, et `engine.scan(source)` enchaîne le tout (`engine.py` ajouté à l'architecture). `SourceError` porte un message en français, montré tel quel (`scan` sur un chemin inexistant : « forceupdate scan : le chemin « … » n'existe pas. », code 2). `LocalSource.read_text` refuse un chemin qui sort de la source (`ValueError`).
- **Fichier seul** : analysé avec les lockfiles posés à côté de lui (`lockfile_candidates`). Pour `requirements/dev.txt` ou `gradle/libs.versions.toml`, la racine est le dossier du dessus, pour que le motif reste reconnu. Un fichier de code seul donne ses langages et aucun projet (E28 fera mieux).
- **Langages** (`detect/languages.py`) : 57 langages, sur les noms de Linguist. Seuls comptent la programmation et le balisage, comme chez Linguist (`build.gradle`, JSON, YAML, Markdown ne comptent pas). Écartés sur le chemin seul : règles de `vendor.yml` (`vendor/`, `dist/`, `.github/`, `*.min.js`, jQuery, wrappers Gradle…), de `generated.rb` (`*.pb.go`, `*_pb2.py`, `*.Designer.cs`, `__generated__/`, `*.g.dart`) et de `documentation.yml` (`docs/`, `examples/` à la racine, `documentation/` partout). Linguist lit aussi le contenu et `.gitattributes` : pas nous. Un `.h` va au C s'il y en a, sinon au C++, sinon à l'Objective-C. Un langage à 0 octet n'apparaît pas.
- **Fichiers de dépendances** (`detect/manifests.py`) :
  - motifs comparés sans la casse, avec `fnmatch` ; un motif avec un dossier (`requirements/*.txt`, `gradle/libs.versions.toml`) rattache le fichier au projet du dessus ;
  - manifestes et lockfiles séparés (`DEPENDENCY_MANIFESTS`, `LOCKFILES`), alors qu'Argos les mélangeait ;
  - ajoutés en plus de la liste du plan : `requirements*.in` (pip-tools, utile à E03 et E11), `*.fsproj`, `*.vbproj` (E26), `pdm.lock` (déjà dans `MANIFEST_LOCKFILES` d'Argos) ;
  - un dossier avec seulement un lockfile est aussi un projet, pour ne rien perdre ;
  - lockfile de workspace : un projet sans lockfile sur place prend celui du plus proche dossier parent qui a **le même manifeste** et un lockfile qui va avec, pour `package.json` (npm, Yarn, pnpm), `pyproject.toml` (`uv.lock` seulement) et `Cargo.toml`. Pas pour Poetry, Pipenv, Bundler, Composer, qui n'ont pas de workspaces. Rattaché par proximité, sans lire les fichiers : l'appartenance au workspace est vérifiée par les parseurs (cases ajoutées à E03, E04, E21) ;
  - `is_test_path` corrigé : il travaille sur les éléments du chemin (le chemin relatif `tests/x` ne commence pas par `/`) ; les fins `Test.java`, `Test.cs` gardent la casse (`Contest.java` n'est pas un test) ; les fins de noms sont testées avec `endswith`, plus avec `in` ;
  - `IGNORED_DIRS` (ex-`_IGNORE_DIRS_COMMON`, public parce que `sources/` s'en sert) : `egg-info` ne marchait pas (les dossiers s'appellent `x.egg-info`), remplacé par un test de suffixe. Ajoutés : `.yarn` (ses `sdks/` contiennent des `package.json`), `.pnpm-store`, `jspm_packages`, `target` (Cargo, Maven), `.gradle`, `.terraform`, `.dart_tool`, `.angular`, `.turbo`, `.output`, `Pods`, `site-packages`, `.nox`, `.hypothesis`, `htmlcov` ;
  - `discover_dependency_manifests` prend des chemins au lieu de parcourir le disque : le parcours est dans `sources/local.py`.
- **`scan`** : affichage provisoire dans `cli.py` (`_print_report`), en texte simple, pourcentages à la française. E07 le remplace par `report/terminal.py`.
- **Vérifié à la main** :
  - `scan "C:/Users/pauzzle/Desktop/the good guy"` (moins d'une seconde) : Python 90,4 %, JavaScript 8,8 %, HTML 0,3 %, CSS 0,3 %, Shell 0,1 %, Dockerfile 0,0 %. Recompté à part sur `git ls-files` : 28,43 Mo de `.py` et 2,78 Mo de `.js` / `.jsx` / `.mjs` sur 31,43 Mo, soit les mêmes chiffres. Pas de Go : `tools/oob-server-go` n'a qu'un Dockerfile et un README dans git. Deux projets, les seuls manifestes suivis par git : `.` (`pyproject.toml` + `uv.lock`) et `sechunter/dashboard/frontend` (`package.json` + `package-lock.json`) ;
  - `scan` sur `protocol/runs/2026-09-18-campagne/depots` (dossier ignoré, avec trois clones dedans) : 37 projets. Les 18 membres du workspace pnpm d'ariakit prennent le `pnpm-lock.yaml` de la racine ; juju donne `go.mod` + `go.sum`. Écartés : `examples/package.json` d'ariakit, et deux `go.mod` sous `tests/` de juju ;
  - fichier seul (`package.json` → avec son `package-lock.json` ; `main.jsx` → JavaScript, aucun projet), chemin inexistant (code 2).
- Tests : 202 verts sous 3.11, 3.12 et 3.14, ruff propre. Le test des liens symboliques est sauté sous Windows (pas le droit d'en créer) ; il tournera sous Linux en CI. Fixtures communes ajoutées à `conftest.py` : `make_tree` (crée une arborescence) et `no_git` (fait comme si git n'était pas installé). Les tests git sont sautés si git est absent.

### E03 — Parseurs Python, lien manifeste ↔ lockfile

**But** : pour un projet Python, la liste juste des dépendances directes, avec
leur contrainte, leur emplacement et leur version installée.

- [x] Reprendre `parse_requirements_txt`, `parse_pyproject_toml`, `_parse_pep508`, `parse_poetry_lock`, `parse_pipfile_lock`, avec leurs tests.
- [x] Corriger les limites de `reference/README.md` :
  - `-r autre.txt` et `-c` suivis (sans boucle infinie) ;
  - `poetry.lock` sans `category` : le scope vient des groupes du `pyproject.toml` ;
  - dépendances URL ou chemin (`pkg @ git+https://…`) : non vérifiables.
- [x] Ajouter les parseurs `uv.lock` (TOML), `Pipfile` (TOML) et `setup.cfg` (`install_requires`). `setup.py` est signalé « non lu » : il faudrait l'exécuter.
- [x] Noms normalisés selon PEP 503.
- [x] Emplacement exact de chaque contrainte (ligne, colonnes de début et de fin), pour E10.
- [x] Lien manifeste ↔ lockfile :
  - directes = celles du manifeste ;
  - version installée = celle du lockfile ;
  - le reste du lockfile = transitives (`direct=False`).
- [x] Workspace uv : E02 rattache le `uv.lock` du dossier parent le plus proche, sans lire les fichiers. Vérifier que le projet est bien membre (`[tool.uv.workspace] members` / `exclude` du `pyproject.toml` racine) ; sinon, pas de lockfile pour lui.
- [x] Le moteur (`engine.scan`) appelle les parseurs pour chaque projet, en lisant les fichiers avec `Source.read_text`, et remplit `Project.dependencies`.
- [x] `scan` affiche aussi, provisoirement (comme à E02), les dépendances directes de chaque projet : nom, contrainte, version installée. C'est ce qui permet de vérifier à la main.
- [x] Ajoutés en route : `pdm.lock` lu (E02 le repère déjà) ; `Project.notices` pour ce qui n'a pas pu être lu ; plafond de 50 Mo pour tous les lockfiles (voir les notes).

**À reprendre** : `reference/argos_sca_parsers.py` L389-645, et les classes de test `TestParseRequirementsTxt`, `TestParsePipfileLock`, `TestParsePoetryLock`, `TestParsePyprojectToml`.

**Fini quand** : sur des mini-projets pip, pip-tools, Poetry, uv et Pipenv
(`tests/projects/`), on obtient les bonnes directes et les bonnes versions
installées.

**Notes** (session 3) :

- **Organisation** :
  - `parsers/__init__.py` : `parse_project(project, read_text)`, qui choisit le parseur par écosystème. Un écosystème pas encore lu (npm jusqu'à E04…) donne une remarque, pour que le rapport ne laisse pas croire que le projet n'a pas de dépendances ;
  - `parsers/base.py` : `ParseError`, `ReadText` ;
  - `parsers/toml_spans.py` (ajouté) : `tomllib` ne donne pas les positions. Ce module parcourt un document déjà validé par `tomllib` et rend, pour chaque chaîne sur une ligne, sa ligne et ses colonnes, par chemin (`("project", "dependencies", 3)`). Il resservira pour `Cargo.toml` (E21), `libs.versions.toml` (E25) et l'auto-vérification de E10 ;
  - `parsers/python.py` : les parseurs par fichier (`parse_requirements_txt`, `parse_pyproject_toml`, `parse_pipfile`, `parse_setup_cfg`, `parse_uv_lock`, `parse_poetry_lock`, `parse_pdm_lock`, `parse_pipfile_lock`), puis le lien par projet (`parse_project`).
- **Modèle** : `Notice(file, message)` et `Project.notices` (ajoutés). C'est ce que l'analyse n'a pas pu faire : `setup.py` non lu, TOML ou JSON invalide, fichier illisible ou trop gros, `-r` hors du dossier, lockfile écarté, écosystème pas encore lu. Argos rendait une liste vide pour un fichier invalide ; le test repris `test_invalid_json_returns_empty` devient `test_invalid_json_raises` (`ParseError`).
- **Une `Dependency` par déclaration**. Un paquet déclaré deux fois dans un fichier (runtime et groupe dev, ou deux extras) donne deux `Dependency`, chacune avec son emplacement : il faut réécrire les deux. Dans Argos : `httpx` et `ruff` (runtime + dev), `playwright` (extras `browser` et `screenshots`). « Sans doublon » veut dire qu'un fichier atteint par plusieurs `-r` est lu une fois, et qu'une déclaration n'est jamais rendue deux fois.
- **Contraintes et emplacements** :
  - la contrainte est gardée telle qu'écrite (`>= 2.25, < 3`, `^2.31`, `*`). Celles de Poetry (`^`, `~`, version nue, `*`) et de Pipfile (`*`) ne sont pas du PEP 440 : noté pour E05 ;
  - sans contrainte, l'emplacement est vide, juste après le nom et les extras : c'est là qu'E10 en insérerait une ;
  - pas d'emplacement (`None`) pour une dépendance git ou URL, une contrainte TOML qui contient un échappement, ou une contrainte continuée sur la ligne suivante (`\` dans un `requirements.txt`) ;
  - vérifié : sur Argos et les six mini-projets, chaque emplacement redonne exactement la contrainte (test `test_every_location_points_at_its_constraint`).
- **Scopes** :
  - extras et groupes (PEP 735, groupes Poetry, catégories Pipfile) : `dev` si le nom l'indique (`dev…`, `test…`, `lint`, `doc(s)`, `typing`, `ci`…), sinon `optional`. Le groupe Poetry `main` est `runtime`, une dépendance Poetry `optional = true` est `optional` ;
  - `[build-system] requires` et `setup_requires` : `build`. Elles ne prennent pas de version dans le lockfile (uv ne les fige pas), et ne cachent pas une transitive du même nom ;
  - `requirements` : d'après le nom du fichier, puis un fichier tiré par `-r` depuis un fichier `runtime` est `runtime` ;
  - transitives : avec le graphe (`uv.lock`, `poetry.lock`), le scope des directes qui les tirent, extras compris, dans l'ordre `runtime` > `peer` > `optional` > `dev`. C'est ce qui règle `poetry.lock` sans `category` (Poetry 1.5 à 1.8). Sans graphe : ce que dit le lockfile (`category`, `groups`, section `develop`), sinon `runtime`.
- **Non vérifiables** (raison en français, sans jamais citer l'URL, qui peut contenir un token) : dépendance git (ou hg, svn, bzr), chemin local, URL, membre du workspace, et paquet attaché explicitement à un autre index (`index =` de uv, `source =` de Poetry, `index =` de Pipfile). Un index global (`--index-url`, miroir de PyPI) ne rend rien non vérifiable. Le projet qui se cite lui-même (`sechunter[all]`) est sauté, comme `-e .` et les chemins locaux sans nom de paquet.
- **pip-tools (tranché)** : un `X.txt` posé à côté d'un `X.in` du même nom est le lockfile du `.in`. C'est décidé sur les chemins, dans `detect/manifests.py` (`compiled_requirements`) : le `.txt` passe dans `Project.lockfiles`, et `lockfile_candidates("requirements.in")` donne le `.txt`. Les directes viennent du `.in`, la version installée des `==` du `.txt`, et le reste du `.txt` donne des transitives qui gardent leur contrainte `==X` et leur emplacement. Limite : un `requirements.txt` généré sans `.in` à côté (`uv export`, `poetry export`, `pip-compile pyproject.toml`) reste un manifeste, et tous ses paquets sortent comme directes (case ajoutée à E29).
- **`-r` et `-c`** : chemins relatifs au fichier qui les cite, comme pip ; chaque fichier lu une fois (les cycles ne bouclent pas). Un fichier `-c` fixe la version installée des directes des fichiers lancés avec lui ; ses autres lignes sont des transitives. URL, chemin absolu ou sortie du dossier : remarque, pas suivi.
- **Lockfile d'un `pyproject.toml`** : `poetry.lock` s'il y a `[tool.poetry]`, `pdm.lock` s'il y a `[tool.pdm]`, sinon `uv.lock`, `poetry.lock`, `pdm.lock` dans cet ordre. Un autre lockfile présent reçoit une remarque « pas lu ». Un lockfile sans manifeste : tout son contenu est transitif.
- **Workspace uv** : membre si le chemin du projet, relatif à la racine, correspond à un motif de `members` (`*`, `**`) et à aucun de `exclude`. Les membres héritent des `[tool.uv.sources]` de la racine (`{ workspace = true }`…). Un non-membre perd le `uv.lock` (retiré de `Project.lockfiles`, sans remarque). Comme `uv.lock` couvre tout le workspace, un projet n'y prend que les paquets que tirent ses directes ; les membres eux-mêmes (`editable`, `virtual`) ne sont jamais des transitives.
- **Plusieurs versions d'un paquet dans `uv.lock`** (fourches par marqueurs : `numpy` 1.x pour Python < 3.10, 2.x au-dessus) : la version installée est la plus haute, les autres ne sont pas listées. Noté pour E08.
- **Plafond de lecture** : `DEFAULT_MAX_LOCKFILE_SIZE` (50 Mo) pour tous les lockfiles, npm compris, via `max_read_size(path)` dans `LocalSource.read_text` ; 2 Mo pour le reste. Le `.txt` compilé de pip-tools garde 2 Mo.
- **`setup.cfg`** : `install_requires` (`runtime`), `extras_require`, `tests_require` (`dev`), `setup_requires` (`build`). Comme setuptools : une dépendance par ligne si la valeur est sur plusieurs lignes, sinon séparées par `;`.
- **`scan`** : sous chaque projet, les directes (nom, contrainte, version installée ; scope s'il n'est pas `runtime`, fichier s'il y en a plusieurs, raison si non vérifiable), le nombre de transitives, et les remarques. Toujours provisoire : E07 le remplace.
- **Mini-projets** (`tests/projects/`, avec un `README.md`) : `pip`, `pip-tools`, `poetry`, `uv` (workspace : un membre, un exclu, un projet hors `members`), `pipenv`, et `setuptools` (ajouté : `setup.cfg` + `setup.py`). Les lockfiles viennent des vrais outils : `uv lock` (uv 0.10.11), `pip-compile` (pip-tools, Python 3.12), `poetry lock` de Poetry 1.8.5 (`lock-version = "2.0"`, sans `category` ni `groups`), `pipenv lock`. Leurs versions sont celles du jour (flask 3.1.3, requests 2.34.2…).
- **Vérifié à la main** :
  - `scan "C:/Users/pauzzle/Desktop/the good guy"` (0,65 s) : 62 directes du `pyproject.toml` (43 runtime, 10 optional, 8 dev, `hatchling` en build), 95 transitives. Versions relues dans `uv.lock` avec `awk` : anthropic 0.125.0, cryptography 50.0.2, sslyze 6.3.1, python-dateutil 2.9.0.post0, mcp 2.3.0, xxhash 4.0.2, types-pyyaml 6.0.12.20260906. Le compte tombe juste : 154 paquets − 1 local (`sechunter`) − 58 directes présentes dans le lock = 95. Transitives en `dev` : `coverage`, `iniconfig`, `pluggy`, `mypy-extensions`… (pytest, pytest-cov, mypy) ;
  - les six mini-projets, comparés à leurs lockfiles. Dans Poetry, `colorama` est bien `dev` : `click` 8.5.0 n'en dépend plus (le lock et pip-compile le confirment).
- Tests : 285 verts sous 3.11, 3.12 et 3.14, ruff propre ; les 31 tests de `reference/` passent toujours.

### E04 — Parseurs npm (npm, Yarn, pnpm)

**But** : même chose que E03 pour JavaScript / TypeScript.

- [x] Reprendre `parse_package_json`, `parse_package_lock_json`, `parse_yarn_lock`, `parse_pnpm_lock_yaml`, avec leurs tests.
- [x] Corriger :
  - `_strip_npm_version` : `^1.2`, `1.x`, `>=1 <2`, `||` → garder la contrainte brute (la borne basse viendra de E05) ;
  - `git+…`, `file:`, `link:`, `workspace:` : non vérifiables ;
  - `npm:autre@1.0` : alias, on vérifie le vrai paquet.
- [x] Ajouter Yarn 2+ (`yarn.lock` au format YAML) et pnpm v6 et v9 (`pyyaml`).
- [x] Lockfile v2/v3 : directes = `packages[""]`, version installée = `packages["node_modules/x"]`.
- [x] Workspaces npm, Yarn et pnpm : un lockfile à la racine pour plusieurs `package.json`. E02 rattache déjà le lockfile du dossier parent le plus proche, sans lire les fichiers : vérifier l'appartenance (`workspaces` du `package.json` racine, `pnpm-workspace.yaml`, ou l'entrée `packages["chemin/du/membre"]` du lockfile v2/v3).
- [x] Relever le plafond de taille pour les lockfiles (un `package-lock.json` dépasse souvent 2 Mo). Déjà fait à E03 pour tous les lockfiles (50 Mo, `max_read_size`) : reste à le vérifier sur un gros `package-lock.json`.
- [x] Emplacement exact de chaque contrainte dans `package.json`.
- [x] Suivre le schéma de E03 : `parsers/npm.py` enregistré dans `_PARSERS` de `parsers/__init__.py` (la remarque « dépendances npm pas encore lues » disparaît), un fichier invalide donne une `Notice`, les tests sur des mini-projets dans `tests/projects/` vérifient que chaque emplacement redonne la contrainte.
- [x] Ajoutés en route : le lien manifeste ↔ lockfile sorti de `parsers/python.py` dans `parsers/lockfiles.py`, commun aux écosystèmes ; un graphe de lockfile en nœuds (un paquet npm peut être installé en plusieurs versions) ; pnpm 5.4 (pnpm 7), package-lock v1, et le lockfile à deux documents de pnpm 11+ ; les membres d'un workspace Yarn 1, absents de son `yarn.lock` (voir les notes).

**À reprendre** : `reference/argos_sca_parsers.py` L405-416, L648-797, et les classes de test `TestParsePackageJson`, `TestParsePackageLockJson`, `TestParseYarnLock`.

**Fini quand** : des mini-projets npm, Yarn 1, Yarn 4, pnpm 9, et un workspace
donnent les bonnes directes et versions installées.

**Notes** (session 4) :

- **Organisation** :
  - `parsers/lockfiles.py` (ajouté) : ce qui, dans `parsers/python.py`, ne dépendait pas de PyPI. `Declared`, `LockedPackage`, `Lockfile` (qui porte maintenant son `ecosystem`), `with_installed`, `transitives`, `reachable_scopes`, `reach`, `graph_starts`, et les aides de workspace (`in_workspace`, `glob_match`) et de chemins (`dirname`, `join`, `relative_to`). La façon de trouver la version installée reste propre à chaque écosystème : `python.installed_version` (la plus haute selon PEP 440, pour les fourches de `uv.lock`), la résolution de `node_modules` pour npm. Les raisons `REASON_*` sont passées dans `parsers/base.py` ;
  - `parsers/json_spans.py` (ajouté) : l'équivalent de `toml_spans.py` pour JSON. Il reprend `StringSpan`, qui compte maintenant une paire de substituts (`\ud83d\ude00`) pour un caractère, comme `json.loads`. Un `BOM` en tête (éditeurs Windows) est accepté : npm l'ignore, `json.loads` le refuse ;
  - `parsers/npm.py` : `parse_package_json` (des `Dependency`), `parse_package_lock_json`, `parse_yarn_lock`, `parse_pnpm_lock_yaml` (des `NpmLockfile` : les paquets, plus ce que chaque projet du lockfile reçoit), puis `parse_project` ;
  - `parsers.parse_project(project, read_text, project_dirs)` : nouvel argument, les dossiers de tous les projets de la source (le moteur les passe). Il ne sert qu'aux workspaces Yarn 1 ;
  - `pyyaml` 6.0.3 ajouté, lu avec `CBaseLoader` (libyaml, et des chaînes seulement : `1.10` reste `"1.10"`, rien d'autre n'est construit).
- **Graphe en nœuds (tranché)** : avec le graphe par noms de E03, un workspace npm attribuait à un membre les versions d'un autre (`is-number 6.0.0` de la racine se retrouvait chez `packages/lib`). npm installe un même paquet en plusieurs versions ; donc chaque `LockedPackage` a une clé (`node`) et ses dépendances désignent des clés, résolues exactement : chemin `node_modules/a/node_modules/x` (en remontant les dossiers comme Node) pour `package-lock.json`, descripteur (`lodash@^4.17.0`) pour Yarn, référence (`react-dom@18.3.1(react@18.3.1)`) pour pnpm. Les projets d'un workspace sont des nœuds aussi (`importer:packages/lib`, locaux) : ce qu'un membre tire revient à ceux qui en dépendent, comme pour uv. Python garde des nœuds par nom (clé vide).
- **Directes et versions installées** :
  - les directes viennent du `package.json`, que `packages[""]` répète (npm l'écrit toujours) ; leur version est celle du nœud que le projet reçoit ;
  - une directe que le lockfile résout vers un projet local devient « membre du workspace » : `"a": "^1.0.0"` dans un workspace npm désigne le membre `packages/a`, pas le paquet `a` du registre, qu'E07 aurait interrogé ;
  - un pair (`peerDependencies`) n'a de version que si l'outil l'installe : npm 7+ et pnpm 8+ oui, Yarn et pnpm 7 non.
- **Transitives** : une par (nom, version). Une autre version du nom d'une directe en est une (`node_modules/is-odd/node_modules/is-number` 6.0.0 à côté de la directe 7.0.0) : E08 devra toutes les vérifier. Scope : celui des directes qui les tirent (`runtime` > `peer` > `optional` > `dev`), sinon les drapeaux du lockfile (`dev`, `devOptional`, `optional`, `peer`), sinon `runtime`. Le lockfile d'un workspace (plusieurs projets dedans, ou des motifs de workspace) est « partagé » : un projet n'y prend que ce que tirent ses directes. Hors workspace, tout le lockfile est au projet. Les entrées `patch:` que Yarn 4 ajoute d'office (`typescript`, `fsevents`) ne sont pas une deuxième fois des transitives.
- **Contraintes** (telles qu'écrites, sans les espaces autour) :
  - `^1.2`, `1.x`, `>=1 <2`, `^1 || ^2`, `1.2.3 - 2.3.4`, `*`, `""`, et les étiquettes (`latest`) : E05 les interprétera ;
  - alias `npm:autre@^1.0` : le paquet `autre`, contrainte `^1.0`, emplacement sur `^1.0` seulement ; `npm:^1.0` (Yarn 2+) désigne le paquet de la clé ; `npm:autre` sans version : contrainte vide, sans emplacement (il faudrait ajouter le `@`) ;
  - `catalog:` (catalogues pnpm) : gardé tel quel, sans emplacement. La vraie plage est dans `pnpm-workspace.yaml` (case ajoutée à E05 et E10) ;
  - non vérifiables, sans contrainte ni emplacement (une URL peut contenir un token) : git (`git+…`, `git:`, `github:`, `gitlab:`, `bitbucket:`, `gist:`, `utilisateur/depot`, URL en `.git`), chemin local (`file:`, `link:`, `portal:`, `exec:`, `./`, `../`, `/`), URL d'archive, `workspace:`, et `patch:` (« modifiée par un correctif local (patch:) »).
- **Formats**, chacun vérifié sur la sortie des vrais outils (npm 11.6, Yarn 1.22 et 4.18, pnpm 7.33, 8.15, 9.15) :
  - `package-lock.json` v1 (npm 5 et 6) : son arbre `dependencies` est remis sous la forme `packages` des v2 et v3, puis lu pareil ;
  - `yarn.lock` de Yarn 1 : un petit lecteur du format (indentation, guillemets). Yarn l'écrit en CRLF sous Windows ;
  - Yarn 2+ : reconnu à sa section `__metadata` ; le nom vient de `resolution` (`ms@npm:2.0.0` pour un alias) ;
  - pnpm 5.4 (`/nom/1.0.0_pair@2`), 6.0 (`/nom@1.0.0(pair@2)`), 9.0 (`nom@1.0.0(pair@2)`, `snapshots`). Sans workspace, avant le format 9, le projet est écrit à la racine du fichier ;
  - **pnpm 11+** (trouvé sur ariakit, `pnpm@12.4.1`) : `pnpm-lock.yaml` commence par un document YAML qui fige pnpm lui-même, puis vient le lockfile du projet après `---`. On lit le dernier document ;
  - dépendance git : `resolved: git+ssh://…` (npm), descripteur `github:…` (Yarn 1), clé `github.com/…` avec `name` et `version` à côté (pnpm 6), clé `nom@https://codeload…` (pnpm 9).
- **Choix du lockfile** : celui de `packageManager` (`"pnpm@9.15.9"`) du `package.json` du dossier du lockfile, sinon dans l'ordre `npm-shrinkwrap.json` (npm ignore alors `package-lock.json`), `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`. Les autres reçoivent « pas lu : X est le lockfile pris pour package.json ».
- **Workspaces** : un projet est membre si le lockfile le décrit (`packages["chemin"]` de npm, `importers` de pnpm, `nom@workspace:chemin` de Yarn 2+), ou si son chemin correspond aux `workspaces` du `package.json` racine (liste, ou `{packages: […]}` de Yarn 1) ou aux `packages` de `pnpm-workspace.yaml`, où `!motif` exclut. Sinon il perd le lockfile, sans remarque (comme uv). La cible d'un `file:` que décrit le `package-lock.json` est membre aussi : ses dépendances sont installées dans l'arbre de la racine. **Yarn 1 n'écrit pas les membres dans `yarn.lock`** : on les reconstruit depuis leurs `package.json` (d'où `project_dirs`), sinon `"a": "^1.0.0"` vers le membre `a` partait au registre et ce que `a` tire était perdu.
- **Lockfile seul, ou `package.json` illisible** : tout le lockfile est transitif, comme en Python.
- **Performance** : le lockfile d'un workspace est lu par chacun de ses membres ; il n'est analysé qu'une fois par contenu (`functools.lru_cache`, 4 lockfiles). ariakit (21 projets, `pnpm-lock.yaml` de 770 Ko, 2 059 paquets) : 4,9 s → 1,2 s. Plafond de 50 Mo vérifié : un test lit un `package-lock.json` de 3 Mo par `LocalSource` ; à la main, un `package-lock.json` de 26,6 Mo (80 000 paquets en chaîne) passe en 2,2 s.
- **Pas lus** (cases ajoutées) : `overrides` (npm), `resolutions` (Yarn), `pnpm.overrides`, qui forcent la version d'une transitive (E09) ; la plage d'un `catalog:` (E05, E10). `engines.node` est prévu à E27. `bundleDependencies` n'est pas traité à part : les paquets embarqués sont dans le lockfile (`inBundle`) et sortent comme transitives.
- **Mini-projets** (`tests/projects/`, README complété) : `npm` (chaque forme de plage, alias, `file:`, pair, facultative, version imbriquée), `yarn1` (le même `package.json`), `yarn4` (workspace, `typescript` et `fsevents` patchés d'office), `pnpm9` (workspace, membres reliés par `workspace:*`, un exclu), `npm-workspace` (deux membres en conflit de versions, un dossier hors workspace). Les formats plus anciens (package-lock v1, pnpm 5.4 et 6.0, git) sont testés sur des extraits de vrais fichiers dans `tests/test_parsers_npm.py`. Dans le scratchpad, npm v1, v2 et v3 et Yarn 1 donnent le même résultat sur le même projet, et pnpm 7, 8 et 9 aussi.
- **Vérifié à la main** :
  - `scan "C:/Users/pauzzle/Desktop/the good guy"` (0,8 s) : `sechunter/dashboard/frontend`, 24 directes (7 runtime, 17 dev) et 389 transitives. Versions relues dans `package-lock.json` avec `grep` : dompurify 3.4.17, react-router-dom 7.18.4, recharts 3.10.1, puppeteer 25.16.0, vite 8.3.5, @types/react 19.3.0, eslint-plugin-react-hooks 7.1.1. Le compte tombe juste : 413 paires (nom, version) distinctes − 24 directes = 389. La partie Python ne bouge pas (62 directes, 95 transitives), et les 86 emplacements d'Argos redonnent leur contrainte ;
  - les clones de `protocol/runs/2026-09-18-campagne/depots` : ariakit donne 21 projets npm sans remarque (avant le correctif du lockfile à deux documents : « YAML invalide » partout) ; juju n'a que des remarques Go, attendues.
- Tests : 375 verts sous 3.11, 3.12 et 3.14, ruff propre.

### E05 — Versions : comparer, classer l'écart, tester une contrainte

**But** : une interface commune de versions, implémentée pour PyPI et npm.

- [x] `versions/base.py` : `parse`, `compare`, `is_prerelease`, `gap(a, b)` (`patch` / `minor` / `major`), `satisfies(constraint, version)`, `lower_bound(constraint)`, `max_satisfying(constraint, versions)`.
- [x] PyPI : `packaging` (`Version`, `SpecifierSet`). Les contraintes Poetry (`^1.2`, `~1.2`, `1.2.*`, version nue `6.0.2`, `*`, `||`) et Pipfile (`*`) sont gardées telles qu'écrites depuis E03 : ce n'est pas du PEP 440, il faut les traduire (une chaîne que `SpecifierSet` refuse est de la syntaxe Poetry).
- [x] npm :
  - semver 2.0, écrit à la main (pas de dépendance) ;
  - plages npm : `^`, `~`, `x`, `*`, `||`, `a - b`, `>= <` ;
  - règles du 0.x : `^0.2.3` veut dire `<0.3.0`.
- [x] Contraintes npm gardées telles qu'écrites depuis E04, qui ne sont pas des plages : `""` (veut dire `*`), une étiquette (`latest`, `next` : pas de borne basse), `catalog:` (la plage est dans `pnpm-workspace.yaml`, sous `catalog:` ou `catalogs:` ; la lire là, ou à défaut se fier à la version installée). Pour un alias (`npm:autre@^1.0`), E04 donne déjà la plage seule.
- [x] Pré-versions exclues des candidates, sauf si la version actuelle en est une.
- [x] L'interface accueille les autres écosystèmes, ajoutés à leur étape (E21-E26).
- [x] Ajoutés en route : `candidates`, `latest`, `highest`, `sort_key` ; `Dependency.resolved_constraint` et `effective_constraint` (plage d'un catalogue pnpm) ; le tri des transitives par version ; le mini-projet `pnpm-catalog` (voir les notes).

**Tests** :

- tableaux de cas : `1.10 > 1.9`, `1.0.0-beta < 1.0.0`, `2.0.0rc1` pré-version, règles du 0.x ;
- exemples de la doc node-semver ;
- exemples de PEP 440.

**Fini quand** : tous les cas passent ; aucune comparaison de versions ailleurs
dans le code ne passe par des chaînes.

**Notes** (session 5) :

- **Organisation** :
  - `versions/base.py` : `VersionScheme` (les règles d'un écosystème), `Constraint` (une contrainte lue), `InvalidVersion`, `InvalidConstraint` ;
  - `versions/pypi.py` (`PYPI`), `versions/npm.py` (`NPM`, `SemVer`, `NpmRange`) ;
  - `versions.for_ecosystem(Ecosystem)` : les règles d'un écosystème, `LookupError` s'il n'est pas encore géré ;
  - versions et contraintes entrent et sortent en chaînes. Un écosystème n'écrit que `parse`, `parse_constraint`, `_release` et `_is_pre` (plus `_same_release` et `_gap` au besoin) ; l'écart, les candidates et les recherches sont communs ;
  - ajoutés au plan : `candidates` (les versions qu'on peut proposer), `latest` (la plus haute candidate, pour E07), `highest` (pré-versions comprises, pour les fourches de `uv.lock`), `sort_key` (un tri qui ne lève jamais : les versions lisibles d'abord, puis le reste par texte). Versions et contraintes lues sont gardées en cache (`lru_cache`).
- **Écart et 0.x (tranché)** : `gap` suit `^`. En `0.y.z`, `y` est la majeure (`0.2.3` → `0.3.0` majeure, `0.2.3` → `0.2.4` correctif) ; en `0.0.z`, tout changement est majeur. Ça vaut pour npm et PyPI : fastapi `0.110` → `0.115` est majeure, et elle casse souvent. E09 ne pré-coche donc pas une montée de `0.y`. Autres règles :
  - depuis une pré-version, celle de `semver.diff` : `1.0.0-rc.1` → `1.0.0` est majeure, `1.2.0-rc.1` → `1.2.0` mineure ;
  - PyPI : changer d'époque (`1!`) est majeur, un 4ᵉ nombre ou une post-version est un correctif.
- **Pré-versions** : écartées des candidates. Si la version actuelle en est une, seules celles de la même version restent : de `2.0.0-rc.1`, on propose `2.0.0-rc.2`, pas `2.1.0-beta.1`. C'est plus étroit que le « sauf si la version actuelle en est une » du plan : sinon, on proposerait `2.1.0-beta.1` à quelqu'un sur `2.0.0-rc.1` alors que `2.0.0` est sortie.
- **`satisfies`** :
  - npm suit node-semver : une pré-version ne respecte une plage que par un comparateur qui en porte une sur le même `major.minor.patch` ;
  - PyPI : une contrainte est un ensemble de versions, et `2.0rc1` respecte `>=1.0` (`contains(…, prereleases=True)`). `packaging` 26 fait déjà ça par défaut, on le fixe. Ce sont les candidates qui écartent les pré-versions. `<2.0` écarte quand même `2.0rc1`, c'est une règle de PEP 440.
- **`lower_bound`** :
  - npm : comme `semver.minVersion` (`>1.2.3` → `1.2.4`, `^1.2` → `1.2.0`), sauf sans borne basse (`*`, `<2`, `^0`, `>=0.0.0`, une union dont un membre n'en a pas) : `None` au lieu de `0.0.0`. Une version actuelle « 0.0.0 » donnerait de faux constats ;
  - PyPI : la borne telle qu'écrite (`^1.2` → `1.2`). Pour `>1.2`, `1.2` : PEP 440 n'a pas de « version suivante ».
- **PyPI** : `SpecifierSet` d'abord. S'il refuse, c'est de la syntaxe Poetry, traduite en PEP 440 : `^`, `~`, jokers `.*` et `.x`, version nue, `=`, `<>`, `*`, contraintes séparées par des virgules ou des espaces, `||` et `|`. Une union est une liste de `SpecifierSet`. La borne haute de `^` et `~` garde la précision de la version (`^1.2` → `<2.0`, `~1` → `<2`). Un membre vide d'union est refusé, comme le fait Poetry.
- **npm** :
  - versions publiées en semver 2.0 strict (`v` toléré devant, comme node-semver) ; plages en mode lâche, comme npm (`v`, `=`, zéros en tête, `1.2.3beta`, versions partielles) ;
  - `str()` d'une plage donne la forme de `semver.validRange` : c'est ce que testent les exemples du README ;
  - un écart voulu : en mode lâche, node-semver ignore en silence un comparateur illisible (`>=1.2.3<2` devient `*`). Ici, `InvalidConstraint` : « non concluant » plutôt qu'une plage fausse ;
  - expressions en `re.ASCII` : sinon `\d` accepte les chiffres arabes-indiens.
- **Contraintes npm qui ne sont pas des plages** :
  - `""` veut dire `*` ;
  - une étiquette (ce qui n'est pas une plage et commence par une lettre : `latest`, `next`, `v4-lts`) accepte toutes les versions, pré-versions comprises, et n'a pas de borne basse. `NpmRange.tag` la donne : E07 la résoudra par les `dist-tags` du registre (cases ajoutées à E06 et E07) ;
  - `catalog:` seule lève `InvalidConstraint`.
- **Catalogues pnpm** :
  - `Dependency.resolved_constraint` (ajouté) reçoit la plage du catalogue, lue par `parsers/npm.py` dans le `pnpm-workspace.yaml` le plus proche, en remontant depuis le projet. `catalog:` et `catalog:default` désignent `catalog` (ou `catalogs.default`), `catalog:nom` désigne `catalogs.nom` ;
  - `constraint` reste `catalog:…`, sans emplacement. `Dependency.effective_constraint` donne la contrainte à interpréter ;
  - une valeur de catalogue est lue comme dans un `package.json` : un alias `npm:` donne le vrai nom, git rend la dépendance non vérifiable ;
  - introuvable (pas de `pnpm-workspace.yaml`, entrée absente, YAML invalide) : une remarque, et E07 se fiera à la version installée ;
  - `scan` affiche `catalog: (^7.0.0)` ;
  - le même champ servira à `workspace = true` de Cargo (E21) et aux catalogues Gradle (E25).
- **Comparaisons par chaînes retirées** :
  - `_highest` de `parsers/python.py` devient `PYPI.highest` ;
  - le tri des transitives (`d.installed or ""`, dans `python.py` et `npm.py`) passe par `sort_key` : `9.0.0` avant `10.0.0` (deux versions d'une fourche de `uv.lock`, ou d'un paquet npm imbriqué) ;
  - restent des tests de chaînes qui ne comparent pas deux versions : `version[:1].isdigit()` (une référence pnpm), `_pinned_version` (lit un `==X`), et l'égalité exacte `(nom, version)` qui dédoublonne les transitives.
- **Mini-projet** `pnpm-catalog` (pnpm 12.15, `--lockfile-only --ignore-scripts`) : `catalog:`, `catalog:default`, `catalog:legacy`, un alias dans le catalogue. Sans `packageManager` : avec, pnpm 11+ ajoute en tête un document de 180 lignes (pnpm qui se fige lui-même).
- **Vérifié** :
  - doc et tests de node-semver : 22 comparaisons, des égalités, 96 plages qui incluent une version et 69 qui l'excluent, 57 plages développées (README), `minVersion`, règle des pré-versions. PEP 440 : l'ordre de son exemple, `~=`, `==` avec préfixe et versions locales, `>` et `<` exclusifs. Doc de Poetry ;
  - les 12 mini-projets : chaque contrainte se lit, et chaque version installée par le vrai outil la respecte (`test_mini_projects_constraints_are_understood`) ;
  - à la main, Argos (62 PyPI, 24 npm), ariakit (263 npm), juju (52 PyPI) : aucune contrainte illisible, aucune version hors plage ;
  - dans le `package-lock.json` d'Argos, 579 des 580 plages des paquets contiennent la version que npm a résolue. L'autre : monaco-editor demande `dompurify` `3.4.15`, forcé en `3.4.17` par `overrides` (lecture prévue à E09) ;
  - un `poetry.lock` de 240 paquets produit par Poetry 1.8.5 (fastapi, django, celery, boto3, pandas, jupyter…) : ses 239 contraintes, dont 8 unions (`>=1.7.4,<1.8 || >1.8,<1.8.1 || …`), contiennent toutes la version résolue ;
  - `scan` d'Argos inchangé (62 directes et 95 transitives Python, 24 et 389 npm).
- Tests : 914 verts sous 3.11, 3.12 et 3.14, ruff propre.

### E06 — Client HTTP, cache, registres PyPI et npm

**But** : savoir, pour un paquet, toutes ses versions publiées, la dernière stable,
et s'il est déprécié ou retiré.

- [x] `net/http.py` :
  - un `httpx.AsyncClient` partagé, User-Agent `forceupdate/<version> (+https://github.com/Pauzzle-ozz/forceupdate)` ;
  - délais maximaux ; reprises sur 429 et 5xx, en respectant `Retry-After` ;
  - concurrence bornée par hôte.
- [x] `net/cache.py` :
  - cache disque (`platformdirs`), avec une durée de vie par type de donnée (versions : 1 h) ;
  - option « sans cache » ;
  - mode hors ligne : cache seul, le reste « non concluant ».
- [x] `registries/base.py` : interface `PackageInfo`. Elle donne les versions (avec date, retirée ou non), la dernière stable, et la dépréciation (message, ou rien).
- [x] `registries/pypi.py` : une version est retirée si tous ses fichiers sont `yanked`.
- [x] `registries/npm.py` : noms scopés encodés (`@scope%2Fnom`), `deprecated` par version.
- [x] npm : garder les `dist-tags` (`latest`, `next`…) dans `PackageInfo`. Une dépendance écrite avec une étiquette suit cette étiquette (E05 : `NpmRange.tag`).
- [x] Un 404 donne « introuvable » : un paquet privé, ou une faute de frappe. C'est un constat « non vérifiable », pas une erreur fatale.
- [x] Script `tests/fixtures/record.py`, pour ré-enregistrer les réponses réelles quand les formats changent.
- [x] Ajoutés en route : reprises aussi sur coupure et délai dépassé, hôte abandonné pour la session après ses reprises, plafond de taille des réponses, statut du projet PyPI (PEP 792), paquets « security holding » de npm (voir les notes).

**Fini quand** : tests hors ligne verts (`respx`) ; un test `network` par
registre passe avec `--run-network`.

**Notes** (session 6) :

- **Organisation** :
  - `net/http.py` : `HttpClient` (un par session : `async with HttpClient(offline=…) as http`), `Response` (corps lu en entier, `json()`, `media_type`), `NetworkError` (message en français, qui cite l'hôte, jamais l'URL). `request(method, url, headers=, json=, retry=)` : reprises par défaut pour `GET`, `HEAD`, `OPTIONS` ; une recherche en `POST` (OSV, E08) passe `retry=True` ;
  - `net/cache.py` : `Cache` (`Cache.default()`, `Cache.disabled()` pour « sans cache »), `CacheKind` (`VERSIONS`, 1 h ; E08 et E27 ajoutent les leurs), `CacheEntry` (`value`, `stored_at`, `fresh`) ;
  - `registries/` : `base.py` (`Registry`, `PackageInfo`, `PackageVersion`, `PackageNotFound`, `RegistryError`), `pypi.py` (`PyPI`), `npm.py` (`Npm`), et `registries.for_ecosystem(écosystème, http, cache)`. Une instance par session : c'est elle qui fait qu'un paquet n'est demandé qu'une fois, même par des appels simultanés (une tâche partagée, protégée par `asyncio.shield`). Une erreur aussi est gardée pour la session ;
  - `platformdirs` ajouté aux dépendances (4.13.6, prévu dans « Choix techniques »).
- **Client HTTP** :
  - délais : 10 s pour se connecter, 30 s sans rien recevoir, 2 min pour un essai entier (`asyncio.timeout` : un serveur qui envoie un octet toutes les 29 s ne fait pas durer l'essai) ;
  - 3 reprises, sur 429 et 5xx, et aussi (ajouté) sur délai dépassé et connexion refusée ou coupée. Attente 0,5 s, 1 s, 2 s, avec un peu de hasard ; `Retry-After` (secondes ou date HTTP) respecté jusqu'à 60 s, abandon au-delà ;
  - 8 requêtes à la fois par hôte ; réponse plafonnée à 128 Mo décompressés (`next` en fait 32) ;
  - ajouté : un hôte resté injoignable après ses reprises, ou qui limite le débit au-delà de 60 s, n'est plus interrogé de la session. Sans réseau, chaque paquet attendrait sinon ses 3,5 s de reprises (200 paquets : 90 s). Une page en 5xx ne coupe pas l'hôte.
- **Cache** :
  - SQLite (bibliothèque standard) : un fichier, `cache.sqlite3` dans `platformdirs.user_cache_path("forceupdate")`, en mode WAL (l'interface et la ligne de commande peuvent s'en servir en même temps). Clé : l'URL interrogée ;
  - on y range la réponse réduite (`PackageInfo`), pas le document du registre. Un « introuvable » est rangé aussi, une erreur jamais ;
  - « sans cache » : rien n'est lu ni écrit. Hors ligne : `HttpClient(offline=True)` n'envoie rien, et les registres prennent une entrée même périmée. `PackageInfo.fetched_at` la date : E07 dira « données du registre du … » ;
  - jetable : entrées de plus de 30 jours effacées à l'ouverture, fichier abîmé ou d'un autre format recréé, disque en erreur : cache désactivé avec un avertissement, jamais d'échec ;
  - pas de revalidation par `ETag` : une entrée périmée est retéléchargée (`next` : 2,4 Mo compressés). À ajouter seulement si le besoin se fait sentir.
- **PyPI (tranché)** : l'API Simple en JSON (`GET /simple/{nom}/`, `Accept: application/vnd.pypi.simple.v1+json`), pas `/pypi/{nom}/json`. La doc de PyPI déclare sa clé `releases` dépréciée et renvoie vers l'API Simple. Celle-ci est un standard (PEP 691 ; 700 pour `versions` et `upload-time` ; 792 pour `project-status`), parlé aussi par les miroirs, et un tiers plus légère (numpy : 476 Ko compressés contre 656). Elle seule dit si un projet est archivé. PyPI sert la version 1.4 de l'API (vérifié le 2026-10-27).
  - L'API Simple ne range pas les fichiers par version : on lit la version dans leur nom, en comparant le texte exact de la liste, puis la version lue (`1.8rc1` pour `1.8c1`, `69.4` pour `69.4.0`), vieux formats compris (`.exe`, `.egg`, `.tar.bz2`, pytz `2004d`). Vérifié : aucun fichier sans version sur près de 15 000 (requests, django, pytz, setuptools, numpy, pillow, pyyaml, python-dateutil). Une version sans fichier rangé n'est ni datée ni retirée : un nom mal lu ne doit pas faire un faux « retiré ».
  - Retirée si tous ses fichiers sont « yanked », avec la raison (requests 2.32.0, numpy 2.4.0, setuptools 69.3.0…). Date : celle du premier fichier.
  - Statut du projet : `archived` (aioredis, typing, argparse, pathlib) et `deprecated` donnent `PackageInfo.deprecated` ; `quarantined` retire toutes les versions.
  - Un miroir en API 1.0, sans liste `versions` : versions lues dans les noms des wheels et des sdists.
- **npm (tranché)** : le document complet, pas l'abrégé (`application/vnd.npm.install-v1+json`). L'abrégé garde `dist-tags` et `deprecated`, mais pas `time` (les dates), et n'allège pas là où ça compte : compressés, 1,4 Mo contre 1,1 pour `@types/node` ; `next`, le plus gros, fait 31,5 Mo en complet et encore 25,7 en abrégé, lus en 0,9 s chacun. Mesuré le 2026-10-27.
- **« La dernière stable » (tranché, pour E07)** : `PackageInfo.latest`.
  - PyPI : la plus haute des versions non retirées, pré-versions exclues (`PYPI.latest(info.available())`). C'est le `info.version` de l'API JSON : identiques pour 69 paquets sur 69 (les 62 d'Argos, et django, numpy, setuptools, pytz, pyyaml, pillow, requests…) ;
  - npm : `dist-tags.latest` si c'est une version stable. C'est celle que choisit `npm install`, et celle que suivent Renovate et Dependabot. Une version plus haute sous une autre étiquette (une 5.0.0 sous `next`) n'est jamais proposée : le mainteneur ne l'a pas désignée comme la version à installer. Si `latest` est une pré-version : la plus haute stable sous elle ; si elle manque ou est illisible : la plus haute stable ;
  - une version actuelle au-dessus de `latest` (quelqu'un sur la voie `next`) : `gap` rend `None`, rien à signaler ;
  - une version illisible du registre est gardée (à la fin de `versions`), jamais candidate.
- **Dépréciation** :
  - PyPI : le statut du projet (ci-dessus). npm : le `deprecated` de la version `latest`, comme sur npmjs.com (`request`, `@hapi/joi`, `left-pad`) ;
  - par version, npm : `PackageVersion.deprecated` (lodash 4.18.0, « Bad release »). Une chaîne vide veut dire « plus dépréciée » ;
  - ajoutés : un paquet remplacé par l'équipe sécurité de npm (`0.0.1-security`, « security holding package » : crossenv, flatmap-stream), souvent après du code malveillant ; sa `latest` est une pré-version, donc rien à proposer. Et un paquet dont toutes les versions ont été dépubliées ;
  - à trancher à E07 : pour résoudre une plage, npm préfère les versions non dépréciées (`npm-pick-manifest`). `max_satisfying` ne le fait pas.
- **Pour E07** : `info.get(installée)` retrouve une version par son texte, sinon par sa valeur (`1.8rc1` ↔ `1.8c1`) ; `None` si le registre ne la connaît pas. `info.available()` (sans les retirées) est la liste à donner à `versions` (`latest`, `max_satisfying`). `info.tags[étiquette]` résout une étiquette npm.
- **Tests** : `respx`, réponses enregistrées par `tests/fixtures/record.py` (PyPI : flask, requests, aioredis ; npm : left-pad, @hapi/joi, colors, crossenv ; 373 Ko). Les tests asynchrones passent par `asyncio.run`, sans plugin (ni pytest-asyncio, ni celui d'anyio). Fixtures `cache` (un cache neuf par test, jamais celui de l'utilisateur) et `lookup` dans `conftest.py`.
- **Vérifié** : les 86 directes d'Argos (62 PyPI, 24 npm) trouvées en 2,5 s, cache vide ; les deux tests `network` passent ; 1015 tests verts (plus 2 réseau) sous 3.11, 3.12 et 3.14, ruff propre.

### E07 — Constats « plus récente » et « retiré / déprécié », rapports, commande `scan`

**But** : la première version utile de l'analyse. Elle sert telle quelle à l'API (E12).

- [x] `checks/outdated.py`. Pour chaque dépendance directe vérifiable :
  - version actuelle : l'installée, sinon la borne basse de la contrainte, marquée « approximative » (sauf une contrainte exacte `==X`, qui n'a rien d'approximatif) ;
  - la contrainte à interpréter est `Dependency.effective_constraint` (la plage d'un catalogue pnpm, E05), avec `versions.for_ecosystem`. Sans borne basse (`lower_bound` rend `None` : `*`, `<2`, une étiquette) ni version installée, pas de version actuelle : le dire, sans inventer de constat. Une contrainte illisible (`InvalidConstraint`, `catalog:` introuvable) : se fier à la version installée, et ne pas chercher « la plus haute qui respecte la contrainte » ;
  - étiquette npm (`latest`, `next`) : la plus haute qui la respecte est la version de l'étiquette, lue dans les `dist-tags` (E06) ;
  - un paquet déclaré deux fois (runtime et dev, deux extras : voir les notes de E03) donne deux `Dependency` : une seule requête au registre, et un regroupement par nom à l'affichage ;
  - comparée à la dernière stable, avec l'écart (patch, mineur, majeur) ;
  - et « la plus haute qui respecte déjà la contrainte » : celle-là se met à jour sans toucher au manifeste.
- [x] Registres (E06, voir ses notes) : un `HttpClient` et un `Cache` par analyse, un client par écosystème (`registries.for_ecosystem`), les paquets demandés en même temps. `PackageNotFound` donne un constat `UNVERIFIABLE`, `RegistryError` un `INCONCLUSIVE`, avec leur message ; toute autre exception est un bug. Une version installée que le registre ne connaît pas (`info.get` rend `None`) : le dire. Hors ligne, des données venues du cache sont datées (`PackageInfo.fetched_at`) : le rapport le dit.
- [x] `checks/deprecated.py` : version retirée, paquet déprécié (avec le message du registre).
  - PyPI : `PackageVersion.yanked` et `yanked_reason` ; npm : `PackageVersion.deprecated` de la version installée ; le paquet : `PackageInfo.deprecated` ;
  - version retirée : la remplacer par la plus proche non retirée (brief, type 4) ;
  - trancher : pour résoudre une plage, npm préfère les versions non dépréciées (`npm-pick-manifest`) ; `max_satisfying` ne le fait pas.
- [x] Priorisation : celle des décisions du brief (n°8).
- [x] Progression : le moteur émet des événements (projet trouvé, paquet vérifié…). La ligne de commande les affiche en barre de progression ; l'API (E12) les transmettra au navigateur.
- [x] `report/json.py` : `schema_version: 1`, schéma décrit dans `docs/JSON_FORMAT.md`. C'est aussi le format de l'API.
- [x] `report/terminal.py` (`rich`) : par projet, un tableau. Il remplace l'affichage provisoire de E02 et E03 (`_print_report` et `_print_dependencies` dans `cli.py`) et garde ce qu'il montre : langages avec leur écosystème, projets, dépendances, remarques (`Project.notices`), fichiers écartés (`Report.ignored_manifests`).
- [x] `report/markdown.py`.
- [x] Options de `scan` :
  - `--format terminal|json|md`, `--output <fichier>` ;
  - `--dev / --no-dev`, `--transitive` ;
  - `--offline` (cache seul, le reste « non concluant ») et `--no-cache` (E06) ;
  - `--fail-on vuln|major|any`.

  Codes de retour : 0 rien à signaler, 1 seuil `--fail-on` atteint, 2 erreur.
- [x] Encodage de sortie : sous Windows, une sortie redirigée (`scan --format json > rapport.json`) est écrite en cp1252 (constaté à E01). Écrire le JSON et le Markdown en UTF-8, sur la sortie standard comme dans un fichier `--output`. Test sous Windows avec une sortie redirigée.
- [x] Ajoutés en route : `Constraint.exact()` dans `versions/`, deux garde-fous pour tous les tests (ni réseau ni cache de l'utilisateur), `python -m forceupdate`, la cible d'une `latest` dépréciée et des paquets publiés en pré-versions (voir les notes).

**Fini quand** : `scan <vrai projet Python + npm>` donne un rapport juste, vérifié à
la main sur 4 ou 5 paquets.

**Notes** (session 7) :

- **Organisation** :
  - `checks/` : `base.py` (`Current`, `current_version`, `nearest`, `GAP_LABELS`), `outdated.py`, `deprecated.py`, `priority.py` (`priority`, `sort_findings`, `FailOn`, `reaches`, `fails`), plus `checks.check_dependency(dépendance, info)` et `checks.selected(dépendance, options)`. Les contrôles ne parlent pas au réseau : le moteur leur passe le `PackageInfo` ;
  - `engine.py` : `inventory` (l'ancien `scan` : lecture seule, synchrone, sans réseau), `check` (coroutine : registres, puis constats), `analyze` (les deux), `scan` (`asyncio.run(analyze(…))`). Les tests qui ne voulaient que la lecture appellent `engine.inventory` ;
  - `report/` : `__init__.py` (libellés, `plural`, `summarize`, `distinct_findings`, `rows` : une ligne par paquet), `terminal.py`, `json.py` (`build` rend le dictionnaire, pour l'API), `markdown.py` ; le schéma dans `docs/JSON_FORMAT.md` (ajouté) ;
  - `__main__.py` (ajouté) : `python -m forceupdate`, dont se sert le test de sortie redirigée.
- **Modèles** : `Finding.wanted_version` (la plus haute que la contrainte accepte déjà) et `Finding.detail` (le message du registre, tel quel) ; `ScanOptions` ; `Report.options` (`None` pour un inventaire seul), `scanned_at`, `oldest_data` ; `Event` et `EventKind` ; `to_dict` sort les dates en ISO 8601. Dans `versions/` : `Constraint.exact()` et `VersionScheme.exact()` (une contrainte exacte : `==1.2.3`, `===x`, `1.2.3` npm, version nue Poetry).
- **Synchrone et asynchrone (tranché)** : la lecture reste synchrone, seule la vérification est une coroutine. `engine.scan` lance `analyze` avec `asyncio.run`, une boucle par analyse. E12 attendra `analyze(source, options, on_event=…, http=…, cache=…)` avec un `HttpClient` et un `Cache` partagés, hors de la boucle du serveur (`inventory` bloque jusqu'à une seconde sur un gros dépôt, un gros document npm aussi).
- **Registres** : un client par écosystème et par analyse ; chaque paquet (nom normalisé) demandé une fois, tous en même temps (`asyncio.gather`). `PackageNotFound` → `UNVERIFIABLE`, `RegistryError` → `INCONCLUSIVE`, avec leur message ; toute autre exception remonte (testé). Un écosystème sans registre → `INCONCLUSIVE`. `Report.oldest_data` : la plus ancienne `fetched_at` ; hors ligne, le rapport dit « données des registres prises dans le cache, la plus ancienne du … ».
- **Version actuelle** (`checks.base.current_version`) : l'installée ; sinon celle d'une contrainte exacte ; sinon la borne basse, « approximative » (affichée `≈ 2.0`). Sans borne basse ni version installée (`*`, `<2`, `""`, une étiquette, `catalog:` introuvable, contrainte illisible) : pas de version actuelle, et un constat `INCONCLUSIVE` qui le dit (« Version utilisée inconnue : la contrainte « * » n'a pas de borne basse, et pas de version installée. Dernière : 3.1.3. »), jamais un « plus récente » inventé. Contrainte illisible : on se fie à l'installée, sans « permise ».
- **Plus récente** : cible `PackageInfo.latest`, comparée à la version actuelle (`gap`) ; au-dessus de la dernière, rien. Deux précisions, trouvées en comparant à `npm outdated` :
  - une `latest` dépréciée n'est proposée que s'il n'y a pas de version non dépréciée en dessous : `@types/parse-json` 7.0.0 est un paquet vide déprécié, npm ne le propose pas ;
  - une version actuelle en pré-version suit aussi les pré-versions de sa version (E05), et l'étiquette `latest` de npm même si c'en est une : chromium-bidi publie toutes ses versions ainsi (`158.0.8127-2`).
- **Permise (tranché)** : PyPI, la plus haute non retirée qui respecte la contrainte (`max_satisfying`), comme pip. npm, le choix de `npm-pick-manifest` (`npm install`, `npm outdated`) : la version de `latest` si la plage l'accepte et qu'elle n'est pas dépréciée, sinon la plus haute non dépréciée, sinon la plus haute. `>=4` donne donc la `latest` 4.17.21, pas une 5.0.0 publiée sous `next`. Une étiquette donne sa version (`dist-tags`). Pas de « permise » pour une indirecte : sa contrainte est celle du paquet qui la tire.
- **Retiré, déprécié** : examinés seulement sur une version connue (installée, ou contrainte exacte), pas sur une borne basse.
  - paquet déprécié : `DEPRECATED`, sans cible (le remplacer est un choix humain) ;
  - version retirée (PyPI) : `YANKED`, avec la raison (`detail`) et la plus proche non retirée : la plus petite au-dessus sans changer de majeure, sinon la plus haute en dessous, sinon la plus petite au-dessus (requests 2.32.0 → 2.32.2) ;
  - version dépréciée (npm), si le paquet ne l'est pas : `DEPRECATED`, avec la plus proche non dépréciée (lodash 4.18.0 « Bad release » → 4.18.1) ;
  - version inconnue du registre : `INCONCLUSIVE`, « dépubliée, ou venue d'un autre index » (colors 1.4.1, la version sabotée de 2022).
- **Gravité et priorité (tranché)** : ordre du brief (faille > fin de vie > retiré > déprécié > majeure > mineure > correctif), puis non vérifiable, puis non concluant ; à rang égal, par nom. Gravités : retirée `MEDIUM`, déprécié `LOW`, majeure `LOW`, mineure et correctif `INFO`, non vérifiable et non concluant `INFO`. Un paquet malveillant retiré par npm (crossenv) n'est ici qu'un « paquet déprécié » : OSV le connaît (`MAL-…`), E08 en fera une faille.
- **`--fail-on`** : `vuln` (une faille), `major` (tout ce qui précède les mineures), `any` (tout ce qui est à mettre à jour) ; « non vérifiable » et « non concluant » ne comptent jamais. Sans `--fail-on`, le code est 0 même avec des constats.
- **Non vérifiables** : une dépendance git, locale ou URL donne un constat `UNVERIFIABLE` (« Non vérifiable : dépendance git. ») ; un membre du workspace, du code du dépôt lui-même, aucun (le tableau dit « non vérifiable : membre du workspace »).
- **Options de `scan`** : `--format`, `--output`, `--dev/--no-dev` (vérifiées par défaut), `--transitive` (les indirectes passent aussi les contrôles de types 1 et 4, et seules celles qui ont un constat sont affichées), `--offline`, `--no-cache`, `--fail-on`. Pas d'option pour `include_tests` (E29).
- **Rapports** :
  - terminal : par projet, un tableau Paquet / Contrainte / Utilisée / Permise / Dernière / État, une ligne par paquet (un paquet déclaré deux fois : contraintes et scopes réunis), les plus graves en tête ; puis le détail des constats autres que « plus récente », les remarques, les fichiers écartés, et une ligne de résumé. « Permise » remplace « Dans la contrainte », trop large à 80 colonnes. Tout ce qui vient des fichiers ou des registres passe par `Text` : `sechunter[all]` n'est pas du balisage `rich` (testé) ;
  - Markdown : les mêmes tableaux, le texte échappé (`^1 || ^2` ne coupe pas une cellule) ;
  - JSON : `schema_version: 1`, `tool`, tout le rapport, et `summary`. Le résumé compte une fois un paquet déclaré deux fois dans un projet.
- **Encodage** : une sortie standard redirigée est repassée en UTF-8 (`_utf8_stdout`), pour les trois formats ; `--output` écrit en UTF-8 avec des `\n`. Testé dans un vrai sous-processus, sortie dans un tube, sans `PYTHONIOENCODING` ni `PYTHONUTF8`. Sous Windows, la sortie standard garde ses `\r\n`. Limite : PowerShell 5.1 relit la sortie d'un programme dans le codage de la console avant de l'écrire (`>` : en UTF-16) ; là, utiliser `--output` (case ajoutée à E30).
- **Progression** : `READING`, `PROJECTS_FOUND`, `CHECKING` (`total` paquets), `PACKAGE_CHECKED` (`done` sur `total`), `FINISHED`. La ligne de commande les affiche en barre `rich`, sur la sortie d'erreur, effacée à la fin, et seulement dans une console (testé : rien sur une sortie redirigée).
- **Tests** :
  - deux garde-fous automatiques dans `conftest.py` : `Cache.default()` ouvre un cache propre au test, et hors des tests `network` une connexion est refusée (`create_connection`). Le second a attrapé les tests de la ligne de commande, qui interrogeaient le vrai PyPI dès que `scan` s'est mis à vérifier ;
  - fixture `recorded` : PyPI et npm simulés avec toutes les réponses de `tests/fixtures/`, 404 pour le reste ;
  - `tests/test_checks.py`, `tests/test_engine_check.py` (avec un test `network` de bout en bout), `tests/test_report.py` ; `tests/test_cli.py` réécrit pour `scan` (hors ligne, formats, `--output`, `--fail-on`, sortie redirigée).
- **Vérifié à la main** :
  - `scan` d'Argos (2,9 s, 86 directes) : 12 à mettre à jour (6 majeures, 1 mineure, 5 correctifs) et 1 non concluant (`hatchling`, sans contrainte ni lockfile). Dernières versions relues dans l'API JSON de PyPI (anthropic 2.3.0, openai 3.40.0, python-dateutil 3.0.0, fastapi 0.162.0, redis 8.1.0, boto3 1.43.120, google-genai 2.33.0, xhtml2pdf 0.2.28, hatchling 1.32.4) et dans les `dist-tags` de npm (jsdom 30.1.3, vite 8.3.5, react 19.3.1, @types/react 19.3.0, puppeteer 25.16.0) : toutes justes. « Permise » recalculée depuis PyPI : anthropic `<1.0.0` → 0.125.0, openai `<3.0.0` → 2.54.0 ;
  - `scan --transitive` contre `uv pip list --outdated` dans le `.venv` d'Argos : 25 constats sur 25 identiques ;
  - `scan --transitive` contre `npm outdated --all` dans le front d'Argos : 105 identiques sur 114. Le reste s'explique : npm écarte les versions dont `engines.node` exclut le Node installé (24.12.0 ; jsdom 30, which 7, css-color 7, dom-selector 10, w3c-xmlserializer 6, json-parse-even-better-errors 6 demandent `^24.15.0`), ce que forceupdate ne sait pas (case ajoutée à E27) ; et il ne voit pas les paquets de plateforme non installés (`lightningcss-linux-*`), que le lockfile fige quand même. Deux vrais écarts trouvés ainsi, et corrigés : @types/parse-json et chromium-bidi (ci-dessus) ;
  - un projet jetable en ligne : requests 2.32.0 retirée → 2.32.2, aioredis archivé, lodash 4.18.0 dépréciée → 4.18.1, request déprécié, colors 1.4.1 dépubliée, `react: latest` → 19.3.1, un paquet inexistant introuvable ; `--fail-on major` sort avec 1.
- Tests : 1142 verts (plus 3 réseau) sous 3.11, 3.12 et 3.14, ruff propre.

### E08 — Failles (OSV)

**But** : les failles connues, avec la version qui les corrige.

- [x] Reprendre `query_osv_batch`, `_parse_osv_vuln`, le calcul CVSS et leurs tests (les 5 tests OSV, en `skip` dans `reference/`).
- [x] Couper les trois dépendances à Argos :
  - `ARGOS (1)` → `models.Severity` ;
  - `ARGOS (2)` → le client de E06 ;
  - `ARGOS (3)` → récupérer chaque faille complète via `GET /v1/vulns/{id}`, avec cache long et sans doublon.

  Le client de E06 : `HttpClient.request("POST", …, retry=True)` pour `querybatch` (une recherche se rejoue sans risque), un `CacheKind` de plus pour les failles, avec sa durée de vie.
- [x] Version corrigée : la plus petite version corrigée au-dessus de l'actuelle. Lue dans les événements `introduced` / `fixed`, comparée avec les règles de l'écosystème (E05).
- [x] Transitives aussi (versions du lockfile), affichées à part : « faille dans une dépendance indirecte ». En npm, un même paquet peut être installé en plusieurs versions : E04 donne une transitive par (nom, version), y compris une autre version d'une directe (`node_modules/a/node_modules/x`) ; les vérifier toutes.
- [x] `uv.lock` à plusieurs versions d'un même paquet (fourches par marqueurs) : E03 ne garde que la plus haute. Décider s'il faut vérifier les autres aussi (une faille de la version basse passerait inaperçue), et sinon l'écrire dans les limites.
- [x] Constat `VULNERABLE` : sévérité, identifiants (CVE, GHSA), version corrigée minimale, lien.
- [x] Brancher sur E07 : `checks/vulns.py`, appelé par `engine.check`, avec `HttpClient.request("POST", …, retry=True)`. Les failles se cherchent sur toutes les dépendances, indirectes comprises, quelle que soit `--transitive` (qui ne vaut que pour les types 1 et 4) ; `--no-dev` s'applique. `report.rows(direct=False)` ne montre aujourd'hui que les indirectes retenues par `checks.selected` : y faire entrer celles qui ont une faille. Déjà prêts : `Finding.identifiers`, `--fail-on vuln`, la priorité par gravité, le résumé (`vulnerable`), le libellé « faille ». Mettre à jour `docs/JSON_FORMAT.md` (champs remplis par `vulnerable`). crossenv (`MAL-…` chez OSV) devient une faille.

**À reprendre** : `reference/argos_sca_parsers.py` L211-219, L314-329, L1135-1381, et `TestQueryOSVNetworkErrors`.

- [x] Si ce n'est pas déjà fait : avec l'accord de l'utilisateur, créer le dépôt GitHub public `Pauzzle-ozz/forceupdate` (`gh repo create`), y pousser `main`, et vérifier que la CI est verte. Il faut ce dépôt pour le « Trusted Publisher » de PyPI.
- [x] Proposer à l'utilisateur de publier la version `0.1.0` sur PyPI, pour réserver le nom `forceupdate` :
  - il crée son compte PyPI et y déclare le dépôt GitHub comme « Trusted Publisher » (la session le guide) ;
  - `uv build`, puis `uv publish` ;
  - vérifier `uv tool install forceupdate` dans un dossier vierge.

  S'il préfère attendre, le noter, et revérifier que le nom est libre.
- [x] Ajoutés en route : les autres versions d'une directe dans `uv.lock` deviennent des indirectes, les avis d'une même faille réunis, les paquets malveillants en faille critique, la « faille possible », `Finding.cvss_score` et `summary.audited`, le lien vers l'avis dans le Markdown (voir les notes).

**Fini quand** : un projet de test avec `lodash 4.17.15` et `flask 0.12` sort les
CVE attendues, avec la bonne version corrigée.

**Notes** (session 8) :

- **Organisation** :
  - `advisories/` (ajouté) : `osv.py` (`Osv`, le client ; `Advisory`, un avis réduit, avec `fixed_in` et `affects` ; `Vulnerabilities`, les avis d'une version ; `OsvError` ; `parse_vuln`, repris de `_parse_osv_vuln`) et `cvss.py` (`base_score`, `severity`, repris de `_cvss_base_score_from_vector` et `_cvss_to_severity`). Le client n'est pas dans `registries/` : OSV n'est pas un registre de paquets ;
  - `checks/vulns.py` : `audited` (qui est vérifié), `version_to_check`, `check` (les constats), `unchecked` (le « non concluant »). Comme les autres contrôles, il ne parle pas au réseau ;
  - `engine.check` interroge les registres et OSV en même temps (`asyncio.gather`). Événement `VULNERABILITIES_CHECKED` : la barre de progression compte une étape de plus pour les failles ;
  - `checks.base.sentence` (sorti de `deprecated.py`), `report.subject` (le paquet, avec sa version s'il est indirect), `report.POSSIBLE_VULNERABILITY`.
- **Les trois dépendances à Argos coupées** : `ARGOS (1)` → `models.Severity` ; `ARGOS (2)` → `HttpClient.request("POST", …, retry=True)` (une recherche se rejoue : reprises sur 429, 5xx, coupures, comme un `GET`) ; `ARGOS (3)` → chaque avis complet par `GET /v1/vulns/{id}`, une fois par session (une tâche partagée, comme les registres), même s'il concerne plusieurs versions ou plusieurs projets.
- **OSV (vérifié le 2026-10-27)** :
  - `querybatch` : jusqu'à 1000 versions par requête (le maximum d'OSV ; un lot suffit pour Argos), les identifiants et la date de modification seulement ; `{}` pour une version sans faille ; `next_page_token` par version, suivi (10 pages au plus) ;
  - un nom PyPI est normalisé par OSV (`Flask` = `flask`), et `0.12` = `0.12.0` ;
  - **piège** : `querybatch` arrondit `modified` à la microseconde, `vulns/{id}` la donne en nanosecondes (39 avis sur 66). Comparées telles quelles, l'avis en cache ne resservait jamais. Comparées à la microseconde (`_same_time`) ;
  - crossenv n'a pas d'avis `MAL-…`, mais un avis GitHub « crossenv is malware » (CWE-506, `last_affected` 1.0.1). flatmap-stream en a trois (un MAL, deux GitHub) qui ne se citent pas.
- **Cache** : deux `CacheKind` de plus. `VULNERABILITIES` (1 h, comme les versions) : les identifiants des failles d'une version, clé `…/v1/query?ecosystem=…&name=…&version=…`. `ADVISORIES` (7 jours) : le document d'OSV tel quel (2 à 5 Ko), relu à chaque fois ; il resert tant qu'il a moins de 7 jours et la même date de modification. Hors ligne : tout ce qui est en cache, même périmé ; un avis périmé resert aussi en ligne si OSV ne répond pas.
- **Version corrigée (tranché)** : pour un avis, la plus petite des versions `fixed` au-dessus de la version utilisée, parmi les entrées de ce paquet (pas celles de lodash-es dans un avis de lodash), qui n'est elle-même plus concernée (une régression rouvre la faille plus loin). L'algorithme de la spécification d'OSV, sur les plages `SEMVER` et `ECOSYSTEM` (pas `GIT`) et les listes `versions`. Pas de version corrigée pour un `last_affected` seul, une liste de versions, un paquet malveillant. Avis réunis en désaccord : la plus haute de leurs versions. Vérifié contre `npm audit` (lodash : les 6 mêmes avis, mêmes plages) et `pip-audit` (flask 4, jinja2 6, werkzeug 12 : mêmes failles, mêmes versions corrigées).
- **Une faille, un constat (tranché)** : les avis qui partagent un identifiant (le leur, ou un alias), de proche en proche, sont réunis (le GHSA et le PYSEC d'une CVE) ; tous ceux d'un paquet malveillant aussi. Identifiants : les CVE, puis les GHSA, puis les autres ; le message cite les CVE et les GHSA. Titre et lien : ceux de l'avis GitHub de préférence (les PYSEC n'ont pas de titre : leur première ligne de description, coupée entre deux mots à 200 caractères). Les avis retirés (`withdrawn`) sont écartés.
- **Gravité (tranché)** : par avis, le score du vecteur CVSS 3 (calcul de FIRST, arrondi de l'annexe A), sinon le score donné par la base, sinon la gravité de GitHub (`MODERATE` → moyenne) ; CVSS 4 n'est pas calculé (il faut les tables de la spécification), GitHub donne alors la sienne. Avis réunis : la plus grave. Paquet malveillant (`MAL-…`, ou CWE-506 chez GitHub) : toujours critique. Rien du tout : moyenne, et le message dit « gravité inconnue ». Dans un même paquet, les failles d'une même gravité par score décroissant. Scores vérifiés contre NVD (5.3, 7.2, 7.4, 7.5, 8.1…).
- **Quelles dépendances (tranché)** : toutes les vérifiables, indirectes comprises, quelle que soit `--transitive` ; `--no-dev` s'applique ; une par (écosystème, nom, version), donc chaque version installée d'un paquet npm. Sans version actuelle (`*`, une étiquette, une contrainte illisible), rien n'est demandé à OSV : le constat « version utilisée inconnue » de E07 le dit déjà. `summary.audited` compte les versions soumises à OSV (`checked` reste celles vérifiées auprès des registres).
- **Version approximative (tranché)** : sans lockfile, la faille est cherchée sur la borne basse de la contrainte. Constat `VULNERABLE` avec `current_is_approximate`, affiché « faille possible », et une phrase de plus : « Faille possible : 0.12 est la borne basse de « >=0.12 », faute de lockfile ; la version installée peut être plus récente. » Il compte pour `--fail-on vuln` : la contrainte accepte une version concernée, et relever la borne basse corrige (E09).
- **Erreurs (tranché)** : jamais « pas de faille ». OSV injoignable, hors ligne sans cache, réponse illisible : `OsvError`. Une dépendance vérifiée (directe, ou indirecte avec `--transitive`) a alors un constat « non concluant » (« Failles non vérifiées. OSV : … ») ; les autres indirectes, une remarque par lockfile (« Failles non vérifiées pour 5 dépendances indirectes. OSV : … ») plutôt que des centaines de lignes. Le message hors ligne est le même pour toutes les versions, pour que la remarque les réunisse. Un avis illisible reste une faille, de gravité et de version corrigée inconnues. Les 5 tests OSV de `reference/` sont repris ainsi (erreur, jamais résultat vide), avec en plus 400, une réponse au mauvais nombre de résultats, et la vérification des reprises du `POST`.
- **`uv.lock` à fourches (tranché)** : les autres versions d'une directe (numpy 1.26 pour Python < 3.10, 2.x au-dessus) sont maintenant rendues comme des indirectes, comme une autre version d'une directe imbriquée dans `node_modules`. La directe garde la plus haute ; les failles de l'autre sont cherchées, et elle s'affiche à part si elle en a.
- **Rapports** : les indirectes en faille s'affichent dans « Dépendances indirectes à signaler » sans `--transitive` (`report.rows(direct=False)` ne filtre plus par `checks.selected`) ; le détail nomme « jinja2 2.10 (indirecte) » ; le Markdown ajoute un lien `[Avis](https://osv.dev/vulnerability/…)` ; le résumé dit « failles cherchées sur N ». `--transitive` a une aide plus précise. Hors ligne : « données des registres et d'OSV prises dans le cache ».
- **Modèles et JSON** : `Finding.cvss_score` (ajouté), `identifiers` rempli, `detail` (le titre de l'avis), `url` (l'avis sur osv.dev) ; `Summary.audited` ; `docs/JSON_FORMAT.md` à jour (section « Les failles », exemple refait avec les deux failles de requests 2.32.0). `schema_version` reste 1 : des champs ajoutés seulement.
- **Tests** : `tests/test_cvss.py`, `tests/test_osv.py`, `tests/test_checks_vulns.py`, et le bout en bout dans `tests/test_engine_check.py` (dont le critère de fin). Réponses enregistrées dans `tests/fixtures/osv/` (`queries.json` et 66 avis, 316 Ko), par `record.py osv` : les versions du mini-projet `vulnerable`, plus crossenv, flatmap-stream, ua-parser-js, flask 2.3.0, requests 2.0. La fixture `recorded` simule aussi OSV (une version inconnue n'a pas de faille) ; lodash ajouté aux réponses npm. Mini-projet `tests/projects/vulnerable` : lodash 4.17.15 (npm 11.6), flask 0.12 compilé par `uv pip compile --exclude-newer 2019-01-01` (jinja2 2.10, werkzeug 0.14.1). express, d'abord ajouté pour des indirectes npm, est retiré : son document npm pèse 824 Ko ; deux versions de lodash dans un `package-lock.json` écrit pour le test le remplacent.
- **Vérifié à la main** :
  - le mini-projet, en ligne : 28 failles (lodash 6, flask 4, jinja2 6, werkzeug 12), les mêmes que `npm audit` et `pip-audit`, mêmes versions corrigées ; `--fail-on vuln` sort avec 1 ; hors ligne, les mêmes depuis le cache ;
  - Argos (3,8 s, cache vide) : 569 versions soumises à OSV en une requête, aucune faille ; `npm audit` (front) et `pip-audit` (`uv export`, 150 paquets) n'en trouvent aucune non plus ;
  - un clone du dépôt fait par git avec `core.autocrlf=true` (fichiers en CRLF, comme sur la CI Windows) : la suite passe.
- **Dépôt et PyPI** : premier commit (E01 à E07) puis celui de E08, avec l'accord de l'utilisateur ; dépôt public `Pauzzle-ozz/forceupdate` créé (`gh repo create`) et `main` poussé. La première CI a échoué avant même de démarrer : le workflow de E01 citait `astral-sh/setup-uv@v10`, qui n'existe pas (astral ne publie plus d'étiquette de majeure depuis la v7, seulement `v10.3.2`…). Corrigé en `v10.3.2` (troisième commit) : CI verte sur Ubuntu et Windows, Python 3.11 et 3.14. Publication de la 0.1.0 : **l'utilisateur préfère attendre**. Le nom `forceupdate` est toujours libre sur PyPI (vérifié le 2026-10-28) ; à reproposer (case ajoutée à E09), sinon publié à E30.
- **Limites** : CVSS 4 non calculé ; la version corrigée vient d'OSV sans vérifier qu'elle est publiée, ni non retirée ou dépréciée (lodash 4.18.0, qui corrige deux failles, est dépréciée « Bad release » : E09) ; pas de lien entre une indirecte et la directe qui la tire.

---

## Phase C — Mise à jour locale, Python + npm

### E09 — Planificateur et sélection des mises à jour

**But** : pour chaque constat, savoir vers quelle version monter, ce qu'il faut
toucher, et si la mise à jour est pré-cochée.

- [x] `update/planner.py` : pour chaque dépendance, les mises à jour possibles (dernier correctif, dernière mineure, dernière majeure, version corrigée d'une faille).
- [x] Sélection par défaut (décision n°12 du brief) :
  - correctifs, mineures et corrections de failles : cochés ;
  - majeures : proposées, pas cochées, avec l'avertissement « peut demander d'adapter le code ». En 0.x, `gap` (E05) classe déjà en majeure ce qui sort de `^` (`0.2.3` → `0.3.0`, `0.0.3` → `0.0.4`) ;
  - une faille corrigée seulement par une majeure : proposée, pas cochée, avec les deux mentions.
- [x] La sélection est une donnée : l'interface la modifie case par case. En ligne de commande : `--level patch|minor|major` (par défaut `minor`), `--security-only`, `--include`, `--exclude` (motifs de noms), `--ecosystem`.
- [x] Garder le style de contrainte : `^`, `~`, `>=`, `==`, `~=`, version exacte. On calcule le nouveau texte de la contrainte.
- [x] Deux natures d'opérations :
  - la cible sort de la contrainte → modifier le manifeste (et le lockfile) ;
  - la cible est déjà dans la contrainte → lockfile seul.
- [x] Transitives en faille : lockfile seul (`uv lock --upgrade-package x`, `npm update x`).
- [x] Failles (depuis E08) : un paquet a souvent plusieurs failles, chacune avec sa version corrigée (`target_version`), et un constat « retirée » ou « plus récente » a la sienne. Choisir la plus petite version publiée qui les corrige toutes (au moins la plus haute des versions corrigées) et qui n'est ni retirée ni dépréciée : lodash 4.17.15 → 4.18.0 corrige tout, mais est dépréciée (« Bad release ») ; 4.18.1. Une faille sans version corrigée (paquet malveillant, `last_affected` seul) : rien à proposer, le dire (« retirer ce paquet »). Une faille « possible » (borne basse, sans lockfile) : relever la borne basse au-dessus de la version corrigée.
- [x] La publication de la 0.1.0 sur PyPI n'est pas faite (l'utilisateur a préféré attendre, session 8) : revérifier que le nom `forceupdate` est libre, et la reproposer à l'utilisateur. S'il attend encore, la reporter à E30.
- [x] Les constats de E07 ne portent que la dernière version (`target_version`) et la permise (`wanted_version`) ; le dernier correctif et la dernière mineure demandent toutes les versions publiées. Redemander les `PackageInfo` aux registres de la session (le cache les a), ou les garder dans l'analyse. Suivre les choix de E07 : pour npm, éviter les versions dépréciées comme `npm-pick-manifest` ; une version actuelle « approximative » (borne basse, sans lockfile) se met à jour en relevant la borne basse.
- [x] Versions forcées : `overrides` (npm), `resolutions` (Yarn) et `pnpm.overrides` fixent la version d'une transitive, et E04 ne les lit pas. Les lire (avec leur emplacement dans `package.json`) : une transitive forcée ne bouge pas avec `npm update x`, c'est l'override qu'il faut réécrire. Exemple réel (E05) : Argos force `dompurify` `^3.4.13` par `overrides`, alors que monaco-editor demande `3.4.15` exactement.

- [x] Ajoutés en route : `Dependency.lockfile`, la commande `update` qui montre le plan, les mises à jour rangées dans le rapport (`Project.updates`, JSON de `scan`), le workflow de publication sur PyPI (voir les notes).

**Fini quand** : des tableaux de cas couvrent chaque style de contrainte et la
sélection par défaut.

**Notes** (session 9) :

- **Organisation** :
  - `update/` (ajouté) : `constraints.py` (`rewrite` : une contrainte réécrite pour une version, dans son style) et `planner.py` (`plan`, `select`, `choose`, `chosen`, `Rules`, `Selection`). Rien n'y écrit de fichier ;
  - modèles : `Update` (les mises à jour possibles d'un paquet d'un projet : `options`, `selected`, `note`), `UpdateOption` (une version : `gap`, `reasons`, `fixes`, `unfixed`, `edits`, `lockfile`, `manual`, `warnings`), `Edit` (`kind`, `file`, `location`, `old`, `new`, `override`), `UpdateReason`, `EditKind`, `Override` ; `Project.updates` et `Project.overrides` ; `Dependency.lockfile` ;
  - `report/` : `REASON_LABELS`, `update_subject`, `option_gap`, `option_fixes`, `option_fixed`, `option_changes` ; `terminal.render_plan`.
- **Où se calcule le plan (tranché)** : dans `engine.check`, juste après les constats, là où le moteur a les versions publiées (`PackageInfo`) et les avis d'OSV. `planner.plan(report, infos, vulnerabilities)` remplit `Project.updates` : le JSON de `scan` porte les mises à jour possibles, et l'interface aura ses cases avec le rapport, sans redemander les registres. Les indirectes en faille sont demandées en plus aux registres (une requête par paquet, sans événement de progression) : il faut leurs versions publiées pour choisir celle qui corrige. Le planificateur lui-même ne parle pas au réseau.
- **Une mise à jour par paquet (tranché)** : une `Update` par paquet d'un projet (une directe avec toutes ses déclarations, qui montent ensemble ; une indirecte par version installée), et ses options s'excluent : un groupe de cases dont une au plus est cochée. Identifiant : `chemin|écosystème|nom`, plus la version installée pour une indirecte. Ordre : celui des constats. La sélection (`Selection`) est un dictionnaire identifiant → version ; `chosen` la valide.
- **Les options** :
  - dernier correctif et dernière mineure, sans dépasser la cible du constat « plus récente » ; jamais une version retirée, une dépréciée seulement faute d'autre (comme `npm-pick-manifest`), pas de pré-version ;
  - dernière majeure (directes seulement) ;
  - correction des failles ;
  - remplacement d'une version retirée ou dépréciée, parfois en dessous (`gap` à `null`, « Revient à une version plus ancienne. », jamais pré-coché) ;
  - une indirecte en faille, vérifiée sans `--transitive` : son dernier correctif et sa dernière mineure, s'ils corrigent au moins une faille (jinja2 2.10 → 2.11.3 en corrige 2 sur 6 ; seule la 3.1.6, majeure, corrige tout).
- **Correction des failles (tranché)** : la plus petite version publiée, au moins la plus haute des versions corrigées, qu'aucun des avis (`Advisory.affects`) ne concerne plus ; non dépréciée s'il y en a une, jamais retirée. Les avis comptent, pas seulement les versions corrigées : Flask 2.3.0 est au-dessus de 2.2.5 mais concernée (branche corrigée en 2.3.2). Chaque option dit les failles qu'elle corrige (`fixes`) et celles qu'elle laisse (`unfixed`). Faille sans version corrigée : la `note` le dit (« Code malveillant (…) : retirer ce paquet, aucune version sûre connue. » d'après `Advisory.malicious`, ou « Aucune version corrigée connue pour … ») ; registre muet : « Versions publiées inconnues ».
- **Pré-cochée (tranché)** : parmi les options qui ne sont ni majeures, ni un retour en arrière, ni à faire à la main, celle qui corrige le plus de failles, puis la plus récente. `--security-only` : la plus petite qui corrige le plus. `--level` plafonne aussi les corrections de failles : une faille corrigée seulement par une majeure n'est choisie qu'avec `--level major`.
- **Ce qu'on touche (tranché)** :
  - la contrainte n'est réécrite que si elle n'accepte pas la version visée ; sinon le lockfile seul ;
  - sans lockfile (version « approximative »), on relève la borne basse ; une option qui ne changerait rien (`~=1.0` vers 1.0.2) n'est pas proposée ;
  - pour une faille, la nouvelle contrainte n'accepte plus de version concernée (`floor`) ;
  - une contrainte sans emplacement (ligne continuée, échappement TOML) : `manual`, jamais pré-cochée ; un catalogue pnpm : `EditKind.CATALOG`, sans emplacement (E10 le cherchera dans `pnpm-workspace.yaml`) ;
  - une dépendance pair : la plage s'élargit (`^18.0.0` → `^18.0.0 || ^19.3.1`) ; la remplacer retirerait React 18 aux utilisateurs de la bibliothèque ;
  - une indirecte : le lockfile seul, ou la version forcée qui la fige si elle n'accepte pas la cible.
- **Garder le style (tranché)** : seuls les numéros changent (opérateurs, espaces, ordre, préfixes `v` et `=`, `!=` gardés). La borne basse monte jusqu'à la cible (`>=2.25,<3` → `>=3.1,<4`), `>` devient `>=` ; une borne haute qui exclut la cible est déplacée au niveau qu'elle fixait (`<1.5` vers 1.7.2 : `<1.8`) ; une union est remplacée par son membre qui accepte la cible, ou par son dernier. Précision : gardée quand rien ne se perd (`^1` → `^2`, `>=1.0` → `>=2.1`), sinon la version entière, sauf là où le nombre de chiffres a un sens (`~=1.4`, jokers, `~1`, `^0`) : la précision reste, et pour une faille une borne `>=` s'ajoute (`~=1.9,>=1.9.2`). Sans règle évidente (intervalle npm dont la fin complète est dépassée, `*`, étiquette) : `None`, « à réécrire à la main ». Le résultat est relu (`satisfies`).
- **Versions forcées** : `parsers/npm.py` lit `overrides` (clés imbriquées, `"."`, `a@2`), `resolutions` (chemins Yarn, `**/x`) et `pnpm.overrides` (`a>b`, `a@<2`), avec leur emplacement (`Project.overrides`). Celles du `package.json` du dossier du lockfile (la racine d'un workspace) s'appliquent aux indirectes ; celle de tout l'arbre passe devant celle d'un parent ; `$x` et un chemin local sont à réécrire à la main. Argos : 4 lues (flatted, dompurify, nanoid, @babel/core), aucune à réécrire. Pas lues : celles de `pnpm-workspace.yaml` (pnpm 10+, case ajoutée à E10).
- **`Dependency.lockfile`** (ajouté) : le fichier où la version installée a été lue, celui à régénérer. Un `-c constraints.txt` de pip en est un, sans être un lockfile (case ajoutée à E11).
- **`forceupdate update`** (ajouté) : l'analyse de `scan` (`--dev/--no-dev`, `--offline`, `--no-cache`), puis la sélection (`--level`, `--security-only`, `--include`, `--exclude`, `--ecosystem` ; motifs `fnmatch` sans tenir compte de la casse, répétables), puis l'affichage : par projet, un tableau des mises à jour choisies (version, écart, failles corrigées, ce qui change), les options proposées non cochées, ce qui est à savoir. Rien n'est écrit (E10). `ui` est la seule commande encore « pas disponible ».
- **JSON** : `docs/JSON_FORMAT.md` à jour (projet : `overrides`, `updates` ; dépendance : `lockfile` ; sections « Version forcée », « Mise à jour », « Option de mise à jour », « Réécriture » et les raisons ; l'exemple a ses mises à jour). `schema_version` reste 1 : des champs ajoutés.
- **Tests** : `tests/test_update_constraints.py` (99 cas : un tableau par style, npm puis PEP 440 et Poetry, plancher, élargissement), `tests/test_planner.py` (68 cas, avec des constats produits par les vrais contrôles sur des versions et des avis écrits à la main : sélection par défaut npm et PyPI, failles, chaque style avec et sans lockfile, indirectes, versions forcées, règles, `chosen`), lecture des versions forcées et de `Dependency.lockfile` sur les mini-projets, bout en bout (`engine`, et `update` avec chaque option) sur le mini-projet `vulnerable`. jinja2 et werkzeug ajoutés aux réponses enregistrées ; `record.py pypi:jinja2` n'enregistre qu'un paquet.
- **Vérifié à la main** :
  - `vulnerable` : lodash 4.17.15 → 4.18.1 pré-cochée (mineure, corrige les 6 ; 4.18.0, dépréciée, écartée) ; flask 0.12 → 0.12.5 pré-cochée (corrige 1 sur 4), 3.1.3 proposée (majeure, corrige les 4 : CVE-2026-27205 n'est corrigée qu'en 3.1.3) ; jinja2 → 2.11.3 (lockfile seul, 2 sur 6) et 3.1.6 proposée ; werkzeug → 3.1.9 proposée (seule une majeure corrige ses 12 failles) ;
  - Argos (1,4 s) : 9 pré-cochées sur 14, toutes par le lockfile seul (fastapi 0.161.0 → 0.161.1, pas 0.162, majeure en 0.x) ; 5 majeures proposées, dont anthropic `>=0.40.0,<1.0.0` → `>=2.3.0,<3.0.0` et openai `>=1.0.0,<3.0.0` → `>=3.40.0,<4.0.0` ;
  - mini-projets : `npm` (`~4.3.1` → `~4.4.3`, l'alias `npm:ms@2.0.0` → `2.1.3`, la pair `^18.0.0` élargie), `pnpm-catalog` (catalogue `^2.0.0` → `^3.0.1`), `poetry` (`^8.0` → `^9.0.3` pour la faille de pytest, `^9.2` pour la dernière), `setuptools` sans lockfile (bornes basses relevées : `>=2.25` → `>=2.34.2`).
- **Limites** : les options ne sont pas vérifiées auprès d'OSV, et une version proposée peut avoir une faille qui ne concerne pas la version utilisée (case ajoutée à E10) ; une indirecte monte dans la plage que lui laisse le paquet qui la tire, que le planificateur ne connaît pas (avertissement pour une majeure, E11 relira le lockfile) ; une seule majeure proposée (la dernière), pas une par majeure intermédiaire.
- **PyPI** : le nom `forceupdate` est toujours libre (vérifié le 2026-10-28) ; l'utilisateur a choisi de publier. Version `0.1.0` ; workflow `.github/workflows/publish.yml` : une étiquette `v*` lance les tests, `uv build` et `uv publish` par « Trusted Publisher » (environnement `pypi`, aucun token), après avoir vérifié que l'étiquette est la version de `pyproject.toml`. Paquet construit et vérifié en local (`twine check`, 50 fichiers dans le wheel). L'utilisateur a créé son compte PyPI, activé la double authentification et déclaré le « pending publisher » (projet `forceupdate`, `Pauzzle-ozz/forceupdate`, `publish.yml`, environnement `pypi`), guidé pas à pas. Étiquette `v0.1.0` poussée sur le commit de E09 : workflow vert en 26 s, **`forceupdate` 0.1.0 publié** (https://pypi.org/project/forceupdate/, wheel et sdist). Vérifié : `uv tool install --refresh forceupdate` dans un dossier d'outils vierge, `forceupdate --version` donne `0.1.0`, `update` sur `vulnerable` donne le même plan. `pyproject.toml` garde `0.1.0` : la prochaine publication changera la version (le workflow refuse une étiquette qui ne lui correspond pas).

### E10 — Réécriture des manifestes, commande `update`

**But** : les manifestes Python et npm sont modifiés proprement.

- [x] `update/writers/` : remplacer seulement le texte de la contrainte, à l'emplacement enregistré par les parseurs (E03, E04). Si le texte trouvé à cet emplacement n'est pas l'ancienne contrainte, ne pas toucher au fichier et le signaler. Depuis E03 : un emplacement vide (contrainte absente) est le point où insérer une contrainte ; `location=None` (dépendance git, échappement TOML, ligne continuée) veut dire « ne pas réécrire ».
- [x] Formats :
  - `requirements*.txt` ;
  - `pyproject.toml` (PEP 621, Poetry, `dependency-groups`) ;
  - `Pipfile`, `setup.cfg` ;
  - `package.json` (depuis E04, l'emplacement d'un alias `npm:autre@^1.0` ne couvre que `^1.0`) ;
  - catalogues pnpm : une dépendance `catalog:` n'a pas d'emplacement dans `package.json` (E04) ; sa plage est dans `pnpm-workspace.yaml`. La réécrire là (positions YAML : `yaml.compose` donne ligne et colonne de chaque nœud), sinon dire qu'elle n'est pas réécrite. Depuis E05, la plage actuelle est `Dependency.resolved_constraint` ; l'auto-vérification relit le projet et doit la retrouver changée.
- [x] Auto-vérification : relire le fichier réécrit avec son parseur. Il doit redonner la nouvelle contrainte.
- [x] Diff unifié de chaque fichier, calculé avant d'écrire (l'interface l'affichera en E15).
- [x] Commande `update <chemin>` : affiche le diff, demande confirmation (`--yes` pour ne pas demander, `--dry-run` pour s'arrêter au diff).
- [x] Garde-fou : si les fichiers visés ont des changements git non commités, refuser, sauf `--force`.
- [x] Depuis E09 : `update` montre déjà le plan (`terminal.render_plan`) ; la sélection vient de `planner.select` (options de la ligne de commande) ou de l'interface (`planner.Selection`, validée par `planner.chosen`). Chaque option porte ses réécritures (`UpdateOption.edits` : fichier, emplacement, ancien et nouveau texte) ; plusieurs dans un même fichier s'appliquent de la fin vers le début. Une option `manual` n'est pas appliquée : le dire. La déclaration réécrite se retrouve dans `Update.dependencies` par fichier et emplacement.
- [x] Les `overrides` de `pnpm-workspace.yaml` (pnpm 10+) ne sont pas lus (E09 ne lit que ceux du `package.json`) : les lire avec leur position YAML, comme les catalogues.
- [x] Vérifier les versions proposées auprès d'OSV (reporté de E09) : une option qui a elle-même une faille connue (introduite après la version utilisée) n'est pas pré-cochée, et un avertissement le dit ; une seule requête `querybatch` pour toutes les options.
- [x] Ajoutés en route : `parsers/yaml_spans.py`, `parsers.npm.parse_pnpm_workspace`, `update/git.py`, le refus d'une ligne de `requirements` à empreintes (`--hash`), l'emplacement vide collé au nom (voir les notes).

**Fini quand** : sur les mini-projets, le diff ne touche que les contraintes.
Commentaires, ordre et mise en forme restent intacts.

**Notes** (session 10) :

- **Organisation** :
  - `update/writers/` (ajouté) : `__init__.py` fait tout le travail commun (`prepare`, `write`, `unified_diff` ; `Changes`, `FileChange`, `Skipped`, `WriteError`) ; `base.py` (`Target` : une réécriture située, `Declaration` : une contrainte relue, `Refused`) ; `python.py` et `npm.py` ne donnent que le parseur qui relit chaque format (`READERS`, par motif de `detect.manifests`) et ce qu'il vérifie en plus (`CHECKS`), plus, pour npm, `catalog_target` (la plage d'un catalogue dans `pnpm-workspace.yaml`). Un module par format n'avait pas de sens : le remplacement de texte est le même partout ;
  - `parsers/yaml_spans.py` (ajouté, comme `toml_spans` et `json_spans`) : `yaml.compose` avec le chargeur écrit en Python (`SafeLoader`), dont `Mark.index` compte des caractères, BOM compris. Ne rend pas un scalaire sur plusieurs lignes, entre guillemets avec un échappement (`''`, `\"`), ni un nœud cité par un alias ;
  - `parsers.npm` : `parse_pnpm_workspace` (`PnpmWorkspace` : `packages`, `catalogs` en `CatalogEntry` avec leur emplacement, `overrides`), `nearest_pnpm_workspace`, `catalog_name` (devenu public) ; l'analyse des catalogues passe par eux ;
  - `update/git.py` (ajouté) : `uncommitted(root, paths)` ;
  - `report/terminal.py` : `render_changes` (diff coloré, options non appliquées), `render_outcome` (fichiers réécrits, lockfiles à régénérer).
- **`prepare` (tranché)** :
  - une option s'applique en entier ou pas du tout ; une option `manual` n'est jamais appliquée (`Skipped` : « à faire à la main : … ») ;
  - chaque `Edit` est situé (`Target`) puis vérifié : le fichier doit avoir `old` à cet endroit, sinon « a changé depuis l'analyse » ;
  - deux options qui réécrivent la même contrainte (un catalogue partagé par deux projets, la version forcée de deux versions installées) : faite une fois si elles disent la même chose, sinon la seconde n'est pas appliquée ;
  - dans un fichier, de la fin vers le début, sur les emplacements du texte d'origine ;
  - **auto-vérification** : le fichier réécrit est relu par le parseur de l'analyse ; mêmes déclarations dans le même ordre (sorte, nom, scope, raison), la nouvelle contrainte à son nouvel emplacement (décalé si une réécriture avant elle sur la même ligne a changé de longueur), et aucune autre contrainte changée. Sinon le fichier n'est pas réécrit, ni les options qui le touchent (et leurs autres fichiers non plus : on recommence sans elles) ;
  - une mise à jour par le lockfile seul (`edits` vide) est « appliquée » sans fichier : `Changes.lockfiles` dit quel lockfile régénérer.
- **Fichiers** : lus en octets, décodés en UTF-8 strict (sinon pas réécrits), fins de ligne gardées. Les parseurs voient le texte sans `\r` (`LocalSource` convertit les fins de ligne) : les emplacements sont les mêmes, un `\r` n'étant qu'en fin de ligne. Un fichier qui a des `\r` seuls n'est pas réécrit (ses lignes ne seraient pas celles des parseurs). Un lien symbolique ou un chemin hors du dossier non plus. Le BOM compte pour les colonnes de la ligne 1, comme à l'analyse.
- **`write`** : relit chaque fichier ; s'il a changé depuis `prepare`, rien n'est écrit. Chaque fichier passe par un fichier temporaire à côté, qui le remplace (`os.replace`), droits gardés ; si une écriture échoue, ceux déjà écrits sont remis comme avant.
- **Diff** : comme `git diff` (`--- a/…`, `+++ b/…`, 3 lignes de contexte), lignes coupées sur `\n`, sans montrer les `\r`.
- **`--hash` (trouvé sur le mini-projet `pip`)** : `pytest==8.0.0 \ --hash=sha256:…` a un emplacement (la contrainte est sur la première ligne), mais réécrire la version laisserait les empreintes de l'ancienne : pip refuserait d'installer. La ligne logique qui a un `--hash` n'est pas réécrite (« à réécrire à la main, avec celles de la nouvelle »). Le planificateur ne le sait pas : l'option reste pré-cochée, et `prepare` la rend dans `skipped`.
- **Emplacement vide (corrigé dans `parsers/python.py`)** : sans contrainte, il était après les espaces qui suivent le nom (`click ; python_version…` donnait `click >=8;`) ; il est maintenant collé au nom et aux extras, comme le disait la docstring (`click>=8 ;`).
- **pnpm-workspace.yaml** : ses `overrides` vont dans `Project.overrides` du projet de son dossier, **avant** ceux du `package.json` : pnpm 10 les fait passer devant, et pnpm 11+ ne lit plus du tout le champ `pnpm` du `package.json` (vérifié avec pnpm 12.15 : « The "pnpm" field in package.json is no longer read », c'est la version de `pnpm-workspace.yaml` qui est installée). Section `overrides`, `file` = `pnpm-workspace.yaml`. Une plage de catalogue est retrouvée par catalogue, vrai nom (alias compris) et ancienne plage.
- **Failles des versions proposées (tranché)** : après `planner.plan`, le moteur soumet à OSV toutes les versions proposées qu'il n'a pas déjà (`planner.proposed_versions`), en une requête `querybatch` (plus une par avis encore inconnu), puis `planner.audit` : une faille de la version proposée qu'aucune des failles de la version utilisée ne cite (identifiants et alias) va dans `UpdateOption.introduced`, avec l'avertissement « Faille connue dans cette version : … » ; `choose` ne coche jamais une telle option, quelles que soient les règles. Si OSV ne répond pas : options inchangées, une remarque par projet (« Failles non vérifiées pour 4 versions proposées. … »). Aucun cas réel sur Argos ni `vulnerable` ; testé sur des avis écrits à la main.
- **Commande `update`** : le plan, puis le diff de chaque fichier et ce qui ne sera pas appliqué ; `--dry-run` s'arrête là ; sinon le garde-fou (git), puis « Réécrire N fichiers ? [o/N] » (`o`, `oui`, `y`, `yes`), sauf `--yes` ; sans réponse possible (pas de terminal), erreur qui renvoie à `--yes` ou `--dry-run`. Pas de dépôt git : une ligne le dit, et on peut écrire. Pour finir, les fichiers réécrits et les lockfiles à régénérer (« forceupdate ne le fait pas encore »). Codes : 0, ou 2 si le garde-fou refuse ou si l'écriture échoue.
- **Garde-fou git** : `git rev-parse --show-prefix` (la source peut être un sous-dossier du dépôt) puis `git --literal-pathspecs status --porcelain=v1 -z --untracked-files=all -- <fichiers>` ; modifié, dans l'index sans commit, ou pas suivi : refusé, sauf `--force`.
- **JSON** : `introduced` des options ; `overrides` de `pnpm-workspace.yaml`. `docs/JSON_FORMAT.md` à jour, `schema_version` reste 1.
- **Tests** : `tests/test_writers.py` (un tableau par format : requirements, `.in`, PEP 621, extras, PEP 735, build-system, Poetry, Pipfile, setup.cfg, package.json, alias ; versions forcées npm, Yarn, pnpm et de `pnpm-workspace.yaml` ; catalogues, partagés ou introuvables ; CRLF, BOM, deux réécritures sur une ligne ; chaque refus ; diff ; écriture, fichier changé entre-temps, échec et remise en état ; et **sur les 13 mini-projets**, toutes les contraintes réécrites : remettre les anciennes aux nouveaux emplacements redonne le fichier à l'octet près), `tests/test_yaml_spans.py`, `tests/test_update_git.py` (dépôt créé dans le test), audit dans `tests/test_planner.py`, `pnpm-workspace.yaml` dans `tests/test_parsers_npm.py`, et `update` (`--dry-run`, `--yes`, confirmation, garde-fou) dans `tests/test_cli.py`, toujours sur une copie. 1541 tests, plus 4 réseau.
- **Vérifié à la main** (`--dry-run --level major`, sur des copies) :
  - `vulnerable` : `package.json` (lodash `4.17.15` → `4.18.1`) et `requirements.in` (`==0.12` → `==0.12.5`) ; avec `--yes`, seules ces deux lignes changent, puis une relance ne propose plus que le lockfile ;
  - les 12 autres mini-projets : seules les contraintes changent (alias `npm:ms@2.0.0` → `2.1.3`, pair `^18.0.0 || ^19.3.1`, catalogue `legacy` dans `pnpm-workspace.yaml`, Poetry, Pipfile, setup.cfg avec son commentaire, `requests >= 2.34.2, < 3  # client HTTP`) ; `pip/requirements-dev.txt` (à empreintes) n'est pas réécrit, et la raison est dite ;
  - Argos (clone, 3,6 s) : 15 mises à jour, 3 contraintes réécrites (anthropic `>=2.3.0,<3.0.0`, openai `>=3.40.0,<4.0.0` sous leur commentaire, jsdom `^30.1.3`), le reste par les lockfiles ; un `pyproject.toml` modifié sans commit bloque (code 2), `--yes` ne change que ces 3 lignes.
- **Limites** : les lockfiles ne sont pas régénérés (E11) ; un fichier `-c constraints.txt` qui fige l'ancienne version n'est pas réécrit (E11), pip refusera donc la nouvelle tant qu'il ne l'est pas ; une option refusée à la réécriture (`--hash`) reste pré-cochée dans le plan.

### E11 — Régénération des lockfiles

**But** : après la réécriture, les lockfiles suivent.

- [x] `update/lockfiles.py`, une commande par outil, vérifiée sur la version actuelle de chacun (npm 11.6.2, pnpm 12.15.0, Yarn 1.22.22 et 4.18.1, uv 0.10.11, Poetry 1.8.5 et 2.5.1, PDM 2.29.4, pipenv 2026.10.3, pip-tools 7.6.2) :

  | Lockfile | Commande de base | Viser une version (lockfile seul, indirecte) |
  |---|---|---|
  | `package-lock.json` | `npm install --package-lock-only --ignore-scripts` | version exacte épinglée le temps d'un passage ; indirecte : `npm update x` |
  | `yarn.lock` (Yarn 1) | `yarn install --ignore-scripts`, `node_modules` dans un dossier temporaire | entrée du paquet retirée du `yarn.lock` |
  | `yarn.lock` (Yarn 2+) | `yarn install --mode=update-lockfile` | `yarn up -R x --mode=update-lockfile` |
  | `pnpm-lock.yaml` | `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile` | épinglée ; indirecte : `pnpm update x --no-save` (`-r` en workspace) |
  | `uv.lock` | `uv lock` | `-P x==V` |
  | `poetry.lock` | `poetry lock` (`--no-update` avant Poetry 2) | épinglée ; indirecte : `poetry update --lock x` |
  | `pdm.lock` | `pdm lock --update-reuse` | épinglée ; indirecte : `pdm update --no-sync --update-reuse x` |
  | `Pipfile.lock` | `pipenv lock` | (re-résout tout) |
  | pip-tools (`.txt` compilé) | la commande de son en-tête : `pip-compile …` ou `uv pip compile …` | `-P x==V` |
- [x] Outil absent : le manifeste est quand même modifié, et le rapport dit « lockfile à régénérer : `<commande>` ».
- [x] La résolution échoue (conflit de versions) : restaurer les fichiers du projet tels qu'avant et rapporter l'erreur.
- [x] Après régénération, relire le lockfile : la version installée doit être la cible.
- [x] Mise à jour par le lockfile seul (E09 : `UpdateOption.edits` vide, la contrainte accepte déjà la version) : `uv lock` seul garderait la version figée, il faut viser le paquet (`uv lock --upgrade-package x==V`, `poetry update x`, l'équivalent npm sans toucher au `package.json`… à vérifier par outil). Indirecte : pareil, pour un paquet absent du manifeste ; si elle n'atteint pas la cible, dire quel paquet la retient (le graphe du lockfile le sait, `parsers/lockfiles.py`).
- [x] Un fichier de contraintes pip (`-c constraints.txt`) fige des versions (`Dependency.lockfile`, E09) sans outil pour le régénérer : y réécrire la ligne `==X` (son emplacement est connu, E03). Depuis E10 : passer par `update.writers` (un `Target` de plus) ; une ligne à empreintes (`--hash`) n'y est pas réécrite (`writers.python.CHECKS`), le dire.
- [x] Depuis E10 : `update` réécrit les manifestes (`writers.prepare`, puis `writers.write`) et dit quels lockfiles régénérer (`Changes.lockfiles`). Les régénérer juste après l'écriture ; si la résolution échoue, remettre les manifestes comme avant (`FileChange.before`) en plus des lockfiles. Une mise à jour par le lockfile seul est dans `Changes.applied` sans fichier.
- [x] Ajoutés en route : `pdm.lock` (lu depuis E03), les `.txt` de pip-tools qui en citent un autre (`-c requirements.txt`) recompilés après lui, ce que le lockfile a changé d'autre, le garde-fou des tests qui interdit les vrais outils (voir les notes).

**Fini quand** : sur un projet npm et un projet uv, `update` donne un manifeste et
un lockfile cohérents ; sans l'outil, le message est clair.

**Notes** (session 11) :

- **Organisation** :
  - `update/lockfiles.py` (ajouté) : `plan(source, report, changes)` donne les `Job` (lockfile, `LockKind`, programme trouvé ou `None`, commande à lancer à la main, mises à jour qu'il porte, fichiers dont il dépend, avertissements), sans rien lancer ; `regenerate(source, report, changes, jobs)` les lance après `writers.write` et rend des `Regenerated` (`LockStatus` : `regenerated`, `tool_missing`, `failed`, `undone` ; l'erreur, les fichiers remis, `installed` avec un `Reach` — `exact`, `above`, `below`, `unknown` — et `held_by`, `changed`). Un pilote par outil (`_Npm`, `_Pnpm`, `_Yarn1`, `_Yarn`, `_Uv`, `_Poetry`, `_Pdm`, `_Pipenv`, `_PipCompile`, `_UvPipCompile`). Tout passe par `_which` (`shutil.which`) et `_spawn` (`subprocess.run`, `shell=False`) ;
  - `update/writers` : `Target.pattern` (le format d'un fichier dont le nom ne dit rien), `constraints_file`, `python.constraints_target`, `rewrite` (des `Target` réécrites et relues, sans `prepare`), `replace_file` (en octets) ; `npm.catalog_target` prend des dépendances au lieu d'une `Update` ;
  - parseurs : `parsers.parse_lockfile` (un lockfile seul, d'après son nom), `parsers.lockfiles.dependents` (ce qui requiert un paquet à une version), `python.parse_pinned_requirements`, `python.requirements_references`, `python.pinned_version` (devenu public) ;
  - `report/terminal.py` : `render_changes` liste aussi les lockfiles à régénérer et avec quelle commande, `render_outcome` dit ce qu'il est advenu de chacun ;
  - `cli.update` : `lockfiles.plan` après `prepare`, garde-fou git sur les lockfiles aussi, « Réécrire 2 fichiers et régénérer 2 lockfiles ? », `regenerate` après `write` ; code 2 si un lockfile a échoué. Une mise à jour par le lockfile seul se fait maintenant (« Régénérer 1 lockfile ? »).
- **Viser la version choisie (tranché, vérifié outil par outil)** : régénérer garde les versions figées qui satisfont encore les contraintes. uv et pip-compile ont `-P x==V` (une contrainte ferme : uv a même redescendu `httpcore` pour tenir `h11==0.14.0`). npm, pnpm, Poetry et PDM gardent une version figée qui satisfait la contrainte : la version exacte est écrite à la place de la contrainte (`writers.rewrite`, sur le projet relu après l'écriture) le temps d'un premier passage, puis la contrainte est remise et l'outil relancé ; il garde la version et remet son lockfile d'accord avec le manifeste (vérifié : `^4.17.15` donne 4.17.21 si on la demande, au lieu de 4.18.1). Les catalogues pnpm et les versions forcées réécrites sont épinglés pareil. Une indirecte : `npm update x`, `pnpm update x --no-save`, `poetry update --lock x`, `pdm update --no-sync x`, qui ne touchent pas au manifeste (vérifié) et montent aussi haut que le permet ce qui la tire. Si le passage épinglé échoue, on régénère sans, comme une indirecte, et un avertissement le dit. **Yarn 1, Yarn 4 et pipenv ne gardent pas une version épinglée** (`^4.1.0` revient en 4.1.2 dès que la plage revient) : la plus haute permise. `yarn upgrade` (Yarn 1) réordonne le `package.json` : à la place, l'entrée du paquet est retirée du `yarn.lock` avant `yarn install`. `yarn up -R x` (Yarn 4) ne touche pas aux `package.json`. pipenv ignore la version demandée (`pipenv update --lock-only x==V`) et re-résout tout à chaque `pipenv lock`.
- **Relire** : le projet est relu (`engine.inventory`) ; pour une directe, `exact` si la version installée est la cible ; `above` (l'outil a pris la plus haute permise : Yarn, pipenv, repli npm) ; `below` avec les paquets qui la retiennent, trouvés dans le graphe du lockfile (`ms` 2.1.2 retenue par `debug` 4.3.1, qui l'exige exactement). Les autres versions changées sont dites (« aussi changé »), 10 au plus à l'écran.
- **Échec et remise en état (tranché)** : les lockfiles qui dépendent des mêmes fichiers forment un groupe ; avant de le lancer, ses fichiers sont lus en octets (lockfiles, manifestes de son écosystème dans ses projets, `pnpm-workspace.yaml`). Si un outil échoue (code non nul, délai de 600 s, programme qui ne se lance pas) ou sur Ctrl-C, tout le groupe est remis : les manifestes réécrits comme avant leur réécriture (`FileChange.before`), le reste comme avant la régénération. Les autres groupes ne bougent pas. L'erreur garde les 12 dernières lignes de l'outil, sans couleurs. Un projet qui a à la fois `package.json` et `requirements.in` (`vulnerable`) donne deux groupes : il fallait trier les manifestes par écosystème.
- **pip-tools** : l'outil vient de l'en-tête du `.txt` (« autogenerated by uv » → `uv pip compile`), ses options aussi, mais seulement celles d'une liste connue (forme du fichier, index, version de Python…) ; une autre (`--pip-args`) n'est pas reprise, et le plan le dit. `--exclude-newer` n'est pas repris : il écarterait les versions choisies (`vulnerable`, compilé avec `--exclude-newer 2019-01-01`, ne pouvait pas avoir flask 0.12.5). Sources : celles de l'en-tête si ce sont des fichiers du dossier, sinon le `.in`. `--output-file` n'est donné que s'il ne va pas de soi, pour que l'en-tête ne change pas. Un `.txt` qui en cite un autre par `-r`/`-c` (`requirements-dev.in` avec `-c requirements.txt`) est recompilé après lui, dans le même groupe.
- **Fichier de contraintes** : une option dont le « lockfile » n'est pas un lockfile du projet ni un nom de lockfile est un `-c` de pip (`writers.constraints_file`) : sa ligne `==X` devient un `Target` de plus dans `prepare` (diff montré avant de confirmer, garde-fou git compris), relue au format `requirements` ; `Changes.lockfiles` ne le cite plus. `--hash` : refusé avec la raison. Mini-projet `pip` : `certifi==2024.2.2` → `2024.12.14`.
- **Exécuter le code du projet** : `--ignore-scripts` (npm, pnpm, Yarn 1), `--ignore-pnpmfile` (pnpm), `--mode=update-lockfile` (Yarn 4 : rien n'est lié, aucun script). **`uv --no-build` n'est pas passé (tranché)** : il refuse tout paquet sans wheel pour une plateforme, donc change la résolution (Argos : `sslyze` n'a pas de wheel partout, `uv lock --no-build` échoue alors que `uv lock` résout en 0,2 s sans rien construire). uv, Poetry, PDM, pipenv et pip-compile peuvent construire des paquets publiés sans wheel : un avertissement le dit dans le plan, avant de confirmer. Yarn exécute la version de Yarn et les extensions du projet (`yarnPath`, `plugins`, `yarn-path`) : dit si le projet en déclare.
- **Environnement des outils** : sans `VIRTUAL_ENV` (pipenv avait pris le `.venv` de forceupdate pour celui du projet), `PIPENV_ACTIVE`, `POETRY_ACTIVE`, `UV_FROZEN`, `UV_LOCKED` ; avec `NO_COLOR`, pas de questions (`COREPACK_ENABLE_DOWNLOAD_PROMPT=0`, `PIPENV_YES`, `POETRY_NO_INTERACTION`), `YARN_ENABLE_IMMUTABLE_INSTALLS=false` et `--no-frozen-lockfile` (sinon, avec `CI=true`, Yarn 4 et pnpm refusent de changer le lockfile), `PYTHONIOENCODING=utf-8`. Entrée standard fermée. Sous Windows, un `.cmd` (`npm.CMD`) passe par `cmd.exe` : un argument qui contient `"%!&|<>^()` est refusé.
- **Effets de bord constatés** : pipenv crée le virtualenv du projet (dans `~/.virtualenvs`) et PDM un `.venv` dans le projet s'ils n'en ont pas (dit dans l'avertissement) ; Yarn 4 écrit `.yarn/install-state.gz` ; npm 11 ajoute parfois des paquets facultatifs de plateforme (`@emnapi/*` dans Argos), dits dans « aussi changé ». Poetry 2 refuse `--no-update` : la version vient de `poetry --version`.
- **Tests** : `tests/test_lockfiles.py` (44 tests, plus 4 `network` : le plan de chaque outil, en-têtes de pip-tools, cascade, écosystèmes séparés, fichier de contraintes ; avec de faux outils, l'épinglage puis la contrainte remise, indirecte retenue et plus haute, repli, échec et remise en état, outil absent, environnement, workspace lancé une fois depuis la racine, `.cmd`, délai, Ctrl-C, Yarn 1 hors du projet, Yarn 4, catalogue pnpm, Poetry ; les tests `network` lancent les vrais npm, uv et pnpm, sur des copies). `tests/conftest.py` : un troisième garde-fou (hors `network`, `_which` ne trouve rien et `_spawn` refuse) et `FakeTools` ; `update` dans `tests/test_cli.py` (régénéré, échec et code 2, lockfile seul, garde-fou sur un lockfile). 1590 tests, plus 8 réseau.
- **Vérifié à la main** (`update --yes` sur des copies, lockfiles relus) :
  - `vulnerable` : `package-lock.json` (lodash 4.18.1) par npm, `requirements.txt` (flask 0.12.5, jinja2 2.11.3 exactement) par `uv pip compile` ;
  - `npm` : lodash 4.18.1, `debug ~4.4.3`, l'alias `npm:ms@2.1.3` ; `uv` : pytest 9.2.0 par `-P` ; `pnpm-catalog` (`--level major`) : catalogue `legacy` `^3.0.1`, is-odd 3.0.1 et sa dépendance is-number 6.0.0 ; `pip` : `constraints.txt` réécrit ;
  - Argos (clone) : 10 mises à jour par les lockfiles seuls, toutes à la version exacte (`uv lock` avec 9 `-P`, `npm update react-router-dom`), botocore suit boto3 ;
  - cohérence : relancer npm sur les trois `package-lock.json` ne change plus rien, `uv lock --check` et `pnpm install --frozen-lockfile` passent, recompiler `requirements.txt` ne change que l'en-tête ;
  - Yarn 1 et 4, Poetry 1.8 et 2.5, PDM, pipenv et pip-compile vérifiés par `npx`, `corepack` et `uvx` dans le scratchpad (l'utilisateur a choisi de ne rien installer) : sans eux sur le PATH, forceupdate dit la commande à lancer.
- **Limites** : Yarn 1, Yarn 4 et pipenv montent à la plus haute version permise, pas forcément la choisie (dit : `above`) ; à l'expiration du délai sous Windows, seul `cmd.exe` est tué, pas le node qu'il a lancé (case ajoutée à E29) ; dans un workspace npm, une indirecte d'un membre que retient une version forcée de la racine n'a pas pu être reconstituée pour un essai (`npm update x --workspaces --include-workspace-root` est lancé, et la relecture dit si la cible n'est pas atteinte ; case ajoutée à E29).

---

## Phase D — Interface web

Les étapes E13 à E15 commencent par **charger le skill `ui-ux-pro-max`**. À partir
de E14, elles lisent `design-system/MASTER.md` (et la page de l'écran concerné
dans `design-system/pages/`, si elle existe).

### E12 — Serveur local et API

**But** : le moteur se pilote par HTTP, en sécurité, depuis le navigateur de la
personne.

- [x] `web/app.py` : FastAPI, servi par uvicorn. `ui` démarre le serveur sur `127.0.0.1` (port libre), ouvre le navigateur, et s'arrête avec Ctrl+C.
- [x] Sécurité, parce que le serveur lit le disque, écrit des fichiers et détient des tokens :
  - écoute sur `127.0.0.1` seulement ;
  - un jeton de session aléatoire, donné dans l'URL ouverte par la commande puis gardé en cookie `HttpOnly` ; toute requête sans lui est refusée ;
  - en-têtes `Host` et `Origin` vérifiés ; pas de CORS ;
  - les tokens des forges ne sont jamais renvoyés au navigateur.
- [x] Routes :
  - `GET /api/fs?path=` : lister les dossiers, pour les choisir dans l'interface ; dossiers récents ;
  - `POST /api/scans` : lancer une analyse en tâche de fond, renvoie un id ;
  - `GET /api/scans/{id}/events` : la progression (Server-Sent Events) ;
  - `GET /api/scans/{id}` : le rapport (le JSON de E07) ;
  - `DELETE /api/scans/{id}` : annuler l'analyse ;
  - `POST /api/updates/plan` : pour une sélection, le plan et les diffs. Depuis E09, les mises à jour possibles et la sélection par défaut sont déjà dans le rapport (`Project.updates`) ; la sélection envoyée est un `planner.Selection` (identifiant → version), validé par `planner.chosen` ;
  - `POST /api/updates/apply` : appliquer. Depuis E10 : `writers.prepare(root, planner.chosen(…))` donne les diffs (`Changes.files`, `FileChange.diff`) et ce qui ne sera pas appliqué (`Changes.skipped`, avec la raison) ; `git.uncommitted` le garde-fou ; `writers.write` l'écriture (`WriteError` si un fichier a changé depuis le diff). Le plan et l'application doivent porter sur le même `Changes`, ou refaire `prepare`. Depuis E11 : `lockfiles.plan(source, report, changes)` donne les lockfiles à régénérer (`Job` : commande, outil trouvé ou non, avertissements), à montrer avec le diff ; après `writers.write`, `lockfiles.regenerate(…)` les régénère et rend des `Regenerated` (statut, versions relues, fichiers remis, erreur). Les deux sont des dataclasses (`to_dict`). Un outil peut tourner plusieurs minutes (`LOCK_TIMEOUT`, 600 s par commande) : hors de la boucle du serveur, avec un événement de progression par lockfile ;
  - `POST /api/files` : analyser un fichier envoyé par glisser-déposer, et rendre sa version mise à jour à télécharger.
- [x] Le schéma OpenAPI est exporté (`web/openapi.json`) pour générer les types du front (E14).
- [x] Les analyses ne bloquent pas le serveur : lire un gros document npm (`next` : 31 Mo) prend environ 1 s sans rendre la main à la boucle `asyncio`. Les lancer hors de la boucle du serveur (un thread, ou une boucle à part), avec un `HttpClient` et un `Cache` partagés par toutes les analyses. Depuis E07 : `await engine.analyze(source, options, on_event=…, http=…, cache=…)` ; ses `models.Event` passent en SSE par `to_dict`, le rapport par `report.json.build` ; `engine.scan` (`asyncio.run`) ne s'appelle pas depuis une boucle en cours.
- [x] Ajoutés en route : `update/local.py` (l'enchaînement de `cli.update`), un abandon d'hôte qui expire (`net/http.py`), la progression de `lockfiles.regenerate`, le téléchargement d'un fichier réécrit, les pages du front servies, le quatrième garde-fou des tests (navigateur), `httpx2` en dev (voir les notes).

**À reprendre, comme modèle** : l'organisation de `sechunter/dashboard/api/` dans Argos.

**Tests** : client de test FastAPI. Chaque route, le refus sans jeton, le refus d'un `Host` ou d'une `Origin` étrangers, l'annulation.

**Fini quand** : `ui` démarre ; toutes les routes marchent avec `curl` et le
jeton ; rien ne marche sans lui.

**Notes** (session 12) :

- **Organisation** (sur le modèle de `sechunter/dashboard/` d'Argos : l'application, ses middlewares, un routeur par module) :
  - `web/app.py` : `create_app(Settings)` (routes, garde, tâches de fond créées au démarrage et arrêtées à l'arrêt, pages du front) et `serve` (pour `ui`) ; `web/security.py` (`Guard`, middleware ASGI) ; `web/jobs.py` (`Worker`, `Jobs`, `Scan`, `Plan`, `Progress`, `Recent`) ; `web/sse.py` ; `web/schemas.py` (requêtes, réponses, conversions) ; `web/openapi.py` (export) ; `web/routes/` : `fs.py`, `scans.py`, `updates.py`, `files.py`, et dans `__init__.py` `respond`, `errors`, `find_scan`, `find_plan`, `sentence` ;
  - `update/local.py` (ajouté) : `prepare` (sélection validée, `writers.prepare`, `lockfiles.plan`) → `Prepared` (`changes`, `jobs`, `runnable`, `touched`, `empty`), `uncommitted`, `apply` (`writers.write` puis `lockfiles.regenerate`, avec ses événements). `cli.update` passe par lui : la ligne de commande et l'API font la même chose ;
  - `report/json.py` : `Document` (le rapport tel que le rend `build`, par héritage de `Report`), `Tool`, `SummaryDocument` : seulement pour décrire le JSON dans le schéma ;
  - `models.EventKind` : `WRITTEN` et `REGENERATING` (mise à jour) ; `lockfiles.regenerate(…, on_event=)` émet un `REGENERATING` avant chaque outil lancé ; `LocalSource.file` (un fichier seul) ;
  - dépendances : `fastapi` 0.162 et `uvicorn` 0.54 (prévus) ; en dev, **`httpx2`** 2.16 (ajouté) : Starlette 1.10 le demande pour son client de test (« Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` »), c'est le successeur d'httpx maintenu par l'équipe pydantic. Le moteur garde httpx. Pas de `python-multipart` : le fichier envoyé est le corps brut de la requête.
- **Sécurité (`web/security.py`)** :
  - écoute sur `127.0.0.1` seulement, socket ouvert par `serve` (port libre, ou `--port`) et passé à uvicorn ; sous Windows `SO_EXCLUSIVEADDRUSE` ;
  - jeton `secrets.token_urlsafe(32)` à chaque démarrage. L'adresse affichée (`/?token=…`) pose le cookie `forceupdate-<port>` (`HttpOnly; SameSite=Strict; Path=/`) et renvoie (303) vers la même page sans le jeton. Ensuite le cookie, ou `Authorization: Bearer <jeton>` (curl) ; jamais le jeton dans l'adresse d'une route de `/api` ; comparé par `secrets.compare_digest` ; sinon 401 ;
  - `Host` : `127.0.0.1:<port>` ou `localhost:<port>`, sinon 400 (DNS rebinding). `Origin` s'il y en a un : l'adresse du serveur ; `Sec-Fetch-Site` s'il y en a un : `same-origin` ou `none` ; sinon 403. **Trouvé** : `SameSite` ne suffit pas, une page servie par un autre port de 127.0.0.1 est du même « site » pour le navigateur, et les cookies ne distinguent pas les ports (d'où le port dans le nom du cookie) ;
  - pas de CORS (aucun en-tête `Access-Control-*`, une requête `OPTIONS` d'ailleurs est refusée) ; pas de WebSocket ; en-têtes sur toutes les réponses, refus compris : `Cache-Control: no-store`, `Referrer-Policy: no-referrer` (la première adresse porte le jeton), `X-Frame-Options: DENY`, `nosniff`, COOP et CORP `same-origin`, CSP `default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'` (à vérifier avec le front construit, E14) ;
  - uvicorn sans journal des accès (il écrirait le jeton) ; le schéma OpenAPI et `/docs` ne sont pas servis.
- **Tâches de fond (`web/jobs.py`, tranché)** :
  - les analyses tournent dans une boucle `asyncio` à elles, dans leur thread (`Worker`), avec un `HttpClient` et le `Cache` de l'utilisateur partagés ; une analyse hors ligne passe `http=None` (le moteur crée un client qui n'envoie rien), une analyse sans cache `cache=None`. Annuler = annuler la tâche (`run_coroutine_threadsafe`), interrompue à sa prochaine attente ;
  - **trouvé** : sous Windows, une boucle Proactor créée (ou fermée) dans le thread principal y prend (ou y coupe) le réveil sur Ctrl+C (`signal.set_wakeup_fd`) ; la boucle des analyses, créée au démarrage du serveur, le prenait à celle d'uvicorn (« Exception ignored when trying to send to the signal wakeup fd » à l'arrêt). Elle naît et meurt maintenant dans son thread (testé) ;
  - les mises à jour (`local.apply` : écriture puis outils) dans un thread à part, une à la fois ; elles ne s'annulent pas (si un outil échoue, `regenerate` remet tout comme avant). À l'arrêt, le serveur attend celle en cours ;
  - l'état d'une tâche (statut, événements, résultat) n'est modifié que dans la boucle du serveur : les threads y postent leurs événements et leur résultat (`call_soon_threadsafe`) ; les routes le lisent sans verrou. Les calculs synchrones des routes (`LocalSource`, `local.prepare`, `git.uncommitted`, liste d'un dossier) passent par `asyncio.to_thread` ;
  - analyses et plans en mémoire, le temps de la session : les 20 analyses les plus récentes, avec leurs plans ; seuls les 10 derniers chemins analysés sont gardés sur le disque (`recent.json` dans `platformdirs.user_state_path("forceupdate")`).
- **`net/http.py` (changé)** : un hôte abandonné ne l'est plus pour toute la session mais 60 s (`DOWN_FOR`), ou le temps que demande `Retry-After` : le client du serveur sert des heures, le réseau peut revenir. Rien ne change pour une analyse en ligne de commande.
- **Ce que rend l'API (tranché)** : le rapport tel quel (le JSON de E07, champ `report` de `GET /api/scans/{id}`). Les plans désignent les mises à jour par `Update.id` et la version de l'option (`{"update", "version"}`) au lieu de recopier `Update` et `UpdateOption` ; les `Changes`, `Job`, `Regenerated` restent sur le serveur, résumés dans le plan (`files` : chemin et diff, sans le texte avant et après ; `lockfiles` ; `results`). On applique un plan par son identifiant : le navigateur ne renvoie jamais les réécritures, et c'est le même `Prepared` qui est écrit. Un plan s'applique une fois ; le garde-fou git est montré dans le plan (`uncommitted`) et revérifié en appliquant (409, sauf `force`). Tout est décrit dans `docs/JSON_FORMAT.md` (« L'API de l'interface web »).
- **Routes** : en plus de celles du plan, `GET /api/scans` (les analyses de la session), `GET /api/updates/{id}` et `/events` (suivre l'application), `GET /api/updates/{id}/files/{chemin}` (télécharger un fichier réécrit). Codes : 202 pour ce qui part en tâche de fond, 201 pour un plan, 400/404/409/413 avec `{"detail": "…"}` en français, 422 de FastAPI pour un corps mal formé.
- **SSE** : les événements déjà passés d'abord, numérotés (`Last-Event-ID` reprend après le dernier reçu), `event: progress` puis `event: end` (`{"status", "error"}`) ; `: ping` après 15 s sans rien (avec ASGI 2.4, Starlette ne remarque un navigateur parti qu'au prochain envoi). Le front devra fermer son `EventSource` à `end`.
- **Fichier envoyé (tranché)** : `POST /api/files?name=…`, le contenu en corps brut, un manifeste ou un lockfile reconnu par son nom (sinon 400), 2 Mo (50 pour un lockfile, sinon 413). Rangé dans un dossier temporaire et analysé comme un fichier (`kind: "upload"`, `source` : son nom) : même progression, même rapport, même plan. Mais aucun lockfile n'est prévu (`local.prepare(regenerate=False)` : aucun outil ne tourne sur un fichier envoyé), le plan ne s'applique pas (409), et sa version réécrite se télécharge depuis le plan. Le dossier temporaire est effacé avec l'analyse, ou à l'arrêt.
- **`GET /api/fs`** : seulement des noms (dossiers, et fichiers de dépendances reconnus par `match_dependency_file`), jamais un contenu. Sans `path` : le dossier personnel et les lecteurs (`GetLogicalDrives`, sans toucher aux lecteurs : un lecteur réseau déconnecté ferait attendre). Liens symboliques et jonctions écartés (`st_reparse_tag`), mais pas les autres points d'analyse de Windows : le dossier OneDrive en est un. 5000 entrées au plus (`truncated`). Chemins au format POSIX, comme `Report.source`.
- **Pages** : le front construit (`web/static/`, E14) est servi, une adresse inconnue rend `index.html` ; d'ici là, une ligne de texte. Un chemin qui sortirait de `static/` rend `index.html`.
- **Schéma OpenAPI (`web/openapi.json`)** : tiré des dataclasses par FastAPI, `operationId` = nom de la fonction (`start_scan`…). Retouche : FastAPI rend facultatif un champ qui a une valeur par défaut, alors que les réponses portent toujours tous leurs champs ; tous les champs des objets atteints depuis une réponse 2xx sont donc marqués requis, et un type ne doit pas servir à la fois en entrée et en sortie (vérifié). La configuration de pydantic (`json_schema_serialization_defaults_required`) a été essayée : elle ne se propage pas de façon fiable aux dataclasses imbriquées. Un test vérifie que le fichier est à jour, un autre que les vraies réponses le suivent champ par champ.
- **`forceupdate ui`** : `--port` (0 : un port libre), `--no-browser` ; affiche l'adresse d'entrée (jeton compris), ouvre le navigateur dès que le serveur répond, s'arrête avec Ctrl+C (« Interface arrêtée. »). uvicorn renvoie le signal reçu une fois arrêté : `serve` avale le `KeyboardInterrupt` qui en résulte. Ctrl+Break sous Windows arrête proprement aussi, mais le processus sort ensuite avec le code 3, sans le message. Port pris : erreur, code 2.
- **Tests** : `tests/test_web_security.py` (chaque route refusée sans jeton, mauvais jeton ou cookie, cookie d'un autre port, jeton refusé dans l'adresse de l'API, entrée et redirection, `Host`, `Origin`, `Sec-Fetch-Site`, pas de CORS, en-têtes, WebSocket), `tests/test_web_api.py` (dossiers, liens et jonctions, analyses et options, SSE et `Last-Event-ID`, annulation, échec, plan, sélection refusée, application avec de faux npm et uv, outil en échec, fichier changé depuis le plan, garde-fou git et `force`, rien à appliquer, téléchargement, fichier envoyé, pages, oubli des vieilles analyses), `tests/test_web_server.py` (client et cache partagés hors de la boucle du serveur, ordre des événements, pings, `recent.json`, arrêt, schéma à jour et suivi par les réponses, vrai serveur uvicorn sur un port libre, réveil sur Ctrl+C laissé au serveur, Ctrl+C pendant une analyse, port pris, commande `ui`), `tests/test_update_local.py`, et des ajouts à `test_net_http.py` et `test_lockfiles.py`. `conftest.py` : fixtures `web_settings`, `api`, `finished`, et un quatrième garde-fou (`webbrowser.open` refusé) : l'ancien test « `ui` pas encore disponible » lançait le vrai serveur et bloquait la suite. 1706 tests verts (plus 8 réseau) sous 3.11, 3.12 et 3.14, ruff propre.
- **Vérifié à la main** (`forceupdate ui --no-browser`, puis curl) : sans jeton, 401 partout et rien de lancé ; `Host` étranger 400, `Origin` et `Sec-Fetch-Site` étrangers 403 ; l'adresse d'entrée pose le cookie ; `vulnerable` : 28 failles, le plan (deux diffs, deux lockfiles avec npm et uv trouvés, `uncommitted: []`) ; une analyse d'Argos annulée ; sur une copie dans le scratchpad, l'application avec les vrais npm et uv : `package-lock.json` (lodash 4.18.1) et `requirements.txt` (flask 0.12.5, jinja2 2.11.3), versions exactes, puis 409 si on réapplique ; un `requirements.in` envoyé, téléchargé réécrit, application refusée. Arrêt par signal pendant une analyse : 0,2 s.
- **Limites** : analyses et plans perdus à l'arrêt (seuls les chemins récents restent) ; une mise à jour en cours ne s'annule pas ; un serveur web local malveillant visité dans le même navigateur, sur un autre port de 127.0.0.1, recevrait le cookie (les cookies ne distinguent pas les ports ; ses requêtes vers forceupdate restent refusées par `Origin` et `Sec-Fetch-Site`) ; `Jobs.start_scan` prend une `LocalSource` (E17 : une source de forge).

### E13 — Conception de l'interface (skill ui-ux-pro-max)

**But** : savoir exactement à quoi ressemble l'interface avant de la coder, et la
faire valider par l'utilisateur.

- [ ] Charger le skill `ui-ux-pro-max` et suivre son déroulé :
  - analyser le besoin (produit : outil de développeur, tableau de bord, sobre et lisible) ;
  - générer le design system avec `--design-system --persist -p "forceupdate"` → `design-system/MASTER.md`, versionné ;
  - le nom invite à un clin d'œil à Star Wars : à doser (un détail, un message de chargement), sans nuire à la lisibilité ni reprendre de logo ou d'image protégés ;
  - une page `design-system/pages/<écran>.md` pour chaque écran qui s'écarte du master.

  Sous Windows, lancer les scripts du skill avec `python`, pas `python3`.
- [ ] Les écrans :

  | # | Écran | Contenu |
  |---|---|---|
  | 1 | Accueil | Choisir une source : dossier, fichier, ou un compte connecté. Analyses récentes |
  | 2 | Choisir un dossier ou un fichier | Navigateur de dossiers de l'ordinateur, dossiers récents, zone de glisser-déposer |
  | 3 | Analyse en cours | Progression par étape et par projet, annuler |
  | 4 | Rapport | Synthèse (compteurs par type et gravité), langages, projets, tableau des dépendances filtrable et triable, détail d'une dépendance (versions, failles, liens), fichiers écartés (tests, exemples) |
  | 5 | Mise à jour | Cases à cocher (les sûres pré-cochées), avertissements des majeures, diff par fichier, appliquer, résultat |
  | 6 | Comptes | Connecter ou déconnecter GitHub, GitLab, Bitbucket ; qui est connecté, avec quels droits |
  | 7 | Mes dépôts | Liste de toutes les forges, filtres, sélection, analyse groupée, synthèse multi-dépôts |
  | 8 | PR / MR | Récapitulatif avant envoi (N dépôts, M PR), résultat avec les liens |
  | 9 | Réglages | Sélection par défaut, paquets ignorés, dépôts exclus, cache |
- [ ] Pour chaque écran, les états : vide, chargement, erreur, hors ligne, « non concluant ». Clair et sombre. Accessibilité : les règles de priorité 1 du skill.
- [ ] Maquettes HTML statiques des écrans 1, 4, 5 et 7, dans `design-system/mockups/`, ouvrables dans le navigateur. Les montrer à l'utilisateur.
- [ ] Confirmer la pile du front (proposition : React + TypeScript + Vite + Tailwind + shadcn/ui) et les icônes (SVG, pas d'emoji).
- [ ] Depuis E12, ce que l'API permet, à refléter dans les écrans : la progression par étape (`reading`, `projects_found`, `checking`, `package_checked` avec le paquet, `vulnerabilities_checked`) et par lockfile pendant une mise à jour (`written`, `regenerating`) ; l'annulation d'une analyse (pas d'une mise à jour, qui ne s'annule pas) ; « Analyses récentes » de l'écran 1 : l'API garde les chemins récents d'une session à l'autre (`recent`) et les analyses de la session seulement (`GET /api/scans`), pas les rapports ; le garde-fou git (`uncommitted`, puis « appliquer quand même » : `force`) ; un fichier envoyé se télécharge réécrit, il ne s'applique pas. Voir `docs/JSON_FORMAT.md`, « L'API de l'interface web ».

**Fini quand** : l'utilisateur a validé le design system et les maquettes.

### E14 — Front : socle et analyse locale

**But** : dans le navigateur, on choisit un dossier et on lit le rapport.

- [ ] `frontend/` avec la pile choisie en E13 :
  - types générés depuis `web/openapi.json` ;
  - thème tiré de `design-system/MASTER.md` (couleurs, typographie, espacements sous forme de tokens).
- [ ] Build : `npm run build` écrit dans `src/forceupdate/web/static/`, qui est inclus dans le paquet Python. En dev : serveur Vite avec un proxy vers l'API.
- [ ] Depuis E12 :
  - types générés depuis `src/forceupdate/web/openapi.json` (`operationId` : `start_scan`, `plan_update`…) ; tous les champs des réponses y sont requis ;
  - le serveur sert déjà `web/static/` (une adresse inconnue rend `index.html`) avec une CSP `default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'` (`web.security.SECURITY_HEADERS`) : vérifier que le front construit marche avec elle (styles en ligne de bibliothèques ?) et ne l'assouplir qu'au strict nécessaire ;
  - **en dev, le proxy de Vite** : le garde refuse une `Origin` ou un `Host` qui ne sont pas ceux du serveur (`http://localhost:5173` le serait). Le proxy doit réécrire `Host` (`changeOrigin`) et `Origin` vers l'adresse du serveur, et porter le jeton (`Authorization: Bearer`, lu dans une variable d'environnement de dev) ; ne jamais affaiblir le garde pour le dev ;
  - SSE : fermer l'`EventSource` à l'événement `end` (sinon il se rebranche) ; les cookies passent tout seuls (même origine).
- [ ] Écrans 1 à 4 (accueil, choisir un dossier ou un fichier, analyse en cours, rapport).
- [ ] Tests : Vitest + Testing Library pour les composants ; un test Playwright de bout en bout (choisir un mini-projet, voir le bon rapport).
- [ ] Revue avec la checklist du skill : accessibilité, états, clair et sombre.

**Fini quand** : depuis `ui`, on analyse un vrai dossier ; le rapport est juste et
conforme aux maquettes.

### E15 — Front : mise à jour locale

**But** : tout le parcours local se fait dans l'interface.

- [ ] Écran 5 :
  - une case par mise à jour, pré-cochée selon E09. Une `Update` est un groupe de cases dont une au plus est cochée (`options`, `selected`) ; montrer ses avertissements (`warnings`), les failles corrigées, laissées et apportées (`fixes`, `unfixed`, `introduced` depuis E10), sa `note`, et griser une option `manual` en disant pourquoi ;
  - diff par fichier (`FileChange.diff`, E10), et les options cochées qui ne seront pas appliquées (`Changes.skipped` : fichier changé, `--hash`…) ;
  - appliquer ;
  - résultat : lockfiles régénérés, ou commande à lancer. Depuis E11 : avant d'appliquer, les `Job` (commande, avertissements de ce que l'outil exécute) ; après, chaque `Regenerated` : version obtenue (`Installed.reach` : exacte, plus haute, retenue par `held_by`), « aussi changé » (`changed`), fichiers remis (`restored`) et l'erreur de l'outil.
- [ ] Glisser-déposer d'un fichier : analyse, puis téléchargement du fichier mis à jour.
- [ ] Depuis E12 : plan `POST /api/updates/plan` (`files`, `skipped`, `lockfiles`, `uncommitted`, `applicable`) ; appliquer `POST /api/updates/apply` (409 avec les fichiers si git n'a pas leurs changements en commit : proposer d'appliquer quand même, `force`) ; suivre `GET /api/updates/{id}/events` ; résultat dans `results`. Glisser-déposer : `POST /api/files?name=…` (le contenu en corps), puis le même écran de rapport, le plan, et `GET /api/updates/{id}/files/{nom}` pour télécharger.
- [ ] Garde-fous visibles : changements git non commités, outil natif absent, échec de résolution (fichiers restaurés).
- [ ] Tests : composants, et un test de bout en bout qui applique une mise à jour sur une copie d'un mini-projet.

**Fini quand** : choisir → analyser → cocher → voir le diff → appliquer, sans
quitter le navigateur, sur un projet Python et un projet npm.

---

## Phase E — Forges : GitHub, GitLab, Bitbucket

Chaque forge implémente la même interface `Forge` (E16). L'interface web et le
reste de l'outil ne connaissent que cette interface.

### E16 — Interface `Forge` commune, connexion GitHub

**But** : l'utilisateur connecte son compte GitHub depuis l'interface.

- [ ] `forges/base.py`, interface `Forge` :
  - `whoami` ;
  - `list_repos`, `tree`, `read_file` ;
  - `clone`, `push_branch` ;
  - `find_open_request`, `open_or_update_request`.
- [ ] Prérequis, à faire par l'utilisateur une seule fois, en tant qu'auteur de l'outil (la session le guide) : enregistrer l'outil comme OAuth App GitHub, avec une adresse de retour `http://127.0.0.1/…` et le Device Flow activé. Ensuite, chaque personne connecte son propre compte.
- [ ] Connexion GitHub, depuis l'écran « Comptes » :
  - bouton « Se connecter avec GitHub » → page d'autorisation GitHub → retour sur le serveur local. GitHub accepte un retour vers `127.0.0.1` sur n'importe quel port pour une OAuth App : à vérifier ;
  - `state` anti-CSRF, comme dans `oauth_sso.py` d'Argos ;
  - si le retour ne marche pas : device flow affiché dans l'interface (un code à taper sur github.com) ;
  - autres options : coller un token, ou reprendre celui de `gh` s'il est connecté ;
  - portée : `repo` (lire les dépôts privés, pousser une branche, ouvrir une PR). À confirmer au moment de coder.
- [ ] `forges/accounts.py` : tokens rangés dans le trousseau du système (`keyring`). Jamais affichés, jamais dans les logs, jamais envoyés au navigateur. Se déconnecter les efface.
- [ ] `forges/github.py` :
  - client REST (pagination `Link`, limites de débit, messages clairs pour 401, 403 et 404) ;
  - `whoami`, avec ce que le token permet (lecture seule, ou écriture et PR).
- [ ] Écran 6 (Comptes) pour GitHub.

**À reprendre** : `sechunter/dashboard/api/routes/oauth_sso.py` d'Argos (flux OAuth, `state` en cookie).

**Tests** : API GitHub et OAuth simulés.

**Fini quand** : depuis l'interface, l'utilisateur connecte son vrai compte
GitHub, le voit dans « Comptes », puis se déconnecte.

### E17 — GitHub : dépôts et analyse sans cloner

**But** : tous les dépôts GitHub de la personne, analysés depuis l'interface.

- [ ] `list_repos` : `/user/repos` (`affiliation=owner,collaborator,organization_member`). Chaque dépôt est marqué archivé, vide, fork, et avec ou sans droit de push. Les organisations qui restreignent l'accès des OAuth Apps sont signalées.
- [ ] `sources/forge.py`, pour chaque dépôt :
  - arborescence de la branche par défaut (`git/trees?recursive=1`), sans les dossiers ignorés (`detect.manifests.is_ignored_path`) ;
  - `read_text` plafonné comme en local, avec `detect.manifests.max_read_size` (50 Mo pour un lockfile) ; il est aussi appelé pour les `-r` des `requirements.txt`, pour le `pyproject.toml` racine d'un workspace uv, et pour `pnpm-workspace.yaml` (E04), qui ne sont pas des manifestes repérés : les télécharger aussi. Il doit rendre `None`, sans erreur, pour un fichier absent (`pnpm-workspace.yaml` est facultatif) ;
  - langages : détecteur de E02 (`detect_languages`) appliqué aux chemins et tailles de l'arborescence ; projets : `find_projects` ;
  - télécharger seulement les manifestes et lockfiles, dans un dossier temporaire qui reproduit les chemins ;
  - puis le pipeline local, inchangé.
- [ ] Cas particuliers :
  - arborescence tronquée → clone superficiel (E18) ;
  - fichier de plus de 1 Mo → `Accept: application/vnd.github.raw` ;
  - dépôt vide → sauté, signalé.
- [ ] Concurrence bornée entre dépôts ; cache des registres partagé ; nombre de requêtes API consommées affiché.
- [ ] Analyser un dépôt public d'un autre compte : champ « `owner/repo` ou URL ».
- [ ] Écran 7 (Mes dépôts : liste, filtres, sélection, synthèse) ; le rapport d'un dépôt réutilise l'écran 4.
- [ ] Depuis E12 : `web.jobs.Jobs.start_scan` prend une `LocalSource` ; l'ouvrir à la source d'un dépôt (et `ScanSummary.kind` à `repository`), les analyses de dépôts passant par le même `Worker` (client et cache partagés, concurrence bornée).

**Fini quand** : dans l'interface, tous les dépôts du compte sont listés et
analysés ; le rapport est vérifié à la main sur 2 ou 3 dépôts.

### E18 — GitHub : une PR par dépôt

**But** : chaque dépôt à mettre à jour reçoit une PR propre.

- [ ] `forges/git.py` :
  - adapter `git_client.py` d'Argos : token donné à git via un credential helper éphémère, jamais dans `argv`, masqué dans les messages ;
  - sans `target_validator` : on ne parle qu'à des forges connues ;
  - clone superficiel de la branche par défaut ;
  - le même mécanisme sert au push.
- [ ] Dossier de travail temporaire nettoyé à la sortie (adapter `workspace.py` d'Argos).
- [ ] Pour chaque dépôt :
  1. clone ;
  2. sélection (E09), réécriture (E10), lockfiles (E11 : `lockfiles.plan` puis `regenerate`, sur le clone). Un outil absent ou qui échoue : la PR le dit dans sa description (la commande à lancer, l'erreur), et les fichiers remis comme avant ne sont pas commités ;
  3. branche `forceupdate/dependencies`, commit (auteur : l'utilisateur du token), push ;
  4. PR, avec en description le rapport Markdown du dépôt.
- [ ] Idempotence : si la PR existe déjà, pousser la branche à jour et mettre à jour la description, sans ouvrir de nouvelle PR. Rien à faire → rien poussé.
- [ ] Garde-fous :
  - jamais de push sur la branche par défaut ;
  - dépôts archivés ou sans droit de push : sautés et signalés ;
  - un récapitulatif avant d'envoyer (N dépôts, M PR, le détail par dépôt), et rien n'est poussé sans validation.
- [ ] Écran 8 (récapitulatif, puis résultat avec les liens des PR).

**À reprendre** : `~/Desktop/the good guy/sechunter/core/repo/git_client.py`,
`workspace.py`, et `github_app.py` (`create_pull_request`, pour les appels REST).

**Tests** : un dépôt git local « bare » sert de remote ; l'API GitHub est simulée.

**Fini quand** : depuis l'interface, une PR s'ouvre sur un dépôt de test de
l'utilisateur ; relancer met à jour la même PR.

### E19 — GitLab

**But** : la même chose que E16 à E18, pour GitLab.

- [ ] Prérequis, à faire par l'utilisateur (la session le guide) : enregistrer l'outil comme application OAuth sur gitlab.com, « non confidentielle » (PKCE, pas de secret), avec un retour vers `127.0.0.1`.
- [ ] Connexion :
  - gitlab.com : OAuth avec PKCE, portée `api` ;
  - instance auto-hébergée : son URL et un token personnel. Pour l'OAuth, il faudrait enregistrer l'outil sur chaque instance.
- [ ] `forges/gitlab.py` :
  - projets (`membership=true`), y compris ceux des groupes et sous-groupes ;
  - langages, arborescence (paginée), fichiers bruts ;
  - clone (`oauth2:<token>`, déjà prévu par `git_client.py` d'Argos) ;
  - merge requests : création, mise à jour, idempotence.
- [ ] L'interface dit « merge request » pour GitLab, « pull request » ailleurs.

**Fini quand** : sur un projet de test gitlab.com, depuis l'interface : connexion,
analyse, MR ouverte, puis mise à jour de la même MR.

### E20 — Bitbucket Cloud

**But** : la même chose, pour Bitbucket Cloud.

- [ ] Prérequis, à faire par l'utilisateur (la session le guide) : créer un « OAuth consumer » Bitbucket, avec un retour vers `127.0.0.1`.
- [ ] Connexion : OAuth ; en repli, un token d'API Atlassian (les « app passwords » sont en fin de vie : à vérifier).
- [ ] `forges/bitbucket.py` :
  - workspaces et dépôts (`role=member`) ;
  - fichiers (`/src/{commit}/{chemin}`) ;
  - clone (`x-token-auth:<token>`) ;
  - pull requests : création, mise à jour, idempotence.
- [ ] Bitbucket ne donne pas l'arborescence complète en un appel : parcours dossier par dossier avec `max_depth`, ou clone superficiel pour un gros dépôt. Il ne donne qu'un langage par dépôt : on utilise le détecteur de E02 sur l'arborescence.
- [ ] Bitbucket Data Center (auto-hébergé) : hors V1, écrit dans la doc.

**Fini quand** : sur un dépôt de test Bitbucket, depuis l'interface : connexion,
analyse, PR ouverte, puis mise à jour de la même PR.

---

## Phase F — Les 6 autres écosystèmes

Chaque étape fait, pour son écosystème, ce que les phases B et C ont fait pour
Python et npm :

- parseurs (repris de `reference/` et corrigés), avec l'emplacement des contraintes ;
- règles de versions (E05) : une `VersionScheme` dans `versions/`, ajoutée à `versions._SCHEMES`. Une contrainte écrite dans un autre fichier (`workspace = true` de Cargo, catalogue Gradle) va dans `Dependency.resolved_constraint`, comme `catalog:` de pnpm ;
- client du registre (E06) ;
- failles (E08) : rien à écrire, OSV couvre les 8 écosystèmes, mais elles ne sont cherchées que si `versions.for_ecosystem` connaît l'écosystème (`checks.vulns.version_to_check`). Vérifier le nom qu'OSV attend (Maven `groupe:artefact`, Go le chemin du module, NuGet sans tenir compte de la casse) et qu'un avis de l'écosystème donne la bonne version corrigée (`Advisory.fixed_in`) ;
- styles de contrainte (E09) : leurs règles de réécriture dans `update/constraints.py`, avec un tableau de cas (Cargo : `1.2` veut dire `^1.2` ; `~>` de Ruby, qui ressemble à `~=` ; Composer : `^`, `~`, `||` et `|` ; plages Maven et NuGet `[1.0,2.0)`) ;
- réécriture des manifestes (E10) ;
- régénération du lockfile (E11) : un `LockKind` et son pilote dans `update/lockfiles.py`, la commande vérifiée sur la version actuelle de l'outil (garde-t-il une version épinglée ? sait-il viser un paquet sans toucher au manifeste ?), sans les scripts du projet, et ce qu'il exécute quand même dans `_RUNS_CODE`. Cargo : `cargo update -p x --precise V`.

L'interface et les forges en profitent sans travail en plus.

**Fini quand**, pour chaque étape : sur un mini-projet de l'écosystème, l'analyse
et la mise à jour donnent un résultat juste, dans l'interface et en ligne de
commande. Si l'outil natif n'est pas installé sur la machine, la régénération du
lockfile est testée avec une commande simulée, et c'est noté.

### E21 — Rust (crates.io)

- [ ] Reprendre `parse_cargo_toml`, `parse_cargo_lock` et leurs tests. Corriger :
  - `workspace = true` : version lue dans `[workspace.dependencies]` à la racine ;
  - `[target.'…'.dependencies]` ;
  - dépendances renommées (`package = "…"`) ;
  - `git` / `path` : non vérifiables ;
  - membres de workspace : E02 rattache le `Cargo.lock` du parent le plus proche ; vérifier `[workspace] members` / `exclude`.
- [ ] Versions Cargo : `1.2` veut dire `^1.2` ; `=`, `~`, `*`.
- [ ] Registre : l'index « sparse » (`index.crates.io`) plutôt que l'API (1 requête par seconde). Il donne `yanked`.
- [ ] Réécriture de `Cargo.toml` ; lockfile : `cargo update -p <nom> --precise <version>`.

### E22 — Go

- [ ] Reprendre `parse_go_mod` et ses tests. Corriger :
  - `// indirect` → `direct=False` ;
  - `replace` vers un chemin local → non vérifiable ; vers un autre module → c'est lui qu'on vérifie ;
  - `exclude`, `retract`.

  `go.sum` n'est plus une source de versions.
- [ ] Workspaces Go (`go.work`, `go.work.sum`) : à reconnaître dans `detect/manifests.py`, qui ne les connaît pas encore.
- [ ] Versions :
  - semver avec `v` ;
  - pseudo-versions (`v0.0.0-20230101…-abcdef`), comparées par date ;
  - `+incompatible`.
- [ ] Registre : `proxy.golang.org` (`/@v/list`, `/@latest`, chemins avec majuscules encodées).
- [ ] Changer de majeur (v2 et plus) change le chemin du module : signalé, jamais appliqué.
- [ ] Réécriture de `go.mod` ; régénération : `go get <module>@<version>` puis `go mod tidy`.

### E23 — PHP (Composer)

- [ ] Reprendre `parse_composer_json`, `parse_composer_lock` et leurs tests. Corriger :
  - `dev-master` et autres branches : non vérifiables ;
  - `php` et `ext-*` sont mis de côté pour E27 (version de PHP).
- [ ] Contraintes Composer : `^`, `~`, `||`, `|`, `-`, `*`, suffixes de stabilité (`@dev`).
- [ ] Registre : Packagist `p2`. `abandoned` donne un constat « déprécié », avec le paquet de remplacement s'il est indiqué.
- [ ] Réécriture de `composer.json` ; lockfile : `composer update <nom> --no-install --no-scripts --no-plugins`.

### E24 — Ruby (Bundler)

- [ ] Reprendre `parse_gemfile_lock` et ses tests.
- [ ] Ajouter `Gemfile`, lu par motifs : c'est du Ruby, on ne l'exécute pas. À lire :
  - `gem "nom", "~> 1.2"` ;
  - les groupes (`group :development`) ;
  - `gemspec`.
- [ ] Versions : `Gem::Version` (segments, `.pre`) et `~>`.
- [ ] Registre : RubyGems (`/api/v1/versions/<nom>.json`).
- [ ] Réécriture du `Gemfile` ; lockfile : `bundle lock --update <nom>`. Prévenir que Bundler évalue le `Gemfile`, donc exécute du code du projet.

### E25 — Java (Maven, Gradle)

- [ ] Reprendre `parse_pom_xml` et ses tests, puis le réécrire avec `xml.etree` (bibliothèque standard) au lieu de motifs :
  - ordre des balises libre ;
  - `${propriété}` résolues depuis `<properties>` (et le parent s'il est dans le dépôt) ;
  - `dependencyManagement`, plugins ;
  - version héritée d'un parent ou d'un BOM distant : « gérée par le parent ».
- [ ] Gradle :
  - catalogue `gradle/libs.versions.toml` (TOML, donc fiable) ;
  - `build.gradle` et `build.gradle.kts`, formes littérales courantes (`implementation("g:a:v")`) ;
  - variables non résolues : non vérifiables.
- [ ] Ordre des versions Maven : qualificatifs `alpha` < `beta` < `milestone` < `rc` < `snapshot` < `""` < `sp`.
- [ ] Registre : `maven-metadata.xml` de Maven Central, et Google Maven pour `androidx.*` et `com.android.*`.
- [ ] Réécriture là où la version est définie (la balise ou la propriété), dans `libs.versions.toml`, ou dans les littéraux Gradle. Pas de lockfile : les verrous Gradle sont hors V1.

### E26 — .NET (NuGet)

- [ ] Reprendre `parse_packages_config` et ses tests.
- [ ] Ajouter :
  - `*.csproj`, `*.fsproj`, `*.vbproj` : `<PackageReference>`, version en attribut ou en élément ;
  - `Directory.Packages.props` (versions centralisées). E02 en fait un projet à part, dans son dossier : le rattacher aux `.csproj` qui sont en dessous ;
  - `packages.lock.json`.
- [ ] Versions NuGet : 4 segments, pré-versions, plages `[1.0,2.0)`.
- [ ] Registre : « flat container » pour les versions, API « registration » pour la dépréciation.
- [ ] Réécriture des `.csproj`, `.props` et `packages.config` ; lockfile : `dotnet restore --force-evaluate` si `packages.lock.json` existe.

---

## Phase G — Compléments d'analyse

### E27 — Fin de vie des runtimes et frameworks

**But** : le type 3 du brief.

- [ ] Détecter la version de chaque runtime :

  | Runtime | Où la lire |
  |---|---|
  | Python | `requires-python`, `.python-version`, `runtime.txt` |
  | Node | `engines.node`, `.nvmrc`, `.node-version` |
  | Go | directive `go` de `go.mod` |
  | Ruby | `.ruby-version`, `ruby "…"` du `Gemfile` |
  | PHP | `require.php` de `composer.json` |
  | Java | `maven.compiler.release`, `java.version`, toolchain Gradle |
  | .NET | `TargetFramework` |

  Plus les `FROM` des `Dockerfile` (images `python`, `node`, `ruby`, `php`, `golang`, `eclipse-temurin`…).
- [ ] Frameworks : table dépendance → produit endoflife.date (`django`, `rails`, `spring-boot`, `laravel`, `symfony`, `angular`, `vue`, `nuxt`, `electron`…).
- [ ] Client endoflife.date (cache 24 h). Constat `EOL` dans deux cas : fin de vie passée, ou dans moins de 6 mois. Il donne la date et le cycle conseillé.
- [ ] Pas de mise à jour automatique d'un runtime (signalé seulement). Un framework monte comme toute autre dépendance.
- [ ] Versions qui demandent un Node plus récent : `npm outdated` écarte celles dont `engines.node` exclut le Node installé (E07 : jsdom 30 demande `^24.15.0`, il ne la propose pas sous Node 24.12). forceupdate les propose. Une fois connue la version de Node du projet, dire quand la version proposée en demande une plus récente (garder `engines` de chaque version dans `registries/npm.py` et son cache).
- [ ] Interface : les fins de vie apparaissent dans le rapport (écran 4), avec la date et le cycle conseillé.

**Fini quand** : un projet Python 3.8 + Django 3.2 + Node 16 sort trois constats
datés et justes, dans l'interface.

### E28 — Fichier de code isolé

**But** : choisir un fichier de code donne un résultat utile.

- [ ] Fichier dans un projet : remonter les dossiers jusqu'au premier manifeste (arrêt à la racine git ou du disque). Analyser ce projet, en disant « analysé via `<manifeste>` ».
- [ ] Fichier seul :
  - Python : bloc PEP 723 (`# /// script`), qui est un vrai manifeste, avec contraintes, et réécrivable. Sinon les imports (module `ast`), sans la bibliothèque standard (`sys.stdlib_module_names`), avec une table import → paquet (`yaml` → `PyYAML`, `cv2` → `opencv-python`, `PIL` → `Pillow`, `sklearn` → `scikit-learn`, `bs4` → `beautifulsoup4`…) ;
  - JS / TS : `import` et `require` de paquets (scopés compris), sans `node:` ni modules intégrés ;
  - Go : imports, rattachés à leur module.
- [ ] Sans version, le constat est « version non fixée, dernière = X ». Les failles ne sont pas vérifiables sans version, et le rapport le dit.
- [ ] Mise à jour d'un fichier seul : seulement le bloc PEP 723.
- [ ] Marche aussi par glisser-déposer dans l'interface.

**Fini quand** : les trois cas (fichier dans un projet, script PEP 723, script avec
seulement des imports) donnent un rapport juste.

---

## Phase H — Livraison

### E29 — Configuration, page Réglages, robustesse

- [ ] Fichier de configuration par projet : `forceupdate.toml` à la racine, ou `[tool.forceupdate]` dans `pyproject.toml`. Il permet :
  - d'ignorer des paquets ou des versions (`ignore = ["lodash@<5"]`) ;
  - de fixer la sélection par défaut par écosystème ;
  - d'exclure des dossiers ;
  - d'analyser aussi les projets rangés dans des dossiers de tests ou d'exemples, écartés par défaut depuis E02 (`engine.scan(include_tests=True)`).
- [ ] Réglages de l'utilisateur (`platformdirs`) : sélection par défaut, dépôts exclus, cache (le vider : `Cache.clear`, E06). Écran 9 (Réglages) pour les modifier.
- [ ] `requirements.txt` générés sans `.in` à côté (`uv export`, `poetry export`, `pdm export`, `pip-compile pyproject.toml`) : depuis E03, ils restent des manifestes et tous leurs paquets sortent comme directes. Les reconnaître (en-tête « autogenerated by pip-compile / uv », commentaires `# via`) et les traiter comme des lockfiles du manifeste du projet.
- [ ] Une ligne de `requirements` à empreintes (`--hash`) : depuis E10, la réécriture la refuse, mais le planificateur ne le sait pas et pré-coche quand même l'option. Le marquer à l'analyse, pour que l'option soit `manual` (jamais pré-cochée, avec la raison).
- [ ] Robustesse :
  - dossiers énormes (plafonds, nombre maximal de fichiers) ;
  - fichiers illisibles, encodages exotiques ;
  - liens symboliques : déjà jamais suivis (E02) ; reste les jonctions Windows, et les sous-modules git non initialisés ;
  - erreurs réseau partielles : section « non concluant » du rapport ;
  - réseau d'entreprise : un proxy (`HTTPS_PROXY`, déjà suivi par httpx) et ses certificats. httpx se fie à `certifi`, pas au magasin du système : `SSL_CERT_FILE`, ou `truststore` (une dépendance de plus, à justifier). À tester derrière un proxy ;
  - fermeture de l'interface ou Ctrl+C pendant une mise à jour : fichiers restaurés. Depuis E11, c'est fait pendant la régénération des lockfiles (`lockfiles.regenerate`) ; depuis E12, le serveur attend la fin de la mise à jour en cours avant de s'arrêter (Ctrl+C atteint aussi l'outil, qui échoue, et le groupe est remis). Reste l'écriture des manifestes, et un navigateur fermé (rien ne se perd : la mise à jour continue) ;
  - Ctrl+Break sous Windows : l'arrêt est propre, mais uvicorn renvoie le signal ensuite et le processus sort avec le code 3, sans « Interface arrêtée. » ;
  - délai d'un outil de lockfile dépassé sous Windows : `subprocess.run` ne tue que `cmd.exe` (`npm.CMD`), pas le node qu'il a lancé. Tuer tout l'arbre (groupe de processus, `taskkill /T`) ;
  - workspace npm : une indirecte d'un membre, retenue par une version forcée de la racine. E11 lance `npm update x --workspaces --include-workspace-root` et la relecture dit si la cible n'est pas atteinte, mais le cas n'a pas pu être reconstitué : le vérifier sur un vrai workspace ;
  - le délai des outils (`LOCK_TIMEOUT`, 600 s) réglable dans la configuration.
- [ ] Performance : mesurer sur un gros dépôt (Argos par exemple). Viser moins de 30 s, cache vide, pour environ 500 dépendances directes. Noter la mesure dans le journal.

**Fini quand** : tests de robustesse verts, mesure notée, réglages modifiables
depuis l'interface.

### E30 — Documentation, packaging, CI

- [ ] `README.md` : à quoi ça sert, installation, démarrage (`ui`), captures d'écran, la ligne de commande, les limites par écosystème.
- [ ] Docs :
  - `docs/USAGE.md` : l'interface écran par écran, et toutes les commandes et options. Dire que sous PowerShell 5.1, `>` recode la sortie d'un programme (en UTF-16, via le codage de la console) : y préférer `--output` (E07) ;
  - `docs/JSON_FORMAT.md` : à jour ;
  - `docs/FORGES.md` : connexion à GitHub, GitLab et Bitbucket, droits nécessaires, ce que contient une PR, comment enregistrer l'outil auprès de chaque forge ;
  - `CHANGELOG.md`.
- [ ] Packaging :
  - le front est construit avant `uv build`, et le paquet le contient ;
  - `uv tool install .` testé sous Windows (Linux via la CI), sur une machine sans node ;
  - version `1.0.0` ;
  - licence MIT : le fichier `LICENSE` est bien inclus dans le paquet.
- [ ] CI GitHub Actions :
  - ruff + pytest, sur Ubuntu, Windows et macOS, avec Python 3.11 et 3.14 ;
  - lint, tests et build du front ;
  - un job hebdomadaire avec les tests `network`.
- [ ] Publication sur PyPI (décision n°19 du brief) :
  - un workflow GitHub Actions publie le paquet quand on pousse un tag `v*` (Trusted Publishing, sans mot de passe stocké) : fait à E09 (`.github/workflows/publish.yml`), y ajouter la construction du front avant `uv build` ;
  - publier la `1.0.0`, avec l'accord de l'utilisateur ;
  - vérifier `uv tool install forceupdate` depuis PyPI, sur une machine sans node.

**Fini quand** : `uv tool install forceupdate` depuis PyPI, dans un dossier vierge,
marche ; la CI est verte.

### E31 — Recette finale

- [ ] Dérouler « Le livrable », case par case, dans l'interface :
  - un vrai projet local par écosystème disponible ;
  - un fichier de code isolé, et un fichier glissé-déposé ;
  - les comptes GitHub, GitLab et Bitbucket de l'utilisateur : analyse de tous les dépôts, puis une PR / MR sur un dépôt de test de chaque forge.
- [ ] Revue finale avec le skill `ui-ux-pro-max` : accessibilité, clair et sombre, petites et grandes fenêtres.
- [ ] Corriger les écarts. Un écart trop gros pour cette session devient une nouvelle étape (E32…) dans ce plan.
- [ ] Cocher « Le livrable ». Taguer `v1.0.0`, avec l'accord de l'utilisateur.

**Fini quand** : toutes les cases de « Le livrable » sont cochées.

---

## Modèle de prompt de session

Chaque session écrit le prompt de la suivante dans
[PROCHAINE_SESSION.md](PROCHAINE_SESSION.md), sur ce modèle :

```markdown
# Session <n> — Étape <EXX> : <titre>

Contexte : <où en est le projet, en 2-3 lignes ; ce que la session d'avant a fait ou laissé>.

Lis CLAUDE.md, puis l'étape <EXX> de PLAN.md, et ce qu'elle cite (docs/BRIEF.md, reference/, Argos, design-system/).
<Si l'étape touche à l'interface : charge d'abord le skill ui-ux-pro-max.>

À faire :
- <les cases de l'étape, moins celles déjà cochées>

Attention :
- <pièges rencontrés, décisions prises en route, choses à demander à l'utilisateur>

Fini quand : <critère de l'étape>. Vérifier avec : <commandes>.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
```

## Journal des sessions

| Session | Date | Étape | Résultat |
|---|---|---|---|
| 0 | 2026-10-27 | — | Brief adapté à la nouvelle idée, puis aux retours de l'utilisateur : interface web locale en V1, majeures jamais cochées d'office, PR toujours, GitHub + GitLab + Bitbucket (chacun connecte son compte, l'utilisateur enregistre l'outil auprès des forges), nom `forceupdate`, publication gratuite sur PyPI, licence MIT. Plan écrit (31 étapes), règles de suivi et d'interface ajoutées à CLAUDE.md. Plus aucune question ouverte |
| 1 | 2026-10-27 | E01 | Fait. `git init` (aucun commit), `LICENSE` MIT (Pauzzle), `pyproject.toml` prêt pour PyPI, `uv.lock`, CLI (`--version` ; `ui`, `scan`, `update` « pas encore disponible »), `models.py`, conftest avec le marqueur `network`, CI, section « Commandes » dans CLAUDE.md. 25 tests verts sous 3.11, 3.12 et 3.14, ruff propre, tests de `reference/` inchangés. Ajouté au plan : sortie UTF-8 (E07), création du dépôt GitHub (E08) |
| 2 | 2026-10-27 | E02 | Fait. `sources/` (`Source`, `LocalSource`), `detect/languages.py` (57 langages, règles de Linguist), `detect/manifests.py` (motifs, projets, lockfiles de workspace), `engine.py`, `scan` affiche langages et projets. Ajouté en route : `.gitignore` respecté via `git ls-files` (Argos a 48 000 fichiers ignorés). Tranché : les manifestes des dossiers de tests ou d'exemples ne font pas de projets, ils sont listés à part. Modèles : `Language`, `Project.ecosystems`, `Report.ignored_manifests`. Vérifié à la main sur Argos et sur trois clones. 202 tests verts sous 3.11, 3.12 et 3.14. Cases ajoutées à E03, E04, E07, E13, E17, E21, E22, E26, E29 |
| 3 | 2026-10-27 | E03 | Fait. `parsers/` : `python.py` (`requirements` avec `-r`/`-c`, `pyproject.toml` PEP 621/735/Poetry/uv/PDM, `Pipfile`, `setup.cfg` ; `uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock`, `.txt` compilé de pip-tools), `toml_spans.py` (positions des chaînes TOML). Directes avec contrainte telle qu'écrite et emplacement exact, version installée, transitives avec leur scope tiré du graphe, workspace uv vérifié. Ajouté : `Notice` / `Project.notices`, `pdm.lock`, plafond de 50 Mo pour les lockfiles. Tranché : le `.txt` compilé à côté d'un `.in` est son lockfile. Six mini-projets aux lockfiles produits par les vrais outils. Argos vérifié à la main (62 directes, 95 transitives, versions relues). 285 tests verts sous 3.11, 3.12 et 3.14. Cases ajoutées à E04, E05, E07, E08, E10, E17, E29 |
| 4 | 2026-10-27 | E04 | Fait. `parsers/npm.py` : `package.json` (contraintes telles qu'écrites, emplacements exacts, alias, non vérifiables), `package-lock.json` v1/v2/v3, `yarn.lock` de Yarn 1 et 2+, `pnpm-lock.yaml` 5.4/6.0/9.0 et celui à deux documents de pnpm 11+. `parsers/json_spans.py`, `parsers/lockfiles.py` (lien manifeste ↔ lockfile sorti de `python.py`, commun). Tranché : graphe de lockfile en nœuds (un paquet npm a plusieurs versions installées). Workspaces npm, Yarn et pnpm vérifiés, membres Yarn 1 reconstruits ; une directe résolue vers un membre est « membre du workspace ». `pyyaml` ajouté. Cinq mini-projets aux lockfiles produits par npm, Yarn 1, Yarn 4, pnpm 9. Argos vérifié à la main (24 directes, 389 transitives, versions relues), ariakit (21 projets pnpm) aussi. 375 tests verts sous 3.11, 3.12 et 3.14. Cases ajoutées à E05, E08, E09, E10, E17 |
| 5 | 2026-10-27 | E05 | Fait. `versions/` : `base.py` (`VersionScheme` : `compare`, `gap`, `satisfies`, `lower_bound`, `candidates`, `latest`, `max_satisfying`, `highest`, `sort_key` ; `for_ecosystem`), `pypi.py` (PEP 440 avec `packaging`, syntaxe Poetry et Pipfile traduite, unions `||`), `npm.py` (semver 2.0 et plages de node-semver écrits à la main, étiquettes). Tranché : `gap` suit `^` en 0.x (`0.2` → `0.3` est majeure, donc pas pré-cochée à E09) ; pré-versions candidates seulement celles de la version actuelle. Ajouté : catalogues pnpm lus dans `pnpm-workspace.yaml` (`Dependency.resolved_constraint`), tri des transitives par version, mini-projet `pnpm-catalog` (pnpm 12). Vérifié sur les mini-projets, Argos, ariakit, juju, les 580 plages du `package-lock.json` d'Argos et un `poetry.lock` de 240 paquets. 914 tests verts sous 3.11, 3.12 et 3.14. Cases ajoutées à E06, E07, E09, E10, phase F |
| 6 | 2026-10-27 | E06 | Fait. `net/http.py` (`HttpClient` : User-Agent, délais, reprises sur 429, 5xx et coupures avec `Retry-After`, 8 requêtes par hôte, hôte injoignable abandonné pour la session, réponses plafonnées), `net/cache.py` (SQLite dans le cache de l'utilisateur, 1 h pour les versions, sans cache, hors ligne avec les entrées périmées), `registries/` (`PackageInfo`, PyPI, npm, une requête par paquet et par session). Tranché : PyPI par l'API Simple en JSON (PEP 691/700/792 : `releases` de l'API JSON est déprécié) ; npm par le document complet (l'abrégé perd les dates sans alléger `next`) ; la dernière stable npm est `dist-tags.latest`. Ajouté : statut des projets PyPI (archivé, quarantaine), paquets « security holding » de npm. `platformdirs` ajouté, `tests/fixtures/record.py`. Vérifié sur les 86 directes d'Argos, et contre l'API JSON de PyPI (69 sur 69). 1015 tests verts (plus 2 réseau) sous 3.11, 3.12 et 3.14. Cases ajoutées à E07, E08, E12, E29 |
| 7 | 2026-10-27 | E07 | Fait. `checks/` (version actuelle, « plus récente », retirée et dépréciée, priorité, `--fail-on`), `engine` (`inventory`, `check`, `analyze` en coroutine, `scan` par `asyncio.run` ; événements de progression), `report/` (terminal `rich`, JSON `schema_version: 1` décrit dans `docs/JSON_FORMAT.md`, Markdown), options de `scan`, sortie redirigée en UTF-8. Tranché : version permise npm comme `npm-pick-manifest`, gravités des constats autres que les failles, une version actuelle inconnue donne « non concluant » et jamais un faux constat. Ajouté : `Constraint.exact()`, garde-fous des tests (ni réseau ni cache de l'utilisateur), `python -m forceupdate`. Vérifié contre l'API JSON de PyPI, les `dist-tags` npm, `uv pip list --outdated` (25 sur 25) et `npm outdated --all` (écarts expliqués par `engines`, deux bugs trouvés et corrigés : `latest` dépréciée, versions en pré-versions). 1142 tests verts (plus 3 réseau) sous 3.11, 3.12 et 3.14. Cases ajoutées à E08, E09, E12, E27, E30 |
| 8 | 2026-10-28 | E08 | Fait. Premier commit (E01 à E07). `advisories/` (client OSV : `querybatch`, puis chaque avis une fois par session, en cache 7 jours ; CVSS 3 calculé), `checks/vulns.py` branché sur `engine.check` : toutes les dépendances, indirectes comprises, quelle que soit `--transitive`. Les trois dépendances à Argos coupées, ses 5 tests OSV repris (une erreur n'est jamais « pas de faille »). Tranché : un constat par faille (GHSA et PYSEC réunis), version corrigée lue dans les plages, paquet malveillant toujours critique, « faille possible » sur une borne basse, OSV en panne → « non concluant » ou une remarque par lockfile ; les autres versions d'une directe dans `uv.lock` deviennent des indirectes. Trouvé : OSV arrondit `modified` à la microseconde dans `querybatch`. Mini-projet `vulnerable` (lodash 4.17.15, flask 0.12) : 28 failles, les mêmes que `npm audit` et `pip-audit`. Argos : 569 versions, aucune faille, comme `npm audit` et `pip-audit`. 1240 tests verts (plus 4 réseau) sous 3.11, 3.12 et 3.14. Dépôt GitHub public créé, `main` poussé ; CI verte (Ubuntu, Windows ; 3.11, 3.14) après avoir fixé `setup-uv` en `v10.3.2` (pas d'étiquette `v10`). PyPI : l'utilisateur préfère attendre, le nom est toujours libre. Cases ajoutées à E09 et à la phase F |
| 9 | 2026-10-28 | E09 | Fait. `update/` : `constraints.py` (réécrire une contrainte dans son style : opérateurs, précision, bornes hautes, unions, plancher pour une faille), `planner.py` (pour chaque paquet, ses options — dernier correctif, dernière mineure, dernière majeure, correction des failles, remplacement —, ce qu'elles corrigent et touchent, la pré-cochée ; `Rules`, `select`, `chosen`). Plan calculé dans `engine.check` et rangé dans `Project.updates` (JSON de `scan`). Tranché : une `Update` par paquet aux options exclusives ; correction des failles d'après les avis, non dépréciée (lodash → 4.18.1) ; pré-cochée = non majeure qui corrige le plus, puis la plus récente ; dépendance pair élargie. Ajouté : `Dependency.lockfile`, versions forcées lues (`overrides`, `resolutions`, `pnpm.overrides`), `forceupdate update` qui montre le plan (`--level`, `--security-only`, `--include`, `--exclude`, `--ecosystem`), `record.py registre:paquet`, workflow `publish.yml`. Vérifié sur `vulnerable`, Argos et 4 mini-projets. 1430 tests verts (plus 4 réseau) sous 3.11, 3.12 et 3.14. PyPI : **0.1.0 publiée** par Trusted Publisher (`publish.yml`, étiquette `v0.1.0`), installation vérifiée. Cases ajoutées à E10, E11, E12, E15, E30, phase F |
| 10 | 2026-10-28 | E10 | Fait. `update/writers/` : `prepare` (chaque `Edit` situé et vérifié, une option appliquée en entier ou pas, conflits entre options, réécritures de la fin vers le début, auto-vérification par le parseur de l'analyse, diff unifié) et `write` (rien si un fichier a changé depuis le diff, fichier temporaire puis `os.replace`, remise en état si une écriture échoue) ; CRLF et BOM gardés. `parsers/yaml_spans.py` et `parse_pnpm_workspace` : catalogues et `overrides` de `pnpm-workspace.yaml` avec leur position (pnpm 11+ ne lit plus le champ `pnpm` du `package.json`, vérifié avec pnpm 12.15). `update/git.py` : garde-fou (`--force`). `forceupdate update` : diff, confirmation `[o/N]`, `--yes`, `--dry-run`. Versions proposées soumises à OSV en une requête (`planner.audit`, `UpdateOption.introduced`), jamais pré-cochées si elles apportent une faille. Trouvé et traité : une ligne `requirements` à `--hash` n'est pas réécrite ; l'emplacement vide est collé au nom. Vérifié à la main sur `vulnerable`, les 12 autres mini-projets et un clone d'Argos (garde-fou compris) : seules les contraintes changent. 1541 tests verts (plus 4 réseau) sous 3.11, 3.12 et 3.14. Cases ajoutées à E11, E12, E15, E29 |
| 11 | 2026-10-28 | E11 | Fait. Commit de E10 d'abord (accord de l'utilisateur). `update/lockfiles.py` : `plan` (un `Job` par lockfile : outil, commande à lancer à la main, avertissements) et `regenerate` (lancé après `writers.write`, sans shell, délai de 600 s, sans scripts du projet), un pilote par outil — npm, pnpm, Yarn 1 et 2+, uv, Poetry 1 et 2, PDM (ajouté), pipenv, pip-tools et `uv pip compile` d'après l'en-tête —, chacun vérifié sur sa version actuelle (par `npx`, `corepack`, `uvx` pour ceux qui ne sont pas installés). Tranché : la version choisie est visée par `-P x==V` (uv, pip-compile) ou épinglée le temps d'un passage (npm, pnpm, Poetry, PDM) ; Yarn et pipenv prennent la plus haute permise ; `uv --no-build` écarté (il change la résolution, Argos échouait). Relu ensuite : version obtenue, ce qui retient une indirecte, ce qui a changé d'autre. Échec ou Ctrl-C : le groupe de fichiers remis comme avant, manifestes compris. Fichier de contraintes de pip réécrit par `writers`. `.txt` de pip-tools qui en cite un autre recompilé après lui. Garde-fou des tests : aucun vrai outil hors `network` (`FakeTools`). Vérifié à la main sur `vulnerable`, `npm`, `uv`, `pnpm-catalog`, `pip` et un clone d'Argos (10 mises à jour exactes) ; lockfiles stables quand on relance l'outil. 1590 tests verts (plus 8 réseau) sous 3.11, 3.12 et 3.14. Cases ajoutées à E12, E15, E18, E29, phase F |
| 12 | 2026-10-28 | E12 | Fait. `web/` : FastAPI servi par uvicorn sur `127.0.0.1` (port libre), `forceupdate ui` (`--port`, `--no-browser`, Ctrl+C). Sécurité : jeton de session aléatoire (l'adresse affichée pose un cookie `HttpOnly`, `SameSite=Strict`, au nom portant le port, puis renvoie sans le jeton ; ou `Authorization: Bearer`), `Host`, `Origin` et `Sec-Fetch-Site` vérifiés, pas de CORS, en-têtes (`no-store`, `no-referrer`, CSP). Routes : dossiers (noms seulement, sans liens ni jonctions), analyses en tâche de fond avec progression SSE et annulation, plans (diffs, lockfiles, garde-fou git) appliqués par leur identifiant avec la progression par outil, fichier envoyé (analysé, téléchargé réécrit, jamais appliqué). Tranché : analyses dans une boucle à elles (client et cache partagés), mises à jour dans un thread à part une à la fois, état tenu dans la boucle du serveur ; l'API désigne les mises à jour par identifiant et version au lieu de les recopier. Ajouté : `update/local.py` (l'enchaînement de `cli.update`, partagé), progression de `lockfiles.regenerate`, abandon d'un hôte limité à 60 s, `report.json.Document`, schéma OpenAPI exporté (`web/openapi.json`, champs des réponses requis, vérifié contre les vraies réponses), `httpx2` en dev pour le client de test de Starlette. Trouvé : `SameSite` ne protège pas d'un autre port de 127.0.0.1 ; sous Windows, la boucle des analyses volait le réveil sur Ctrl+C à celle du serveur. Vérifié à la main avec curl (jeton, puis sans) : `vulnerable` analysé et planifié, application sur une copie avec les vrais npm et uv (versions exactes), annulation, fichier envoyé ; arrêt en 0,2 s. 1706 tests verts (plus 8 réseau) sous 3.11, 3.12 et 3.14. Pas de commit (E11 non plus) : à proposer. Cases ajoutées à E13, E14, E15, E17, E29 |
