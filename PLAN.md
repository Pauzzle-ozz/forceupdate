# Plan — forceupdate

Ce plan couvre **100 % du livrable** : quand toutes les étapes sont faites et
toutes les cases de « Le livrable » cochées, l'outil est livrable.

Une session = une étape. Les règles de suivi (mise à jour de ce fichier, prompt
de la session suivante) sont dans [CLAUDE.md](CLAUDE.md), section « Travail par
sessions ». L'idée et les décisions sont dans [docs/BRIEF.md](docs/BRIEF.md).

## Le livrable

Ce qui doit être vrai à la fin. Coché seulement à l'étape E36 (recette), après
vérification à la main.

- [x] `uv tool install forceupdate` installe l'outil depuis PyPI, interface comprise (pas besoin de node pour l'utiliser), sous Windows et sous Linux.
- [x] `forceupdate ui` ouvre l'interface web dans le navigateur. Dans l'interface, on peut :
  - choisir un dossier ou un fichier de l'ordinateur, ou glisser-déposer un fichier ;
  - voir les langages, les projets, les dépendances directes avec leur version installée, et les constats des 4 types (version plus récente, faille, fin de vie, déprécié ou retiré), du plus grave au moins grave ;
  - cocher les mises à jour (les sûres sont pré-cochées), voir le diff et appliquer : manifestes réécrits sans casser leur mise en forme, lockfiles régénérés quand l'outil natif est installé, commande à lancer indiquée sinon ;
  - connecter son compte GitHub, GitLab ou Bitbucket en quelques clics, et le déconnecter ;
  - voir tous ses dépôts, les analyser sans les cloner : un rapport par dépôt, plus une synthèse ;
  - ouvrir une PR (une MR sur GitLab) par dépôt à mettre à jour. Relancé, l'outil met à jour la même PR ; il ne pousse jamais sur la branche par défaut.
- [x] L'interface suit `design-system/MASTER.md`. Elle est accessible (contraste, clavier), en clair et en sombre, en français.
- [x] En ligne de commande, `forceupdate scan` (terminal, JSON, Markdown, `--fail-on`) et `forceupdate update` marchent sur un chemin local, pour les scripts et la CI.
- [x] Les 8 écosystèmes (Python, JS/npm, Rust, Go, PHP, Ruby, Java, .NET) sont couverts en analyse et en mise à jour. Les limites restantes sont écrites dans la doc.
- [x] Sans réseau, les tests passent. Une erreur réseau donne « non concluant », jamais un faux constat.
- [x] La doc utilisateur est complète, la CI est verte, la version 1.0.0 est taguée.

## Architecture cible

```
src/forceupdate/
├── cli.py            commandes : ui, scan, update
├── engine.py         le moteur : enchaîne source → projets → dépendances → constats → rapport
├── models.py         Dependency, Finding, Project, Report, Language, Severity, FindingKind…
├── sources/          d'où vient le code : base.py (interface Source), local.py, forge.py
├── detect/           languages.py (langages), manifests.py (découverte, regroupement en projets)
├── parsers/          un module par écosystème : python, npm, rust, go, php, ruby, java, nuget
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
  - React + TypeScript + Vite + Tailwind 4 + shadcn/ui, icônes Lucide : confirmé à E13. Polices IBM Plex Sans et JetBrains Mono, embarquées (fontsource) ;
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
| E13 | D | Conception de l'interface (skill ui-ux-pro-max) | fait |
| E14 | D | Front : socle et analyse locale | fait |
| E15 | D | Front : mise à jour locale | fait |
| E16 | E. Forges | Interface `Forge` commune, connexion GitHub | fait |
| E17 | E | GitHub : dépôts et analyse sans cloner | fait |
| E18 | E | GitHub : une PR par dépôt | fait |
| E19 | E | GitLab | fait |
| E20 | E | Bitbucket Cloud | fait |
| E21 | F. Autres écosystèmes | Rust (crates.io) | fait |
| E22 | F | Go | fait |
| E23 | F | PHP (Composer) | fait |
| E24 | F | Ruby (Bundler) | fait |
| E25 | F | Java (Maven, Gradle) | fait |
| E26 | F | .NET (NuGet) | fait |
| E27 | G. Compléments | Fin de vie des runtimes et frameworks | fait |
| E28 | G | Fichier de code isolé | fait |
| E29 | H. Livraison | Configuration et page Réglages | fait |
| E30 | H | Robustesse et performance | fait |
| E31 | H | Forges : robustesse | fait |
| E32 | H | Mise à jour : le npm du projet, Python, NuGet, Go | fait |
| E33 | H | Registres et dépôts privés | fait |
| E34 | H | Compléments d'analyse | fait |
| E35 | H | Documentation, packaging, CI | fait |
| E36 | H | Recette finale | fait |
| E37 | I. Après la 1.0.0 | Indirectes retenues et majeures refusées, plus loin (1.1.0) | à faire |

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

- [x] Charger le skill `ui-ux-pro-max` et suivre son déroulé :
  - analyser le besoin (produit : outil de développeur, tableau de bord, sobre et lisible) ;
  - générer le design system avec `--design-system --persist -p "forceupdate"` → `design-system/MASTER.md`, versionné ;
  - le nom invite à un clin d'œil à Star Wars : à doser (un détail, un message de chargement), sans nuire à la lisibilité ni reprendre de logo ou d'image protégés ;
  - une page `design-system/pages/<écran>.md` pour chaque écran qui s'écarte du master.

  Sous Windows, lancer les scripts du skill avec `python`, pas `python3`.
- [x] Les écrans :

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
- [x] Pour chaque écran, les états : vide, chargement, erreur, hors ligne, « non concluant ». Clair et sombre. Accessibilité : les règles de priorité 1 du skill.
- [x] Maquettes HTML statiques des écrans 1, 4, 5 et 7, dans `design-system/mockups/`, ouvrables dans le navigateur. Les montrer à l'utilisateur.
- [x] Confirmer la pile du front (proposition : React + TypeScript + Vite + Tailwind + shadcn/ui) et les icônes (SVG, pas d'emoji).
- [x] Depuis E12, ce que l'API permet, à refléter dans les écrans : la progression par étape (`reading`, `projects_found`, `checking`, `package_checked` avec le paquet, `vulnerabilities_checked`) et par lockfile pendant une mise à jour (`written`, `regenerating`) ; l'annulation d'une analyse (pas d'une mise à jour, qui ne s'annule pas) ; « Analyses récentes » de l'écran 1 : l'API garde les chemins récents d'une session à l'autre (`recent`) et les analyses de la session seulement (`GET /api/scans`), pas les rapports ; le garde-fou git (`uncommitted`, puis « appliquer quand même » : `force`) ; un fichier envoyé se télécharge réécrit, il ne s'applique pas. Voir `docs/JSON_FORMAT.md`, « L'API de l'interface web ».

- [x] Ajoutés en route : `design-system/ECRANS.md` (les 9 écrans, leurs états, leurs adresses, ce que l'API n'a pas encore), un aperçu du design system dans `mockups/index.html`, des cases ajoutées à E14 à E18 (voir les notes).

**Fini quand** : l'utilisateur a validé le design system et les maquettes.

**Notes** (session 13) :

- **Commit d'abord** : E11 et E12 commités ensemble (`f23eab6`), avec l'accord de l'utilisateur.
- **Ce qui est produit** (tout dans `design-system/`, rien dans `src/`) :
  - `MASTER.md` : provenance (la commande du skill, ce qui a été changé et pourquoi), principes, tokens clair et sombre, typographie, mouvement, mise en page, icônes, composants, textes, le clin d'œil, accessibilité, correspondance avec shadcn/ui et Tailwind 4, anti-motifs, checklist ;
  - `ECRANS.md` : les 9 écrans (contenu, action principale, appels à l'API, états vide / chargement / erreur / hors ligne / non concluant), les états de la coquille (serveur arrêté, session terminée, hors ligne, page introuvable), les adresses du front, ce que l'API n'a pas encore ;
  - `pages/` : `analyse-en-cours.md`, `rapport.md`, `mise-a-jour.md`, `depots.md` (les écrans qui s'écartent du master) ;
  - `mockups/` : `index.html` (les 9 écrans, aperçu des couleurs et composants), `accueil.html`, `rapport.html`, `mise-a-jour.html`, `depots.html`, et `assets/` (feuille de style aux tokens, petit script pour l'état et le thème, 76 icônes Lucide en sprite, 2 polices, licences). Chaque maquette a une barre « MAQUETTE » pour choisir l'état et le thème (aussi par l'adresse : `?state=…&theme=dark`).
- **Données réelles** : `vulnerable` analysé par l'API (`forceupdate ui` et curl, sur une copie dans le scratchpad) : 28 failles (13 élevées, 14 moyennes, 1 faible), 2 plus récentes, 4 mises à jour (lodash 4.18.1, flask 0.12.5 et jinja2 2.11.3 pré-cochées ; flask 3.1.3 et werkzeug 3.1.9 majeures), le plan (deux diffs, `npm` et `uv pip compile` trouvés, deux avertissements d'uv, `uncommitted: []`), puis appliqué sur la copie : versions exactes. L'écran 7 est fictif (forges à venir), et le dit.
- **Tranché avec le skill** (détail dans MASTER, « Provenance ») : style « Data-Dense Dashboard », clair et sombre. Rejeté de la proposition : l'accent vert (blanc dessus : 2,3:1 ; et le vert veut dire « à jour »), le sombre seul, Google Fonts (interdit par la CSP, et hors ligne), le motif de page « landing ». **Accent bleu**, couleurs de sens réservées (gravités, succès, avertissement, erreur, violet pour « non concluant », toujours avec icône et mot). **IBM Plex Sans + JetBrains Mono** (paire « Developer Mono » du skill), polices variables de fontsource (OFL), embarquées. Contrastes de toutes les paires calculés : texte ≥ 4,5:1, composants ≥ 3:1, dans les deux thèmes.
- **Trouvé** : les ligatures de JetBrains Mono changent `--package-lock-only` en tiret long et `==` en signe double : coupées partout où il y a du code (une commande lue doit être celle à taper). Lucide 1.x n'a plus de logos de marque (GitHub, GitLab) : choix reporté à E16. Le sous-ensemble latin des polices n'a pas `→` : icône `arrow-right` dans les tableaux.
- **Pile confirmée par l'utilisateur** : React + TypeScript + Vite + Tailwind 4 + shadcn/ui, icônes Lucide (décision n°17 du brief).
- **Le clin d'œil (validé)** : la « lame » (un trait bleu devant `forceupdate`, et la barre de progression, qui luisent en sombre), la devise du brief en pied de page, un message pendant la recherche des failles (« Recherche d'une perturbation dans la Force… », sous la ligne fonctionnelle, hors de la zone annoncée), la page introuvable (« Ce n'est pas la page que vous cherchez. »). Jamais dans une erreur ou un résultat ; aucun logo ni image repris.
- **Ce que l'API permet, reflété** : progression par étape (`reading`… `vulnerabilities_checked`, paquet en cours) et par lockfile (`written`, `regenerating`) ; annuler une analyse, pas une mise à jour (l'écran 5 le dit, sans bouton) ; « Cette session » (`GET /api/scans`) et « Chemins récents » (`recent`) séparés, avec la phrase « les rapports ne vivent que le temps de la session » ; garde-fou git (vert, `null` : hors de git, liste : « Appliquer quand même… » et confirmation, `force`) ; fichier envoyé : deux étapes, « Télécharger », pas de lockfile.
- **Ce que l'API n'a pas** (ajouté au plan, l'API n'a pas bougé) : les chiffres d'une analyse dans `GET /api/scans` et la nature d'un chemin récent (E14) ; comptes, dépôts, synthèse multi-dépôts calculée par le serveur, récapitulatif des PR (E16 à E18). La progression « par projet » de l'écran 3 n'existe pas dans l'API et n'est pas nécessaire : nombre de projets, puis progression par paquet.
- **Vérifié** : chaque maquette en clair et en sombre, à 1440 et à 375 px, chaque état de l'écran 5 et les principaux des autres (captures d'Edge sans fenêtre ; **sous Windows, sa fenêtre ne descend pas sous 492 px** : les captures à 375 px passent par un cadre `iframe` de 375 px). Un contrôle d'accessibilité statique des 5 pages (boutons et liens nommés, champs étiquetés, icônes cachées ou nommées, titres sans saut, un seul `h1`, `lang`, lien d'évitement, références `aria-*` existantes) : aucun problème. `uv run pytest` (1706 verts) et `uv run ruff check` inchangés.
- **Le skill sous Windows** : ses dossiers `scripts/` et `data/` sont des liens git non résolus (des fichiers texte) ; le script est dans `~/.claude/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py`. `--persist` écrit dans `design-system/<projet>/MASTER.md` (`-o` pour le dossier de sortie) : le fichier a été repris, adapté et rangé à `design-system/MASTER.md`. Le générateur de pages (`--page`) produit un gabarit de page commerciale : les pages ont été écrites à la main.

### E14 — Front : socle et analyse locale

**But** : dans le navigateur, on choisit un dossier et on lit le rapport.

- [x] `frontend/` avec la pile choisie en E13 :
  - types générés depuis `web/openapi.json` ;
  - thème tiré de `design-system/MASTER.md` (couleurs, typographie, espacements sous forme de tokens).
- [x] Build : `npm run build` écrit dans `src/forceupdate/web/static/`, qui est inclus dans le paquet Python. En dev : serveur Vite avec un proxy vers l'API.
- [x] Depuis E12 :
  - types générés depuis `src/forceupdate/web/openapi.json` (`operationId` : `start_scan`, `plan_update`…) ; tous les champs des réponses y sont requis ;
  - le serveur sert déjà `web/static/` (une adresse inconnue rend `index.html`) avec une CSP `default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'` (`web.security.SECURITY_HEADERS`) : vérifier que le front construit marche avec elle (styles en ligne de bibliothèques ?) et ne l'assouplir qu'au strict nécessaire ;
  - **en dev, le proxy de Vite** : le garde refuse une `Origin` ou un `Host` qui ne sont pas ceux du serveur (`http://localhost:5173` le serait). Le proxy doit réécrire `Host` (`changeOrigin`) et `Origin` vers l'adresse du serveur, et porter le jeton (`Authorization: Bearer`, lu dans une variable d'environnement de dev) ; ne jamais affaiblir le garde pour le dev ;
  - SSE : fermer l'`EventSource` à l'événement `end` (sinon il se rebranche) ; les cookies passent tout seuls (même origine).
- [x] Écrans 1 à 4 (accueil, choisir un dossier ou un fichier, analyse en cours, rapport).
- [x] Depuis E13 :
  - pile : React + TypeScript + Vite + Tailwind 4 + shadcn/ui + `lucide-react` ; polices `@fontsource-variable/ibm-plex-sans` et `@fontsource-variable/jetbrains-mono`, embarquées, **ligatures coupées** dans tout ce qui est code ;
  - tokens : ceux de `design-system/mockups/assets/mockups.css` (la référence exacte), dans `frontend/src/styles/tokens.css`, sous `:root` et `.dark` ; correspondance avec les variables de shadcn/ui : MASTER, « Pour E14 » ; thème clair, sombre ou système, gardé dans le `localStorage` ;
  - écrans 1 à 4 selon `design-system/ECRANS.md`, `pages/analyse-en-cours.md`, `pages/rapport.md` et les maquettes `accueil.html`, `rapport.html` (tous leurs états) ; la coquille et ses états communs (serveur arrêté : `fetch` qui échoue ; session terminée : `401` ; hors ligne : `navigator.onLine` ; page introuvable) ; les adresses de ECRANS.md (« Adresses ») ;
  - **API à compléter d'abord** (petit) : `summary` du rapport (ou `null`) dans `ScanSummary` (`GET /api/scans`), pour les chiffres des « Analyses récentes » ; `recent` en `{path, kind}` (dossier ou fichier). Refaire `web/openapi.json`, `docs/JSON_FORMAT.md` et les tests ;
  - le tableau des dépendances sous 768 px : une vraie liste de cartes (un tableau restylé en blocs perd sa sémantique) ; virtualisé au-delà de 50 lignes ;
  - annonces : l'étape en cours en `aria-live`, le nom du paquet au plus toutes les 5 s.
- [x] Tests : Vitest + Testing Library pour les composants ; un test Playwright de bout en bout (choisir un mini-projet, voir le bon rapport).
- [x] Revue avec la checklist du skill : accessibilité, états, clair et sombre.
- [x] Ajoutés en route : la répartition par gravité dans le résumé (`summary.severities`, `summary.vulnerabilities`), le serveur de test hors ligne (`tests/e2e_server.py`), le contrôle axe-core, le job « Front » de la CI, le front construit dans la publication (voir les notes).

**Fini quand** : depuis `ui`, on analyse un vrai dossier ; le rapport est juste et
conforme aux maquettes.

**Notes** (session 14) :

- **API d'abord** : `ScanSummary.summary` (le `summary` du rapport, `null` avant la fin ou sans rapport) ; `Listing.recent` en `RecentPath` (`{path, kind}`, `kind` : `folder` ou `file`, un lecteur est un dossier). **Ajouté** : `Summary.severities` (les constats de `to_update` par gravité) et `Summary.vulnerabilities` (les failles par gravité), toutes les gravités présentes : la maquette montre « 13 élevées · 14 moyennes · 1 faible » et la barre des gravités, et le front ne doit pas recompter (un paquet déclaré deux fois compte pour un, règle de `distinct_findings`). Champs ajoutés, `schema_version` inchangé. `report.json.summary_document` sert au rapport et à la liste des analyses. `web/openapi.json` et `docs/JSON_FORMAT.md` refaits, tests ajoutés.
- **Pile** (node 24.12, npm 11.6) : Vite 8.3, React 19.3, Tailwind 4.3, shadcn/ui 4 (base Radix, composants réécrits aux mesures des maquettes), lucide-react 1.63, react-router 8.5, TanStack Query 5 et Virtual 3, polices fontsource (sous-ensemble latin seulement), oxlint (règles React et `jsx-a11y`, sans avertissement), Vitest 5 + Testing Library + jsdom, Playwright 1.64 + axe-core. Le tout figé dans `frontend/package-lock.json`. **TypeScript 5.9, pas 7** : le gabarit de Vite propose la 7 (le compilateur natif), qui n'a pas d'API JavaScript, et openapi-typescript en a besoin. **TanStack Table écarté** (passé en v9, nouvelle API) : deux tris et cinq filtres s'écrivent en quelques lignes (`lib/report.ts`), et servent aussi la liste de cartes.
- **Organisation** (`frontend/src/`) : `api/` (`schema.d.ts` généré par `npm run gen:api`, un test vérifie qu'il suit `openapi.json` ; `types.ts`, alias tirés du schéma et des `operationId` ; `client.ts`, `fetch` et l'état de la liaison : serveur arrêté, session terminée), `lib/format.ts` (règles françaises : `fr()` pose les espaces insécables, dates, durées, accords), `lib/report.ts` (les déductions d'affichage permises : rattacher constats et mises à jour à leur ligne, gravité la plus haute, « non vérifiée », filtres et tris ; l'ordre des constats, la pré-sélection et les chiffres viennent de l'API), `hooks/` (thème, réseau, SSE, actions), `shell/` (coquille, bandeaux, page introuvable, écrans à venir), `screens/` (Home, Choose, ScanPage, ScanProgress, `report/`).
- **CSP vérifiée** avec le front construit, sans l'assouplir : rien en ligne dans `index.html` (le thème est posé par `public/theme.js`, un fichier), pas d'URL `data:` (`assetsInlineLimit: 0`), polices servies par le serveur. **Trouvé** : Radix Dialog (react-remove-scroll) et Sonner injectent un `<style>`, refusé : le panneau de détail est un `<dialog>` natif (`ui/sheet.tsx` : focus au titre, Échap, focus rendu, voile en `::backdrop`, page figée par `html:has(dialog[open])`). Les tests de bout en bout échouent sur toute erreur de console : aucune.
- **Build et livraison** : `npm run build` écrit dans `src/forceupdate/web/static/`, **ignoré par git** (fichiers aux noms hachés) et embarqué par hatchling (`artifacts`, wheel et sdist : vérifié). `publish.yml` construit et teste le front avant `uv build`, et vérifie que le wheel porte `index.html`. La version du pied de page vient de `pyproject.toml` à la construction. Sans front construit, `ui` sert toujours sa ligne de texte.
- **Dev** : `FORCEUPDATE_URL=<adresse de « forceupdate ui »> npm run dev` ; le proxy de Vite réécrit `Host` et `Origin` vers le serveur et porte le jeton en `Authorization: Bearer` (le garde n'a pas bougé).
- **Écrans** : 1 (accueil : sources, chemin, options repliées, analyses de la session avec leurs chiffres et leur lame, chemins récents en pastilles, glisser-déposer sur toute la page), 2 (le serveur liste ; chemin éditable dans l'adresse `?chemin=`, points de départ et récents, cachés repliés, filtre, flèches / Début / Fin / Entrée / Retour arrière, « Analyser ce dossier » ou « ce fichier », envoi d'un fichier), 3 (étapes, lame indéterminée puis déterminée ; **le moteur vérifie les paquets et cherche les failles en même temps**, le total compte une vérification de plus pour OSV : deux lignes en parallèle, « Vérification des paquets et des failles : 41 sur 64 » ; annonces sans les nombres, paquet au plus toutes les 5 s ; le clin d'œil hors de la zone annoncée ; « Annuler »), 4 (en-tête, alertes hors ligne / non concluant / remarques, synthèse aux compteurs filtrants, barre des gravités, langages et projets, tableau ou cartes, panneau de détail à l'adresse `?paquet=PyPI:flask`, fichiers écartés, remarques ; états vide, rien à mettre à jour, échouée, annulée, introuvable). Le glisser-déposer analyse le fichier envoyé (son téléchargement réécrit reste à E15). Dépôts, Comptes, Réglages, PR et l'écran 5 : une page « pas encore disponible » (le bouton « Mettre à jour » du rapport y mène).
- **Trouvé en vérifiant** : des liens habillés en bouton sans bordure (classes contradictoires non fusionnées hors de `<Button>` : `buttonVariants` fusionne maintenant) ; le tableau coupé entre 768 et 1024 px sur un vrai dossier (la colonne « Projet » passe alors sous le nom, les cellules se resserrent, les en-têtes passent à la ligne) ; « régénérer le lockfile suffit » affiché quand la version acceptée est déjà l'installée ; le nom accessible d'un bouton avec un texte `sr-only` (Chrome : « flask , voir le détail ») : `aria-label`.
- **Tests** : 48 tests de composants (`npm test` : logique d'affichage, accueil, choisir, analyse en cours avec un `EventSource` simulé, rapport et ses états, coquille, thème, types à jour) ; 7 tests Playwright (`npm run test:e2e`) sur le vrai serveur hors ligne (`tests/e2e_server.py` : réponses enregistrées par `conftest.recorded_responses`, cache et chemins récents temporaires, jeton fixe) : choisir `vulnerable` par l'écran 2 et lire le bon rapport, 375 px et thème gardé, axe-core sans violation (WCAG 2.1 AA) sur les écrans 1 à 4 en clair et en sombre, à 1440 et 375 px, clavier. Les tests Python ne lancent jamais node. 1706 tests Python verts (plus 8 réseau), ruff propre. CI : job « Front » (types, lint, Vitest, build, Playwright avec uv).
- **Vérifié à la main** (`forceupdate ui`, vrai réseau) : `vulnerable` (28 failles, 13 élevées, 14 moyennes, 1 faible ; 3 mises à jour cochées ; werkzeug majeure proposée, pas cochée) et ce dépôt même (2 projets, 542 dépendances virtualisées, majeures de typescript, jsdom et @types/node proposées sans être cochées, hatchling approximative faute de lockfile) ; en clair et en sombre, à 375, 768, 1024 et 1440 px, sans défilement horizontal ni erreur de console. **Une faille réelle** : `deepmerge` 4.3.1 (CVE-2026-93753, moyenne, aucune version corrigée), tiré seulement par la CLI de shadcn (outil de dev, rien n'arrive dans le navigateur).
- **Limites** : pas de tri par version (comparer des versions est l'affaire du moteur : il faudrait une clé de tri de l'API) ; la répartition « par projet » de l'écran 3 n'existe pas (l'API ne la donne pas, ECRANS l'avait noté) ; un fichier envoyé ne se relance pas, il se redépose.

### E15 — Front : mise à jour locale

**But** : tout le parcours local se fait dans l'interface.

- [x] Écran 5 :
  - une case par mise à jour, pré-cochée selon E09. Une `Update` est un groupe de cases dont une au plus est cochée (`options`, `selected`) ; montrer ses avertissements (`warnings`), les failles corrigées, laissées et apportées (`fixes`, `unfixed`, `introduced` depuis E10), sa `note`, et griser une option `manual` en disant pourquoi ;
  - diff par fichier (`FileChange.diff`, E10), et les options cochées qui ne seront pas appliquées (`Changes.skipped` : fichier changé, `--hash`…) ;
  - appliquer ;
  - résultat : lockfiles régénérés, ou commande à lancer. Depuis E11 : avant d'appliquer, les `Job` (commande, avertissements de ce que l'outil exécute) ; après, chaque `Regenerated` : version obtenue (`Installed.reach` : exacte, plus haute, retenue par `held_by`), « aussi changé » (`changed`), fichiers remis (`restored`) et l'erreur de l'outil.
- [x] Glisser-déposer d'un fichier : analyse, puis téléchargement du fichier mis à jour.
- [x] Depuis E12 : plan `POST /api/updates/plan` (`files`, `skipped`, `lockfiles`, `uncommitted`, `applicable`) ; appliquer `POST /api/updates/apply` (409 avec les fichiers si git n'a pas leurs changements en commit : proposer d'appliquer quand même, `force`) ; suivre `GET /api/updates/{id}/events` ; résultat dans `results`. Glisser-déposer : `POST /api/files?name=…` (le contenu en corps), puis le même écran de rapport, le plan, et `GET /api/updates/{id}/files/{nom}` pour télécharger.
- [x] Garde-fous visibles : changements git non commités, outil natif absent, échec de résolution (fichiers restaurés).
- [x] Depuis E13 : écran 5 selon `design-system/pages/mise-a-jour.md` et la maquette `mise-a-jour.html`, avec toutes ses variantes (garde-fou, hors de git, outil absent, hors ligne, plan périmé, échec d'un outil, fichier envoyé, option `manual`, faille apportée, `note`) ; récapitulatif en colonne collante, barre collante en bas sous 1024 px ; `AlertDialog` pour « Appliquer quand même… » ; adresses `/analyses/{id}/mise-a-jour` et `/plans/{id}`.
- [x] Tests : composants, et un test de bout en bout qui applique une mise à jour sur une copie d'un mini-projet.
- [x] Depuis E14 :
  - l'écran 5 remplace la page « pas encore disponible » de `/analyses/{id}/mise-a-jour` et `/plans/{id}` (`UpdateSoon` dans `frontend/src/App.tsx`) ; le panneau de détail du rapport y envoie avec `?paquet=<Update.id>` : ouvrir (et faire défiler jusqu'à) la carte de ce paquet ;
  - **CSP** : le dialogue « Appliquer quand même… » est un `<dialog>` natif, comme `ui/sheet.tsx` (l'AlertDialog de Radix injecte un `<style>`, refusé) ; pas de Sonner (même raison) : une notification « Copié » par une région `aria-live` ;
  - réutiliser : `components/ui/*` (boutons, badges, alertes, cases à reprendre en Checkbox / RadioGroup), `Blade`, `screens/report/cells.tsx` (`VersionArrow`, `fixesText`, badges d'écart), `lib/format.ts` (`fr`, `count`), `test/api.tsx` (`mockApi`, `renderApp`) ; le rapport d'exemple `src/test/fixtures/vulnerable.json` (`tests/e2e_server.py --report`) a les 4 mises à jour de `vulnerable` ;
  - fichier envoyé : l'analyse marche déjà (glisser-déposer, « Choisir un fichier ») ; reste le plan et « Télécharger *nom* » ;
  - le test de bout en bout qui applique : `tests/e2e_server.py` sert un dossier temporaire ; y copier le mini-projet et simuler les outils de lockfile (comme `FakeTools`, ou outil absent : « commande à lancer »), jamais de vrai npm ni uv dans les tests.
- [x] Ajoutés en route : npm et uv simulés par le serveur de test, `e2e/helpers.ts`, le contrôle des largeurs (375 à 1440 px) et axe-core sur l'écran 5, `useScan` / `usePlan` partagés avec l'écran 4 (voir les notes).

**Fini quand** : choisir → analyser → cocher → voir le diff → appliquer, sans
quitter le navigateur, sur un projet Python et un projet npm.

**Notes** (session 15) :

- **Commit d'abord** : E14 commitée seule, avec l'accord de l'utilisateur.
- **Organisation** (`frontend/src/`) : `screens/update/` — `UpdatePage.tsx` (`/analyses/{id}/mise-a-jour`, étape Choisir), `UpdateCard.tsx` (une carte par `Update`), `PlanPage.tsx` (`/plans/{id}` : Vérifier selon le statut du plan, ou `ApplyStep.tsx`, `ResultStep.tsx`), `Layout.tsx` (fil d'Ariane, titre, fil d'étapes, squelettes) ; `lib/update.ts` (les déductions d'affichage : groupes, cocher et décocher, récapitulatif, fichiers d'une option du plan, découpage d'un diff unifié) ; `hooks/usePlanEvents.ts` (SSE de l'application, `EventSource` fermé à `end`) ; `hooks/useScan.ts` (`useScan`, `usePlan`, l'écran 4 s'en sert aussi) ; `components/Diff.tsx`, `components/Command.tsx`, `ui/choice.tsx` (cases et radios natifs), `ui/dialog.tsx` (confirmation) ; `api/client.ts` (`planUpdate`, `applyUpdate`, `getPlan`, `planEventsUrl`, `planFileUrl`).
- **Tranché** :
  - la sélection est l'état de l'étape Choisir ; le plan créé, l'adresse de Choisir devient `?plan=<id>` (remplacée), puis `/plans/{id}` : le retour du navigateur, « Modifier la sélection » et « Réessayer » retrouvent la sélection en relisant ce plan ;
  - le récapitulatif se compte sur la sélection affichée : failles corrigées de l'option cochée sur celles de chaque paquet qui a des options, fichiers de ses `edits`, son `lockfile`. Ce qui sera vraiment écrit, sauté ou régénéré, c'est le plan qui le dit (étape Vérifier) ;
  - groupes de cartes : les lockfiles dans l'ordre de `Project.lockfiles` (c'est celui de la maquette), puis « sans lockfile » ; l'outil n'est pas nommé à Choisir (il ne l'est que par le plan) ;
  - faille apportée : l'avertissement de l'API qui cite un identifiant d'`introduced` est en rouge, pas de phrase recomposée ; `fixesText` de `cells.tsx` pas repris, la maquette veut « Corrige 4 failles sur 6, en laisse 2 » (`fixesSentence`) ;
  - plan `failed` (fichier changé depuis le diff, rien n'est écrit) : il reste à Vérifier avec ce qui s'est passé ; `running` : Appliquer, rechargement compris (les événements sont rejoués) ; `done` : Résultat. Un 409 en appliquant (garde-fou revérifié, plan appliqué ailleurs) relit le plan ;
  - quand l'application avance sous les yeux, le focus va au titre « Application en cours », puis à l'alerte du résultat ;
  - barre collante sous 1024 px : à Choisir seulement (la maquette) ; à Vérifier, « Appliquer » reste sous les diffs et le garde-fou. Écarts notés dans `design-system/pages/mise-a-jour.md`, « Fait à E15 ».
- **Serveur de test** (`tests/e2e_server.py`) : npm et uv simulés (`fake_which`, `fake_spawn`, comme `FakeTools`) : npm met dans `package-lock.json` les versions exactes de `package.json` (épinglées le temps du passage), uv met les `-P nom==version` dans le fichier `-o` ; les autres outils sont absents. Les tests e2e qui écrivent travaillent sur une copie dans un dossier temporaire (`e2e/helpers.ts`) ; le garde-fou git, sur une copie passée par `git init` avec un changement non commité.
- **Trouvé** : le nom d'un bouton radio fait de son libellé se lisait « 4.18.1Mineure » (badges collés) : `aria-label` en mots séparés ; le chemin d'un lockfile part de la source (`frontend/package-lock.json`) : ne pas lui ajouter le projet ; le serveur de test est partagé entre les tests, ses chemins récents s'accumulent (`report.spec.ts` vise maintenant le chemin exact) ; après application, les failles relues dépendent de ce que savent les réponses enregistrées d'OSV (seulement les anciennes versions) : le test e2e vérifie les versions relues, pas le nombre de failles.
- **Tests** : 74 tests Vitest (26 de plus : `lib/update`, et l'écran 5 avec ses variantes — option `manual`, faille apportée, notes, `?paquet=`, `?plan=`, vide, non concluant, plan refusé, hors de git, outil absent, hors ligne, option sautée, confirmation et `force`, 409, plan échoué, fichier envoyé, plan oublié, application suivie par un `EventSource` simulé, commande copiée, outil en échec, versions plus hautes ou retenues) ; 16 tests Playwright (9 de plus : appliquer sur une copie de `vulnerable` puis relancer l'analyse, changer de version sans rien écrire, garde-fou et « Appliquer quand même », fichier envoyé téléchargé, largeurs de 375 à 1440 px, axe-core sur Choisir, Vérifier, la confirmation et Résultat en clair et en sombre à 1440 et 375 px), sans erreur de console. 1706 tests Python verts (plus 8 réseau), ruff propre.
- **Vérifié à la main** (`forceupdate ui`, vrais npm et uv, vrai réseau) : une copie de `vulnerable` dans le scratchpad — sélection proposée (3 sur 4, 9 failles corrigées sur 28), plan (deux diffs, npm et uv trouvés, hors de git), application suivie (npm, puis uv pip compile), résultat : trois versions exactes, fichiers relus sur le disque (lodash 4.18.1, flask 0.12.5, jinja2 2.11.3) ; ce dépôt (deux projets : `uv.lock`, « sans lockfile » pour hatchling, `frontend/package-lock.json`). Captures de chaque étape en clair et en sombre, à 375 et 1440 px, et de la confirmation.
- **Limites** : pas de durée par ligne à l'étape Appliquer (un rechargement rejoue les événements d'un coup) ; l'outil d'un lockfile n'est nommé qu'à Vérifier ; une mise à jour lancée ne s'annule pas (la page le dit). Le serveur de test laisse son dossier temporaire (`%TEMP%/forceupdate-e2e-*`) quand Playwright le tue en fin de série (déjà le cas à E14) : à nettoyer à E30 (CI, documentation).

---

## Phase E — Forges : GitHub, GitLab, Bitbucket

Chaque forge implémente la même interface `Forge` (E16). L'interface web et le
reste de l'outil ne connaissent que cette interface.

### E16 — Interface `Forge` commune, connexion GitHub

**But** : l'utilisateur connecte son compte GitHub depuis l'interface.

- [x] `forges/base.py`, interface `Forge` :
  - `whoami` ;
  - `list_repos`, `tree`, `read_file` ;
  - `clone`, `push_branch` ;
  - `find_open_request`, `open_or_update_request`.
- [x] Prérequis, à faire par l'utilisateur une seule fois, en tant qu'auteur de l'outil (la session le guide) : enregistrer l'outil comme OAuth App GitHub, avec une adresse de retour `http://127.0.0.1/…` et le Device Flow activé. Ensuite, chaque personne connecte son propre compte.
- [x] Connexion GitHub, depuis l'écran « Comptes » :
  - bouton « Se connecter avec GitHub » → page d'autorisation GitHub → retour sur le serveur local. GitHub accepte un retour vers `127.0.0.1` sur n'importe quel port pour une OAuth App : à vérifier ;
  - `state` anti-CSRF, comme dans `oauth_sso.py` d'Argos ;
  - si le retour ne marche pas : device flow affiché dans l'interface (un code à taper sur github.com) ;
  - autres options : coller un token, ou reprendre celui de `gh` s'il est connecté ;
  - portée : `repo` (lire les dépôts privés, pousser une branche, ouvrir une PR). À confirmer au moment de coder.
- [x] `forges/accounts.py` : tokens rangés dans le trousseau du système (`keyring`). Jamais affichés, jamais dans les logs, jamais envoyés au navigateur. Se déconnecter les efface.
- [x] `forges/github.py` :
  - client REST (pagination `Link`, limites de débit, messages clairs pour 401, 403 et 404) ;
  - `whoami`, avec ce que le token permet (lecture seule, ou écriture et PR).
- [x] Écran 6 (Comptes) pour GitHub.
- [x] Depuis E13 : écran 6 selon `design-system/ECRANS.md` (états compris, device flow en grand avec « Copier ») ; l'API des comptes : lister, connecter (OAuth, device flow, token collé, `gh`), déconnecter, droits du token. Logos des forges : Lucide n'en a plus ; le nom en texte avec une icône neutre, ou leurs logos officiels (Simple Icons, CC0) dans le respect des chartes de chaque marque : trancher avec l'utilisateur.
- [x] Ajoutés en route : l'adresse de retour d'OAuth hors de `/api` et son exception dans le garde, la révocation du token à la déconnexion, la relecture des droits (`verify`), le cinquième garde-fou des tests (trousseau et `gh`), un GitHub simulé dans le serveur de test, les comptes sur l'accueil, un verrou sur `accounts.json` (voir les notes).

**À reprendre** : `sechunter/dashboard/api/routes/oauth_sso.py` d'Argos (flux OAuth, `state` en cookie).

**Tests** : API GitHub et OAuth simulés.

**Fini quand** : depuis l'interface, l'utilisateur connecte son vrai compte
GitHub, le voit dans « Comptes », puis se déconnecte.

**Notes** (session 16) :

- **Commit d'abord** : E15 commitée seule (`7aee325`), avec l'accord de l'utilisateur.
- **Tranché avec l'utilisateur** : OAuth App (pas GitHub App : un clic, tous les dépôts, sans installer l'app sur chaque compte ni organisation) ; portées `repo` et `read:org` (`read:org` pour lister les organisations et signaler, à E17, celles qui restreignent l'accès des OAuth Apps) ; logos officiels de Simple Icons en une couleur (décision n°21 du brief). Tokens sans expiration : la case « Expire user access tokens », cochée d'office par GitHub, a été décochée (renouveler un token de 8 h, en concurrence entre la boucle du serveur et celle des analyses, est reporté à E29).
- **L'OAuth App** : enregistrée par l'utilisateur, guidé pas à pas. **Trouvé** : le formulaire de GitHub a changé (« Redirect URIs », jusqu'à 10, au lieu de « Authorization callback URL » ; la case d'expiration des tokens). Adresse de retour `http://127.0.0.1/oauth/github/callback`, Device Flow activé ; client id `Ov23lihqeEYz35ddy5Pm` et secret dans `forges/github.py` (public, comme celui de `gh` ; `FORCEUPDATE_GITHUB_CLIENT_ID` et `…_SECRET` les remplacent).
- **Organisation** : `forges/base.py` (`Forge`, ses 8 méthodes abstraites ; `Identity`, `Access`, `RateLimit`, `Repository`, `Tree`, `TreeEntry`, `ChangeRequest` ; `ForgeError` et `TokenRefused`, `AccessDenied`, `NotFound`, `RateLimited`) ; `forges/github.py` (`GitHub` : `request`, `get`, `paginate`, `whoami`, `rate_limit` ; le reste lève `NotImplementedError` en disant l'étape ; `access_of`, `warnings_of` ; OAuth : `authorization_url` avec PKCE, `exchange_code`, `authorization_error`, `revoke` ; device flow : `start_device`, `wait_device` ; `gh_token`) ; `forges/accounts.py` (`Accounts`, `Account`, `ConnectMethod`, `connect`, `verify`) ; `forges/__init__.py` (`FORGES`, `info`, `client`) ; `web/connections.py` (les connexions en cours : `state`, PKCE, tâches du device flow, et le `HttpClient` des comptes, dans la boucle du serveur) ; `web/routes/accounts.py`, `web/routes/oauth.py`. Dépendance : `keyring` 25.7 (prévue).
- **Le retour d'OAuth et le garde (tranché)** : `/oauth/github/callback`, hors de `/api`, est la seule adresse que le garde laisse passer sans jeton de session ni contrôle de `Sec-Fetch-Site` (`Guard(returns=…)`) : seulement en `GET`, en navigation (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document` s'ils sont là), sans `Origin` étrangère, avec le bon `Host`. Le `state` (32 octets, en mémoire, 10 min, une seule fois) la protège ; PKCE en plus du secret. Elle rend une page qui renvoie elle-même vers `/comptes?connexion=<id>` (`<meta http-equiv="refresh">`) : **une redirection HTTP ne marche pas**, la page suivante resterait « d'un autre site » (chaîne de redirections partie de github.com), sans cookie. Testé pour de vrai dans Chromium (la fausse page d'autorisation du serveur de test est sur `localhost`, un autre site que 127.0.0.1) et avec le vrai GitHub. GitHub ne revient que vers 127.0.0.1 : `POST …/oauth` refusé (409) si l'interface est ouverte par `localhost`.
- **Tranché** : le token reste dans le trousseau (`forceupdate`, `github:github.com`), le reste dans `accounts.json` (dossier d'état), un compte n'existe que si son token est dans le trousseau ; un refus de la forge n'est jamais un 401 de l'API (400, 409 pour une limite, 502 forge injoignable) ; lister ne demande rien à GitHub, l'écran relit les droits une fois à l'ouverture (`POST …/verify` : un token révoqué sur github.com devient `problem`, le compte reste) ; se déconnecter révoque le token donné à forceupdate (`DELETE /applications/{id}/token`), jamais un token collé ni celui de `gh` ; démarrer une connexion annule celle qui attendait pour la même forge ; pas d'avatar (CSP ; le servir par le serveur local n'apportait rien) ; `ForgeKind` sert en entrée (chemin) et en sortie : l'export du schéma permet maintenant une énumération des deux côtés (`web/openapi.py`).
- **Trouvé** : les captures ont montré, de temps en temps, « Connecté à GitHub » sur une carte « Non connecté » : **sous Windows, `os.replace` échoue (WinError 5 et 32) quand une autre écriture ou une lecture touche le fichier**, et `_load` prenait l'échec pour « aucun compte » (la relecture des droits écrivait pendant que l'écran relisait la liste). Verrou dans `Accounts` (testé par des threads). Aussi : `getByText` de Playwright cherche une sous-chaîne ; un `display: flex` sur un `<li>` efface son numéro ; axe-core veut un lien souligné au milieu d'une phrase.
- **Front** (`frontend/src/`) : `screens/accounts/` (`AccountsPage.tsx`, `ForgeCard.tsx`, tests), `components/ForgeLogo.tsx`, `hooks/useAccounts.ts` (`useAccounts`, `useAccountConnection` relue toutes les 2 s tant qu'elle attend, `browser.go`), `hooks/useCopy.ts` (sorti de `Command`) ; `api/client.ts` et `types.ts` ; l'accueil montre les comptes connectés ; `mockApi` rend par défaut une liste de comptes vide.
- **Tests** : 5e garde-fou dans `conftest.py` (`keychain` : trousseau en mémoire, neuf par test ; `gh` absent, le lancer échoue) ; `test_forges_github.py` (droits, erreurs, pagination, interface, PKCE contre l'exemple de la RFC 7636, OAuth, révocation, device flow avec une horloge simulée, `gh`), `test_forges_accounts.py` (trousseau, fichier sans token, concurrence), `test_web_accounts.py` (toutes les routes, retour d'OAuth, `state` à usage unique, expiration, device flow, réponses conformes au schéma), refus ajoutés à `test_web_security.py`. Serveur de test : `FakeGitHub`, fausse page d'autorisation sur `localhost`, trousseau en mémoire, `gh` simulé ; `recorded_responses(extra=…)`. 1851 tests Python verts (plus 8 réseau), ruff propre ; 98 Vitest (24 de plus) ; 25 Playwright (9 de plus : OAuth inter-sites, `state` rejoué, device flow, token refusé puis accepté, `gh` et l'accueil, axe-core en clair et en sombre à 1440 et 375 px).
- **Vérifié à la main** avec le vrai compte de l'utilisateur (`forceupdate ui`) : OAuth (autorisation sur github.com, retour, « Connecté », `Pauzzle-ozz`, `repo` et `read:org`, token dans le Gestionnaire d'identification de Windows et nulle part ailleurs), déconnexion (token révoqué, trousseau et fichier vides), device flow, token classic collé puis déconnexion (reste valable, supprimé par l'utilisateur sur GitHub). Device flow vérifié aussi par curl contre le vrai GitHub (le corps JSON est compris). Captures de chaque état en clair et en sombre, à 375 et 1440 px.
- **Limites** : un compte par forge ; tokens sans expiration ; `revoke` est propre à GitHub dans la route de déconnexion (à généraliser à E19) ; l'OAuth ne marche que par l'adresse `127.0.0.1` (pas par le serveur de dev de Vite).

### E17 — GitHub : dépôts et analyse sans cloner

**But** : tous les dépôts GitHub de la personne, analysés depuis l'interface.

- [x] `list_repos` : `/user/repos` (`affiliation=owner,collaborator,organization_member`). Chaque dépôt est marqué archivé, vide, fork, et avec ou sans droit de push. Les organisations qui restreignent l'accès des OAuth Apps sont signalées.
- [x] `sources/forge.py`, pour chaque dépôt :
  - arborescence de la branche par défaut (`git/trees?recursive=1`), sans les dossiers ignorés (`detect.manifests.is_ignored_path`) ;
  - `read_text` plafonné comme en local, avec `detect.manifests.max_read_size` (50 Mo pour un lockfile) ; il est aussi appelé pour les `-r` des `requirements.txt`, pour le `pyproject.toml` racine d'un workspace uv, et pour `pnpm-workspace.yaml` (E04), qui ne sont pas des manifestes repérés : les télécharger aussi. Il doit rendre `None`, sans erreur, pour un fichier absent (`pnpm-workspace.yaml` est facultatif) ;
  - langages : détecteur de E02 (`detect_languages`) appliqué aux chemins et tailles de l'arborescence ; projets : `find_projects` ;
  - télécharger seulement les manifestes et lockfiles, dans un dossier temporaire qui reproduit les chemins ;
  - puis le pipeline local, inchangé.
- [x] Cas particuliers :
  - arborescence tronquée → clone superficiel (E18) ; à E17 : dit dans le rapport, le dépôt est « non concluant » ;
  - fichier de plus de 1 Mo → `Accept: application/vnd.github.raw` ;
  - dépôt vide → sauté, signalé.
- [x] Concurrence bornée entre dépôts ; cache des registres partagé ; nombre de requêtes API consommées affiché.
- [x] Analyser un dépôt public d'un autre compte : champ « `owner/repo` ou URL ».
- [x] Écran 7 (Mes dépôts : liste, filtres, sélection, synthèse) ; le rapport d'un dépôt réutilise l'écran 4.
- [x] Depuis E13 : écran 7 selon `design-system/pages/depots.md` et la maquette `depots.html`. L'API doit rendre : les drapeaux de chaque dépôt (archivé, fork, vide, privé, droit de push), les organisations qui restreignent l'accès, les requêtes d'API restantes ; des analyses groupées avec la progression par dépôt et l'annulation ; **la synthèse multi-dépôts, calculée par le serveur** (compteurs par type et gravité, dépôts à jour, à mettre à jour, non concluants, sautés, PR ouvertes) : pas de logique métier dans le front. Les PR ouvertes passent à E18 (`find_open_request` y arrive).
- [x] Depuis E12 : `web.jobs.Jobs.start_scan` prend une `LocalSource` ; l'ouvrir à la source d'un dépôt (et `ScanSummary.kind` à `repository`), les analyses de dépôts passant par le même `Worker` (client et cache partagés, concurrence bornée).
- [x] Depuis E16 :
  - le token d'un compte : `Accounts.token(forge, hôte)` (dans un thread : `asyncio.to_thread`), côté serveur seulement ; la forge : `forges.client(kind, http, token)`. Les analyses tournent dans la boucle du `Worker` : y créer la forge avec **son** `HttpClient` (celui de `web.connections` vit dans la boucle du serveur, pour les comptes) ;
  - `GitHub.paginate` (`Link`, 100 par page) et `GitHub.rate_limit` (requêtes restantes) existent ; `list_repos`, `tree`, `read_file` lèvent encore `NotImplementedError`. Les types `Repository`, `Tree`, `TreeEntry` de `forges/base.py` sont à compléter si besoin (archivé, vide, fork, droit de push, langages) ;
  - les organisations qui restreignent l'accès : `GET /user/orgs` (portée `read:org`), puis un 403 sur `/orgs/{org}/repos` ; un token sans `read:org` (collé) le dit déjà dans `warnings` ;
  - un token refusé (401) pendant une analyse : noter `problem` sur le compte (`Accounts.refused`), l'écran 6 le montre ;
  - l'accueil : la carte « Mes dépôts » montre déjà les comptes connectés ; y ajouter le nombre de dépôts, et le lien vers l'écran 7.

- [x] Ajoutés en route : `Forge.repository` (un dépôt par son nom) et `Forge.restrictions`, un client GitHub sans token (dépôts publics), `report/synthesis.py` (verdict d'un dépôt, constats additionnés), l'étape `downloading` des analyses, le GitHub simulé `tests/fake_forge.py`, la dernière analyse de chaque dépôt jamais oubliée, le débordement de la vue d'ensemble du rapport à 375 px (voir les notes).

**Fini quand** : dans l'interface, tous les dépôts du compte sont listés et
analysés ; le rapport est vérifié à la main sur 2 ou 3 dépôts.

**Notes** (session 17) :

- **Commit d'abord** : E16 commitée seule (`eef28c7`), avec l'accord de l'utilisateur.
- **Organisation** :
  - `forges/base.py` : `Repository` gagne `empty`, `language`, `pushed_at`, `owner`, `name` ; `Restriction` et `RestrictionKind` (`app_access`, `sso`) ; erreurs `AppRestricted`, `SsoRequired` (avec `url`), `EmptyRepository` ; `Forge.requests` (requêtes envoyées), `Forge.rate_limit`, `Forge.repository(full_name)` (abstraite, 9e méthode), `Forge.restrictions()` (aucune par défaut) ;
  - `forges/github.py` : `list_repos`, `repository`, `restrictions`, `tree`, `read_file` ; `GitHub(http, None)` lit les dépôts publics sans token ; `forges/__init__.py` : `parse_repository` (« `owner/nom` ou adresse » : https, `github.com/…`, `.git`, `git@…:`, une page du dépôt ; GitLab et Bitbucket reconnus par leur hôte) ;
  - `sources/forge.py` : `fetch` (arborescence, téléchargements) et `ForgeSource` (la `Source` que lit le moteur) ; `report/synthesis.py` : `verdict` et `combine` ;
  - `web/jobs.py` : `RepositoryTarget`, `Jobs.start_repository_scan`, `Jobs.latest`, `Worker.analyze_repository` ; `Scan.source` devient une `Source` (`None` tant qu'un dépôt n'est pas lu), `Scan.local`, `Scan.repository`, `Scan.batch` ; `web/repositories.py` (`Repositories` : liste, lots, lignes, synthèse) ; `web/routes/repositories.py` ; `models.EventKind.DOWNLOADING`.
- **Tranché** :
  - **ce qui se télécharge** : les parseurs le disent. Ils tournent sur ce qui est déjà téléchargé et l'on note ce qu'ils demandent (d'abord manifestes et lockfiles, puis les `-r`/`-c`, le `pyproject.toml` racine d'un workspace uv, le `pnpm-workspace.yaml` parent), jusqu'à ce qu'ils ne demandent plus rien (8 tours au plus) ; les lockfiles ne sont pas lus pendant ces tours (rien ne les suit, 50 Mo au plus). Un `setup.py` n'est donc jamais téléchargé. Les fichiers au-delà de `max_read_size` non plus (le rapport le dit, comme en local). Rangés dans un dossier temporaire qui reproduit les chemins (effacé avec l'analyse) ; un chemin que Windows refuse (`aux/`, `con.txt`) est sauté ;
  - **GitHub** : le commit d'abord (`commits/{branche}` avec `Accept: application/vnd.github.sha`), puis `git/trees/{commit}?recursive=1` (sans sous-modules ni liens symboliques), puis chaque fichier par `contents/{chemin}?ref={commit}` avec `Accept: application/vnd.github.raw` (jusqu'à 100 Mo, au lieu de 1 Mo en JSON) : les fichiers sont lus au commit de l'arborescence, même si la branche avance. Un dépôt vide : GitHub ne le dit pas dans la liste ; ceux de `size` nulle (un petit dépôt peut l'avoir) sont vérifiés par `commits?per_page=1` (409 : vide). Organisations : `/user/orgs`, puis `/orgs/{org}/repos?per_page=1` ; un 403 « OAuth App access restrictions » donne `app_access` (lien : `github.com/settings/applications`, où un membre demande l'accès), `X-GitHub-SSO` donne `sso` ; sans `read:org`, rien ;
  - **qui parle à GitHub d'où** : la liste dans la boucle du serveur, avec le client des comptes (`Connections.http`), gardée le temps de la session (rechargée par « Recharger la liste », ou si le compte a été reconnecté) ; les analyses dans la boucle du `Worker`, avec une forge créée sur **son** client, une par lot (elle compte les requêtes du lot). Concurrence : 4 dépôts à la fois (sémaphore du lot), 8 requêtes à la fois par hôte (le client) ; registres et cache partagés ;
  - **l'état d'un dépôt** (`RepositoryState`), du serveur : `to_update` dès un constat à mettre à jour ; `up_to_date` seulement si rien n'est resté sans réponse et toute l'arborescence lue ; `inconclusive` sinon, et pour une analyse échouée (avec l'erreur) ; `no_dependencies` ; `skipped` pour un vide (toujours) et un archivé ou un fork pas analysé (masqués et sautés par défaut, décision du brief) ; `not_scanned`. Un `package.json` sans dépendance est « à jour ». La synthèse additionne les résumés de la dernière analyse de chaque dépôt (un même paquet dans deux dépôts compte deux fois) ; le front ne recompte rien (il somme seulement les mises à jour pré-cochées de la sélection, que le serveur donne par dépôt) ; `counts.worst` donne la couleur du badge des failles ;
  - **un dépôt public d'un autre compte** : `POST /api/repositories/scans`, avec le token du compte connecté s'il y en a un, sans token sinon (60 requêtes par heure) ; il n'entre pas dans la liste ; ses analyses (comme celles relancées depuis un rapport) restent dans « Cette session » de l'accueil, celles d'un lot n'y sont pas (`ScanSummary.batch`) ;
  - **mise à jour** : un plan sur un dépôt est refusé (409) ; le rapport d'un dépôt n'a pas « Mettre à jour » ni le lien du panneau de détail. La PR arrive à E18 ;
  - **mémoire** : les 20 analyses les plus récentes, plus la dernière de chaque dépôt (jamais oubliée) ;
  - **PR ouvertes** (synthèse, colonne « PR / MR », « Préparer N PR » dans la barre de sélection) : à E18, avec `find_open_request`. À E17, la barre de sélection a « Analyser ces N dépôts » en action principale.
- **Trouvé** : la vue d'ensemble du rapport (écran 4, E14) débordait de 36 px à 375 px avec un long chemin de projet (grille sans `minmax(0, 1fr)`) : corrigé ; pendant une analyse groupée, « Failles : 0, aucune connue » s'affichait en vert et les dépôts en attente avaient une lame animée : corrigé (« analyse en cours », pas de lame en attente) ; Testing Library ramène les espaces insécables à des espaces dans les textes, pas dans les noms accessibles (`\s` dans les motifs) ; le squelette de l'écran 7 porte déjà le `h1` : les tests attendent la synthèse ; Playwright compare les noms par sous-chaîne (le lien « Ouvrir … sur GitHub » contient le nom du dépôt : `exact: true`) ; le navigateur consigne en erreur une réponse 404 voulue ; `git archive` sous Windows écrit en CRLF (tailles des langages plus grandes qu'avec GitHub, qui donne celles des blobs).
- **Front** (`frontend/src/`) : `screens/repositories/` (`RepositoriesPage.tsx` : états, alertes, comptes, synthèse, analyse groupée, dépôt public ; `RepositoryList.tsx` : filtres, tableau trié, cartes sous 768 px, cases et barre de sélection, cellule « Analyse » par état), `lib/repositories.ts` (filtres, tri, sélection, progression, requêtes restantes), `hooks/useRepositories.ts` (liste relue chaque seconde pendant une analyse), `useRescan` et `useScanRepository` (`hooks/useScanActions.ts`), étape « Téléchargement » de l'écran 3, rapport d'un dépôt (fil d'Ariane « Mes dépôts », commit, « Voir sur GitHub », arborescence tronquée), accueil (nombre de dépôts, « Voir mes dépôts »). `e2e/accounts.spec.ts` devient `e2e/forges.spec.ts` (écrans 6 et 7 : le compte du serveur de test est partagé, les deux écrans doivent se suivre dans un seul fichier).
- **Tests** : `tests/fake_forge.py` (GitHub simulé : liste paginée, dépôts, commits, arborescence, fichiers bruts, organisations restreintes, SSO, coupure, requêtes restantes ; dépôts faits des mini-projets) ; `test_forges_repos.py` (liste et drapeaux, vides, sans token, organisations, arborescence, fichiers, `parse_repository`) ; `test_sources_forge.py` (**chacun des 14 mini-projets lu par l'API donne le même inventaire que le dossier local**, seuls les fichiers de dépendances téléchargés, inclusions sur plusieurs tours, `pnpm-workspace.yaml` parent, fichier absent, trop gros, dossiers de tests, événements, arborescence tronquée, chemins hors du dépôt ; un test réseau sur `pallets/markupsafe`) ; `test_report_synthesis.py` ; `test_web_repositories.py` (liste, drapeaux, organisations, cache de la liste, token refusé puis compte reconnecté, GitHub muet, analyse groupée, synthèse, rapport, plan refusé, refus, token refusé pendant un lot, annulation, mémoire, dépôt public, schéma). 1941 tests Python verts (plus 9 réseau), ruff propre ; 113 Vitest (15 de plus) ; 32 Playwright (7 de plus : liste, analyse groupée et rapport, dépôt public, axe-core en clair et en sombre à 1440 et 375 px, sans compte, largeurs de 375 à 1440 px).
- **Vérifié à la main** avec le vrai compte de l'utilisateur, reconnecté par OAuth (`forceupdate ui`, piloté ensuite par Playwright) : 7 dépôts (dont 2 de l'organisation `Omnividens-argos`), aucun masqué ni restreint ; « Analyser tous les dépôts » : 7 analyses en 15 s, 32 requêtes d'API ; 358 failles dont 18 critiques dans 4 dépôts, 6 à mettre à jour, 1 sans fichier de dépendances. **Rapports comparés à l'analyse locale du même commit** (`git archive`, puis `forceupdate scan`) : `Omnividens-argos/sechunter` à `52c714b7` (le clone d'Argos de l'utilisateur ; 570 dépendances, 16 constats) et `Pauzzle-ozz/forceupdate` à `9f4d1bd` (37 dépendances, 3 constats) : mêmes projets, dépendances, constats, remarques et fichiers écartés. Captures de la liste, de l'analyse en cours, du rapport d'un dépôt et de son analyse, de l'accueil, en clair et en sombre, à 375 et 1440 px, sans erreur de console ni défilement horizontal.
- **Limites** : une arborescence tronquée donne une analyse partielle (le clone superficiel est à E18) ; un dépôt vidé entre la liste et l'analyse sort « non concluant » (« Dépôt vide ») ; le tableau des dépôts n'est pas virtualisé (écart à MASTER, noté dans `pages/depots.md`) ; sur le rapport d'un dépôt, la navigation montre « Analyser » comme écran actif (l'adresse `/analyses/{id}` ne dit pas la source) ; `parse_repository` ne garde que deux segments du chemin (les sous-groupes de GitLab : à E19) ; les requêtes restantes sont celles de la dernière réponse connue.

### E18 — GitHub : une PR par dépôt

**But** : chaque dépôt à mettre à jour reçoit une PR propre.

- [x] `forges/git.py` :
  - adapter `git_client.py` d'Argos : token donné à git via un credential helper éphémère, jamais dans `argv`, masqué dans les messages ;
  - sans `target_validator` : on ne parle qu'à des forges connues ;
  - clone superficiel de la branche par défaut ;
  - le même mécanisme sert au push.
- [x] Dossier de travail temporaire nettoyé à la sortie (adapter `workspace.py` d'Argos).
- [x] Pour chaque dépôt :
  1. clone ;
  2. sélection (E09), réécriture (E10), lockfiles (E11 : `lockfiles.plan` puis `regenerate`, sur le clone). Un outil absent ou qui échoue : la PR le dit dans sa description (la commande à lancer, l'erreur), et les fichiers remis comme avant ne sont pas commités ;
  3. branche `forceupdate/dependencies`, commit (auteur : l'utilisateur du token), push ;
  4. PR, avec en description le rapport Markdown du dépôt.
- [x] Idempotence : si la PR existe déjà, pousser la branche à jour et mettre à jour la description, sans ouvrir de nouvelle PR. Rien à faire → rien poussé.
- [x] Garde-fous :
  - jamais de push sur la branche par défaut ;
  - dépôts archivés ou sans droit de push : sautés et signalés ;
  - un récapitulatif avant d'envoyer (N dépôts, M PR, le détail par dépôt), et rien n'est poussé sans validation.
- [x] Écran 8 (récapitulatif, puis résultat avec les liens des PR).
- [x] Depuis E13 : écran 8 selon `design-system/ECRANS.md` : récapitulatif par dépôt (PR existante mise à jour ou nouvelle, sélection, lockfiles et commandes, dépôts sautés et pourquoi), envoi suivi dépôt par dépôt, résultat avec les liens ; `#41` sur GitHub et Bitbucket, `!12` sur GitLab.
- [x] Depuis E16 : les signatures sont fixées dans `forges/base.py` (`clone(repo, destination)`, `push_branch(repo, checkout, branch)`, `find_open_request(repo, branch)`, `open_or_update_request(repo, *, branch, title, body)` → `ChangeRequest`) ; `GitHub.request` donne déjà les en-têtes, les erreurs claires et les requêtes restantes. Le commit a pour auteur l'utilisateur du token (`Identity.login`, `name`) ; un compte connecté par un token fine-grained a des droits « non vérifiés » : un push ou une PR refusés (403) doivent le dire.
- [x] Depuis E17 :
  - l'écran 7 attend ses PR : la colonne « PR / MR » (le numéro, `#41`, lien vers la forge), le compteur « PR et MR ouvertes » de la synthèse (calculé par le serveur, comme le reste : `RepositorySynthesis`), « Préparer *N* PR » en action principale de la barre de sélection (« Analyser ces *N* dépôts » devient secondaire), et sur le rapport d'un dépôt l'action qui remplace « Mettre à jour » (absente à E17, comme le lien du panneau de détail : `DependencyDetail` reçoit `scanId={null}`) ;
  - `POST /api/updates/plan` refuse un dépôt (409, `routes/updates.REPOSITORY`) : la sélection d'un dépôt passera par l'écran 8 ;
  - une arborescence tronquée (`ForgeSource.truncated`, `RepositoryRef.truncated`) : analyser sur le clone superficiel ;
  - ce qui existe : `Repositories` (`web/repositories.py`) tient la liste et les lots ; `RepositoryTarget` et `Worker.analyze_repository` font travailler une forge dans la boucle des analyses, avec **son** client (`Repositories._worker_forge`) ; `Forge.requests` compte les requêtes, `Forge.rate_limit` les restantes ; le token se lit par `Repositories._token` (dans un thread) ; un 401 note le compte (`Accounts.refused`) ; `tests/fake_forge.py` simule les dépôts (à compléter : branches, PR, push vers un dépôt « bare »).
- [x] Ajoutés en route : `Forge.branch` et le bail de `push_branch` (`expected`), les commits d'un autre jamais écrasés, `Identity.email` (adresse `noreply`), le choix d'un dépôt à l'écran 5 (`?pr=`), le récapitulatif enrichi (`ProposedUpdate`, `ProposedSkip`), le sixième garde-fou des tests (git), `EventKind.CLONING`, `forges.github.GIT_URL` (voir les notes).

**À reprendre** : `~/Desktop/the good guy/sechunter/core/repo/git_client.py`,
`workspace.py`, et `github_app.py` (`create_pull_request`, pour les appels REST).

**Tests** : un dépôt git local « bare » sert de remote ; l'API GitHub est simulée.

**Fini quand** : depuis l'interface, une PR s'ouvre sur un dépôt de test de
l'utilisateur ; relancer met à jour la même PR.

**Notes** (session 18) :

- **Commit d'abord** : E17 commitée seule (`e35bb59`), avec l'accord de l'utilisateur. Dépôt de test : l'utilisateur a choisi qu'il soit créé pour lui ; `Pauzzle-ozz/forceupdate-demo`, privé, copie de `tests/projects/vulnerable` (+ un README qui dit de le supprimer après l'essai).
- **Organisation** :
  - `forges/git.py` (adapté de `git_client.py` et `workspace.py` d'Argos) : `clone`, `head`, `tree`, `commit`, `push`, `redact`, `Workspace`, `remove_tree` ; `GitError(ForgeError)` avec `GitFailure` (`auth`, `denied`, `not_found`, `protected`, `stale`, `network`, `timeout`, `missing`, `other`) lue dans ce que dit git (en anglais : `LC_ALL=C`) ; `_spawn` (sans shell, délai : 600 s pour clone et push, 60 s sinon) ;
  - `forges/base.py` : `Branch` et `BranchCommit` (`Forge.branch`, 10e méthode abstraite), `push_branch(…, *, expected)`, `Identity.email` ; `forges/github.py` : `clone`, `branch` (`git/ref/heads/…` puis `compare/{défaut}...{sha}`), `push_branch`, `find_open_request` (`pulls?state=open&head=owner:branche&base=défaut`), `open_or_update_request` (PATCH si elle existe ; un 422 « already exists » à la création : on la retrouve et on la met à jour), `GIT_URL` (d'où git clone ; les tests le font pointer vers des dépôts « bare »), `_message` lit aussi `errors[].message` ;
  - `update/forge.py` : `deliver` (clone, `local.prepare` puis `local.apply` sur le clone, commit, branche, push, PR ; ne lève pas, rend un `Delivered`), `committable`, `commit_message`, `request_body`, `ours` ; `BRANCH`, `TITLE`, `MARKER`, `MAX_BODY` ; `Step`, `Outcome` ; `report/markdown.py` : `escape` et `code` publics ;
  - `sources/forge.py` : `ClonedSource` et `clone` ; `web/jobs.py` : le clone d'une arborescence tronquée, `Scan.request` (la PR trouvée pendant l'analyse), `Jobs.in_updates`, `Jobs.post`, `same` ; `web/repositories.py` : `remember` et `request` (la PR la plus récente qu'on connaisse d'un dépôt), `token`, `connected`, `worker_forge`, `refused_callback` rendus publics ; `web/proposals.py` (`Proposals`, `Proposal`, `Proposed`) et `web/routes/proposals.py` ; `models.EventKind.CLONING`.
- **Tranché** :
  - **le récapitulatif ne clone rien** : la sélection se prépare (`local.prepare`) sur les fichiers téléchargés à l'analyse (le dossier de la `ForgeSource`, ou le clone d'une arborescence tronquée) : diffs, lockfiles, outil trouvé ou commande, en une seconde. Le clone n'arrive qu'à l'envoi, où la sélection est **préparée de nouveau sur le clone** : un fichier qui a changé depuis l'analyse voit ses options sautées (« a changé depuis l'analyse »), le reste part (vérifié en vrai : `main` avancé, la PR refaite dessus) ;
  - **la branche est remplacée à chaque envoi** : un seul commit, fait sur la branche par défaut du moment, poussé par `--force-with-lease=refs/heads/forceupdate/dependencies:<sha vu>` (vide : elle ne doit pas exister) : si quelqu'un la change entre-temps, rien n'est poussé. **Jamais par-dessus le travail d'un autre** : si la branche a un commit qui n'a pas la marque `Generated-by: forceupdate` (une correction poussée à la main pour une majeure), rien n'est poussé et l'erreur le dit ; une fusion de la branche par défaut (« Update branch ») est tolérée (décision n°22 du brief). Si la branche a déjà exactement ce contenu (même arbre), rien n'est poussé : la description seule est refaite ;
  - **ce qui part dans le commit** : les manifestes réécrits et les lockfiles régénérés, nommés un par un (`git add -- …`), jamais ce qu'un outil en échec a remis comme avant ni ce qu'il a laissé à côté (un `.venv`) ; outil absent : les manifestes partent, la description donne la commande ; rien de changé au bout du compte : `nothing`, rien n'est poussé ;
  - **git et la configuration de la personne** : gardée (proxy, certificats, `http.sslbackend`), sauf ce qui changerait le résultat, imposé par `-c` : `core.autocrlf=false` et `core.eol=lf` (le contenu tel qu'il est dans le dépôt, comme celui que donne l'API), `core.longpaths=true`, `core.hooksPath` vers un dossier qui n'existe pas et `--no-verify` (aucun hook), `commit.gpgsign=false`, `credential.helper=` vidé avant le nôtre (le gestionnaire d'identification de Windows ne garde rien : vérifié, `cmdkey`), `GIT_LFS_SKIP_SMUDGE=1`, pas de prompt ; les variables `GIT_DIR`, `GIT_AUTHOR_*`… héritées sont retirées. L'auteur et le committer passent par `GIT_AUTHOR_*`/`GIT_COMMITTER_*` ;
  - **l'auteur** : le compte du token (`whoami` au début de l'envoi), son nom (ou son login) et son adresse `noreply` (`{id}+{login}@users.noreply.github.com`, qui rattache le commit au compte sans dévoiler son adresse) ;
  - **la description** : en français (l'outil l'est), un tableau des mises à jour (version, failles corrigées, état : faite, plus haute, retenue, lockfile à régénérer, pas faite), les lockfiles (régénéré par…, commande à lancer, erreur de l'outil dans un bloc de code qu'elle ne peut pas fermer), les options non appliquées, puis le rapport Markdown de l'analyse (titres descendus d'un niveau), raccourci au-delà de 60 000 caractères (GitHub refuse au-delà de 65 536) ;
  - **qui tourne où** : le récapitulatif dans la boucle du serveur (forge sur le client des comptes, `find_open_request` en parallèle) ; l'envoi dans la boucle du `Worker` (forge sur **son** client), **un dépôt à la fois**, git et outils de lockfile dans le thread des mises à jour (`Jobs.in_updates` : jamais en même temps qu'une mise à jour locale) ; l'état n'est modifié que dans la boucle du serveur (`Jobs.post`). Un dépôt qui échoue n'arrête pas les autres ; un envoi ne s'annule pas ;
  - **les PR connues de l'écran 7** : cherchées à chaque analyse d'un dépôt où l'on peut pousser (une requête de plus), puis à chaque récapitulatif et à chaque envoi ; la plus récente gagne. Le compteur « PR ouvertes » compte les dépôts qui en ont une ;
  - **« non concluant » au récapitulatif** veut dire « l'analyse n'a pas tout vérifié » (un constat `inconclusive`, une arborescence tronquée), pas le verdict du dépôt (qui dit « à mettre à jour » dès un constat, avant « non concluant ») : prêt, mais pas coché ;
  - **arborescence tronquée** : le dépôt est cloné pendant l'analyse (`destination/clone`) et c'est le clone qui est analysé (`RepositoryRef.cloned`) ; si le clone échoue (git absent…), l'analyse partielle reste, comme à E17 ;
  - **API** : `POST /api/proposals` (201, le récapitulatif), `GET /api/proposals/{id}`, `POST /api/proposals/{id}/send` (202), suivis par relecture chaque seconde (comme les lots de E17), pas par SSE. Le récapitulatif donne de quoi afficher sans décoder les identifiants (`ProposedUpdate` : nom, écosystème, versions, écart, failles ; `ProposedSkip`). Les 10 derniers en mémoire ;
  - **front** : `/pr?forge=github&depots=a/b,c/d` prépare le récapitulatif puis passe à `/pr/{id}` ; l'écran 5 sait choisir pour un dépôt (« Préparer la PR », étapes Choisir → Récapitulatif → Envoi → Résultat ; `?pr=<id>` : « Modifier la sélection » d'un récapitulatif, qui en garde les autres dépôts).
- **Trouvé** :
  - le credential helper d'Argos (`-c !f() {…}` sans `credential.helper=` devant) ne pouvait pas marcher ; celui d'ici est vérifié par `git credential fill` (même sous Git pour Windows, qui le lance par son `sh`) et par un vrai push vers GitHub ;
  - avec `push --porcelain`, git dit son refus (« stale info ») sur la **sortie standard**, pas sur la sortie d'erreur : le diagnostic lit les deux ;
  - `--force-with-lease=ref:<sha>` marche depuis un clone superficiel qui n'a pas ce commit (le serveur compare) ;
  - le 422 de GitHub pour une PR déjà ouverte a son détail dans `errors[].message` ;
  - **une coupure réseau d'un registre** (`ConnectError`) fait abandonner l'hôte 60 s **pour toutes les analyses** du client partagé (`DOWN_FOR`) : un test qui simulait un registre muet ainsi privait les autres dépôts de PyPI (jinja2 perdait ses options). Un 503 rend le paquet non concluant sans abandonner l'hôte ;
  - `monkeypatch.undo()` dans un test défait aussi les garde-fous des fixtures automatiques (trousseau, réseau) : `monkeypatch.context()` ;
  - les vrais npm et uv redonnent exactement les mêmes lockfiles : relancer ne pousse rien (même arbre).
- **Tests** : `test_forges_git.py` (le token par le helper, jamais dans les arguments, masqué ; environnement hérité écarté ; clone superficiel sans conversion de fin de ligne ; commit au nom du compte ; push avec bail : création, remplacement, refus si elle a bougé ; diagnostic ; dossier de travail effacé malgré les fichiers en lecture seule ; git jamais vers GitHub), `test_forges_requests.py` (`whoami` et l'adresse `noreply`, clone, branche et ses commits, push jamais sur la branche par défaut, PR ouverte puis mise à jour, ouverte entre-temps, 403), `test_update_forge.py` (`deliver` de bout en bout : PR ouverte avec les quatre fichiers, relancer sans rien pousser puis après que `main` a avancé, outil absent, outil en échec, rien à faire, commit d'un autre, archivé et lecture seule, token refusé, fine-grained, description raccourcie), `test_web_proposals.py` (récapitulatif et raisons des sautés, envoi puis relance, sélection modifiée, refus, un échec n'arrête pas les autres, fichiers changés depuis l'analyse, rien à faire, token refusé à l'envoi, PR trouvée à l'analyse, schéma) ; `test_web_repositories.py` : l'arborescence tronquée clonée, ou partielle si le clone échoue. `fake_forge.py` : dépôts « bare » (`make_remote`, `push_commit`, `remotes_url`), `git/ref`, `compare`, `pulls`, `/user`. **Sixième garde-fou** (`conftest.py`) : hors `network`, git ne parle qu'à des dépôts locaux. 1998 tests Python verts (plus 9 réseau), aussi sous 3.11 pour les nouveaux ; 127 Vitest (14 de plus : écran 8, colonne et compteur de l'écran 7, « Préparer la PR » du rapport, l'écran 5 pour un dépôt) ; 37 Playwright (5 de plus : la PR ouverte puis mise à jour de bout en bout, axe-core sur le récapitulatif et le résultat en clair et en sombre à 1440 et 375 px), sans erreur de console. Le serveur de test a ses dépôts « bare » (`tests/e2e_server.py`).
- **Vérifié avec le vrai compte** (`forceupdate ui`, vrais npm et uv, piloté par Playwright) : `Pauzzle-ozz/forceupdate-demo` analysé (28 failles), récapitulatif (3 mises à jour, 9 failles corrigées, npm et uv trouvés), « Envoyer la PR » : **PR #1 ouverte**, un commit de `Pauzzle-ozz <256361197+Pauzzle-ozz@users.noreply.github.com>`, quatre fichiers (`package-lock.json` +4 −4, `package.json` +1 −1, `requirements.in` +1 −1, `requirements.txt` +3 −3 : lodash 4.18.1, flask 0.12.5, jinja2 2.11.3), `main` intact, description de 9 000 caractères ; relancer depuis le rapport : « met à jour la PR #1 », rien poussé (même contenu), description refaite ; `main` avancé (un commit sur le README), relancer : branche refaite sur le nouveau `main` (un commit) et poussée avec le bail, **toujours la PR #1**. Ni token dans `.git/config`, ni entrée dans le gestionnaire d'identification de Windows. Captures des écrans 7, 8 et 5 (dépôt) en clair et en sombre, à 1440 et 375 px, sans erreur de console ni défilement horizontal.
- **Limites** : un envoi ne s'annule pas, et un arrêt du serveur pendant un envoi peut laisser une branche poussée sans PR (relancer la reprend) ; une PR fermée sans fusion est rouverte (nouvelle) au prochain envoi : rien ne garde le souvenir d'un refus ; les récapitulatifs ne vivent que le temps de la session ; un `url.<base>.insteadOf` de la configuration git de la personne pourrait faire passer le clone par SSH (hors du credential helper) ; un commit de la branche fait à la main bloque les envois suivants jusqu'à ce qu'il soit fusionné ou la branche supprimée ; la description est en français ; l'écran 7 ne prépare les PR que d'une forge à la fois.

### E19 — GitLab

**But** : la même chose que E16 à E18, pour GitLab.

- [x] Prérequis, à faire par l'utilisateur (la session le guide) : enregistrer l'outil comme application OAuth sur gitlab.com, « non confidentielle » (PKCE, pas de secret), avec un retour vers `127.0.0.1`.
- [x] Connexion :
  - gitlab.com : OAuth avec PKCE, portée `api` ;
  - instance auto-hébergée : son URL et un token personnel. Pour l'OAuth, il faudrait enregistrer l'outil sur chaque instance.
- [x] `forges/gitlab.py` :
  - projets (`membership=true`), y compris ceux des groupes et sous-groupes ;
  - langages, arborescence (paginée), fichiers bruts ;
  - clone (`oauth2:<token>`, déjà prévu par `git_client.py` d'Argos) ;
  - merge requests : création, mise à jour, idempotence.
- [x] L'interface dit « merge request » pour GitLab, « pull request » ailleurs.
- [x] Depuis E16 : passer GitLab à `available=True` dans `forges.FORGES`, l'ajouter à `forges.client` ; son adresse de retour (`/oauth/gitlab/callback`) dans `web.routes.oauth.RETURN_PATHS` (le garde ne laisse passer que ces adresses) et son test de refus ; les façons de se connecter (`methods`) et la révocation, aujourd'hui propres à GitHub dans `web/routes/accounts.py` et `web/connections.py` (`github.revoke`, `github.start_oauth`…), à faire passer par la forge ; plusieurs comptes GitLab (gitlab.com et une instance) : la clé du trousseau est déjà `forge:hôte`, mais l'API désigne un compte par sa seule forge. L'écran 6 a déjà sa carte « Bientôt ».
- [x] Depuis E17 : `list_repos`, `repository`, `tree`, `read_file` de GitLab (l'arborescence est paginée) suffisent à `sources/forge.py` et à l'écran 7 ; `forges.parse_repository` ne garde que `owner/nom` (deux segments) : y prendre le chemin complet d'un projet GitLab (sous-groupes) ; `Repositories._accounts` ne prend que les forges `available`.
- [x] Depuis E18 : les MR passent par la même mécanique (`update.forge.deliver`, `web/proposals.py`, écran 8) : il faut à GitLab `clone`, `branch` (ses commits propres : `repository/compare`), `push_branch` (`forges.git.push`, nom `oauth2`, bail `expected`), `find_open_request` et `open_or_update_request` (MR ouverte depuis `forceupdate/dependencies` vers la branche par défaut), `Identity.email` (adresse `noreply` de GitLab), et une adresse git par forge (`GIT_URL` est propre à `forges.github`). Le front dit déjà « MR » et `!12` pour GitLab (`lib/proposals.ts`) ; la barre de sélection de l'écran 7 ne prépare qu'une forge à la fois (`propose`, `RepositoriesPage.tsx`) : « Préparer N PR et M MR » = un récapitulatif par forge, ou un récapitulatif à plusieurs forges (`ProposalRequest.forge`). Simuler GitLab avec des dépôts « bare » comme `fake_forge.py`.

- [x] Ajoutés en route : le renouvellement des tokens d'OAuth de GitLab (2 h, refresh token à usage unique), un compte par forge **et par hôte** dans l'API (`?host=`), les lots et les récapitulatifs à plusieurs comptes (`RepositoryKey`), `OAuthFlow` (l'OAuth de chaque forge derrière la même interface), l'arbre d'un commit recalculé (`gitlab.tree_id`), les tailles inconnues dans l'arborescence, le nom accessible d'un dépôt qui en double un autre, le GitLab simulé `tests/fake_gitlab.py` (voir les notes).

**Fini quand** : sur un projet de test gitlab.com, depuis l'interface : connexion,
analyse, MR ouverte, puis mise à jour de la même MR.

**Notes** (session 19) :

- **Commit d'abord** : E18 commitée seule (`849e013`), avec l'accord de l'utilisateur. **Décision n°22 confirmée** par l'utilisateur (la branche remplacée à chaque envoi, jamais par-dessus le commit d'un autre), pour les MR aussi. Dépôt de test GitHub `Pauzzle-ozz/forceupdate-demo` et sa PR #1 : **gardés pour la recette (E31)**. Projet de test GitLab : créé exprès pour l'utilisateur (par l'API, le token lu dans le trousseau), `Pauzzle-ozz/forceupdate-demo` sur gitlab.com, privé, copie de `tests/projects/vulnerable` + un README qui dit de le supprimer après l'essai ; gardé aussi pour E31.
- **L'application OAuth** : enregistrée par l'utilisateur, guidé (avatar → « Edit profile » → « Access » → « Applications ») : « forceupdate », retour `http://127.0.0.1/oauth/gitlab/callback`, **non confidentielle**, portée `api`. Application ID dans `forges/gitlab.py` (`CLIENT_ID` ; `FORCEUPDATE_GITLAB_CLIENT_ID` le remplace). Le port quelconque sur 127.0.0.1 : accepté (Doorkeeper, que GitLab utilise, ignore le port d'une adresse de bouclage, RFC 8252 §7.3 ; vérifié en vrai).
- **Organisation** :
  - `forges/base.py` : `Grant` (token, refresh token, expiration), `Renew` (ce qui rend un token à jour), `OAuthFlow` (l'OAuth d'une forge : `authorization_url`, `exchange_code`, `refresh`, `revoke`, `redirect_uri`…), `new_verifier` et `challenge_of` (sortis de `github.py`) ; `TreeEntry.size` peut être `None` ;
  - `forges/gitlab.py` : `GitLab` (API v4 sur `https://{hôte}/api/v4`, `request` qui renouvelle une fois un token refusé, `paginate` par `Link` avec une limite de pages, `whoami` et ses portées, `list_repos`, `repository`, `tree`, `read_file`, `clone`, `branch`, `push_branch`, `find_open_request`, `open_or_update_request`), `OAuthApp` (PKCE sans secret, `refresh`, `revoke`), `tree_id`, `access_of`, `warnings_of`, `label`, `token_settings_url`, `GIT_URL` (les tests), `MAX_TREE_PAGES` ; `github.OAuthApp` devient une `OAuthFlow` ;
  - `forges/__init__.py` : GitLab `available`, `ForgeInfo.self_hosted` et `request` (« PR », « MR »), `label(forge, hôte)`, `client(…, host=, renew=)`, `parse_repository(…, instances=)` rend un `RepositoryName` (forge, hôte, chemin complet d'un projet GitLab, jusqu'à `/-/`) ;
  - `forges/accounts.py` : le trousseau garde un `Grant` en JSON quand le token expire ; `Accounts.grant`, `renewed`, `renewing` (verrou par compte) ; `renewer` ; `connect(…, host=)`, `verify(…, renew=)` ; comptes triés service en ligne d'abord ;
  - `web/connections.py` : `Connections.apps` (une `OAuthFlow` par forge), `web_flow`, `renew(account)` ; `web/routes/accounts.py` : `methods` par forge, `?host=` sur `verify` et `DELETE`, `url` d'une instance sur `token` (`_instance`), la révocation par l'application de la forge ; `web/routes/oauth.py` : `/oauth/gitlab/callback` (même handler) ;
  - `web/schemas.py` : `RepositoryKey`, `BatchRequest.repositories` et `SendRequest.repositories` en clés, `ProposedSelection` en clé + sélection, `ProposalRequest` sans `forge` ; `ForgeStatus.self_hosted`, `request`, `instances` ; `TokenRequest.url` ; `Disconnection.host` ; `RepositoryBatch` et `Proposal` sans `forge`, `host` (ni `rate_limit` pour le lot) ;
  - `web/repositories.py` : `Batch.forges` (une par compte), `listed(forge, hôte, nom)`, `chosen(keys)`, `forge(account, http)` (token et renouvellement), `worker_forge_of`, `connected(forge, hôte)` ; `web/proposals.py` : `Proposed.account`, `create(wanted)` cherche les PR par compte, `send` groupe par compte (`_send(groups)`), un `whoami` refusé n'échoue que les dépôts de ce compte ; `update/forge.py` : « cette MR » dans la description sur GitLab ; `sources/forge.py` : `ForgeSource.small_enough`, une taille inconnue compte 1.
- **Tranché** :
  - **GitLab** : portée `api` seule (`read_api` ne permet pas d'ouvrir une MR, `write_repository` pas l'API) ; un token personnel collé pour gitlab.com aussi ; une instance auto-hébergée **par token seulement** (l'OAuth demanderait d'enregistrer forceupdate sur chaque instance), adresse `https://hôte[:port]` sans chemin (une instance sous un chemin, `https://exemple.org/gitlab`, n'est pas prise : limite) ; `can_push` = rôle Developer au moins, lu par une deuxième liste `min_access_level=30` (les rôles hérités des groupes y sont) ; `visibility` autre que `public` (dont `internal`) = privé ; `fork` = `forked_from_project` présent ; l'auteur des commits : `{id}-{login}@users.noreply.{hôte}` ;
  - **les tokens d'OAuth de GitLab expirent après 2 h** (non désactivable) : rangés avec leur refresh token et leur expiration ; renouvelés 5 min avant d'expirer ou quand GitLab refuse celui qu'on lui passe, **un seul renouvellement à la fois pour un compte** (verrou pris sans bloquer la boucle, par essais de 50 ms : la boucle du serveur et celle des analyses peuvent renouveler en même temps), celui qui attend relit le trousseau ; avant git (clone, push), le token est d'abord rendu à jour ; un refresh token refusé : `problem` sur le compte, « se reconnecter » ;
  - **l'arbre du dernier commit de la branche** (pour ne rien pousser quand le contenu est le même, décision n°22) : l'API de GitLab ne le donne pas ; il est recalculé depuis la liste de la racine du commit (`repository/tree?ref=`, non récursive), comme `git mktree` (tri des noms, un dossier comme s'il finissait par `/`, modes sans zéro de tête, SHA-1 ou SHA-256) : vérifié contre git (test), puis sur gitlab.com (relancer n'a rien poussé) ; si la réponse n'a pas la forme attendue, `None` : on pousse ;
  - **l'arborescence de GitLab** : paginée (100 par page, `pagination=keyset`), sans tailles ; au-delà de `MAX_TREE_PAGES` (100 pages) elle est tronquée et le dépôt cloné, comme pour GitHub ; les langages d'un projet GitLab sont pesés en fichiers ; un fichier de dépendances trop gros est téléchargé puis écarté à la lecture (le rapport dit la même chose qu'en local) ;
  - **plusieurs comptes** : un par forge **et par hôte** (gitlab.com, plus un par instance) ; l'API désigne un compte par `?host=` (sans lui, le service en ligne) ; les dépôts, lots, récapitulatifs et envois par `RepositoryKey` (forge, hôte, nom) ; **un lot et un récapitulatif peuvent mêler les comptes** (un seul « Préparer N PR et M MR », un seul « Analyser tous les dépôts ») ;
  - **front** : l'adresse de l'écran 8 devient `/pr?depots=forge:hôte/chemin,…` ; les mots « PR » / « MR » / « PR et MR » viennent de `lib/proposals.ts` ; la carte GitLab a ses instances ; le nom accessible d'un dépôt dit sa forge s'il en double un autre.
- **Trouvé** :
  - en vrai, **gitlab.com répond 400** (« This endpoint requires token type to be a personal access token ») sur `/personal_access_tokens/self` pour un token d'OAuth : la première connexion a échoué là ; corrigé (toute erreur fait passer à `/oauth/token/info`), et le GitLab simulé répond de même ;
  - les MR sont sous `/projects/:id/merge_requests`, pas sous `/repository` (trouvé par les tests) ;
  - un même `owner/nom` sur GitHub et sur GitLab (`Pauzzle-ozz/forceupdate-demo`) donnait deux cases de même nom accessible : corrigé (`spokenName`) ;
  - gitlab.com annonce `RateLimit-Limit: 100` sur certains points d'API (par minute) : l'écran montre « 91 requêtes restantes sur 100 », d'après la dernière réponse ; le retour d'OAuth (`?connexion=`) allait à toutes les cartes : chacune ne suit plus que les siennes ;
  - Playwright : le premier « GitLab (hôte) » d'une ligne est celui caché au-delà de 1024 px ; « MR !1 mise à jour : … » a deux espaces insécables (`\s` avant `!` et autour de `:`).
- **Tests** : `tests/fake_gitlab.py` (`FakeGitLab` : gitlab.com ou une instance, `/user`, portées d'un token personnel ou d'OAuth, projets paginés et `min_access_level`, un projet par chemin encodé, commits, arborescence paginée sans tailles, racine d'un commit lue dans le dépôt « bare », fichiers bruts, branches, `compare`, MR et leur 409, OAuth : code lié au `code_challenge`, refresh token à usage unique, révocation) ; `test_forges_gitlab.py` (compte et portées, instance, token refusé puis renouvelé, projets et drapeaux, sous-groupes, arborescence paginée et tronquée, fichiers, messages d'erreur, `tree_id` contre git, clone, branche, push avec bail, MR ouverte puis mise à jour, ouverte entre-temps, jamais sur la branche par défaut, git sans le token, OAuth sans secret, refresh, révocation) ; `test_forges_accounts.py` (un compte par hôte, `Grant` en JSON, un seul renouvellement pour trois demandes, token refusé renouvelé sauf si un autre l'a fait, refresh refusé) ; `test_web_gitlab.py` (OAuth par l'API et le retour, renouvellement à `verify`, révocation, instance, adresses refusées, pas de device flow, liste des trois comptes, **un lot et un récapitulatif GitHub + GitLab : PR et MR ouvertes, puis la même MR relancée sans rien pousser**, projet public par son adresse `/-/tree/main`, schéma) ; `test_sources_forge.py` (**chacun des 14 mini-projets lu par l'API de GitLab donne le même inventaire qu'en local**, langages comptés à part ; fichier trop gros) ; `test_forges_repos.py` (chemins GitLab, instances connectées) ; mises à jour des tests existants pour l'API à clés. 2068 tests Python verts (plus 9 réseau), ruff propre ; 134 Vitest (7 de plus : carte GitLab et instances, retour d'OAuth propre à sa carte, écran 7 à deux forges, récapitulatif et résultat PR + MR, même nom sur deux forges) ; 43 Playwright (6 de plus : OAuth GitLab, instance refusée en http puis acceptée, déconnexion ; projets des deux forges, MR ouverte puis relancée ; axe-core sur les écrans 6, 7 et 8 avec GitLab en clair et en sombre à 1440 et 375 px), sans erreur de console. Le serveur de test sert gitlab.com et une instance (`tests/e2e_server.py`).
- **Vérifié avec le vrai compte** (`forceupdate ui`, vrais npm et uv, piloté par Playwright pour l'analyse et les envois) : connexion par OAuth à gitlab.com par l'utilisateur (le premier essai a trouvé le 400 ci-dessus, corrigé, puis connecté : `Pauzzle-ozz`, « Lecture et MR », portée `api`), GitHub toujours connecté ; projet `Pauzzle-ozz/forceupdate-demo` analysé par l'API de GitLab (28 failles, 30 constats à mettre à jour, 7 requêtes) ; « Préparer la MR », « Envoyer la MR » : **MR !1 ouverte**, un commit de `Pauzzle-ozz <43887964-Pauzzle-ozz@users.noreply.gitlab.com>`, les quatre mêmes fichiers qu'à E18 (`package-lock.json` +4 −4, `package.json` +1 −1, `requirements.in` +1 −1, `requirements.txt` +3 −3), `main` intact, description de 8 988 caractères ; relancer depuis le rapport : « MR !1 mise à jour : elle avait déjà ces changements, rien n'est poussé » (branche inchangée : l'arbre recalculé est le bon) ; `main` avancé (README), relancer : branche refaite sur le nouveau `main`, poussée avec le bail, **toujours la MR !1**. git n'a rien laissé dans le gestionnaire d'identification de Windows pour gitlab.com (seule l'entrée `forceupdate` du trousseau). Captures des écrans 6, 7 et du rapport en clair et en sombre, à 1440 et 375 px, et de l'écran 8, sans erreur de console ni défilement horizontal.
- **Limites** : une instance GitLab sous un chemin (`https://exemple.org/gitlab`) n'est pas prise ; pas d'OAuth sur une instance (token seulement) ; un token personnel de GitLab qui expire n'est pas renouvelé (son échéance est dite dans les droits) ; les langages d'un projet GitLab sont pesés en fichiers ; les requêtes restantes de GitLab sont celles de la dernière réponse, par minute et parfois par point d'API ; `forked_from_project` n'apparaît pas toujours (fork d'un projet invisible) ; les limites de E18 restent (un envoi ne s'annule pas…).

### E20 — Bitbucket Cloud

**But** : la même chose, pour Bitbucket Cloud.

- [x] Prérequis, à faire par l'utilisateur (la session le guide) : créer un « OAuth consumer » Bitbucket, avec un retour vers `127.0.0.1`.
- [x] Connexion : OAuth ; en repli, un token d'API Atlassian (les « app passwords » sont en fin de vie : à vérifier).
- [x] `forges/bitbucket.py` :
  - workspaces et dépôts (`role=member`) ;
  - fichiers (`/src/{commit}/{chemin}`) ;
  - clone (`x-token-auth:<token>`) ;
  - pull requests : création, mise à jour, idempotence.
- [x] Bitbucket ne donne pas l'arborescence complète en un appel : parcours dossier par dossier avec `max_depth`, ou clone superficiel pour un gros dépôt. Il ne donne qu'un langage par dépôt : on utilise le détecteur de E02 sur l'arborescence.
- [x] Bitbucket Data Center (auto-hébergé) : hors V1, écrit dans la doc.
- [x] Depuis E16 : comme pour GitLab (E19) : `available=True` dans `forges.FORGES`, `forges.client`, l'adresse de retour dans `RETURN_PATHS` et son test, `methods` et révocation par la forge ; carte « Bientôt » déjà là.

- [x] Depuis E18 : comme GitLab (E19) : `clone`, `branch`, `push_branch` (nom `x-token-auth`), PR trouvée, ouverte et mise à jour, l'adresse `noreply` s'il y en a une, l'adresse git de la forge.
- [x] Depuis E19 :
  - l'OAuth d'une forge passe par `base.OAuthFlow` (comme `github.OAuthApp` et `gitlab.OAuthApp`) : `Connections.apps[ForgeKind.BITBUCKET]`, l'adresse de retour dans `routes/oauth.py` (un handler par forge, même `_callback`), `routes/accounts.py` (`SCOPES`, `TOKEN_URLS`, `APPLICATIONS_URLS`, `_methods`) ; un consumer Bitbucket a un secret (il n'est pas « public ») : le garder comme celui de GitHub ;
  - **les tokens d'OAuth de Bitbucket Cloud expirent aussi** (2 h, refresh token) : `OAuthFlow.refresh`, et `Connections.renew` le prend déjà pour tout compte connecté par OAuth (`accounts.renewer`, un seul renouvellement à la fois) ; `forges.client(…, renew=)` à brancher pour Bitbucket ;
  - un compte se désigne par forge et hôte (`?host=`), les lots et récapitulatifs par `RepositoryKey` et peuvent mêler les forges : rien à changer pour un troisième ; « PR » vient de `ForgeInfo.request` et de `lib/proposals.ts` (`requestWord`, `#41` déjà) ;
  - l'arbre d'un commit pour ne rien pousser à contenu égal : si l'API de Bitbucket ne le donne pas, le recalculer comme `gitlab.tree_id` (le sortir dans `forges/base.py` ou `git.py`) ; une arborescence sans tailles : `TreeEntry.size = None` est déjà pris ;
  - simuler Bitbucket comme `tests/fake_gitlab.py` (dépôts « bare », PR, OAuth et refresh) ; e2e : `tests/e2e_server.py` sert déjà GitHub, gitlab.com et une instance, la fausse page d'autorisation distingue les forges par son chemin.

- [x] Ajoutés en route : les secrets longs découpés dans le trousseau (`accounts.MAX_PART`), le corps en formulaire du client HTTP (`form=`), le statut HTTP d'une `NetworkError`, `Forge.branch_tree` et `git.remote_tree` (l'arbre de la branche lu par git), `OAuthFlow.revocable`, `ForgeStatus.token_scopes`, `revocable` et `applications_url`, `detect.languages.known_name`, le Bitbucket simulé `tests/fake_bitbucket.py` (voir les notes).

**Fini quand** : sur un dépôt de test Bitbucket, depuis l'interface : connexion,
analyse, PR ouverte, puis mise à jour de la même PR.

**Notes** (session 20) :

- **Commit d'abord** : E19 commitée seule (`E19 : GitLab`), avec l'accord de l'utilisateur. Il n'avait pas de compte Bitbucket : guidé pour le créer (compte Atlassian, workspace `pauzzle`). Dépôt de test : créé par l'utilisateur à la main (le token n'a pas `repository:admin`), `pauzzle/forceupdate-demo`, privé ; Bitbucket y a mis un `.gitignore` (option cochée d'office à la création) ; rempli ensuite d'une copie de `tests/projects/vulnerable` + un README qui dit de le supprimer après la recette, par un commit poussé sur `main` avec le token du compte (credential helper de `forges.git`, bail sur le commit vu). **Gardé pour la recette (E31)**, comme ceux de GitHub et de GitLab.
- **L'application** : le formulaire d'Atlassian a changé (**« OAuth clients »**, plus « OAuth consumers ») : Workspace settings → Apps and features → OAuth clients → « Create OAuth client », trois onglets : Details (nom `forceupdate`, description, « Learn more URL » vers le dépôt GitHub), Authorization (« Authorization code » et « Refresh token » cochés, « Client credentials » **pas** coché : avec le secret embarqué, il donnerait un accès sans la personne), Scopes (Account : Email, Read ; Repositories : Read, Write ; Pull requests : Read, Write). Client id et secret dans `forges/bitbucket.py` (`CLIENT_ID`, `CLIENT_SECRET` ; `FORCEUPDATE_BITBUCKET_CLIENT_ID` et `…_SECRET` les remplacent), publics de fait comme ceux de GitHub : Bitbucket n'a **ni PKCE ni client sans secret** (PKCE accepté, pas vérifié ; envoyé quand même). L'adresse de retour `http://127.0.0.1/oauth/bitbucket/callback` : **un port quelconque est accepté** (vérifié en vrai, port 52730).
- **Recherche faite d'abord** (changelog d'Atlassian, spec OpenAPI à jour, fils de la communauté), puis **vérifiée en vrai** : voir le brief, « Bitbucket, constaté à E20 ». Deux écarts entre la recherche et la vraie forge : l'ancienne liste de tous les dépôts répond **404** (« There is no API hosted at this URL »), pas 410 ; `/user/workspaces?sort=workspace.slug` répond **400** (« Invalid field name ») : le premier `list_repos` l'aurait échoué en vrai, corrigé et simulé.
- **Organisation** :
  - `forges/bitbucket.py` : `Bitbucket` (API 2.0 sur `https://api.bitbucket.org/2.0`, `request` qui renouvelle une fois un token refusé et ne suit jamais une adresse hors de l'API, `paginate` par `next` avec une limite de pages, `whoami` (portées par `X-OAuth-Scopes`, adresse par `/user/emails`), `list_repos` (`/user/workspaces`, puis `/repositories/{ws}?role=member`, droits par `…/permission` et `…/permissions/repositories`), `repository`, `tree` (`src/{commit}/?max_depth=12`), `read_file`, `clone`, `branch` (`refs/branches`, puis `commits?include=&exclude=`), `branch_tree`, `push_branch`, `find_open_request`, `open_or_update_request`), `OAuthApp` (Basic + formulaire, `refresh`, pas de `revoke`), `access_of`, `warnings_of`, `GIT_URL` (les tests), `MAX_TREE_DEPTH`, `MAX_TREE_PAGES` ;
  - `forges/base.py` : `Forge.branch_tree` (par défaut `Branch.tree`), `OAuthFlow.revocable` ; `forges/git.py` : `remote_tree` (`fetch --depth 1` de la branche dans le clone, puis `FETCH_HEAD^{tree}`) ; `update/forge.py` : `deliver` passe par `branch_tree` ;
  - `forges/accounts.py` : `MAX_PART`, `_read_secret`, `_write_secret`, `_delete_secret` (morceaux `<forge>:<hôte>#1`, `#2`…, l'entrée du compte disant `forceupdate-parts:N`, sous le verrou) ;
  - `net/http.py` : `request(…, form=)` (corps en formulaire), `NetworkError.status` ;
  - `forges/__init__.py` : Bitbucket `available`, `client` le rend, `parse_repository` accepte un workspace à `_` ; `web/connections.py`, `web/routes/accounts.py` (`TOKEN_SCOPES`, `revocable`, `applications_url`, le message d'une déconnexion sans révocation), `web/routes/oauth.py` (`/oauth/bitbucket/callback`) ; `web/schemas.py` : `ForgeStatus.token_scopes`, `revocable`, `applications_url` ; `detect/languages.py` : `known_name`.
- **Tranché** :
  - **Bitbucket n'a pas d'adresse `noreply`** : l'auteur des commits est l'adresse principale et confirmée du compte (c'est par elle que Bitbucket rattache un commit au compte : vérifié, « Dumiot paul » sur la PR). Sans elle (token sans `account` ni `email`), un avertissement le dit et `deliver` garde son repli ;
  - **le token d'OAuth fait plus de 2 000 caractères** (2 775 en vrai) : le Gestionnaire d'identification de Windows refuse au-delà de 1 280 caractères (2 560 octets en UTF-16, erreur 1783 : vérifié par une entrée d'essai effacée aussitôt). Un secret de plus de `MAX_PART` (1 000) caractères est rangé en morceaux ; le trousseau simulé des tests refuse désormais, comme Windows, un secret de plus de 1 280 caractères ;
  - **l'arbre de la branche** (ne rien pousser à contenu égal, décision n°22) : l'API ne donne ni l'arbre d'un commit ni les identifiants des fichiers, impossible à recalculer comme sur GitLab ; il est lu par git (`Forge.branch_tree` → `git.remote_tree` : un `fetch` superficiel de la branche dans le clone). Si git n'y arrive pas (sauf token refusé), on pousse : le bail protège la branche ;
  - **les dépôts** : workspace par workspace (Bitbucket a retiré la liste de tous les dépôts d'un compte en avril 2026) ; `can_push` : administrateur du workspace (`permission` vaut `owner`, vérifié), ou `write`/`admin` sur le dépôt ; `archived` toujours faux (Bitbucket Cloud n'en a pas) ; `language` mis à la forme du détecteur (`python` → `Python`) ; un dépôt vide : `mainbranch` absent, ou sa branche introuvable ;
  - **l'arborescence** : `src/{commit}/?max_depth=12`, en largeur, 100 par page, 100 pages au plus, avec les tailles ; un dossier au 12e niveau (pas parcouru), plus de 100 pages, ou un 555 de Bitbucket (trop lent, demandé sans reprise) : tronquée, le dépôt est cloné ;
  - **les PR** : trouvées par BBQL (`source.branch.name`, `destination.branch.name`, `state=OPEN`), du dépôt même ; mises à jour par `PUT` avec leurs relecteurs relus d'abord (un `PUT` sans eux pourrait les effacer) ; une création refusée (sauf 401, 403, 404, 429) fait chercher la PR de nouveau ; la description, 8 984 caractères en vrai, passe ;
  - **git** : `x-token-auth` pour un token d'OAuth, `x-bitbucket-api-token-auth` pour un token d'API Atlassian (`ATAT…`) ; le token rendu à jour avant git ;
  - **la connexion** : OAuth (action principale) et le token d'API Atlassian collé (`Bearer`, ses six portées dans l'aide, « Créer un token sur id.atlassian.com ») ; ses droits « non vérifiés » (Bitbucket ne dit pas les portées d'un token d'API). **Pas de révocation** par l'API : se déconnecter efface le token, `revoked` vaut `false`, la confirmation ne promet rien, et l'écran donne le lien « Retirer l'accès sur bitbucket.org » ;
  - **pas de requêtes restantes** : Bitbucket ne les dit pas (1 000 par heure sur les dépôts) ; l'écran 7 n'en montre pas pour lui.
- **Trouvé** :
  - en vrai : `X-OAuth-Scopes` n'écrit que les portées « du dessus » (`account, pullrequest:write`) : `account` comprend `email`, `pullrequest:write` comprend `repository:write` ; l'avertissement « sans la portée email » qui s'en déduisait était faux (l'adresse se lisait) : il se fonde maintenant sur la lecture de l'adresse ; `X-Credential-Type: oauth2_legacy` ; la permission d'un workspace administré vaut `owner` ; les deux écarts à la recherche ci-dessus ;
  - Git Bash réécrit un argument qui commence par `/` en chemin Windows (`/user/…` → `C:/Program Files/Git/user/…`) : `MSYS_NO_PATHCONV=1` pour un script qui prend des chemins d'API ;
  - un heredoc a encore abîmé un `\n` (CLAUDE.md le dit) : les scripts passent par l'outil d'écriture.
- **Tests** : `tests/fake_bitbucket.py` (`FakeBitbucket` : `/user` et `X-OAuth-Scopes` comme le vrai, `/user/emails`, workspaces et droits, dépôts paginés par `next`, un dépôt, branches, commits propres lus dans le dépôt « bare », arborescence en largeur avec tailles, liens et sous-modules, 555, fichiers bruts, PR filtrées par BBQL, création, lecture, `PUT` qui garde les relecteurs, OAuth : `Basic` et formulaire, code lié à l'adresse de retour, refresh token renouvelé, l'ancien refusé en 403, tokens de plus de 2 000 caractères, `sort` refusé sur `/user/workspaces`) ; `test_forges_bitbucket.py` (21 : compte, token d'API, droits, renouvellement, dépôts workspace par workspace et administrateur, dépôt public, arborescence tronquée trop profonde, trop longue ou trop lente, fichiers, messages, adresse hors de l'API refusée, clone, branche et son arbre lu par git, PR ouverte puis mise à jour avec ses relecteurs, bail, branche par défaut, lecture seule, PR ouverte entre-temps, git sans le token et ses deux noms, OAuth) ; `test_web_bitbucket.py` (7 : OAuth par l'API et le retour, token en morceaux, renouvellement, déconnexion sans révocation, token d'API, **un lot et un récapitulatif GitHub + Bitbucket : deux PR ouvertes, puis la même PR de Bitbucket relancée sans rien pousser**, dépôt public par son adresse, schéma) ; `test_sources_forge.py` (**les 13 mini-projets lus par l'API de Bitbucket donnent le même inventaire qu'en local**, tailles comprises) ; `test_forges_accounts.py` (un secret en morceaux, renouvelé plus court puis effacé ; un morceau manquant) ; `test_net_http.py` (corps en formulaire) ; mises à jour des tests qui disaient Bitbucket « pas encore disponible ». 2114 tests Python verts (plus 9 réseau), ruff propre ; 138 Vitest (4 de plus : aide du token d’API, déconnexion sans révocation, écrans 7 et 8 avec Bitbucket ; la carte Bitbucket dans le test sans compte) ; 49 Playwright (6 de plus : OAuth Bitbucket, déconnexion et son lien, token d'API ; dépôts des deux forges, PR ouverte puis relancée sans rien pousser ; axe-core sur les écrans 6, 7 et 8 avec Bitbucket en clair et en sombre à 1440 et 375 px), sans erreur de console. Le serveur de test sert Bitbucket (`tests/e2e_server.py`).
- **Vérifié avec le vrai compte** (`forceupdate ui`, vrais npm et uv) : connexion par OAuth par l'utilisateur (« Se connecter avec Bitbucket », autorisation, retour : `pauzzle-admin`, « Lecture et PR »), GitHub et GitLab toujours connectés ; token de 2 775 caractères en 5 morceaux dans le trousseau, relu ; `pauzzle/forceupdate-demo` analysé par l'API (28 failles, 7 requêtes) ; « Préparer la PR », « Envoyer la PR » par l'utilisateur : **PR #1 ouverte**, un commit au nom de l'utilisateur (rattaché à son compte), marqué `Generated-by`, les quatre mêmes fichiers qu'à E18 et E19 (`package-lock.json` +4 −4, `package.json` +1 −1, `requirements.in` +1 −1, `requirements.txt` +3 −3), `main` intact, description de 8 984 caractères ; relancée depuis le rapport : même PR, **rien poussé** (l'arbre lu par git ; la PR mise à jour à 21 h 44, la branche toujours de 21 h 42) ; `main` avancé (README), relancée par l'API du serveur : branche refaite sur le nouveau `main` (un commit) et poussée avec le bail, **toujours la PR #1**. Captures des écrans 6, 7, 4 (rapport du dépôt) et 8 en clair et en sombre, à 1440 et 375 px, sans erreur de console ni défilement horizontal.
- **Limites** : pas de révocation par l'API (la personne retire l'accès dans ses réglages) ; un refresh token inutilisé pendant 3 mois expire (se reconnecter) ; Bitbucket Data Center : hors V1 ; les droits d'un token d'API Atlassian ne se vérifient pas ; un dépôt où le compte écrit par un groupe sans droit explicite ni administration du workspace : vu en lecture seule (cas non vérifié) ; plus de 30 commits propres sur la branche : `ahead` est un minimum ; une arborescence de plus de 12 niveaux ou 10 000 entrées est clonée ; les requêtes restantes ne se savent pas ; les « access tokens » de dépôt ou de workspace (Premium) ne sont pas pris ; selon un fil de la communauté, l'écran de consentement de Bitbucket reviendrait à chaque autorisation (non constaté).

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

Depuis E21 (voir ses notes) : une plage reprise d'un autre fichier se réécrit par un
`EditKind.CATALOG`, que `writers.catalog_target` situe d'après le manifeste (pnpm, Cargo : y
ajouter le catalogue Gradle) ; l'épinglage `=V` le temps d'un passage (`_Context.run_pinned`)
vaut pour tout outil qui ignore la version visée quand la contrainte a changé ; un outil reçoit
son environnement par `_Context.env` ; `transitives(…, order=)` si le lockfile fige les
dépendances de build. Les tests qui disaient un écosystème « pas encore géré » prennent le
suivant (Go à E21, Packagist à E22) : les déplacer encore.

Depuis E22 (voir ses notes) : une `VersionScheme` a trois points d'extension, inertes par
défaut : `written` (la version telle que l'écrit le manifeste : Go remet le `v` des avis d'OSV),
`unlisted` (une version que le registre ne liste jamais : une pseudo-version Go n'est pas
« inconnue du registre ») et `moved` (une version publiée sous un autre nom : une majeure Go,
proposée à la main) ; un `Registry` a `not_found_statuses` et `_complete` (d'autres requêtes avant
le cache) ; `Dependency.excluded` (versions jamais proposées) ; une indirecte écrite dans un
manifeste (`file` différent de `lockfile`) s'y réécrit ; `lockfiles._versions_path` dit où relire
les versions après la régénération quand ce n'est pas le lockfile.

Depuis E23 (voir ses notes) : `Dependency.excluded` tient des contraintes (une version de `exclude`
pour Go, une contrainte de `conflict` pour Composer) : `checks.base.is_excluded` les lit, pour le
constat « plus récente », la version permise et le planificateur. Les tests qui disaient un
écosystème « pas encore géré » prennent RubyGems : à E24, les passer à Maven.

Depuis E24 (voir ses notes) : une contrainte peut s'écrire autrement qu'elle ne se lit
(`update.writers._WRITTEN` : Ruby, une chaîne par contrainte, jointes par `, `) ;
`_Context.run_pinned(…, appended=)` ajoute du texte à la fin d'un fichier le temps d'un passage
(une ligne `gem "x", "= V"` pour épingler une indirecte) ; `detect.manifests.WORKSPACE_ROOTS`
rattache un membre au lockfile d'un parent dont le manifeste n'est pas le sien (une gem `path:`,
un `.gemspec` sous un `Gemfile`) ; `tests/fake_bundler.py` sert un faux outil à deux fichiers de
tests. Les tests qui disaient un écosystème « pas encore géré » prennent Maven : à E25, les
passer à NuGet.

Depuis E25 (voir ses notes) : une version peut être écrite une fois pour plusieurs dépendances
(une propriété Maven, une entrée `[versions]` du catalogue Gradle) : chacune a cet emplacement,
et `Dependency.file` est le fichier où la version est écrite (le `pom.xml` parent d'un module) ;
la réécriture n'a lieu qu'une fois et le planificateur le dit (`_shared_warnings`). Sans
lockfile, une version exacte qui est celle de l'outil va dans `Dependency.installed`.
`VersionScheme.compatible` écarte une autre variante d'une version (`-jre` / `-android`).
`parsers/xml_spans.py` lit un XML avec la position du texte (pour les `.csproj`).
`writers._reader` reconnaît un fichier par son nom quand ce n'est pas un manifeste
(`gradle.properties`). Les tests qui disaient un écosystème « pas encore géré » prennent NuGet :
à E26, il n'en reste plus (voir E26).

Depuis E26 (voir ses notes) : les huit écosystèmes sont gérés ; les tests du chemin « pas encore
géré » retirent NuGet des tables le temps du test. Une `VersionScheme` a trois points d'extension
de plus, inertes ailleurs : `lowest` (le gestionnaire prend la plus basse version qui convient :
une indirecte ne monte pas en régénérant), `reaches` (il prend la version sans réécriture : le
planificateur s'en sert à la place de `satisfies`) et `chosen` (sa version « permise »).
`parsers/xml_spans.py` situe aussi la valeur des attributs (`Element.attribute_locations`).
`lockfiles._readers` régénère le lockfile d'un autre projet qui lit une version réécrite (une
version centrale NuGet) ; `lockfiles._manifests_of` compte, pour NuGet, les fichiers où ses
versions sont écrites. Les réponses d'un registre à plusieurs fichiers par paquet (le proxy Go,
NuGet) s'enregistrent par `record.py` (`record_several`), compressées pour NuGet (`.json.gz`).

**Fini quand**, pour chaque étape : sur un mini-projet de l'écosystème, l'analyse
et la mise à jour donnent un résultat juste, dans l'interface et en ligne de
commande. Si l'outil natif n'est pas installé sur la machine, la régénération du
lockfile est testée avec une commande simulée, et c'est noté.

### E21 — Rust (crates.io)

- [x] Reprendre `parse_cargo_toml`, `parse_cargo_lock` et leurs tests. Corriger :
  - `workspace = true` : version lue dans `[workspace.dependencies]` à la racine ;
  - `[target.'…'.dependencies]` ;
  - dépendances renommées (`package = "…"`) ;
  - `git` / `path` : non vérifiables ;
  - membres de workspace : E02 rattache le `Cargo.lock` du parent le plus proche ; vérifier `[workspace] members` / `exclude`.
- [x] Versions Cargo : `1.2` veut dire `^1.2` ; `=`, `~`, `*`.
- [x] Registre : l'index « sparse » (`index.crates.io`) plutôt que l'API (1 requête par seconde). Il donne `yanked`.
- [x] Réécriture de `Cargo.toml` ; lockfile : `cargo update -p <nom> --precise <version>` (voir les notes : épinglage `=V` pour une directe, `--precise` pour une indirecte).
- [x] Ajoutés en route : failles (OSV `crates.io`, versions corrigées d'avis RUSTSEC), styles de contrainte Cargo (`update/constraints.py`), mini-projets `cargo` et `cargo-workspace` aux `Cargo.lock` faits par cargo, réponses enregistrées de l'index (`tests/fixtures/crates/`), libellés du rapport et de l'écran 5 pour une contrainte reprise du workspace, et le récapitulatif de l'écran 5 qui citait le manifeste d'un catalogue au lieu du fichier réécrit (pnpm compris, depuis E15).

**Notes** (session 21) :

- **Commit d'abord** : E20 commitée seule (`E20 : Bitbucket Cloud`), avec l'accord de l'utilisateur. **cargo installé** avec son accord (rustup 1.29.1 par winget, toolchain `stable-x86_64-pc-windows-msvc`, cargo 1.99.1), dans `~/.cargo/bin`, hors du `PATH` des outils de la session (voir CLAUDE.md).
- **Vérifié contre le vrai cargo**, avant d'écrire :
  - **une quarantaine de contraintes** de `rand` passées à `cargo generate-lockfile` : la version choisie est la plus haute non retirée qui respecte la contrainte, pré-versions comprises quand un comparateur en nomme une du même `x.y.z` (`>=0.9.0-beta.0, <0.9.0` → `0.9.0-beta.3`) ; refusées : vide, `~>0.8`, `0.8 0.9`, `v0.8`, `>=*`, `0.08`, `0.*.3`, `0.8,`, `||`, une étiquette ; acceptées : `^0.1.*`, `0.8.5+build`, les espaces autour des opérateurs et des virgules. C'est le comportement du crate `semver` (`VersionReq`), réécrit dans `versions/cargo.py` ; le tableau relevé est un test (`CARGO_CHOICES`, sur l'index enregistré de `rand`) ;
  - **`cargo update -p x@V --precise W` ignore `--precise`** quand la contrainte du manifeste n'accepte plus la version figée (manifeste réécrit en `1.0.200`, serde figée en 1.0.150 : cargo prend 1.0.229, pas 1.0.210 ; c'est la condition `req.matches(current)` du registre de Cargo). D'où : une directe est épinglée (`=V` à la place de la contrainte) le temps d'un `cargo update --workspace`, puis la contrainte est remise et `cargo update --workspace` relancé, qui garde la version (vérifié : 1.0.210 obtenue, rien d'autre ne bouge) ; une indirecte : `cargo update -p x@actuelle --precise V` (vérifié) ;
  - **`build.rs` ne tourne pas** à `cargo update` (un `build.rs` qui écrit un fichier puis panique : rien) ; **mais `rustc` peut être lancé** : avec le résolveur 3 (édition 2024) sans `rust-version`, cargo lance `rustc -vV` pour connaître sa version, donc le `build.rustc` ou le `rustc-wrapper` d'un `.cargo/config.toml` du projet. `RUSTC` (le `rustc` installé) et `RUSTC_WRAPPER` / `RUSTC_WORKSPACE_WRAPPER` vides les écartent (vérifié) ;
  - **rustup lit le `rust-toolchain.toml` du projet** : un `path` vers un dossier du projet est lancé (« the path … has no bin/ directory » : il l'a essayé) ; un canal absent est **installé tout seul** (Rust 1.80.0 téléchargé pendant l'essai, désinstallé ensuite). `RUSTUP_TOOLCHAIN` l'empêcherait, mais changerait la version de cargo et de rustc (le résolveur 3 choisit d'après elle) : pas passé, le plan le dit (`_cargo_runs_code`, comme `yarnPath` de Yarn) ; de même pour un `.cargo/config.toml` (registres, sources, `credential-provider`) ;
  - un `Cargo.lock` au format 3 reste au format 3 ;
  - **l'index sparse** : `https://index.crates.io/config.json`, fichiers `1/a`, `2/cc`, `3/l/log`, `se/rd/serde` ; le chemin en minuscules (`Serde` : 404, une erreur S3 en XML) ; une ligne JSON par version : `name`, `vers`, `deps`, `cksum`, `features`, `yanked`, `rust_version`, et **`pubtime`**, même pour les versions de 2014 ; `Cache-Control: max-age=600` ; pas de raison de retrait ;
  - **OSV** : l'écosystème `crates.io`, avec le nom du crate ; les avis RUSTSEC et GHSA d'une même faille sont réunis (aliases) ; `introduced: 0.0.0-0` lu ; time 0.1.45 → 0.2.23 (CVE-2020-26235), regex 1.5.4 → 1.5.5 (CVE-2022-24713), smallvec 1.6.0 → 1.6.1 (CVE-2021-25900), et un avis de 2026 sans CVSS (RUSTSEC-2026-0190, anyhow < 1.0.103).
- **Organisation** :
  - `parsers/rust.py` : `parse_cargo_toml` (sections, plateformes, formes en `_`, `[project]`, chaîne, table en ligne, `[dependencies.x]`, `package =`, `optional`, `git`, `path`, `registry`, `registry-index`, emplacement exact par `toml_spans`), `parse_workspace` (`CargoWorkspace` : `members`, `exclude`, `[workspace.dependencies]`, `[workspace.package] version`), `read_workspace_root` (le plus proche `Cargo.toml` à `[workspace]` en remontant), `parse_cargo_lock` (`CargoLockfile`, formats 1 à 4, `[root]`, nœuds `nom version`, sources), `parse_project` ; `WORKSPACE_CONSTRAINT`, `SCOPES` ;
  - `parsers/lockfiles.py` : `transitives(…, order=)` et `reachable_scopes(…, order=)` ; `versions/cargo.py` (`CARGO`, `CargoRequirement`) ; `registries/crates.py` (`Crates`, `index_path`) ; `checks/base.py` : « la plage de « workspace = true » est introuvable » ;
  - `update/constraints.py` : opérateurs et séparateur du plancher par écosystème, une version sans opérateur est un `^` pour Cargo, `=1.2` un joker ; `update/writers/rust.py` (`read_cargo_toml`, `workspace_target`), `writers.catalog_target` (pnpm ou Cargo d'après le manifeste, aussi pour l'épinglage) ; `update/lockfiles.py` : `LockKind.CARGO`, `_Cargo`, `_cargo_spec`, `_cargo_locks`, `_cargo_environment`, `_cargo_runs_code`, `_Context.env` ;
  - `report/__init__.py` : « [workspace.dependencies] (racine du workspace) » ; front : `lib/update.ts` (`isCargoManifest`, `editTarget`, « (workspace Cargo) »), `screens/report/cells.tsx` (« (workspace) ») ; `openapi.json` et `schema.d.ts` (`LockKind` : `cargo`).
- **Tranché** :
  - **`workspace = true`** : la contrainte telle qu'écrite est `workspace = true`, celle de la racine va dans `resolved_constraint`, et la réécriture est un `EditKind.CATALOG` (pas de nouveau genre : même mécanique que `catalog:` de pnpm, retrouvée à l'écriture par `writers.catalog_target`). Un `package`, `git`, `path` ou `registry` de la racine vaut pour la dépendance ;
  - **membre d'un workspace** (le `Cargo.lock` de la racine lui est gardé) : la racine elle-même, un dossier de `members` (motifs), ou un crate que le lockfile connaît comme local (une dépendance `path` d'un membre en est un d'office, comme pour Cargo) ; `exclude` est un préfixe de chemin et l'emporte. Sans `[workspace]` à la racine, un crate plus bas n'est pas membre (Cargo lui ferait son propre lockfile). `workspace = true` est résolu dès qu'une racine non exclue est au-dessus ;
  - **la version installée d'une directe** : parmi ce que requiert le crate du projet dans le lockfile (le graphe du `Cargo.lock`), celle de ce nom, qui respecte la contrainte s'il y en a deux (`rand` 0.8 et `rand09 = { package = "rand" }` 0.9) ; une source git ou d'un autre registre dans le lockfile (un `[patch]`) rend la directe non vérifiable ;
  - **les scopes** : le `Cargo.lock` mêle dev et build ; les dépendances de build y sont figées et reçoivent une version (contrairement à Python) ; le scope d'une transitive suit `runtime`, `peer`, `optional`, `build`, puis `dev` ;
  - **la version permise** (`wanted`) : la plus haute que permet la contrainte, retirées exclues, comme cargo (vérifié) ; le résolveur 3 préfère en plus celles dont le `rust-version` convient : pas pris (case ajoutée à E29) ;
  - **la commande à la main** : `cargo update -p x@V --precise W` pour une seule mise à jour dont la contrainte n'a pas changé ; sinon `cargo update -p x@V -p y@V…` (Cargo monte à la plus haute permise) ;
  - **les réponses enregistrées** : six crates (rand, regex, time, anyhow, log, smallvec : 784 Ko) ; OSV ré-enregistré pour les versions des deux mini-projets (`OSV_PROJECTS`) ; les 26 avis déjà là, identiques une fois lus, remis tels quels (seul leur texte bougeait).
- **Trouvé** :
  - le récapitulatif de l'écran 5 et la liste des fichiers du plan citaient, pour une plage de catalogue, le manifeste qui y renvoie (`package.json`, `crates/app/Cargo.toml`) au lieu du fichier réécrit : corrigé (`editTarget` : `pnpm-workspace.yaml`, « Cargo.toml (racine du workspace) ») ; les diffs étaient justes ;
  - le libellé « pnpm-workspace.yaml (catalogue) » de `forceupdate update` valait pour Cargo : corrigé ;
  - deux membres qui visent la même indirecte, ou une directe épinglée qui a déjà déplacé un paquet : le second `-p x@actuelle` aurait échoué (et remis tout le groupe) ; sauté quand le lockfile ne fige plus cette version ;
  - un `lib.rs` vide pèse 0 octet : pas de Rust en local, mais un fichier pour GitLab, qui pèse en fichiers (le test de la source GitLab l'a vu) ; les mini-projets ont trois lignes de Rust ;
  - un heredoc a encore réduit `\\n` à `\n` (CLAUDE.md le dit) : les remplacements de texte passent par l'outil d'édition.
- **Tests** : `test_versions_cargo.py` (141 : comparaisons, versions strictes, écart, les cas du crate `semver`, refusées, forme normalisée, borne basse, exacte, et **les 26 choix de cargo**) ; `test_parsers_rust.py` (31, dont `TestParseCargoLock` repris de `reference/`) ; `test_registries_crates.py` (19, plus 1 réseau) ; `test_rust_projects.py` (8 : inventaire des deux mini-projets, failles et plan, `scan` et `update` en ligne de commande, cargo simulé) ; `test_update_constraints.py` (tableau Cargo et planchers) ; `test_writers.py` (Cargo.toml dans chaque forme, `[workspace.dependencies]`, ce qui ne se réécrit pas) ; `test_lockfiles.py` (8 : commande, épinglage puis contrainte remise, environnement, épinglage refusé, workspace, avertissements, échec remis ; plus le vrai cargo en `network`) ; les mini-projets passent aussi par les tests des sources GitHub, GitLab et Bitbucket et de la réécriture ; les tests qui prenaient crates.io pour « pas encore géré » prennent Go. 2377 tests Python verts (plus 11 réseau), ruff propre ; 139 Vitest ; 49 Playwright.
- **Vérifié à la main**, sur des copies dans le scratchpad, avec le vrai cargo : `forceupdate scan` (3 failles, versions permises, git et chemin non vérifiables) ; `forceupdate update --yes` sur `cargo` (regex 1.13.1, anyhow 1.0.104, log 0.4.34, serde 1.0.229 : versions exactes, rien d'autre de changé que leurs dépendances), puis analysé de nouveau (plus que les deux majeures) ; sur `cargo-workspace` (smallvec réécrite dans la racine, 1.16.4 dans le lockfile, le membre exclu réécrit sans lockfile) ; `forceupdate ui` piloté par Playwright : analyse, rapport (« =1.6.0 (workspace) »), écran 5 (« crates/app/Cargo.toml (workspace Cargo) »), plan (diff de la racine, « cargo trouvé », la commande), application : 7 mises à jour, toutes « version exacte », sans erreur de console.
- **Limites** : la version permise ne tient pas compte de `rust-version` (résolveur 3) ; un `rust-toolchain.toml` ou un `.cargo/config.toml` du projet est dit, pas neutralisé ; deux renommages du même crate (`rand` 0.8 et 0.9) montent ensemble, comme les alias npm ; `[patch]` et `[replace]` ne sont vus que par le lockfile ; un registre privé (`registry = "…"`) n'est pas vérifié ; `[package] workspace` doit désigner un dossier de la source.

### E22 — Go

- [x] Reprendre `parse_go_mod` et ses tests. Corriger :
  - `// indirect` → `direct=False` ;
  - `replace` vers un chemin local → non vérifiable ; vers un autre module → c'est lui qu'on vérifie ;
  - `exclude`, `retract`.

  `go.sum` n'est plus une source de versions.
- [x] Workspaces Go (`go.work`, `go.work.sum`) : à reconnaître dans `detect/manifests.py`, qui ne les connaît pas encore.
- [x] Versions :
  - semver avec `v` ;
  - pseudo-versions (`v0.0.0-20230101…-abcdef`), comparées par date ;
  - `+incompatible`.
- [x] Registre : `proxy.golang.org` (`/@v/list`, `/@latest`, chemins avec majuscules encodées).
- [x] Changer de majeur (v2 et plus) change le chemin du module : signalé, jamais appliqué.
- [x] Réécriture de `go.mod` ; régénération : ~~`go get <module>@<version>` puis~~ `go mod tidy` (voir les notes : `go get` peut retirer des modules).
- [x] Ajoutés en route : failles (OSV `Go`, versions corrigées remises avec leur `v`, une faille corrigée seulement sous une autre majeure le dit), retraits (`retract`, avec leur raison) et dépréciation (`// Deprecated:`) lus dans le `go.mod` de la dernière version, majeure suivante cherchée sous son chemin, `exclude` respecté par le planificateur et le constat « plus récente », indirectes réécrites dans `go.mod`, `replace` de `go.work` réécrit sans régénération, mini-projets `go` et `go-workspace` faits par le vrai `go`, réponses enregistrées du proxy (`tests/fixtures/goproxy/`), deux libellés de l'écran 5 (une indirecte Go ne passe pas « par le lockfile seul » ; « Aussi changé dans go.mod »), et un double point dans les options « à la main » de `forceupdate update` (depuis E10).

**Notes** (session 22) :

- **Commit d'abord** : E21 était déjà commitée (`4b3b4a3`, arbre propre) : rien à proposer. **Go installé** avec l'accord de l'utilisateur : `winget install GoLang.Go` a échoué deux fois (code 1618, une autre installation Windows en cours) ; l'archive officielle de go.dev (Go 1.27.3, SHA-256 vérifié contre `go.dev/dl/?mode=json`) est dépliée dans `~/sdk/go1.27.3`, hors du `PATH` des outils (voir CLAUDE.md). Les essais ont mis le cache de modules dans le scratchpad (`GOMODCACHE`).
- **Vérifié contre le vrai `go`** (1.27.3), avant d'écrire :
  - **`go.mod` donne la version utilisée** : une version réécrite à la main est gardée par `go mod tidy` ; une dépendance qui en demande une plus haute fait monter la ligne (x/text v0.3.8 → v0.13.0, tirée par x/net v0.17.0) ; depuis `go 1.17`, les indirectes y sont toutes (`// indirect`) ; en `go 1.16`, seules les directes. **`go.sum` n'en est pas une source** : il garde aussi `gopkg.in/check.v1` (un test de `yaml.v3`), qu'aucun paquet n'utilise ;
  - **`go get x@V` pour descendre retire les modules qui demandent plus** (x/text v0.14.0 → v0.3.8 a retiré x/net) et range une indirecte dans un nouveau bloc `require` : d'où la réécriture de `go.mod` par forceupdate (diff visible), puis `go mod tidy` ;
  - **tidy relève la directive `go`** quand une version choisie en demande un plus récent (x/text v0.30.0 : `go 1.21` → `go 1.24.0`), sans ajouter de `toolchain` ; **sans directive `go`, il écrit celle du go installé** (`go 1.27.3`) : le résultat le dit ;
  - **`GOTOOLCHAIN=auto` télécharge et lance** le Go que demandent `go` ou `toolchain` (« downloading go1.99.0 ») ; `GOTOOLCHAIN=local` refuse clairement (« go.mod requires go >= 1.99 ») et ignore la ligne `toolchain` : passé, et dit dans le plan quand `go.mod` a une ligne `toolchain` ;
  - **`GOFLAGS=-modfile=other.mod` fait refaire un autre fichier à tidy**, et une variable vide retombe sur `go env -w` : `GOFLAGS=-mod=mod` (sans effet sur tidy) ; `GOWORK=off` par précaution (tidy ignore déjà `go.work`). `GOPROXY`, `GOPRIVATE`… restent ceux de la personne ;
  - `go mod tidy` ne compile rien et ne lance pas `go generate` ; il télécharge les modules (sans exécuter leur code), et lance git pour un module hors proxy (`GOPRIVATE`, `GOPROXY=direct`), comme toujours avec `go` ;
  - **un `vendor/` devient périmé** : `go build` refuse alors (« inconsistent vendoring ») ; le refaire (`go mod vendor`) toucherait des centaines de fichiers qu'on ne saurait pas remettre : le plan le dit ;
  - écrire dans `require` une version **exclue** (`exclude`) fait sauter tidy à la **dernière** version (v0.43.0) : jamais proposée ;
  - un `replace X v => X v'` fait utiliser v' (`go.sum` n'a que v') ; un **`replace` de `go.work`** réécrit : le premier `go build` du workspace complète `go.work.sum` tout seul ; `go mod tidy` ignore le workspace ;
  - l'ordre de `golang.org/x/mod/semver` et sa détection des pseudo-versions, relevés par un petit programme Go (`GO_ORDER`, `GO_PATHS` dans `test_versions_go.py`) ;
  - **le proxy** : `@v/list` dans le désordre, sans pseudo-versions ni dates ; `@v/V.mod` (une ligne `module` pour une version sans `go.mod`) ; `@latest` ; chemins encodés `!minuscule` (`github.com/BurntSushi/toml` tel quel : 404) ; 404 pour un module inconnu (410 aussi, selon la référence) ; `Cache-Control: max-age=60` ;
  - **OSV** accepte `v0.3.7` comme `0.3.7`, mais ses avis Go écrivent `fixed: 0.3.8` (sans `v`), parfois une pseudo-version (`yaml.v3` : `3.0.0-20220521103104-8f96da9f5d5e`) ; un avis Go cite chaque majeure du module (chi : aucune version corrigée sous `github.com/go-chi/chi`, corrigée en 5.2.4 sous `…/chi/v5`) ; les avis `GO-…` n'ont pas de gravité, leurs alias GHSA si.
- **Organisation** :
  - `versions/go.py` (`GO`, `GoRequirement`, `canonical`, `is_pseudo`, `path_major`, `module_path`) ; `parsers/go.py` (un lexer comme celui de `modfile` : identifiants, chaînes, blocs, commentaires de ligne et de bloc ; `parse_go_mod_file` → `GoMod`, `parse_go_mod`, `locked_versions`, `parse_project`, workspaces) ; `registries/goproxy.py` (`GoProxy`, `escape`, `latest_of`, `has_go_mod`) ; `update/writers/go.py` (`read_go_mod`, pour `go.mod` et `go.work`) ; `update/lockfiles.py` : `LockKind.GO`, `_Go`, `_go_environment`, `_go_warnings`, `_versions_path` ;
  - points d'extension génériques (voir « Depuis E22 » en tête de la phase F) ; `checks/deprecated.py` (« retirée par l'auteur du module (retract) », pas de « version inconnue » pour une pseudo-version, remplacement sous le même chemin et hors versions exclues) ; `checks/outdated.py` (une majeure sous un autre module le dit ; une version exclue n'est jamais la dernière) ; `checks/vulns.py` (`_fixed_elsewhere`) ; `planner.py` (`_in_manifest`, `_moved_manual`, `proposed_versions` sans les autres modules) ; `advisories/osv.py` (`fixed_in` écrit la version comme le manifeste).
- **Tranché** :
  - **une version de `go.mod` est la version utilisée**, une contrainte Go n'accepte qu'elle (`satisfies`, `lower_bound`, `exact`) : aucune autre ne s'obtient sans réécrire `go.mod`, donc pas de « lockfile seul » ; `Dependency.installed` vient de `go.mod`, `Dependency.lockfile` est le `go.sum` du module, même absent ; après tidy, les versions se relisent dans `go.mod` ;
  - **une indirecte Go est écrite dans `go.mod`** : elle s'y réécrit comme une directe (`_in_manifest` : une indirecte dont le fichier n'est pas le lockfile) ;
  - **une majeure** (v2+, `gopkg.in/x.vN`) est un autre module : le proxy cherche la liste du chemin de la majeure suivante (après la plus haute, `+incompatible` compris : chi v4 → `chi/v5`), tant qu'il y en a une publiée (pas seulement des pré-versions) ; sa dernière version devient la « dernière » ; l'option est `manual`, avec `go get …/vN@V` et « remplacer les imports », jamais soumise à OSV sous l'ancien nom ;
  - **la dernière** suit `go` : la plus haute publiée, sinon pré-version, sinon `@latest` ; les `+incompatible` n'y comptent pas quand la dernière compatible a un vrai `go.mod` (`versionHasGoMod` : autre chose qu'une ligne `module`) ; retraits et dépréciation lus dans le `go.mod` de cette dernière, retraits ignorés ; une version retirée l'est avec sa raison ;
  - **workspaces** : un module est membre si le `go.work` le plus proche le cite dans `use` ; un `require` d'un autre membre est « membre du workspace » ; un `replace` de `go.work` l'emporte, se réécrit dans `go.work` sans régénération ; la version d'un `go.mod` est gardée même si le workspace en construit une plus haute (limite) ;
  - **la régénération** : `go mod tidy` (pas `go get`), `GOTOOLCHAIN=local`, `GOFLAGS=-mod=mod`, `GOWORK=off` ; un changement de directive `go` ou `toolchain` est rapporté ;
  - **une pseudo-version d'un `X.0.0` à `X.0.y`** est une majeure (règle de semver de E05) : la correction de `yaml.v3` est proposée, pas pré-cochée ;
  - **les réponses enregistrées** : 12 modules (`PACKAGES["goproxy"]`), chacun avec toutes les réponses que demande le client (liste, `go.mod`, `@latest`, majeure suivante, 404 compris) ; OSV ré-enregistré pour les mini-projets Go, les 33 avis déjà là remis tels quels (identiques une fois lus).
- **Trouvé** :
  - en relançant l'analyse après une mise à jour : toml restait « mineure v1.6.0 » alors que v1.6.0 est exclue et que rien n'était proposé ; corrigé (le constat « plus récente » écarte les versions exclues) ;
  - une majeure suivante sans version publiée (que des pré-versions) devenait « la dernière » ; corrigé ;
  - `forceupdate update` écrivait « … les imports.. » (double point) après une option « à la main » : depuis E10, pour toute option `manual` ; corrigé (`report/terminal.py`) ;
  - un heredoc a encore réduit `\\n` à `\n` dans un script Python (CLAUDE.md le dit) : les remplacements de texte passent par l'outil d'édition.
- **Tests** : `test_versions_go.py` (73 : l'ordre et les pseudo-versions de `x/mod`, les chemins de majeure, contraintes, écarts) ; `test_parsers_go.py` (37, dont `test_require_block` repris de `reference/`) ; `test_registries_goproxy.py` (25, plus 1 réseau) ; `test_go_projects.py` (9 : inventaire des deux mini-projets, failles, plan, `scan` et `update` en ligne de commande, `go` simulé) ; `test_lockfiles.py` (7 : commande, environnement et versions gardées, ce que tidy fait monter, directive `go` relevée ou écrite, `go.sum` absent, avertissements, `replace` de `go.work` ; plus le vrai `go` en `network`, `GOPATH`, `GOMODCACHE` et `GOCACHE` dans le dossier du test : un premier passage avait laissé `~/go` et `go-build` chez l'utilisateur, effacés) ; `test_writers.py`, `test_update_constraints.py`, `test_manifests.py` (Go) ; 2 Vitest (libellés de l'écran 5) ; les tests qui prenaient Go pour « pas encore géré » prennent Packagist. 2551 tests Python verts (plus 13 réseau, avec les vrais go, cargo, npm, uv, pnpm), ruff propre ; 141 Vitest ; 49 Playwright.
- **Vérifié à la main**, sur des copies dans le scratchpad, avec le vrai proxy, OSV et `go` : `forceupdate scan` (7 failles, la retirée et sa raison, chi déprécié, v5 et jwt/v5 « publiées sous un autre module ») ; `forceupdate update --yes` (6 mises à jour, versions exactes ; tidy a remplacé `gopkg.in/yaml.v3` par `go.yaml.in/yaml/v3`, que testify v1.12.1 utilise, et la relecture le dit), puis `go build`, `go vet` et `go mod tidy -diff` sans rien à changer, puis l'analyse relancée (plus que les majeures et les failles qu'elles seules corrigent) ; sur `go-workspace` (`replace` de `go.work` réécrit, le conflit entre `app` et `lib` écarté avec sa raison, `tools` hors workspace régénéré avec sa ligne `toolchain`, `go build` du workspace qui complète `go.work.sum`) ; `forceupdate ui` piloté par Playwright : analyse, rapport, écran 5 (options « autre module » grisées avec la commande), plan (diff de `go.mod`, « go mod tidy »), application : 6 « version exacte », « Aussi changé dans go.mod », sans erreur de console.
- **Limites** : dans un workspace, la version construite peut être plus haute que celle d'un `go.mod` (la plus haute des membres) : celle du `go.mod` est vérifiée ; avant `go 1.17`, les indirectes absentes de `go.mod` ne sont pas vérifiées (une remarque le dit) ; la majeure suivante d'un module qui a déjà des `+incompatible` de cette majeure sous un chemin `/vN` n'est pas cherchée ; un module qui change d'hôte (`go-redis` → `redis/go-redis`) n'est vu que par sa dépréciation ; un module privé est demandé au proxy public et à OSV (comme un paquet npm privé) ; `vendor/` n'est pas refait ; la retraite d'une pseudo-version n'est pas vérifiée (le proxy ne liste pas les pseudo-versions) ; `tool` (Go 1.24) ne change pas le scope.

### E23 — PHP (Composer)

- [x] Reprendre `parse_composer_json`, `parse_composer_lock` et leurs tests. Corriger :
  - `dev-master` et autres branches : non vérifiables ;
  - `php` et `ext-*` sont mis de côté pour E27 (version de PHP).
- [x] Contraintes Composer : `^`, `~`, `||`, `|`, `-`, `*`, suffixes de stabilité (`@dev`).
- [x] Registre : Packagist `p2`. `abandoned` donne un constat « déprécié », avec le paquet de remplacement s'il est indiqué.
- [x] Réécriture de `composer.json` ; lockfile : ~~`composer update <nom> --no-install --no-scripts --no-plugins`~~ `composer update x:V… -W --no-install --no-scripts --no-plugins` (voir les notes).
- [x] Ajoutés en route : `lib-*`, `composer-plugin-api` et les autres paquets « plateforme » écartés comme `php` ; noms en minuscules (Composer et OSV) ; `replace` et `provide` (fournies par le projet : non vérifiables) ; `conflict` respecté (versions jamais proposées, ni « permises ») ; dépôts `path` et autres (`vcs`, `package`, `artifact`) non vérifiables d'après le lockfile ; `minimum-stability` sans `prefer-stable` signalé ; OSV `Packagist` (noms comparés sans la casse) ; le blocage des versions à faille de Composer 2.9+ levé le temps de la régénération (décision de l'utilisateur) ; mini-projet `composer` fait par le vrai Composer, réponses enregistrées de Packagist (`tests/fixtures/packagist/`) ; la version permise d'une dépendance tient compte des versions écartées (aussi `exclude` de Go).

**Notes** (session 23) :

- **Commit d'abord** : E22 commitée seule (`E22 : Go`), avec l'accord de l'utilisateur. **PHP et
  Composer installés** avec son accord, dans `~/sdk`, hors du `PATH` (voir CLAUDE.md) : PHP 8.5.12
  (l'archive NTS x64 de windows.php.net, SHA-256 vérifié contre `releases.json`, un `php.ini`
  minimal), Composer 2.11.0 (le `composer.phar` de getcomposer.org, SHA-256 vérifié contre les deux
  sommes publiées, et un `composer.bat`). Les essais ont mis `COMPOSER_HOME` et le cache dans le
  scratchpad.
- **Vérifié contre le vrai Composer** (2.11), avant d'écrire :
  - **les règles de version** : `versions/composer.py` réécrit `VersionParser` de composer/semver
    (lu dans le phar) et l'ordre de `version_compare` de PHP ; comparé à composer/semver lancé par
    PHP sur 1 282 versions de Packagist (`normalize`), 19 600 paires (ordre) et 99 contraintes
    × 1 267 versions : **aucun écart** (une mutation de l'ordre en donne, la comparaison mord) ;
    puis **22 choix de `composer update`** reproduits sur monolog et twig (`COMPOSER_CHOICES`) ; les
    deux écarts relevés ne sont pas des contraintes : une version qui demande PHP 7 (E27), et
    `4.*@dev`, où Composer prend la branche `4.x-dev` (forceupdate ne propose jamais de branche) ;
  - **`composer update x --with x:V`** (ou la forme courte `x:V`) vise la version, pour une directe
    comme pour une indirecte ; sans elle, la plus haute permise ; il **ne touche jamais au
    `composer.json`** ; une mise à jour partielle garde tout le reste, même des paquets vulnérables ;
  - **`-W` est nécessaire** quand la nouvelle version exige de bouger une autre directe (monolog 3
    demande psr/log 2) ; `-w` ne suffit pas. **`-m` (`COMPOSER_MINIMAL_CHANGES`)** ne bouge que le
    nécessaire (avec 7.4.5, guzzle garde promises et deprecation-contracts ; sans, ils montent), et
    ce qui doit bouger va à la plus haute permise (psr7 2.13.2), comme cargo ;
  - **`composer update --lock` garde monolog 2.3.5 sous une contrainte réécrite en `^2.9`**, et
    refait quand même le `content-hash` : le lockfile devient faux sans un mot. Jamais utilisé ;
  - **Composer 2.9+ refuse pendant un `update` toute version qui a encore un avis de sécurité**
    (`config.policy.advisories.block`, vrai par défaut ; la base de Packagist) : sur le mini-projet,
    twig 3.4.* et guzzle 7.4.5 refusés, alors que 3.4.3 corrige une faille. `--no-blocking`,
    `--no-security-blocking`, `COMPOSER_NO_BLOCKING` lèvent tout, logiciels malveillants compris ;
    **`COMPOSER_POLICY_ADVISORIES_BLOCK=0` (Composer 2.10+) ne lève que les failles**, et l'emporte
    sur la config du projet. Une config temporaire ne va pas : Composer 2.11 compte
    `config.policy` dans le `content-hash`. Composer 2.9 n'a ni variable ni option : seulement
    `config.audit.block-insecure`. **Tranché avec l'utilisateur** : lever les failles seules, sauf
    si le projet (`config.policy`, `config.audit.block-insecure`) ou la personne (la variable déjà
    là) le règle ; le plan le dit ;
  - **ce que Composer exécute** : deux témoins qui écrivaient un fichier. Sans `--no-scripts`,
    `pre-update-cmd` et `post-update-cmd` tournent même avec `--no-install` ; sans `--no-plugins`, un
    plugin déjà dans `vendor/` est activé ; avec les deux, rien. `--no-install` ne télécharge aucune
    archive (seulement les métadonnées) ;
  - **l'environnement hérité** : `COMPOSER=autre.json` fait lire un autre fichier ;
    `COMPOSER_PREFER_LOWEST=1` fait **descendre** monolog (2.3.5 → 2.3.0) : retirés, avec
    `COMPOSER_NO_DEV`, `COMPOSER_PREFER_STABLE`, `COMPOSER_WITH_(ALL_)DEPENDENCIES`,
    `COMPOSER_IGNORE_PLATFORM_REQ(S)`. `COMPOSER_HOME`, `COMPOSER_AUTH` (dépôts privés) restent ;
  - **une extension absente de la machine** (`ext-intl`) fait échouer la résolution :
    `--ignore-platform-req=ext-*` (et `lib-*`) ; la version de PHP reste celle de
    `config.platform.php`, sinon celle de la machine (le plan le dit) ;
  - **le lockfile** : `packages`, `packages-dev`, la version telle qu'écrite (`v5.4.10`),
    `require` de chaque paquet, `notification-url` (`https://packagist.org/downloads/`) pour un
    paquet de Packagist, `"dist": {"type": "path"}` pour un dépôt `path` ; `stability-flags`,
    `platform`, `content-hash` ;
  - **Packagist `p2`** : versions de la plus récente à la plus ancienne, pré-versions comprises
    (twig `v4.0.0-alpha1` en tête), minifiées (`__unset`), `abandoned` dans la plus récente (`true`
    ou le remplaçant), `time`, 404 ; un nom en majuscules donne aussi 200 ; `max-age=900` ;
  - **OSV** : l'écosystème `Packagist`, le nom en minuscules (`GuzzleHttp/Guzzle` : aucune faille),
    `v7.4.0` accepté comme `7.4.0` ; les avis écrivent `fixed: 5.4.20` (sans le `v` de Symfony) ;
    les failles de guzzle (14 avis) et psr7 (6) sont celles de `composer audit`, celles de twig 15
    sur 17 : les deux autres viennent de FriendsOfPHP seulement, OSV ne les a pas (limite) ;
  - `composer outdated` donne les mêmes dernières versions, sauf symfony/console : 6.4.49, la plus
    haute pour le PHP du projet (8.1.30) ; forceupdate dit v8.1.10, qui demande PHP 8.4 (case
    ajoutée à E27).
- **Organisation** :
  - `versions/composer.py` (`COMPOSER`, `ComposerVersion`, `ComposerConstraint`, `normalize`,
    `parse_stability`, `is_branch`, `STABILITIES`) ; `parsers/php.py` (`parse_composer_json`,
    `parse_composer_lock`, `parse_project`, `is_platform`, `REASON_BRANCH`, `REASON_PROVIDED`,
    `REASON_OTHER_REPOSITORY`) ; `registries/packagist.py` (`Packagist`, `expand`,
    `abandoned_message`) ; `update/writers/php.py` (`read_composer_json`) ; `update/lockfiles.py` :
    `LockKind.COMPOSER`, `_Composer`, `_composer_specs`, `_composer_environment`,
    `_composer_warnings`, `_composer_unblocks`, et les variables retirées dans `_DROPPED_ENV` ;
  - `checks/base.py` : `is_excluded` (versions de Go, contraintes de Composer), repris par
    `checks/deprecated.py`, `checks/outdated.py` (la dernière et la permise) et `planner.py` ;
    `advisories/osv.py` : noms Packagist sans la casse ; `update/constraints.py` : opérateurs
    Composer, `~1.2` qui garde sa précision, l'intervalle comme npm, le `v` de Packagist retiré de la
    version visée ; `openapi.json` et `schema.d.ts` (`LockKind` : `composer`).
- **Tranché** :
  - **une version nue est exacte** (`1.2` = `==1.2.0.0`), **`~1.2` va jusqu'à 2.0** ; une contrainte
    accepte les pré-versions qu'encadrent ses bornes, c'est la stabilité qui les écarte :
    seulement les stables, sauf un drapeau (`@beta`) ou une pré-version écrite (`^2.0-beta1`), comme
    `extractStabilityFlags` ; `minimum-stability` n'est pas connue d'une contrainte : une remarque
    quand elle est basse sans `prefer-stable` ;
  - **une branche** (`dev-main`, `1.x-dev`, avec alias, référence ou drapeau) n'est pas vérifiable,
    ni une version figée qui en est une (`*@dev` résolu en `dev-master`) ;
  - **un dépôt de `repositories`** : `path` se voit dans le lockfile ; `vcs`, `package`, `artifact`
    rendent non vérifiables les paquets sans le `notification-url` de Packagist (une fourche par
    `vcs` en est un) ; un dépôt `composer` (miroir, Satis, Private Packagist) n'est pas distingué :
    ses paquets sont cherchés sur Packagist (un privé y est introuvable) ;
  - **`conflict`** : des contraintes dans `Dependency.excluded` (aussi pour les transitives) ;
    `replace` et `provide` : ce que le projet fournit, absent du lockfile, non vérifiable s'il est
    aussi requis ;
  - **la régénération** : un seul `composer update x:V… -W --no-install --no-scripts --no-plugins
    --no-interaction --no-progress --no-ansi --ignore-platform-req=ext-* --ignore-platform-req=lib-*`,
    `COMPOSER_MINIMAL_CHANGES=1`, `COMPOSER_NO_AUDIT=1`, et `COMPOSER_POLICY_ADVISORIES_BLOCK=0`
    (voir plus haut) ; pas d'épinglage le temps d'un passage : `x:V` vise déjà la version. Sous
    Windows, `composer` est le `composer.bat` de l'installateur : `^` y serait refusé
    (`_BATCH_UNSAFE`), les versions passées sont exactes ;
  - **les réponses enregistrées** : huit paquets (`PACKAGES["packagist"]`, 840 Ko) ; pour OSV,
    seules les 20 versions du mini-projet ont été ajoutées à `queries.json`, avec leurs 35 avis
    (un script qui fait la requête de `record.py osv` pour ce projet seul) : rien d'autre n'a bougé.
- **Trouvé** :
  - la version permise de monolog était 2.11.1, que le `conflict` exclut (Composer prend 2.10.0) :
    la permise écarte maintenant les versions exclues (Go compris) ;
  - le plan annonçait le blocage levé même quand la personne avait réglé
    `COMPOSER_POLICY_ADVISORIES_BLOCK` (que forceupdate respecte) : la même décision sert aux deux ;
  - le heredoc a encore cassé un script (CLAUDE.md le dit) : les scripts passent par l'outil
    d'écriture.
- **Tests** : `test_versions_composer.py` (159 : la normalisation, l'ordre et les contraintes
  relevés sur composer/semver, bornes, versions exactes, drapeaux, et les 22 choix de
  `composer update`) ; `test_parsers_php.py` (49, dont `TestParseComposerJson` repris de
  `reference/`) ; `test_registries_packagist.py` (15, plus 1 réseau) ; `test_php_projects.py`
  (9 : inventaire, constats, plan, `scan` et `update` en ligne de commande, Composer simulé qui
  refuse une version à faille quand le blocage n'est pas levé) ; `test_lockfiles.py` (8 : commande,
  versions visées et environnement, réglages du projet ou de la personne gardés, avertissements,
  échec remis ; plus le vrai Composer en `network`, son cache dans le dossier du test) ;
  `test_update_constraints.py` (35 cas Composer), `test_writers.py` (6), `test_checks.py`
  (`is_excluded`) ; le mini-projet passe aussi par les tests des sources GitHub, GitLab et
  Bitbucket et de la réécriture ; les tests qui prenaient Packagist pour « pas encore géré »
  prennent RubyGems. 2838 tests Python verts (plus 15 réseau, avec les vrais Composer, go,
  cargo, npm, uv, pnpm), ruff propre ; 141 Vitest ; 49 Playwright.
- **Vérifié à la main**, sur des copies dans le scratchpad, avec le vrai Packagist, OSV et
  Composer : `forceupdate scan` (34 failles, deux abandonnés et le remplaçant, la branche et le
  dépôt `path` non vérifiables, monolog permise 2.10.0) ; `forceupdate update --yes` (7 mises à
  jour, versions exactes, promises 1.5.1 → 2.6.0 exigée par guzzle 7.16.1 et dite ; pas de
  `script-ran.txt` ; `composer validate` et `composer install --dry-run` sans rien à redire), puis
  l'analyse relancée (plus aucune faille ; les majeures et les abandonnés restent) ;
  `forceupdate ui` piloté par Playwright : rapport, écran 5 (psr/log, une majeure, pas cochée),
  plan (diff de `composer.json`, « composer trouvé », la commande, l'avertissement), application :
  7 « version exacte », « Aussi changé dans le lockfile », sans erreur de console.
- **Limites** : une version qui demande un PHP plus récent que celui du projet est proposée
  (Composer la refuse ; E27) ; les avis de FriendsOfPHP absents d'OSV ne sont pas vus (twig : 2
  sur 17) ; avec Composer 2.9, le blocage des failles ne se lève pas (la mise à jour d'une version
  qui en garde échoue, tout est remis) ; un dépôt `composer` privé est cherché sur Packagist ;
  `minimum-stability` sans `prefer-stable` : seules les stables sont proposées ; `prefer-stable`
  n'est pas lu pour un drapeau `@beta` (Composer le préfère alors stable) ; une branche n'est
  jamais proposée ; `vendor/` n'est pas mis à jour (le plan le dit).

### E24 — Ruby (Bundler)

- [x] Reprendre `parse_gemfile_lock` et ses tests.
- [x] Ajouter `Gemfile`, lu par motifs : c'est du Ruby, on ne l'exécute pas. À lire :
  - `gem "nom", "~> 1.2"` ;
  - les groupes (`group :development`) ;
  - `gemspec`.
- [x] Versions : `Gem::Version` (segments, `.pre`) et `~>`.
- [x] Registre : RubyGems ~~(`/api/v1/versions/<nom>.json`)~~ (l'index compact de Bundler, `index.rubygems.org/info/<nom>` : voir les notes).
- [x] Réécriture du `Gemfile` ; lockfile : ~~`bundle lock --update <nom>`~~ `bundle lock`, chaque version épinglée le temps d'un passage (voir les notes). Prévenir que Bundler évalue le `Gemfile`, donc exécute du code du projet.
- [x] Ajoutés en route : `gems.rb` et `gems.locked` (les autres noms de Bundler) ; le `.gemspec` comme manifeste (`*.gemspec`), seul ou cité par `gemspec` ; une gem `path:` résolue dans le `Gemfile.lock` du `Gemfile` qui la cite (`WORKSPACE_ROOTS`) ; versions à plateforme ; sources à part, git et plugins non vérifiables ; `platforms` sans gem dans le lockfile ; OSV `RubyGems` ; styles de contrainte Ruby (`~>` garde sa précision, plancher `, >= V`) ; une contrainte en plusieurs chaînes réécrite avec ses guillemets (`writers._WRITTEN`) ; la plateforme que Bundler ajoute, retirée ; mini-projet `bundler` fait par le vrai Bundler, réponses enregistrées de RubyGems (`tests/fixtures/rubygems/`), faux Bundler partagé (`tests/fake_bundler.py`).

**Notes** (session 24) :

- **Commit d'abord** : E23 était déjà commitée (`8d52d26`, arbre propre) : rien à proposer. **Ruby
  installé** avec l'accord de l'utilisateur : RubyInstaller 4.0.9-1 (x64, l'archive 7z sans
  devkit), SHA-256 vérifié deux fois (GitHub et rubyinstaller.org), dépliée par le `tar` de Windows
  dans `~/sdk/ruby-4.0.9`, hors du `PATH` (voir CLAUDE.md) : Ruby 4.0.9, RubyGems et Bundler 4.0.20.
  Les essais ont mis `BUNDLE_USER_HOME`, `GEM_HOME` et `GEM_SPEC_CACHE` dans le scratchpad.
- **Vérifié contre le vrai RubyGems et le vrai Bundler** (4.0.20), avant d'écrire :
  - **les règles de version** : `versions/rubygems.py` réécrit `Gem::Version` et `Gem::Requirement`
    (lus dans RubyGems 4.0.20) ; comparé au vrai, lancé par Ruby, sur 6 013 versions (l'index compact
    de 39 gems, et des cas limites), 90 926 paires et 221 contraintes (1,27 million de tests) :
    **aucun écart** ; trois mutations (borne de `~>`, mot avant nombre, zéros de fin) en donnent 22,
    7 538 et 1 315 : la comparaison mord. Puis **25 choix de `bundle lock`** sur rack et mustermann
    reproduits (`BUNDLER_CHOICES`) : la plus haute permise, une pré-version seulement si la
    contrainte en nomme une ;
  - **Bundler résout pour le Ruby qui tourne** : minitest 5.15 (Ruby < 4.0) est refusé sous Ruby
    4.0.9 ; les versions anciennes du mini-projet ont été choisies en conséquence (E27) ;
  - **`bundle lock --update x`** prend la plus haute version permise, et débloque aussi les
    dépendances de x (racc a suivi nokogiri) ; `--conservative` laisse celles qu'une autre gem
    partage ; une contrainte réécrite sans épinglage donne aussi la plus haute. **Bundler ne sait pas
    viser une version sans toucher au `Gemfile`** : `= V` le temps d'un `bundle lock`, puis la
    contrainte remise et `bundle lock` relancé garde V (directe, `.gemspec`, et indirecte par une
    ligne `gem "x", "= V"` ajoutée puis retirée, `DEPENDENCIES` redevenant celle du `Gemfile`) ;
    l'épinglage ne bouge pas les dépendances (racc reste) ; `--update` d'une gem absente : code 7 ;
  - **ce que Bundler exécute** : quatre témoins (dans le `Gemfile`, un fichier d'`eval_gemfile`, le
    `.gemspec` du projet, celui de la gem `path:`) ont tous écrit leur fichier pendant `bundle
    lock` : aucune option ne l'empêche. Les crochets des plugins ne tournent qu'à l'installation
    (`bundle lock` n'installe pas le `plugin` d'un `Gemfile`) ; une source de plugin (`source …,
    type:`) charge le sien ;
  - **l'environnement** : `BUNDLE_FROZEN` et `BUNDLE_DEPLOYMENT` (environnement ou `.bundle/config`)
    n'empêchent pas `bundle lock` d'écrire (il pose `frozen: false`) ; `BUNDLE_GEMFILE` lui fait lire
    un autre `Gemfile`, `BUNDLE_LOCKFILE` écrire un autre lockfile : remplacés par ceux du projet ;
    `BUNDLE_FORCE_RUBY_PLATFORM` ajoute la plateforme `ruby` : retiré ; `BUNDLE_COOLDOWN` (Bundler 4)
    écarte les versions récentes (l'épinglage échoue, code 7) : respecté, et dit dans le plan ; la
    configuration du projet (`.bundle/config`) passe devant l'environnement ;
  - **les plateformes** : sous Windows, `bundle lock` ajoute `x64-mingw-ucrt` à un lockfile qui ne
    l'a pas (Linux seul, ou `ruby` seul), avec ses gems à plateforme ; `bundle lock
    --remove-platform` ensuite ne change aucune version (dans la même commande, il re-résout) ; une
    plateforme absente : code 15 ;
  - **`BUNDLED WITH`** prend la version du Bundler qui tourne (2.4.10 → 4.0.20, et 9.9.9 → 4.0.20)
    ; `bundle lock` ne change pas de Bundler (seul `bundle install` le fait) ; `RUBY VERSION` suit la
    directive `ruby` (écrite à la version qui tourne si elle manque, gardée si elle est là, retirée
    sans directive) ; `ruby "3.3.6"` n'empêche pas `bundle lock` sous Ruby 4.0 ;
  - **le lockfile** : une section `GEM` par source (`source "https://gem.coop" do` en donne une
    seconde, la gem marquée `!` dans `DEPENDENCIES`), `PATH` (`remote: .` pour le `gemspec`, dont les
    dépendances de dev sont dans `DEPENDENCIES`), `PLATFORMS`, `DEPENDENCIES` (deux déclarations
    d'une gem fondues : `diff-lcs (~> 1.4, = 1.4.4)`), `CHECKSUMS` (Bundler 4), `BUNDLED WITH` ; une
    gem à plateforme `nokogiri (1.19.0-x86_64-linux-gnu)` sous `PLATFORMS x86_64-linux`. La section
    `GIT` n'a pas pu être produite en vrai (cloner un dépôt externe, dont Bundler évalue le
    `.gemspec`, n'a pas été permis pendant la session) : ses tests suivent le `LockfileParser` de
    Bundler ;
  - **RubyGems** : l'index compact (`index.rubygems.org/info/{nom}`, celui que lit Bundler), huit
    fois plus léger que l'API v1 (186 Ko pour nokogiri, 1,4 Mo pour l'API), une ligne par version et
    plateforme, `created_at` même pour 2009, 404 pour une gem inconnue, `max-age=60`. Les versions
    retirées (rest-client 1.6.10 à 1.6.13) sont absentes de l'index comme de l'API v1, et l'API v2
    répond 404 pour elles : un retrait ne se distingue pas d'une version jamais publiée ;
  - **OSV** : l'écosystème `RubyGems`, le nom tel qu'écrit, la version sans plateforme ; nokogiri
    1.19.0 : 11 avis, corrigés en 1.19.1, 1.19.3 et 1.19.4 ; rack 2.2.3 : 32, dont une correction à
    quatre nombres (2.2.8.1).
- **Organisation** :
  - `versions/rubygems.py` (`RUBYGEMS`, `GemVersion`, `GemRequirement`) ; `parsers/ruby_spans.py`
    (un lexer de Ruby : chaînes, symboles, étiquettes, `%w[]`/`%i[]`, heredocs, expressions
    régulières, `=begin`, `__END__`, et les instructions) ; `parsers/ruby.py` (`parse_gemfile`,
    `parse_gemspec`, `parse_gemfile_lock` → `GemfileLock`, `parse_project`, `is_rubygems`, les
    `REASON_*`, `MANIFESTS`) ; `registries/rubygems.py` (`RubyGems`, `parse_info`) ;
    `update/writers/ruby.py` (`read_gemfile`, `read_gemspec`, `written_target`) ;
    `update/lockfiles.py` : `LockKind.BUNDLER`, `_Bundler`, `_bundler_environment`,
    `_bundler_warnings`, `_appended`, `_Context.run_pinned(…, appended=)` ;
  - `detect/manifests.py` : `gems.rb`, `gems.locked`, `*.gemspec`, `WORKSPACE_ROOTS` ;
    `update/constraints.py` : opérateurs RubyGems, `~>` qui garde sa précision, `>= ` du plancher ;
    `update/writers/__init__.py` : `_WRITTEN` ; `openapi.json` et `schema.d.ts` (`LockKind` :
    `bundler`).
- **Tranché** :
  - **une contrainte Ruby** s'écrit comme dans `Gemfile.lock` (`>= 1.19.0, < 1.20`) ; son
    emplacement couvre toutes ses chaînes d'une ligne, guillemets intérieurs compris, et
    `written_target` passe d'une forme à l'autre (séparateurs et guillemets du fichier, une
    contrainte ajoutée ou retirée) ; plusieurs chaînes sur plusieurs lignes : à réécrire à la main ;
  - **`~>` garde toujours sa précision** (le nombre de nombres y fixe la borne haute) : `~> 2.2.3`
    vers 2.2.8.1 donne `~> 2.2.8`, et `~> 2.2.8, >= 2.2.8.1` pour une faille (la forme des avis de
    Rails) ; `=` et une version nue sont exactes ;
  - **le `Gemfile` est lu par motifs** (jetons, blocs `do … end`, conditions), jamais exécuté :
    groupes `development` et `test` seuls : `dev` ; un groupe `optional: true` : `optional` ; git,
    chemin, autre serveur (source à part), plugin : non vérifiables ; une gem `platforms:` absente du
    lockfile : non vérifiable ; la source globale n'est pas distinguée (un miroir est cherché sur
    rubygems.org) ; `gemspec` lit le `.gemspec` du dossier (`name:` le choisit) ; un `.gemspec` que
    le `Gemfile` ne cite pas, `eval_gemfile`, une condition, une variable : une remarque (la
    contrainte d'une variable vient de `DEPENDENCIES`, à réécrire à la main) ;
  - **une gem `path:`** (un `.gemspec` sans `Gemfile`, citée par le `Gemfile` d'un dossier parent)
    est résolue dans le `Gemfile.lock` de ce parent, comme un membre de workspace ; un `.gemspec`
    qu'aucun `Gemfile` ne cite est une gem sans lockfile ;
  - **une version à plateforme** est lue sans sa plateforme (avant le premier `-`, comme Bundler) ;
    ses variantes ne font qu'une version, au lockfile comme au registre ;
  - **la régénération** : `bundle lock`, avec `BUNDLE_GEMFILE` et `BUNDLE_LOCKFILE` du projet, sans
    `BUNDLE_FORCE_RUBY_PLATFORM` ; directes (`Gemfile`, `.gemspec`) et indirectes épinglées le temps
    d'un passage, puis `bundle lock` ; un épinglage refusé : `bundle lock --update … --conservative`
    ; pas de ligne ajoutée après `__END__` ni pour un nom qui n'est pas celui d'une gem (il deviendrait
    du Ruby) ; la plateforme ajoutée par Bundler est retirée ; un changement de `BUNDLED WITH` ou de
    `RUBY VERSION` est dit ; la commande à la main : `bundle lock --update x… --conservative` ;
  - **`bundler` lui-même**, déclaré dans un `Gemfile` : non vérifiable (sa version est celle de
    `BUNDLED WITH`) ;
  - **les réponses enregistrées** : 23 gems (`PACKAGES["rubygems"]`, 568 Ko) ; pour OSV, les 22
    versions du mini-projet ajoutées à `queries.json` avec leurs 51 avis, rien d'autre de changé.
- **Trouvé** :
  - la gem `path:` d'abord vue comme un projet à part, sans lockfile : sa contrainte réécrite
    (json `>= 2.21.2`) faisait monter json à 3.1.0 dans le `Gemfile.lock` de la racine, que Bundler
    résout avec elle ; d'où le rattachement (ci-dessus) ;
  - une expression régulière en fin de ligne (`=~ /darwin/`) faisait continuer l'instruction sur la
    ligne suivante : le lexer la lit comme un littéral ;
  - le plancher s'écrivait `>=4.2.1` : `>= 4.2.1` pour Ruby ;
  - le heredoc a encore réduit `\\n` (CLAUDE.md le dit) : les scripts passent par l'outil d'écriture.
- **Tests** : `test_versions_rubygems.py` (191 : l'ordre, les égalités, les pré-versions, la
  normalisation, les refusées, `~>` et les contraintes relevés sur RubyGems, `bump`, `release`,
  écarts, bornes, et les 25 choix de `bundle lock`) ; `test_parsers_ruby.py` (32, dont
  `test_specs_section` repris de `reference/`) ; `test_registries_rubygems.py` (10, plus 1 réseau) ;
  `test_ruby_projects.py` (6 : inventaire, constats, plan, `scan` et `update` en ligne de commande,
  Bundler simulé) ; `test_lockfiles.py` (12 : plan, versions visées et environnement, épinglage
  refusé, plateforme retirée et `BUNDLED WITH`, `__END__`, nom étrange, `cooldown`, échec remis ;
  plus le vrai Bundler en `network`, sur un lockfile privé de la plateforme de la machine) ;
  `test_writers.py` (10), `test_update_constraints.py` (23), `test_manifests.py` (6) ; le
  mini-projet passe aussi par les tests des sources GitHub, GitLab et Bitbucket et de la réécriture ;
  les tests qui prenaient RubyGems pour « pas encore géré » prennent Maven. 3133 tests Python verts
  (plus 17 réseau, avec les vrais Bundler, Composer, go, cargo, npm, uv, pnpm), ruff propre ; 141
  Vitest ; 49 Playwright.
- **Vérifié à la main**, sur des copies dans le scratchpad, avec le vrai RubyGems, OSV et Bundler :
  `forceupdate scan` (51 failles, nokogiri à plateforme, la gem locale non vérifiable) ;
  `forceupdate update --yes` (11 mises à jour, toutes à la version exacte, json de la gem locale
  compris ; rack-protection et rspec-* montés parce que sinatra et rspec l'exigent, et dits ; le
  `Gemfile` et les `.gemspec` remis ; un témoin ajouté au `Gemfile` a bien tourné, comme le plan le
  dit), puis l'analyse relancée (plus que les majeures et les quatre failles qu'elles seules
  corrigent) ; `forceupdate ui` piloté par Playwright : rapport, écran 5 (11 cochées, 47 failles
  corrigées sur 51), plan (diff du `Gemfile`, « bundle trouvé », la commande, l'avertissement),
  application : 11 « version exacte », « Aussi changé dans le lockfile », sans erreur de console.
- **Limites** : la version permise ne tient pas compte du Ruby que demande une version
  (`required_ruby_version` : Bundler l'écarte ; E27) ; le `Gemfile` est lu par motifs : une
  condition ou une variable n'est pas évaluée, le fichier d'un `eval_gemfile` n'est pas lu ;
  plusieurs chaînes sur plusieurs lignes ne se réécrivent pas ; une indirecte qui ne s'épingle pas
  monte à la plus haute permise ; une gem retirée est « inconnue du registre », sans raison ; `git:`
  et une source à part ne sont pas vérifiés, la section `GIT` est testée d'après le code de Bundler ;
  `gemspec path:` d'un autre dossier est lu avec son propre projet ; `vendor/cache` n'est pas
  refait ; sous une directive `ruby` sans section `RUBY VERSION`, Bundler y écrit le Ruby de la
  machine (dit après coup).

### E25 — Java (Maven, Gradle)

- [x] Reprendre `parse_pom_xml` et ses tests, puis le réécrire avec ~~`xml.etree`~~ `xml.parsers.expat` (l'analyseur de `xml.etree`, bibliothèque standard : il donne la position du texte) au lieu de motifs :
  - ordre des balises libre ;
  - `${propriété}` résolues depuis `<properties>` (et le parent s'il est dans le dépôt) ;
  - `dependencyManagement`, plugins ;
  - version héritée d'un parent ou d'un BOM distant : « gérée par le parent ».
- [x] Gradle :
  - catalogue `gradle/libs.versions.toml` (TOML, donc fiable) ;
  - `build.gradle` et `build.gradle.kts`, formes littérales courantes (`implementation("g:a:v")`) ;
  - variables non résolues : non vérifiables.
- [x] Ordre des versions Maven : qualificatifs `alpha` < `beta` < `milestone` < `rc` < `snapshot` < `""` < `sp`.
- [x] Registre : `maven-metadata.xml` de Maven Central, et Google Maven pour `androidx.*` et `com.android.*`.
- [x] Réécriture là où la version est définie (la balise ou la propriété), dans `libs.versions.toml`, ou dans les littéraux Gradle. Pas de lockfile : les verrous Gradle sont hors V1.
- [x] Ajoutés en route : profils (`<profiles>`), `<parent>` distant et BOM importés vérifiés comme des dépendances, modules du même build non vérifiables, `<scope>system` (fichier local), plugins sans `groupId` (`org.apache.maven.plugins`) ou sans version ; les plugins Gradle (bloc `plugins`, `[plugins]` du catalogue) cherchés sur le portail des plugins Gradle ; les variables Gradle (`val`, `def`, `ext`, `extra`, `gradle.properties`) ; les plages Maven et Gradle (`1.+`, `latest.release`, `V!!`, `]a,b[`) ; les **variantes** (`-jre` / `-android` de Guava : jamais l'une pour l'autre, un point d'extension `VersionScheme.compatible`) ; une version partagée (propriété, `[versions]`, variable) dite dans le plan ; les avertissements d'une option cochée et la ligne « Aucun lockfile à régénérer » dans le plan en ligne de commande ; `../pom.xml` pour le fichier d'un parent ; la remarque sur `gradle.lockfile` ; mini-projets `maven` et `gradle`, réponses enregistrées de Maven (`tests/fixtures/maven/`).

**Notes** (session 25) :

- **Commit d'abord** : E24 commitée seule (`E24 : Ruby (Bundler)`, `0529c0e`), avec l'accord de
  l'utilisateur, après 3133 tests verts. **Ni Maven ni Gradle installés** (choix de l'utilisateur :
  pas besoin pour lire ni réécrire) ; seul le jar `maven-artifact` 3.9.16 a été téléchargé, avec son
  accord, dans `~/sdk/maven-artifact/` (SHA-1 identique à celle publiée sur Maven Central), pour
  l'oracle des versions. Java 8 n'a qu'un JRE (pas de `javac`) : l'oracle est un script lancé par
  Nashorn (`jjs -cp maven-artifact-3.9.16.jar`), qui appelle `ComparableVersion` et `VersionRange`.
- **Vérifié contre le vrai `ComparableVersion`** (maven-artifact 3.9.16), avant d'écrire les tests :
  - **l'ordre** : `versions/maven.py` réécrit l'algorithme de Maven 3.9 (éléments, sous-listes,
    `normalize`, mots connus, `a1`/`b1`/`m1`, `cr`, `ga`/`final`/`release`, et la règle de MNG-7559 :
    « `.X` se lit comme `-X` ») ; comparé à l'oracle sur **9 102 versions** publiées de 67 artefacts
    de Maven Central et de Google Maven (Guava `-jre`/`-android`, Hibernate `.Final`/`.CR1`, Jetty
    `.v2023…`, OkHttp `-alpha.11`, PostgreSQL `.jre7`, aws-sdk…) et les cas limites des tests de
    `ComparableVersion` : formes canoniques et **4 980 600 comparaisons, aucun écart** ; trois
    mutations (rc et snapshot échangés, zéros retirés seulement en fin, sans la règle de MNG-7559)
    en donnent 108, 4 398 et 1 094 : la comparaison mord ;
  - **`ComparableVersion` n'est pas transitif** : le tri de Java refuse le corpus (« Comparison
    method violates its general contract ») ; `1` < `1a` < `1-0.alpha`, mais `1` > `1-0.alpha`.
    forceupdate a les mêmes réponses ; `sort_key` ne lève pas ;
  - **`VersionRange`** : 45 spécifications, lues ou refusées comme Maven (intervalles, plusieurs,
    chevauchement, intervalle vide, version seule hors de `[]`), et ce qu'elles contiennent : aucun
    écart, sauf `[1.0,2.0,3.0]` (une borne haute « 2.0,3.0 ») refusée exprès ; **une version nue**
    « contient » toutes les versions pour Maven (c'est une recommandation) : ici elle n'accepte
    qu'elle (voir « Tranché ») ; **`[1.0,2.0)` contient `2.0-alpha-1`** (sous `2.0`) ;
  - **Maven Central** : `maven-metadata.xml`, versions dans l'ordre de publication, **`<latest>` et
    `<release>` peuvent être des pré-versions** (log4j-core : `3.0.0-beta3` ; maven-artifact :
    `4.0.0-rc-7`), aucune date par version (`<lastUpdated>` date le fichier) ; 404 en HTML pour un
    inconnu. **Google Maven** (`dl.google.com/android/maven2`) : le même fichier, `max-age=86400`.
    **Le portail des plugins Gradle** (`plugins.gradle.org/m2`) : le marqueur `{id}:{id}.gradle.plugin`,
    `max-age=43200` ; ce qu'il n'a pas est renvoyé (303) vers Maven Central ;
  - **OSV** : l'écosystème `Maven`, le nom `groupe:artefact`. **Log4Shell** : log4j-core 2.14.1 →
    CVE-2021-44228 corrigée en 2.15.0, puis CVE-2021-45046 en 2.16.0, CVE-2021-45105 en 2.17.0,
    CVE-2021-44832 en 2.17.1 (et des avis de 2025-2026 corrigés en 2.25.x) ; commons-text 1.9 →
    Text4Shell (CVE-2022-42889) en 1.10.0 ; junit 4.12 → CVE-2020-15250 en 4.13.1 ; **Guava : OSV
    écrit `fixed: 32.0.0-android`** (une autre variante que `-jre`).
- **Organisation** :
  - `versions/maven.py` (`MAVEN`, `MavenVersion` : `canonical`, `numbers`, `prerelease`, `flavor` ;
    `MavenRange`, `Restriction`) ; `versions/base.py` : `compatible`/`_compatible` (inerte ailleurs),
    suivi par `candidates` ; `checks/outdated.py` : une dernière d'une autre variante est remplacée
    par la plus haute de la sienne ;
  - `parsers/xml_spans.py` (expat, positions du texte d'un élément, DTD et entités refusées) ;
    `parsers/maven.py` (`read_pom` → `Pom`, `Entry`, `ParentRef`, `Property` ; `parse_pom_xml` un
    fichier seul ; `parse_pom_project` avec les parents du dépôt et les modules du build ; les
    `REASON_*`) ; `parsers/gradle_spans.py` (un lexer de Groovy et de Kotlin) ; `parsers/gradle.py`
    (`read_catalog` → `Catalog`, `read_script` → `Script`, `read_properties`, `script_dependencies`,
    `catalog_dependencies`, `parse_gradle_project`, `configuration_scope`, `plugin_id`) ;
    `parsers/java.py` (`parse_project` : `pom.xml`, puis Gradle) ;
  - `registries/maven.py` (`Maven`, `repository`, `coordinates`, `parse_metadata`) ;
    `update/constraints.py` (`_rewrite_maven`) ; `update/writers/java.py` (`read_pom_xml` : les
    dépendances puis les propriétés ; `read_build_script` : puis les variables ;
    `read_version_catalog` : puis `[versions]` ; `read_gradle_properties`, reconnu par son nom dans
    `writers._reader`) ; `update/planner.py` : `_shared_warnings` (index des emplacements de tout le
    rapport) ; `report/__init__.py` : `_relative` ; `report/terminal.py` : avertissements des options
    cochées, « Aucun lockfile à régénérer ».
- **Tranché** :
  - **une version est située là où elle est écrite** : le texte de `<version>`, ou la valeur de la
    propriété qu'elle cite (`Dependency.file` est alors le fichier de la propriété : le `pom.xml`
    parent pour un module), l'entrée `[versions]` d'un `version.ref`, la variable d'un script, la
    ligne de `gradle.properties`. Pas d'`EditKind.CATALOG` : plusieurs dépendances ont le même
    emplacement, la réécriture n'a lieu qu'une fois (deux versions différentes : la seconde refusée,
    avec la raison), et le planificateur le dit (« Version partagée avec … : elle monte aussi ») ;
    le front n'a rien eu à changer ;
  - **une version nue est la version utilisée** (Maven : le plus proche l'emporte, une directe
    gagne ; Gradle : « require ») : elle n'accepte qu'elle, c'est sa borne basse et sa version
    exacte, comme Go ; elle va dans `Dependency.installed` (sans `lockfile`), pour que le rapport la
    montre. Une plage (`[1.9,2.0)`) a sa borne basse, « approximative » ; Maven prendrait la plus
    haute publiée, que dit la version permise ;
  - **un `pom.xml` du dépôt** : ses parents (`<relativePath>`, `../pom.xml` par défaut, s'il a le
    bon `groupId:artifactId`) donnent leurs propriétés (celle de l'enfant l'emporte),
    `dependencyManagement` et `pluginManagement` (avec leur scope si la dépendance n'en écrit
    pas) ; une dépendance sans version gérée par le même fichier ne fait qu'une déclaration ;
    gérée par un parent du dépôt, elle est redonnée dans le module, avec l'emplacement du parent ;
    gérée hors du dépôt : « gérée par un BOM importé (…) », « gérée par le parent … (hors du
    dépôt) », non vérifiable. Le parent distant et les BOM sont des dépendances (leur version est
    écrite) ; un module du même build (`${project.version}`, ou un `groupId:artifactId` d'un
    `pom.xml` du build) est non vérifiable ;
  - **les scopes** : `test` → `dev`, `provided`, `runtime`, `compile`, `import` → `runtime`,
    `<optional>` → `optional`, plugins et extensions → `build` ; Gradle : `test…`, `androidTest…`,
    `developmentOnly` → `dev`, `classpath`, `annotationProcessor`, `kapt`, `ksp` → `build` ; les
    entrées du catalogue prennent le scope des scripts qui les citent (du projet et des
    sous-projets), `runtime` sinon ; un script qui cite `libs.x` ne redonne pas la dépendance ;
  - **Gradle n'est jamais lancé** ; les variables sont cherchées dans le script (`val`, `def`,
    `ext`, `extra`, `by extra`), dans les `ext` des scripts des dossiers parents, puis dans
    `gradle.properties` (du projet, puis des parents) ; une variable définie deux fois autrement,
    une expression (`${deps.x}`), une concaténation : non vérifiables, avec la raison ;
  - **les dépôts** : Google Maven pour `androidx.`, `com.android.`, `com.google.android.`,
    `com.google.firebase`, `com.google.gms` ; le portail pour un plugin (nommé par son `id`) ;
    Maven Central sinon ;
  - **pré-versions** : sous la version finale pour Maven (`alpha`, `beta`, `milestone`, `rc`,
    `snapshot`), plus `dev`, `ea`, `pre`, `preview` ; **variantes** : les autres mots (`jre`,
    `android`, `v` de Jetty) ; une version d'une autre variante n'est jamais candidate (une version
    sans variante l'est toujours) ;
  - **la réécriture** : une version nue devient la version visée (`30.1-jre` → `33.7.2-jre`), `V!!`
    garde ses `!!`, `[V]` aussi ; un intervalle : borne basse à la version visée, borne haute
    dépassée déplacée au même niveau (`[1.9,2.0)` → `[2.3.1,3.0)`) ; `1.+` garde sa précision, sans
    plancher possible ;
  - **pas de lockfile** (pas de `LockKind`) : la mise à jour s'arrête à la réécriture ; le plan dit
    « Aucun lockfile à régénérer » (ligne de commande) et « Lockfiles régénérés 0 » (écran du
    plan) ; un `gradle.lockfile` donne une remarque (ni lu ni régénéré) ;
  - **les réponses enregistrées** : 18 artefacts (`PACKAGES["maven"]`, 108 Ko) ; pour OSV, les 19
    versions des deux mini-projets ajoutées à `queries.json` avec leurs 40 avis (un script qui fait
    la requête de `record.py osv` pour ces projets seuls) : rien d'autre de changé.
- **Trouvé** :
  - sans précaution, la correction des failles de Guava aurait proposé `32.0.0-android` à qui a
    `-jre` (OSV écrit cette version-là) : d'où les variantes ; le constat de faille cite toujours la
    version d'OSV, l'option proposée garde la variante ;
  - une dépendance sans `<scope>` gérée avec `<scope>test</scope>` sortait `runtime` : le scope de
    la gestion vaut, comme dans Maven ;
  - les avertissements d'une option cochée n'apparaissaient pas dans le plan en ligne de commande
    (depuis E10) : ajoutés sous son changement ; la colonne « Changement » d'un module écrivait
    `pom.xml` pour le `pom.xml` parent : `../pom.xml` ;
  - le test qui remet les anciennes contraintes de tous les mini-projets les remettait deux fois à
    un emplacement partagé : une fois.
- **Tests** : `test_versions_maven.py` (554 : formes canoniques, ordre et plages relevés sur
  maven-artifact 3.9.16, non-transitivité, satisfies, bornes, pré-versions, variantes, écarts) ;
  `test_parsers_maven.py` (23, dont `TestParsePomXml` repris de `reference/`, et le lecteur XML) ;
  `test_parsers_gradle.py` (22) ; `test_registries_maven.py` (22, plus 1 réseau) ;
  `test_java_projects.py` (9 : inventaire, constats, plan, `scan` et `update` en ligne de commande) ;
  `test_update_constraints.py` (24 cas Maven et Gradle) ; `test_writers.py` (4, et les deux
  mini-projets) ; les mini-projets passent aussi par les tests des sources GitHub, GitLab et
  Bitbucket ; les tests qui prenaient Maven pour « pas encore géré » prennent NuGet. 3801 tests
  Python verts (plus 18 réseau), ruff propre ; 141 Vitest ; 49 Playwright.
- **Vérifié à la main**, sur des copies dans le scratchpad, avec le vrai Maven Central, Google Maven,
  le portail des plugins et OSV : `forceupdate scan` (Log4Shell et ses suites, la plage
  approximative, les trois non vérifiables du module `app`, le plugin Gradle et `androidx`) ;
  `forceupdate update --yes` sur `maven` (14 mises à jour, 3 fichiers, 9 lignes, `<log4j.version>`
  une fois pour deux dépendances et trois projets ; relancée, l'analyse ne garde que ce que seules des
  majeures corrigent) et sur `gradle` (4 fichiers, dont `gradle.properties` et `[versions]`) ;
  `forceupdate ui` piloté par Playwright : rapport (versions utilisées, plage « approximative »,
  `pom.xml, ligne 28` pour un module), écran 5 (« Version partagée avec … », « sans lockfile »,
  « Lockfiles régénérés 0 »), plan (3 diffs), application (« Pas de lockfile : relancer
  l'installation du projet »), nouvelle analyse ; Gradle jusqu'au plan (4 diffs) ; aucune erreur de
  console.
- **Limites** : un dépôt Maven déclaré (`<repositories>`, `settings.xml`, `repositories { }`) n'est
  pas lu : ses artefacts sont cherchés sur Maven Central ; un artefact déplacé (`<relocation>`,
  mysql-connector-java → mysql-connector-j) n'est pas vu ; une version gérée par un parent ou un
  BOM distant n'est pas vérifiée (le parent ou le BOM, si) ; `settings.gradle(.kts)`, `buildSrc`,
  un autre catalogue que `gradle/libs.versions.toml`, les blocs de version riches des scripts
  (`version { strictly … }`) ne sont pas lus ; Gradle peut résoudre plus haut que la version écrite
  (la plus haute l'emporte) ; un `kotlin("stdlib")` sans version est ignoré ; les verrous de Gradle
  ne sont ni lus ni régénérés ; un constat de faille cite la version corrigée d'OSV, même d'une
  autre variante (Guava : `32.0.0-android`) ; l'ordre de Gradle diffère un peu de celui de Maven
  (`1.1.0` > `1.1` pour Gradle) : celui de Maven sert pour les deux.

### E26 — .NET (NuGet)

- [x] Reprendre `parse_packages_config` et ses tests.
- [x] Ajouter :
  - `*.csproj`, `*.fsproj`, `*.vbproj` : `<PackageReference>`, version en attribut ou en élément ;
  - `Directory.Packages.props` (versions centralisées). E02 en fait un projet à part, dans son dossier : le rattacher aux `.csproj` qui sont en dessous ;
  - `packages.lock.json`.
- [x] Versions NuGet : 4 segments, pré-versions, plages `[1.0,2.0)`.
- [x] Registre : ~~« flat container » pour les versions, API « registration » pour la dépréciation~~ l'API « registration » seule (elle a aussi les versions non listées, voir les notes).
- [x] Réécriture des `.csproj`, `.props` et `packages.config` ; lockfile : `dotnet restore --force-evaluate` si `packages.lock.json` existe.
- [x] Depuis E25 : lire les `.csproj` et les `.props` avec `parsers/xml_spans.py` (positions du texte
  et des attributs à ajouter : `Version="…"` est un attribut) ; une version de
  `Directory.Packages.props` est écrite une fois pour les projets en dessous : la même mécanique que
  les propriétés Maven (l'emplacement de la version, `Dependency.file` = le `.props`) ; les plages
  NuGet ressemblent à celles de Maven (`versions/maven.py`, `Restriction`), mais une version nue y
  est un minimum (`>= V`).
- [x] Les tests qui prenaient NuGet pour « pas encore géré » (`test_checks_vulns.py`, `test_cli.py`,
  `test_parsers_python.py`, `test_registries.py`, `test_versions.py`) : il ne reste plus d'écosystème
  à prendre. Les garder en retirant un écosystème des tables (`_PARSERS`, `_SCHEMES`,
  `_REGISTRIES`) le temps du test, ou retirer ce chemin s'il devient du code mort.
- [x] Ajoutés en route : `Directory.Build.props` (ses propriétés et ses `PackageReference`, et ceux
  qu'il importe plus haut par `GetPathOfFileAbove`), `VersionOverride`, `GlobalPackageReference`,
  les conditions MSBuild (dites, jamais évaluées), un projet de tests (`IsTestProject`,
  `Microsoft.NET.Test.Sdk`) en `dev`, `PrivateAssets="all"` en `build`, les `CentralTransitive`
  rattachées à leur `PackageVersion`, `allowedVersions` de `packages.config` (versions exclues) ;
  les versions flottantes (`1.*`, `1.0.0-beta.*`) ; `VersionScheme.lowest`, `reaches`, `chosen`
  (NuGet prend la plus basse version qui convient) ; une indirecte NuGet proposée à la main ; le
  lockfile d'un autre projet qui lit une version centrale réécrite, régénéré aussi ; le SDK
  absent (`dotnet` des runtimes seuls) traité comme un outil absent ; les avertissements
  `global.json` et `nuget.config` ; mini-projet `nuget`, réponses enregistrées de nuget.org
  (`tests/fixtures/nuget/`, compressées).

**Notes** (session 26) :

- **Commit d'abord** : E25 commitée seule (`E25 : Java (Maven, Gradle)`, `bed170f`), avec l'accord
  de l'utilisateur, après 3801 tests verts. Avec son accord aussi : **NuGet.Versioning 7.9.0** (le
  `.nupkg` de nuget.org, SHA-512 identique à celle de l'API de catalogue) dans
  `~/sdk/nuget-versioning-7.9.0/` pour l'oracle, et **le SDK .NET 10.0.403** (l'archive zip de
  `builds.dotnet.microsoft.com`, SHA-512 identique à celle de `releases.json`) dans
  `~/sdk/dotnet-sdk-10.0.403/`, hors du `PATH` (voir CLAUDE.md). Le paquet n'a plus de
  `netstandard2.0` : sa `lib/net472/` se charge dans PowerShell 5.1.
- **Vérifié contre le vrai NuGet.Versioning** (avant d'écrire les tests ; le code réécrit d'après
  son source, au commit `977537e` du paquet) :
  - **l'oracle** : un script PowerShell qui charge la DLL (`[Reflection.Assembly]::LoadFrom`) ;
    **piège** : `[NuGetVersion]::TryParse` y prend la surcharge héritée de `SemanticVersion`
    (stricte, trois nombres) : `NuGetVersion::Parse` dans un `try` ;
  - **les versions** : 17 866 lues (17 457 publiées de 175 paquets de nuget.org, plus des cas
    limites : espaces, zéros en tête, étiquettes `01`, `-1`, `2147483648`, métadonnées) : forme
    normalisée, nombres, étiquettes, métadonnées ; **leur tri** (17 824 versions, 17 506 rangs,
    158 838 576 comparaisons implicites) ; **141 contraintes** (intervalles, flottantes, refusées)
    et **30 189 vérifications** de `Satisfies` et `FindBestMatch` : **aucun écart** ; six mutations
    (casse des étiquettes, nombres après les mots, sans révision, la plus haute, pré-versions
    permises, zéros en tête) en donnent de 2 à 3 638 : la comparaison mord ;
  - `1.0` = `1.0.0` = `1.0.0.0` ; `01.2` est `1.2.0` ; `1.2.3-beta.01` est refusée ; une étiquette
    `-1` est un nombre ; une version nue est `[V, )` ; `[,1.0]` n'a pas de borne basse ; `1.*`
    accepte `2.0.0` (`Satisfies` : sa borne basse est 1.0.0), mais `FindBestMatch` y prend la plus
    haute 1.x ; `FindBestMatch` écarte une pré-version sauf si une borne en est une, ou une version
    flottante de pré-versions ; `1*` est `[10.0.0, )` (une bizarrerie de `FloatRange`, reproduite).
- **Vérifié avec le vrai SDK .NET 10.0.403** (`dotnet restore` sur des copies du mini-projet) :
  - le lockfile est en **version 2** avec la gestion centrale ; les noms tels que les écrit le
    paquet ; `Project` (le nom du projet référencé, en minuscules) ; **`CentralTransitive` même sans
    épinglage transitif**, pour une version centrale venue par un `ProjectReference` ; un framework
    par section (`net8.0`, `net10.0`) ;
  - **une version centrale réécrite suffit** : `dotnet restore`, sans `--force-evaluate`, refait le
    lockfile (NuGet prend la nouvelle borne basse) ; **une version flottante ne monte qu'avec
    `--force-evaluate`** (sans : « All projects are up-to-date ») ; `--force-evaluate` ne change
    rien à une version nue (lockfile identique) ; restaurer un projet restaure aussi ceux qu'il
    référence, leurs lockfiles compris ;
  - **`RestoreLockedMode`** (du projet ou de l'environnement) fait échouer (NU1004) ;
    `-p:RestoreLockedMode=false` le lève ;
  - **ce qu'il exécute** : une cible de `Directory.Build.targets` accrochée à `Restore` (témoin
    `WriteLinesToFile`) a tourné ; `Directory.Build.rsp` est lu (un témoin `-p:`), sauf avec
    `-noAutoResponse` (passé : il pourrait ajouter un logger, une DLL) ; une fonction de propriété
    qui écrit (`System.IO.File::WriteAllText`) est refusée par MSBuild (MSB4185). Aucun processus
    `dotnet` ne reste ensuite ; `obj/` est écrit dans chaque projet ;
  - **une version non listée est restaurée** : `Version="2.0.7.1"` de log4net donne 2.0.8, non
    listée (avertissement NU1601) : la version « permise » de NuGet se calcule sur toutes les
    versions publiées ;
  - `global.json` qui demande un SDK absent : `dotnet` échoue.
- **Vérifié en vrai** sur nuget.org : l'API « registration » (`registration5-gz-semver2`,
  compressée) donne les versions **non listées comprises** (`listed: false`, `published` à
  1900-01-01), `deprecation` (raisons, message, `alternatePackage`) ; au-delà de 128 versions, les
  pages sont des fichiers à part (24 pour AWSSDK.Core, 7,5 Ko chacune sur le réseau) ; un paquet
  inconnu : 404 en XML ; `Cache-Control: no-store`. Le flat container (les versions seules, en
  minuscules) n'est pas demandé. **OSV** : l'écosystème `NuGet` ne tient pas compte de la casse
  (`newtonsoft.json` trouve GHSA-5crp-9r3c-p9vr) et lit `12.0` ; Newtonsoft.Json 12.0.1 →
  CVE-2024-21907 corrigée en 13.0.1, Microsoft.AspNetCore.Http 2.1.0 → CVE-2020-1045 en 2.1.22,
  System.Text.Encodings.Web 4.5.0 → CVE-2021-26701 en 4.5.1, log4net 2.0.8 → CVE-2018-1285 en
  2.0.10 (et un avis de 2026 corrigé en 3.3.0).
- **Organisation** :
  - `versions/nuget.py` (`NUGET`, `NuGetVersion`, `NuGetRange`, `FloatRange`, `Float`) ;
    `versions/base.py` : `lowest`, `reaches`, `chosen` ;
  - `parsers/xml_spans.py` : `Element.attribute_locations` ; `parsers/nuget.py` (`read_msbuild` →
    `MsBuildFile`, `Property`, `Item` ; `Properties` ; `_Evaluation` (le projet et ce que MSBuild
    lit avant lui) ; `parse_packages_config` ; `parse_packages_lock_json` → `NuGetLockfile`,
    `Locked` ; `parse_project`) ;
  - `registries/nuget.py` (`NuGet`, `deprecation_message`) ; `advisories/osv.py` : noms NuGet sans
    la casse ; `checks/outdated.py` : la version permise par `chosen` (toutes les versions pour
    NuGet) ; `checks/deprecated.py` : « non listée » ;
  - `update/constraints.py` (`_rewrite_nuget`, `_nuget_float`) ; `update/planner.py` : `reaches`,
    `_lowest_manual` ; `update/writers/nuget.py` (`read_msbuild_file`, `read_packages_config`,
    `Directory.Build.props` reconnu par son nom) ; `update/lockfiles.py` : `LockKind.NUGET`,
    `_NuGet`, `_dotnet_environment`, `_dotnet_sdk`, `_dotnet_project`, `_dotnet_warnings`,
    `_readers` ; `openapi.json` et `schema.d.ts` (`LockKind` : `nuget`).
- **Tranché** :
  - **une version nue est un minimum, et NuGet prend la plus basse qui convient** : sans lockfile,
    la version utilisée est sa borne basse (`exact` : celle d'une contrainte qui ne flotte pas,
    `[1.0,2.0)` compris), pas une version « approximative » ; la version « permise » est le choix de
    NuGet (`chosen`, la version utilisée sauf une version flottante) ; **une mise à jour réécrit
    toujours la borne basse** (`reaches` : seule une version flottante monte en régénérant) ;
  - **la réécriture** : une version nue devient la version visée (même précision si elle s'y
    écrit : `1.0` → `2.0`) ; `[V]` ; un intervalle prend la version visée pour borne basse, incluse
    (`(,2.0]` → `[1.5.3,2.0]`), sa borne haute se déplace au même niveau si elle l'exclut ; une
    version flottante garde sa précision (`1.*` → `2.*`), sans plancher (NuGet y prend la plus
    haute) ;
  - **une indirecte ne monte pas** : NuGet la garde à la plus basse version que demandent ceux qui
    la tirent ; l'option est « à la main », avec la `PackageReference` (ou la `PackageVersion`) à
    ajouter ; une `CentralTransitive` se réécrit dans sa `PackageVersion` ;
  - **le projet de `Directory.Packages.props`** donne ses versions centrales que n'utilisent pas
    les projets de son dossier, et ses `GlobalPackageReference` s'il n'en a pas, comme un
    `pom.xml` parent sa `dependencyManagement` ; une version centrale est réécrite une fois ;
  - **un projet à `packages.config`** : NuGet y ignore les `PackageReference` (le `.csproj` n'est
    pas lu) ; la version écrite est l'installée ; pas de lockfile ;
  - **les lockfiles** : `dotnet restore <projet> --force-evaluate -noAutoResponse
    -p:RestoreLockedMode=false`, le projet nommé (un dossier peut aussi avoir une solution) ; ni
    bannière, ni télémétrie, ni certificat de développement, ni nœud MSBuild laissé ; un `dotnet`
    sans SDK (`dotnet --list-sdks` vide) est un outil absent : les manifestes restent réécrits,
    la commande est donnée ; ce qu'il exécute est dit (`_RUNS_CODE`) ; `NUGET_PACKAGES`,
    `nuget.config`, les identifiants d'un flux privé restent ceux de la personne ;
  - **les réponses enregistrées** : onze paquets (`PACKAGES["nuget"]`), compressés (224 Ko au lieu
    de 5,8 Mo) ; pour OSV, les 38 versions du mini-projet ajoutées à `queries.json` avec leurs 5
    avis (un script qui fait la requête de `record.py osv` pour ce projet seul) : rien d'autre de
    changé.
- **Trouvé** :
  - `dotnet` est souvent installé sans SDK (les runtimes seuls, comme sur cette machine avant la
    session) : il aurait fait échouer la régénération, et remettre les manifestes ;
  - les indirectes venues d'un projet référencé par un projet de tests sortaient `runtime` : elles
    sont `dev` ;
  - un heredoc a encore avalé une barre oblique (`L\'ajouter`), et `python -I` ignore
    `PYTHONIOENCODING` (une table écrite en cp1252) : scripts écrits par l'outil d'écriture,
    `-X utf8`.
- **Tests** : `test_versions_nuget.py` (382 : lues ou refusées, ordre, 141 contraintes relevées sur
  NuGet.Versioning 7.9.0, bornes, `reaches`, `chosen`, écarts, candidates) ;
  `test_parsers_nuget.py` (22 : attributs XML, `packages.config` repris de `reference/`, projets,
  conditions, gestion centrale, `Directory.Build.props` en chaîne, lockfile) ;
  `test_registries_nuget.py` (17, plus 1 réseau) ; `test_nuget_projects.py` (6 : inventaire,
  constats, plan, `scan` et `update` en ligne de commande) ; `test_update_constraints.py` (27 cas
  NuGet) ; `test_writers.py` (2, et le mini-projet) ; `test_lockfiles.py` (5, plus le vrai
  `dotnet` en `network`) ; le mini-projet passe aussi par les tests des sources GitHub, GitLab et
  Bitbucket ; les tests « pas encore géré » retirent NuGet des tables le temps du test. 4268 tests
  Python verts (plus 20 réseau), ruff propre ; 141 Vitest ; 49 Playwright.
- **Vérifié à la main**, sur des copies dans le scratchpad, avec le vrai nuget.org, OSV et le vrai
  `dotnet` : `forceupdate scan` (9 failles dont l'indirecte System.Text.Encodings.Web, log4net
  2.0.8 non listée, xunit 2 déprécié et son remplaçant, NUnit gardé sous `allowedVersions`) ;
  `forceupdate update --yes` (4 fichiers réécrits, les deux lockfiles refaits par `dotnet restore`
  aux versions exactes, la `CentralTransitive` du projet de tests comprise) ; `forceupdate ui`
  piloté par Playwright : rapport (versions situées dans `Directory.Packages.props`, l'indirecte
  « à faire à la main »), écran 5 (12 cochées, 4 fichiers, 2 lockfiles), plan (trois diffs,
  « dotnet trouvé », la commande et ce qu'elle exécute), application (12 mises à jour, toutes à la
  version demandée), nouvelle analyse ; aucune erreur de console.
- **Limites** : MSBuild n'est jamais lancé : les conditions ne sont pas évaluées, ni
  `Directory.Build.targets` (une `PackageReference Update=` y est fréquente : dite, pas lue), ni
  les imports autres que les `Directory.*.props` ; une indirecte NuGet se corrige à la main (case
  ajoutée à E29) ; un flux privé (`nuget.config`) n'est pas interrogé : les versions viennent de
  nuget.org ; `PackageDownload`, les SDK de projet (`<Sdk Name=… Version=…>`), un lockfile au nom
  propre (`NuGetLockFilePath`) ne sont pas lus ; `TargetFramework` et `global.json` restent pour
  E27.

---

## Phase G — Compléments d'analyse

### E27 — Fin de vie des runtimes et frameworks

**But** : le type 3 du brief.

- [x] Détecter la version de chaque runtime :

  | Runtime | Où la lire |
  |---|---|
  | Python | `requires-python`, `.python-version`, `runtime.txt` (et `python` de Poetry, `[requires]` du `Pipfile`, `python_requires` de `setup.cfg`) |
  | Node | `engines.node`, `.nvmrc`, `.node-version` (et `volta.node`) |
  | Go | directive `go` de `go.mod` (et `toolchain`, `go.work`) |
  | Ruby | `.ruby-version`, `ruby "…"` du `Gemfile` (et `RUBY VERSION` du `Gemfile.lock`) |
  | PHP | `require.php` de `composer.json` (et `config.platform.php`) |
  | Java | `maven.compiler.release`, `java.version`, toolchain Gradle (et `…target`, `…source`, `sourceCompatibility`, `targetCompatibility`, `jvmToolchain`) |
  | .NET | `TargetFramework`, `TargetFrameworks` (lus par `parsers/nuget.py` sans être gardés), le SDK de `global.json` (et `TargetFrameworkVersion`) |

  Plus les `FROM` des `Dockerfile` (images `python`, `node`, `ruby`, `php`, `golang`, `eclipse-temurin`…), et `.tool-versions` (asdf, mise).
- [x] Frameworks : table dépendance → produit endoflife.date (`django`, `rails`, `spring-boot`, `laravel`, `symfony`, `angular`, `vue`, `nuxt`, `electron`…).
- [x] Client endoflife.date (cache 24 h). Constat `EOL` dans deux cas : fin de vie passée, ou dans moins de 6 mois. Il donne la date et le cycle conseillé.
- [x] Pas de mise à jour automatique d'un runtime (signalé seulement). Un framework monte comme toute autre dépendance.
- [x] Versions qui demandent un Node plus récent : `npm outdated` écarte celles dont `engines.node` exclut le Node installé (E07 : jsdom 30 demande `^24.15.0`, il ne la propose pas sous Node 24.12). forceupdate les propose. Une fois connue la version de Node du projet, dire quand la version proposée en demande une plus récente (garder `engines` de chaque version dans `registries/npm.py` et son cache).
- [x] Depuis E23 : de même pour PHP. Composer refuse une version dont le `require.php` exclut le PHP du projet (`config.platform.php`, sinon la machine) : `composer outdated` propose symfony/console 6.4.49 sous PHP 8.1, forceupdate proposait v8.1.10, qui demande PHP 8.4 (et la mise à jour échouait). Garder le `require.php` de chaque version (les métadonnées `p2` le donnent) et dire, ou écarter, celles qui ne conviennent pas au PHP du projet.
- [x] Depuis E24 : de même pour Ruby. Bundler écarte une version dont le `required_ruby_version` exclut le Ruby qui tourne (minitest 5.15 demande Ruby < 4.0) ; l'index compact de RubyGems le donne pour chaque version (`ruby:< 4.1.dev&>= 3.2`). La directive `ruby` du `Gemfile` et la section `RUBY VERSION` du `Gemfile.lock` disent la version du projet.
- [x] Interface : les fins de vie apparaissent dans le rapport (écran 4), avec la date et le cycle conseillé.
- [x] Depuis E26 : les SDK de projet MSBuild venus de NuGet (`<Project Sdk="Microsoft.Build.NoTargets/3.7.0">`, `<Sdk Name=… Version=…>`, `msbuild-sdks` de `global.json`) sont des paquets versionnés : les vérifier comme des dépendances `build`.
- [x] Ajoutés en route : de même pour Python (`requires-python` de chaque version, l'API Simple de PyPI : uv, Poetry et PDM refusent une version qui ne convient pas à tout le `requires-python` du projet) ; la dernière version du cycle conseillé d'un framework proposée (`UpdateReason.SUPPORTED_CYCLE`), et dite quand le runtime du projet ne la fait pas tourner (`EndOfLife.advised_blocked`) ; la note d'une mise à jour quand la correction des failles demande un runtime plus récent ; les runtimes dans les rapports (terminal, Markdown, carte du projet) ; le mini-projet `eol` ; les SDK de `<Import Sdk= Version=>`.

**Notes** (session 27) :

- **Commit d'abord** : E26 commitée seule (`E26 : .NET (NuGet)`, `262519a`), avec l'accord de
  l'utilisateur, après 4268 tests verts.
- **Vérifié en vrai** sur endoflife.date (2026-11-01), avant d'écrire : la forme v1
  (`/api/v1/products/{produit}`, `result.releases`), sur Python, Node.js, Django, Go, Ruby, PHP,
  Eclipse Temurin, .NET, .NET Framework, Rails, Spring Boot, Laravel, Symfony, Angular, Vue, Nuxt,
  Electron : `isEol` est un booléen calculé le jour de la page, `eolFrom` une date ou `null` (un
  cycle maintenu sans fin fixée : Go 1.27, Vue 3.5 ; un vieux cycle fini sans date : Node.js 1 à 3,
  NestJS 10) ; `isLts`/`ltsFrom` (Node.js 26 LTS depuis le 2026-10-28) ; `latest.name`
  (`8u504-b01` pour Temurin 8) ; les cycles ne sont pas tout à fait dans l'ordre des dates (Python
  2.7 après 3.2) ; un produit inconnu : 404 en HTML ; un alias (`node`) : 301 vers `nodejs` ; la
  `codename` des LTS de Node.js est vide (d'où `NODE_CODENAMES`, pour `lts/gallium`). L'ancienne
  forme (`/api/{produit}.json`, `eol` date ou booléen) existe encore : pas demandée.
  `/api/v1/products/full` (3 Mo) donne les `purl` des produits (`pkg:pypi/django`,
  `pkg:npm/vue`, `pkg:maven/org.springframework.boot/…`) : la table des frameworks en est tirée, plus
  ce qui leur manque (Electron, les composants de Symfony, ASP.NET Core). **Chaque produit de la
  table vérifié** (un script : il existe, et une version typique y trouve son cycle : 58 versions
  de 56 produits).
- **Vérifié en vrai** sur les registres : `engines.node` de chaque version npm (p-limit : 4.0.0
  accepte Node 16, 5 et 6 demandent 18, 7 demande 20) ; `require.php` des métadonnées `p2`
  (symfony/console v8.1.10 : `>=8.4.1`) ; `ruby:` de l'index compact (minitest 5.15.0 :
  `< 4.0&>= 2.2`) ; `requires-python` des fichiers de l'API Simple (Django 5.0 : `>=3.10`, 6.0 :
  `>=3.12`).
- **Organisation** :
  - `endoflife.py` (`EndOfLifeDate`, `Product`, `Release`, `ProductNotFound`, `EndOfLifeError`),
    `CacheKind.LIFECYCLES` (24 h) ;
  - `parsers/runtimes.py` (`detect`, `LABELS`, `ECOSYSTEMS`, `NODE_CODENAMES`, `IMAGES`,
    `dockerfile`, `target_framework`) ; `detect/manifests.py` : `VERSION_FILES`, `DOCKERFILES`,
    `Project.runtime_files` ; `parsers/nuget.py` : `target_frameworks`, `SdkReference`,
    `global_json_sdks` ; `parsers/maven.py` : `java_version` ;
  - `checks/eol.py` (`FRAMEWORKS`, `framework`, `selected_runtimes`, `cycle_of`, `advised`,
    `check_runtime`, `check_framework`, `today`) ; `checks/runtimes.py` (`project_runtime`,
    `probe`, `refused`, `Refusal`) ; `PackageVersion.requires_runtime` (format 2 du cache des
    registres) ; `checks/outdated.py` et `deprecated.py` : `refused` ;
  - `models.py` : `Runtime`, `EndOfLife`, `Finding.eol`, `Project.runtime_files`,
    `Project.runtimes`, `UpdateReason.SUPPORTED_CYCLE` ; `engine.check` : `today`,
    `_record_lifecycles`, `_lifecycles` ; `update/planner.py` : `refused`, `SUPPORTED_CYCLE`, la
    note ; `update/writers/nuget.py` : les SDK, `read_global_json` ;
  - front : `screens/report/Lifecycles.tsx` (la section « Fins de vie »), les runtimes dans la
    carte du projet (`lib/report.ts` : `RUNTIME_LABEL`, `runtimeLines`), `lib/format.ts` :
    `formatDay` ; `openapi.json` et `schema.d.ts` régénérés.
- **Tranché** :
  - **un runtime est lu sans rien exécuter**, dans les manifestes et dans les fichiers de runtime
    (le plus proche de chaque nom, dans le dossier du projet ou au-dessus ; un `Dockerfile` va au
    projet le plus proche au-dessus, sinon à ceux d'en dessous) ; un fichier d'un autre dossier ne
    vaut que pour un projet de l'écosystème du runtime. Une contrainte donne sa borne basse
    (« au moins 3.8 ») ; pour la fin de vie, les versions choisies (`.python-version`, `.nvmrc`, un
    `FROM`) comptent plutôt que les bornes basses ; Java se lit d'après Eclipse Temurin (sauf
    `amazoncorretto`, `.tool-versions`) ;
  - **le cycle d'une version** : le plus long cycle dont les nombres la commencent (`3.5-sp1` pour
    3.5) ; une borne basse se complète de zéros ; une version plus récente que tous les cycles, ou
    moins précise qu'eux (`python:3`), ne dit rien ; une inconnue est « non concluant » ;
  - **le constat** : fin de vie passée (`MEDIUM`) ou dans moins de 6 mois (`LOW`), à la date du jour
    (`checks.eol.today`, que les tests fixent : `record.RECORDED_ON`) ; la date compte plus que
    `isEol`. **Le cycle conseillé** : plus récent que celui utilisé, maintenu, ne finissant pas
    dans les 6 mois (sinon tous les maintenus), le plus récent à support long s'il y en a (Django
    3.2 → 5.2 LTS, Node.js 16 → 26 LTS, Python 3.8 → 3.15) ; une fin prochaine sans cycle plus
    récent (la dernière Electron) n'est pas un constat ;
  - **un framework** : un constat par produit et par cycle, sur la première de ses dépendances
    vérifiées (les starters de Spring Boot, les composants de Symfony ne le répètent pas) ; sa
    montée reste celle du type 1, plus la dernière version du cycle conseillé
    (`SUPPORTED_CYCLE`, si elle est publiée sous ce nom : pas pour Microsoft.AspNetCore.Http) ;
  - **les versions que le runtime ne fait pas tourner ne sont pas proposées** (le constat « plus
    récente » vise la plus haute qui convient, comme `composer outdated` et `npm outdated` ; il dit
    la plus récente écartée et ce qu'elle demande ; si aucune ne convient, il cite la dernière sans
    qu'elle soit proposée). Le runtime retenu est **le plus ancien** de ceux lus pour l'écosystème,
    bornes basses comprises : uv résout pour tout `requires-python`, et un `^8.1` promet PHP 8.1. Une
    version choisie partielle (`.nvmrc : 16`) vaut la dernière de sa ligne, une borne basse sa
    version `.0` ;
  - **une erreur d'endoflife.date** (réseau, hors ligne sans cache, 5xx, réponse illisible, produit
    inconnu) donne un « non concluant », un par produit et par version, jamais un faux constat ;
  - **les SDK de projet MSBuild** : `Sdk="Nom/Version"` (plusieurs séparés par `;`), `<Sdk>`,
    `<Import Sdk= Version=>`, et, pour un SDK sans version, `msbuild-sdks` du `global.json` le plus
    proche : des dépendances `build`, à leur version exacte (`installed`), réécrites là où elles
    sont écrites (la version seule dans l'attribut). Les SDK de .NET (`Microsoft.NET.Sdk`) n'ont pas
    de version : pas des paquets ;
  - **avec `TargetFramework`, MSBuild construit pour lui seul**, même si `TargetFrameworks` est
    défini : la première des deux qui a une valeur ; `netstandard` n'est pas un runtime.
- **Trouvé** : les dates d'endoflife.date bougent avec le temps (« dans moins de 6 mois ») : sans date
  fixée, les tests casseraient au fil des mois (d'où `_fixed_today`, aussi dans `e2e_server.py`) ;
  un `build/` est un dossier écarté par la découverte (un test l'avait pris pour un projet) ; un
  heredoc a encore mangé des barres obliques inverses (scripts écrits avec l'outil d'écriture) ;
  `toHaveTextContent` de Testing Library ramène les espaces insécables à des espaces.
- **Réponses enregistrées** : 19 produits d'endoflife.date (`LIFECYCLES` de `record.py`,
  `endoflife/<produit>.json`) ; PyPI `django`, npm `p-limit` ; pour OSV, les deux versions du
  mini-projet `eol` ajoutées à `queries.json` avec leurs 16 avis (un script qui fait la requête de
  `record.py osv` pour ce projet seul) : rien d'autre de changé.
- **Tests** : `test_parsers_runtimes.py` (63 : les fichiers de runtime rattachés aux projets, chaque
  manifeste, les fichiers de version, les `Dockerfile`, le mini-projet) ; `test_endoflife.py` (10,
  plus 1 réseau) ; `test_checks_eol.py` (68 : cycles, cycle conseillé selon la date, runtimes,
  frameworks, la table) ; `test_checks_runtimes.py` (16, sur les réponses enregistrées des quatre
  registres) ; `test_eol_project.py` (8 : les trois fins de vie, les versions écartées, `scan` en
  terminal, JSON et Markdown, `--fail-on major`, hors ligne, endoflife.date en panne, le cycle
  conseillé de Spring) ; `test_writers.py` (les SDK de projet), `test_sources_forge.py` (les
  fichiers de runtime téléchargés), les fins de vie des mini-projets `composer` et `nuget` ; les
  tests qu'E27 change (symfony/console visé en v6.4.49 sous PHP 8.1, le format du cache des
  registres, les clés du JSON). 4441 tests Python verts (plus 21 réseau), ruff propre ; 146 Vitest
  (`Lifecycles.test.tsx`) ; 53 Playwright (axe-core sur le rapport `eol`, en clair et en sombre, à
  1440 et 375 px).
- **Vérifié à la main** (le 2026-11-01 et 02, vrai réseau) : `forceupdate scan` sur une copie du
  mini-projet `eol` dans le scratchpad (Python 3.8 depuis le 07/10/2024, Node.js 16 depuis le
  11/09/2023, Django 3.2 depuis le 01/04/2024, avec leur cycle conseillé ; Django visé en 4.2.30 et
  p-limit en 4.0.0, les versions écartées dites) ; `forceupdate update --dry-run --level major`
  (django `==4.2.30`, p-limit `^4.0.0`) ; `forceupdate ui` piloté par Playwright en clair à 1440 px
  et en sombre à 375 px : la section « Fins de vie » (trois cycles, dates, sources, cycles
  conseillés, LTS, l'avertissement de Django), la carte du projet (ses runtimes), le compteur, le
  détail de django et son lien vers endoflife.date ; aucune erreur de console, pas de défilement
  horizontal.
- **Limites** : la table des frameworks et `NODE_CODENAMES` sont à tenir à jour (un nouveau produit,
  la LTS 26 quand elle aura un nom) ; les images Docker non officielles (`bitnami/…`, `openjdk`,
  déprécié) ne sont pas lues ; le `required_ruby_version` d'un `.gemspec`, `mise.toml`, le
  `rust-version` de Cargo (case de E29) ne sont pas lus ; un `TargetFramework` sous condition n'est
  pas lu ; le Java d'un `pom.xml` est celui de Temurin, quel que soit le JDK de la machine.

**Fini quand** : un projet Python 3.8 + Django 3.2 + Node 16 sort trois constats
datés et justes, dans l'interface.

### E28 — Fichier de code isolé

**But** : choisir un fichier de code donne un résultat utile.

- [x] Fichier dans un projet : remonter les dossiers jusqu'au premier manifeste (arrêt à la racine git ou du disque). Analyser ce projet, en disant « analysé via `<manifeste>` ».
- [x] Fichier seul :
  - Python : bloc PEP 723 (`# /// script`), qui est un vrai manifeste, avec contraintes, et réécrivable. Sinon les imports (module `ast`), sans la bibliothèque standard (`sys.stdlib_module_names`), avec une table import → paquet (`yaml` → `PyYAML`, `cv2` → `opencv-python`, `PIL` → `Pillow`, `sklearn` → `scikit-learn`, `bs4` → `beautifulsoup4`…) ;
  - JS / TS : `import` et `require` de paquets (scopés compris), sans `node:` ni modules intégrés ;
  - Go : imports, rattachés à leur module.
- [x] Sans version, le constat est « version non fixée, dernière = X ». Les failles ne sont pas vérifiables sans version, et le rapport le dit.
- [x] Mise à jour d'un fichier seul : seulement le bloc PEP 723.
- [x] Marche aussi par glisser-déposer dans l'interface.
- [x] Ajoutés en route : le lockfile d'un script (`uv lock --script` écrit `script.py.lock`) lu pour
  les versions installées et régénéré par `uv lock --script` (`LockKind.UV_SCRIPT`) ; le
  `requires-python` du bloc lu comme un runtime (E27 : fin de vie, versions écartées) ; les fichiers
  de code dans la liste des dossiers (écran 2, `EntryKind.CODE`) et parmi les fichiers envoyés ;
  `--fail-on` qui ne compte jamais une version non fixée ; le lien « voir les remarques » souligné
  (axe : `link-in-text-block`, un défaut d'avant qu'aucun rapport à remarques n'exerçait) ; les huit
  compteurs sur une ligne à 1440 px ; « Gravité du constat » au singulier.

**Notes** (session 28) :

- **Commit d'abord** : E27 commitée seule (`E27 : fin de vie des runtimes et frameworks`,
  `cb1bde4`), avec l'accord de l'utilisateur, après 4441 tests verts.
- **Vérifié en vrai** avant d'écrire (2026-11-02) :
  - uv 0.10 et PEP 723, sur douze scripts (`uv export --script`) : un bloc est lu n'importe où dans
    le fichier, même dans une chaîne (la spécification est une expression régulière sur le texte) ;
    il va jusqu'au **dernier** `# ///` de la suite de commentaires (deux blocs collés, ou un `#` puis
    un second `# ///` : erreur TOML) ; une ligne sans `#` au début (`#dependencies`) : « an opening
    tag was found without a closing tag », refusé ; un champ inconnu est accepté ; `# /// pyproject`
    n'est pas un script ; un BOM cache le bloc ; CRLF va ; `[tool.uv] exclude-newer` est suivi.
    `uv lock --script x.py` écrit `x.py.lock` (au format de `uv.lock`, `[manifest] requirements`) ;
    **un script à bloc ignore le projet autour de lui** (`uv run` dans un projet : ses dépendances ne
    sont pas visibles), un script sans bloc prend celles du projet ;
  - Node 24.12 : `require('module').builtinModules` a 72 noms, dont 4 seulement avec `node:`
    (`node:sea`, `node:sqlite`, `node:test`, `node:test/reporters`) : un `test` nu est un paquet npm ;
    `fs/promises`, `punycode`, `sys`, `wasi` sont intégrés ;
  - Go : le proxy rend 404 pour un sous-dossier qui n'est pas un module
    (`golang.org/x/text/language/@v/list` : « no matching versions »), 404 aussi pour
    `golang.org/x` (« known non-module ») ; le plus long préfixe qui répond est le module
    (`aws-sdk-go-v2/service/s3` est le sien) ; un vrai `go mod tidy` (Go 1.27.3) rattache
    `golang.org/x/text/language` à `golang.org/x/text` v0.43.0 et `go-chi/chi/v5/middleware` à
    `go-chi/chi/v5` ;
  - les 89 paquets de la table import → paquet existent sur PyPI (une requête JSON chacun).
- **Organisation** :
  - `detect/code.py` (`code_language`, `code_ecosystem`, `is_code_file`, `READ_ALONE`,
    `read_alone`) ; `sources/base.py` : `ChosenCode`, `Source.code_file` ; `sources/local.py` :
    `alone`, `_project_dir`, `_has_manifest`, `_project_root`, `_home` ;
  - `parsers/imports.py` (`python_imports` par `ast`, `js_imports` et `go_imports` par des lexers ;
    `Import`) ; `parsers/code.py` (`parse_project`, `imported`, `IMPORT_PACKAGES` : 96 entrées,
    `NAMESPACES`, `PYTHON_STDLIB` et `PYTHON_REMOVED`, `NODE_BUILTINS`, `npm_package`,
    `python_package`, `go_candidates`, `candidates`) ; `parsers/python.py` : `ScriptBlock`,
    `script_block`, `has_script_block`, `is_script`, `parse_script`, `script_requires_python`,
    `_ProjectParser._script` ; `parsers/runtimes.py` : le `requires-python` d'un bloc ;
    `parsers.parse_lockfile` : `script.py.lock` ;
  - `models.py` : `FindingKind.UNPINNED`, `Dependency.imported`, `CodeReading`, `CodeFile`,
    `Report.code` ; `checks/base.py` : `Current.unpinned` ; `checks/outdated.py` : `_unpinned` ;
    `checks/priority.py` : `NOT_TO_UPDATE` ; `engine.py` : `_code_inventory`, `_check` (les clients
    des registres partagés), `_resolve_imports`, `_unpinned_notices` ; `report/` : `code_reading`,
    l'import en note de la ligne, `_IN_TABLE` ; `update/writers` : `read_script` ;
    `update/lockfiles.py` : `LockKind.UV_SCRIPT`, `_UvScript` ; `web` : `EntryKind.CODE`, l'envoi
    d'un fichier de code (`LocalSource(…, alone=True)`) ;
  - front : `unpinned` (`KIND_ICON` : `pin-off`, `KIND_LABEL`, `KIND_WORD`, le compteur « Versions
    non fixées », le badge info « non fixée · dernière X », « Utilisée : non fixée », « aucune : un
    import »), `CodeReading` et `UnpinnedAlert` de `ReportView.tsx`, la carte du projet
    (« Manifeste … (son bloc PEP 723) », « Fichier de code … (ses imports, sans version) »),
    l'écran 2 (`code` : icône `file`, compté à part), les textes de dépôt ; `openapi.json`,
    `schema.d.ts`, les fixtures du front régénérés.
- **Tranché** :
  - **la remontée cherche un manifeste de l'écosystème du fichier** (un `.py` passe un
    `package.json` ; un fichier d'un autre langage prend le premier manifeste venu) ; un lockfile
    seul n'est pas un projet ; elle s'arrête à la racine git (incluse), à celle du disque, ou **avant
    le dossier personnel** (un `package.json` laissé dans `~` ferait parcourir tout `~`) ;
  - **la source est le dépôt git qui contient le projet** (ses lockfiles de workspace, ses
    `Directory.Packages.props`, ses `pom.xml` parents, son `.python-version` sont au-dessus), sauf un
    projet rangé dans un dossier jamais parcouru (`node_modules/x`) : le projet lui-même ; hors git,
    le dossier du projet. Seul ce projet est analysé, même dans un dossier de tests (il a été
    choisi) ; les langages sont ceux de son dossier ;
  - **un script à bloc PEP 723 est son propre manifeste, même dans un projet**, comme pour
    `uv run` ; un bloc mal formé est une remarque (uv refuse le script), sans repli sur les imports ;
  - **un nouveau type de constat, `unpinned`** (« version non fixée »), plutôt qu'un « non
    concluant » : rien n'a échoué, et relancer n'y changerait rien. Il vaut pour un import, et pour
    toute dépendance sans contrainte ni lockfile (`requests` seul dans un `requirements.txt`, avant
    « non concluant ») ; jamais « à mettre à jour », jamais pour `--fail-on`, de gravité `info`,
    rangé avant « non vérifiable ». Une remarque par fichier dit que les failles ne sont pas
    vérifiables ;
  - **un import se rattache à son paquet à la vérification** : un module Go au plus long préfixe que
    le proxy connaît (au moins trois éléments chez `github.com`, `gitlab.com`, `bitbucket.org`,
    `golang.org`) ; un import sous un espace de noms Python partagé (`google`, `azure`, `zope`…) au
    plus long nom que PyPI connaît (`google-cloud-storage`) ; aucun : non vérifiable, avec les noms
    essayés ; le registre muet : non concluant. Deux imports du même module n'en font qu'un ;
  - **un import n'a ni contrainte ni emplacement** : rien n'est réécrit dans le code ; seul le bloc
    PEP 723 l'est. Un module posé à côté du script (`util.py`, `util/__init__.py`) n'est pas un
    paquet ; un import gardé par un `try … except ImportError` est facultatif ; sous
    `if TYPE_CHECKING:` ou `import type`, de développement ;
  - **un fichier envoyé n'a jamais de projet autour** (son dossier temporaire) : ses imports, ou son
    bloc.
- **Trouvé** : l'outil d'écriture change `\uXXXX` en caractère (le lexer en a reçu d'invisibles :
  `chr(…)` à la place), et les heredocs mangent encore des barres obliques inverses (scripts
  d'édition écrits avec l'outil d'écriture) ; un test du moteur et un de la source disaient
  « un fichier de code donne zéro projet » (comportement d'avant, mis à jour) ; le badge « non
  fixée · dernière 5.0.0.93 » débordait de 3 px à 375 px (vu sur le vrai réseau, pas avec les
  réponses enregistrées) : il passe à la ligne.
- **Réponses enregistrées** : PyPI `python-dateutil` (l'import `dateutil`) ; rien d'autre (les
  modules Go, lodash, @hapi/joi, colors, left-pad, flask, requests, jinja2 l'étaient ; un préfixe
  inconnu du proxy simulé rend 404).
- **Tests** : `test_parsers_imports.py` (lecteurs, jamais exécutés), `test_parsers_code.py` (table,
  espaces de noms, `npm_package`, modules intégrés, Go, le projet d'un fichier), `test_pep723.py`
  (le bloc comme uv, positions, lockfile du script, réécriture), `test_sources_code.py` (la
  remontée et ses arrêts), `test_code_files.py` (les trois cas de bout en bout, TypeScript, Go,
  le script verrouillé régénéré par un faux `uv`, `scan` en terminal, JSON, Markdown,
  `--fail-on any`) ; `test_web_api.py` (un script envoyé et sa version téléchargée, la liste des
  dossiers, les récents) ; les tests qu'E28 change. 4587 tests Python verts, ruff propre ;
  151 Vitest (`CodeFile.test.tsx`, l'écran 2) ; 59 Playwright (`code.spec.ts` : un vrai
  « drop » d'un script, son plan et sa version téléchargée ; un fichier dans un projet ; axe-core
  en clair et en sombre, à 1440 et 375 px).
- **Vérifié à la main** (le 2026-11-02, vrai réseau) : `forceupdate scan` sur des copies dans le
  scratchpad : `imports.py` (`google.cloud` → `google-cloud-storage`, `cv2`, `PIL`, `yaml`, un
  module voisin écarté, `ujson` facultatif), `index.ts`, `main.go` (`golang.org/x/text/cases` →
  `golang.org/x/text`), un script PEP 723 (Python 3.9 en fin de vie, requests 2.33 écartée car il
  demande Python 3.10), `app/__init__.py` de `eol` (via `pyproject.toml`), `frontend/src/main.tsx` et
  `src/forceupdate/engine.py` du dépôt (racine git, projet `frontend`, puis `.`) ; `forceupdate
  update --yes` d'un script (le bloc seul réécrit, relu par `uv export --script`) et d'un script
  verrouillé (`uv lock --script locked.py -P requests==2.34.2` : 2.31.0 → 2.34.2) ;
  `forceupdate ui` piloté par Playwright : un script déposé (le voile, le rapport), un fichier dans
  un projet, des imports en sombre à 375 px (le débordement trouvé puis corrigé), le détail, l'écran
  2 ; aucune erreur de console.
- **Limites** (reportées à E29) : les imports `npm:` et `jsr:` (Deno) et les alias de
  `tsconfig.json` (`paths`) ne sont pas lus ; un `.ipynb`, un `.vue` ou un `.svelte` seul n'a pas
  ses imports lus ; `importlib.import_module("x")` non plus ; un dossier voisin sans `__init__.py`
  (paquet d'espace de noms local) passe pour un paquet ; un import dont le nom de paquet n'est pas
  dans la table et existe sur PyPI sous ce nom (un homonyme) est pris pour lui ; `[tool.uv]
  exclude-newer` d'un script (ou d'un `pyproject.toml`) n'est pas suivi : une version proposée peut
  être refusée par uv.

**Fini quand** : les trois cas (fichier dans un projet, script PEP 723, script avec
seulement des imports) donnent un rapport juste.

---

## Phase H — Livraison

### E29 — Configuration et page Réglages

E29 de départ (« Configuration, page Réglages, robustesse ») découpée à la session 29, avec
l'accord de l'utilisateur, en cinq étapes : E29 (configuration et Réglages), E30 (robustesse et
performance), E31 (mise à jour : le npm du projet, Python, NuGet, Go), E32 (registres et dépôts
privés), E33 (compléments d'analyse). La documentation devient E34, la recette E35. Les mentions
« E30 » et « E31 » des notes et du journal d'avant la session 29 désignent donc E34 et E35.

- [x] Fichier de configuration par projet : `forceupdate.toml` à la racine, ou `[tool.forceupdate]` dans `pyproject.toml`. Il permet :
  - d'ignorer des paquets ou des versions (`ignore = ["lodash", "lodash@>=5"]` : voir les notes, la règle donne les versions ignorées) ;
  - de fixer la sélection par défaut par écosystème ;
  - d'exclure des dossiers ;
  - d'analyser aussi les projets rangés dans des dossiers de tests ou d'exemples, écartés par défaut depuis E02 (`engine.scan(include_tests=True)`).
- [x] Réglages de l'utilisateur (`platformdirs`) : sélection par défaut, dépôts exclus, cache (le vider : `Cache.clear`, E06). Écran 9 (Réglages) pour les modifier, selon `design-system/ECRANS.md` (le thème y figure aussi).
- [x] Les délais réglables : celui des outils de lockfile (`LOCK_TIMEOUT`, 600 s ; venu de la robustesse) et celui du clone d'un dépôt (`CLONE_TIMEOUT`, 600 s ; depuis E18 : un gros dépôt peut prendre du temps).
- [x] Depuis E18 : les dépôts exclus des réglages ne sont jamais dans un récapitulatif.
- [x] Depuis E21 : un `rust-toolchain.toml` du projet fait installer et lancer par rustup la chaîne d'outils qu'il désigne (même un dossier du projet) : seulement dit dans le plan. Proposer un réglage qui fixe `RUSTUP_TOOLCHAIN` (la chaîne d'outils par défaut de la personne), avec ce que ça change (la version de cargo et de `rustc` du résolveur).

**Fini quand** : un `forceupdate.toml` (ou `[tool.forceupdate]`) change l'analyse et le plan
comme il le dit, en ligne de commande et dans l'interface ; les réglages se modifient depuis
l'écran 9 et s'appliquent aux analyses et aux plans suivants ; le cache se vide.

**Notes** (session 29) :

- **Commit d'abord** : E28 commitée seule (`E28 : fichier de code isolé`, `8379d8f`), avec
  l'accord de l'utilisateur.
- **Décidé avec l'utilisateur** (pour les étapes qui suivent) : les tokens GitHub restent sans
  expiration (décision n°13, E30) ; `truststore` est ajouté pour les certificats du système (E30) ;
  le lockfile npm se régénère avec le npm qu'attend le projet (`npx -y npm@10`), case cochée
  d'office (E31).
- **Vérifié en vrai** avant d'écrire (2026-11-02) : rustup 1.29.1 : `rustup default` répond
  « stable-x86_64-pc-windows-msvc (default) » et ne lit pas le `rust-toolchain.toml` du dossier ;
  `RUSTUP_TOOLCHAIN` passe devant un `rust-toolchain.toml` qui demande une chaîne absente (1.70.0),
  sans rien installer (« overridden by environment variable ») ; `RUSTUP_AUTO_INSTALL=0` refuse
  d'installer (« toolchain '1.70.0' is not installed »). `platformdirs` : le dossier de
  configuration est celui de l'état (`%LOCALAPPDATA%\forceupdate`), où sont déjà `Cache`,
  `accounts.json` et `recent.json`.
- **Organisation** :
  - `config.py` (la configuration d'un projet : `read`, `parse`, `from_table`, `read_table` et ses
    lecteurs, partagés avec les réglages ; `Problem` ; `folder_pattern`, `is_excluded_path` ;
    `IgnoreRule` : `parse`, `matches`, `covers` ; `ignore_rules`, `mark_ignored`,
    `without_ignored`, `Filtered` ; `ECOSYSTEM_KEYS` et ses alias) ;
  - `preferences.py` (`Preferences`, `DEFAULTS`, `default_path`, `load`, `from_table`, `save` par
    un fichier temporaire, `to_toml` écrit à la main, `repository_pattern`, `excludes`) ;
  - `models.py` : `SelectionRule`, `Configuration`, `Report.config`, `Dependency.ignored`,
    `ScanOptions.ignore` et `selection` ; `checks.selected` écarte un paquet ignoré ;
  - `engine.py` : `inventory` lit la configuration (dossiers exclus, `include-tests`) ; `_check`
    marque les paquets ignorés, filtre les versions ignorées (`_without_ignored`, avec ses
    remarques), donne les règles au planificateur ;
  - `update/planner.py` : `Rules.by_ecosystem`, `for_ecosystem`, `rules(*couches)` ; `plan` et
    `audit` prennent les règles ; un paquet ignoré n'a pas de mise à jour ;
  - `update/lockfiles.py` : `Tools` (délai, chaîne d'outils Rust), `Job.timeout`, `Job.toolchain`,
    `_rustup_default` ; `local.prepare(tools=)`, `forge.deliver(tools=)` ;
  - `net/cache.py` : `Cache.stats`, `CacheStats` ; `clear` fait aussi `VACUUM` ;
  - `sources/forge.py` : la configuration du dépôt téléchargée au premier tour, ses dossiers exclus
    jamais téléchargés ;
  - `report/` : `configuration` (une phrase), dite par le terminal et le Markdown avec ses
    problèmes ;
  - `cli.py` : les réglages lus (`_preferences`, problèmes sur la sortie d'erreur), `--include-tests`
    (scan et update), `--level` sans valeur par défaut (sinon : le projet, puis les réglages) ;
  - `web/` : `preferences.py` (`UserPreferences` : chargés au démarrage, `tools`, `save`, le délai
    du clone posé dans `forges.git` et remis à l'arrêt ; `from_request`, `document`),
    `routes/settings.py` (`GET`/`PUT /api/settings`, `DELETE /api/cache`), schémas
    `SettingsRequest`, `SelectionInput`, `SettingsDocument`, `CacheState`, `FieldError`,
    `SettingsRejected` ; les options des analyses (`ScanRequest.options(settings)`…) ; les dépôts
    exclus (`Repositories.hidden_reason`, « exclu dans les réglages ») ; les PR (sautées, outils) ;
  - front : `screens/settings/SettingsPage.tsx`, `lib/settings.ts` (le formulaire et ce qu'il
    envoie), `hooks/useSettings.ts`, `api/client.ts` (`getSettings`, `saveSettings`, `clearCache`,
    `fieldErrors`, `ApiError.body`), `ScanOptions` du front réduit aux options d'une demande
    (`ReportOptions` pour celles d'un rapport), `useScanOptions` (« dossiers de tests » d'après les
    réglages), la ligne « Configuration du projet » du rapport (`Configured`) ; `ComingSoon`
    retiré (plus aucun écran à venir).
- **Tranché** :
  - **la syntaxe des versions ignorées est celle de forceupdate**, la même pour les huit
    écosystèmes : `nom@>=5`, `nom@<3,>=2.30`, `nom@1.2.3` (comparaisons `<`, `<=`, `>`, `>=`, `==`,
    séparées par des virgules), jugées selon les règles de version de l'écosystème (une borne
    complétée : `5` vaut `5.0.0` pour npm, `v5.0.0` pour Go) ; la syntaxe de chaque écosystème ne
    convenait pas (Go n'a pas de plages, Maven et NuGet en ont d'autres). L'exemple du plan
    (`lodash@<5`) se lit « ignorer les versions sous 5 » : pour rester en 4.x, `lodash@>=5` ;
  - **un paquet ignoré n'est ni vérifié auprès de son registre ni mis à jour, mais ses failles
    restent cherchées et dites** (ignorer ne cache jamais une faille ; `--fail-on vuln` les
    compte) ; une remarque par fichier le dit ;
  - **une version ignorée est retirée de ce que dit le registre** (`without_ignored`) : la
    « plus récente », les options, la correction des failles, le remplaçant d'une version
    dépréciée et le cycle conseillé d'un framework ne la proposent jamais ; la version utilisée
    n'est jamais retirée ; une remarque dit combien de versions une règle écarte, ou qu'elle ne se
    lit pas pour l'écosystème ;
  - **la configuration du projet prime sur les réglages** : sa sélection passe devant (une règle
    d'écosystème devant la règle générale, dans chaque couche ; `--level` et `--security-only`
    devant tout), ses `ignore` s'ajoutent à ceux des réglages ; `forceupdate.toml` prime sur
    `[tool.forceupdate]` (dit), comme ruff ; lue à la racine de la source seulement ;
  - **les réglages de la personne sont un `forceupdate.toml` de son dossier de configuration**
    (comme `uv.toml`), mêmes clés qu'un projet sauf `exclude`, plus `excluded-repositories`,
    `lock-timeout`, `clone-timeout`, `rust-default-toolchain` ; réécrit en entier à chaque
    enregistrement (commentaires perdus) ; une valeur fausse : la valeur par défaut, dite (à
    l'écran et sur la sortie d'erreur de la ligne de commande) ; **une règle générale égale aux
    valeurs par défaut n'est pas gardée** (trouvé par Playwright : après « Valeurs par défaut »,
    les rapports disaient « sélection par défaut réglée ») ;
  - un dépôt exclu est masqué comme un archivé (« exclu dans les réglages »), analysable si on le
    choisit, jamais prêt dans un récapitulatif (« exclu dans les réglages : pas de PR ») ;
  - le délai du clone est un réglage du module `forges.git` posé par le serveur (le passer par les
    trois forges aurait touché leurs douze méthodes) ; le délai des outils et la chaîne d'outils
    Rust passent par le `Job` (`lockfiles.plan`) ;
  - le thème reste une préférence du navigateur (écran 9 et bouton de l'en-tête, même clé) ;
  - le vidage du cache est confirmé ; « Valeurs par défaut » remplit le formulaire sans
    enregistrer.
- **Trouvé** : les tests Playwright partagent le serveur et tournent en parallèle : un paquet
  ignoré enregistré par un test apparaissait dans les rapports des autres (et son lien
  « Réglages », non souligné, faisait échouer axe : `link-in-text-block`) ; le test n'enregistre
  plus que des valeurs sans effet sur eux, et le lien est souligné ; une expression régulière des
  tests ne trouve pas un texte passé par `fr()` (espace insécable : `\s`) ; le heredoc mange
  toujours les barres obliques inverses (`\s` devenu `s` dans une expression régulière : scripts
  écrits avec l'outil d'écriture) ; le titre et les sections de l'écran 9 étaient à la taille du
  texte (vu sur la capture : `text-2xl`, `text-xl` comme les autres écrans).
- **Tests** : `test_config.py` (lecture, problèmes, règles, versions par écosystème, couches de la
  sélection, de bout en bout sur `vulnerable` : paquet ignoré et ses failles, versions ignorées,
  réglages ajoutés, sélection du projet et de la personne, dossiers exclus et de tests, rapports),
  `test_preferences.py` (fichier, ligne de commande, API, cache) ; dans `test_lockfiles.py` (délai,
  chaîne d'outils Rust), `test_sources_forge.py` (la configuration d'un dépôt),
  `test_web_repositories.py` et `test_web_proposals.py` (dépôts exclus) ; septième garde-fou
  (`user_settings` : un fichier de réglages propre au test, et `CLONE_TIMEOUT` remis). Front :
  `SettingsPage.test.tsx` (10), `Configured.test.tsx` (2) ; Playwright `settings.spec.ts`
  (enregistrer et recharger, valeur refusée, cache, projet configuré, axe-core en clair et en sombre
  à 1440 et 375 px). 4667 (plus 21 réseau) tests Python verts, 162 Vitest, 67 Playwright.
- **Vérifié à la main** (le 2026-11-02, vrai réseau) : `forceupdate update --dry-run` et `scan` sur
  une copie de `vulnerable` avec un `forceupdate.toml` (`lodash@>=4.18`, `werkzeug`, `legacy`
  exclu, correctifs, majeures pour PyPI) : lodash plafonné à 4.17.23, werkzeug sans mise à jour et
  dit, `legacy/` jamais lu, « --level patch ; PyPI : --level major » ; `forceupdate ui` piloté par
  Playwright : l'écran 9 (enregistrer, recharger, le dialogue du cache annulé, valeurs par défaut),
  le rapport du projet configuré, aucun débordement à 375 px, aucune erreur de console. Le fichier
  de réglages créé par l'essai a été effacé (il n'existait pas avant).
- **Limites** (pour la doc, E34) : la configuration n'est lue qu'à la racine de la source (pas dans
  chaque projet d'un monorepo) ; les commentaires des réglages ne survivent pas à un
  enregistrement ; un `ignore` sur un nom présent dans deux écosystèmes vaut pour les deux.

### E30 — Robustesse et performance

- [x] Robustesse :
  - dossiers énormes : au plus 200 000 fichiers listés (`sources.local.MAX_FILES`), et 2 000 fichiers de dépendances (`DEFAULT_MAX_FILES`, depuis E02) ; au-delà, la liste s'arrête et **le rapport le dit** (`Report.notices`, nouveau) ;
  - fichiers illisibles, encodages exotiques : UTF-16 et UTF-32 lus d'après leur BOM, BOM UTF-8 retiré (`detect.manifests.decode_text`) ; la réécriture garde le BOM, refuse l'UTF-16 en le disant ;
  - liens symboliques : déjà jamais suivis (E02) ; les jonctions Windows non plus ; un sous-module git non initialisé est dit (avant : `RecursionError`) ;
  - erreurs réseau partielles : la section « non concluant » existait (E07, E08) ; un certificat refusé est dit comme tel, sans reprise ;
  - réseau d'entreprise : `truststore` (le magasin du système), `SSL_CERT_FILE` et `SSL_CERT_DIR` ajoutés au magasin ; `HTTPS_PROXY` vérifié par un vrai proxy `CONNECT` ;
  - Ctrl+C pendant l'écriture des manifestes, pendant un outil, ou arrêt du serveur : ce qui n'était pas fini est remis comme avant ; un navigateur fermé ne change rien (la mise à jour continue) ;
  - Ctrl+Break sous Windows : traité comme Ctrl+C (code 0, « Interface arrêtée. ») ;
  - délai d'un outil dépassé sous Windows : tout l'arbre est tué (`processes.run`, `taskkill /F /T`).
- [x] Performance : Argos mesuré, cache vide (voir les notes et le journal) ; la suite de tests remesurée (`--durations=25`).

**Fini quand** : tests de robustesse verts, mesure notée dans le journal.

**Notes** (session 30) :

- **Commit d'abord** : E29 commitée seule (`E29 : configuration et page Réglages`), avec l'accord
  de l'utilisateur. **E30 découpée avec son accord** : les cases des forges (depuis E16, E18,
  E20) font E31 (« Forges : robustesse ») ; E31 à E35 de départ deviennent E32 à E36. Les
  mentions « E31 » à « E35 » des notes et du journal d'avant la session 30 désignent donc E32 à
  E36.
- **Vérifié en vrai** avant d'écrire (2026-11-02, Windows 11, Python 3.12) :
  - **l'arbre de `npm.CMD`** (un `npm run` qui lance un node de 25 s, délai de 3 s) :
    `subprocess.run(capture_output=True, timeout=3)` lève `TimeoutExpired` après **25,8 s** (il
    ne tue que `cmd.exe`, puis attend la fin de la sortie, que tient le node petit-fils) ; sans
    capture, à 3 s, mais `npm-cli`, son `cmd.exe` et le node **tournent encore** ;
    `taskkill /F /T /PID` tue les quatre processus, la main rendue en 3,6 s. Le `git.exe` de
    `Git\cmd` est aussi un lanceur (46 Ko). Avec `processes.run` : délai rendu en 3,2 s, arrêt
    demandé (`cancel`) en 2,2 s, aucun processus restant ;
  - **Ctrl+Break** sur `forceupdate ui` (lancé dans un nouveau groupe, `CTRL_BREAK_EVENT`) :
    code 3, sans « Interface arrêtée. » ; uvicorn 0.54 remet le gestionnaire d'avant (celui du
    runtime C pour `SIGBREAK`) puis renvoie le signal. Corrigé : code 0, « Interface arrêtée. » ;
  - **une jonction** (`mklink /J`, et `_winapi.CreateJunction` dans les tests) : `is_symlink`
    faux, `is_junction` vrai (3.12), `st_reparse_tag` = `IO_REPARSE_TAG_MOUNT_POINT` ;
    `os.walk` y entre, **`git ls-files --others` liste ce qu'elle contient** (un dossier hors du
    dépôt) ; `LocalSource` le listait, et `read_text` le refusait ensuite (hors de la source) :
    un faux projet « introuvable, illisible ou trop gros » ;
  - **un sous-module non initialisé** (un clone sans `--recurse-submodules`) : git liste le
    dossier (vide) ; dans ce dossier, `git ls-files` répond `./` : `LocalSource` y entrait sans
    fin (**`RecursionError`**). Un sous-module rempli est bien lu ; sous `vendor/`, il est
    ignoré (`IGNORED_DIRS`) ;
  - **les encodages** : un `requirements.txt` écrit par `>` de PowerShell 5.1 (UTF-16 LE, BOM,
    CRLF) donnait « n'est pas une dépendance valide » à chaque ligne ; un `package.json` en UTF-16,
    « JSON invalide ». **Le BOM UTF-8**, essayé sur chacun des fichiers de dépendances des
    mini-projets : TOML (`pyproject.toml`, `Pipfile`, `poetry.lock`, `uv.lock`, `Cargo.toml`,
    `Cargo.lock`), `requirements*.txt`/`.in`, `go.mod`, `go.work`, `Pipfile.lock`, `yarn.lock`
    v1, `.nvmrc`, `.python-version` ne se lisaient plus ; JSON, XML, Gemfile, Gradle passaient.
    Après : aucun écart, en BOM comme en UTF-16 (et un test le garde). Un `composer.json` ou un
    `requirements.txt` en cp1252, un `pom.xml` en ISO-8859-1 : lus (les accents ne sont que
    dans des commentaires) ;
  - **le réseau** (httpx 0.28.1, truststore 0.10.5, un serveur HTTPS local signé par une
    autorité de test faite avec l'openssl de Git, et un proxy `CONNECT` écrit pour l'essai, rien
    d'installé) : httpx seul refuse l'autorité inconnue ; avec `SSL_CERT_FILE`, il accepte le
    serveur local mais **refuse pypi.org** (le fichier remplace `certifi`) ; truststore passe
    pypi.org, refuse le serveur local avec le message de Windows (en français) ; truststore +
    `load_verify_locations` passe les deux. Par le proxy de `HTTPS_PROXY` : `CONNECT pypi.org:443`
    reçu, `NO_PROXY=127.0.0.1` suivi, `trust_env=False` le contourne ; un proxy injoignable :
    `ConnectError` (« pypi.org injoignable », comme sans réseau). `urllib.request.getproxies()`
    ne voit aucun proxy du système ici. Le refus d'un certificat est un
    `ssl.SSLCertVerificationError` sous la `ConnectError`, avec `verify_message` ;
  - **Argos**, cache vide (`forceupdate scan --no-cache`, `uv run` compris) : 1 445 fichiers
    listés en 0,22 s, inventaire en 0,22 s ; **3,2 s** pour 86 directes (83 paquets, PyPI et
    npm) et 569 dépendances passées à OSV ; **7,4 s** avec `--transitive` (570 vérifiées auprès
    des registres) ; aucun « non concluant ». Argos n'a pas 500 directes : les 570 de
    `--transitive` en tiennent lieu, bien sous les 30 s ;
  - **un outil qui dépasse son délai, de bout en bout** : `local.apply` sur une copie de
    `vulnerable` avec le vrai npm et `lockfiles.Tools(timeout=0.3)` : « n'a pas fini », l'arbre
    tué, la main rendue en 0,5 s, `package.json` remis, aucun `npm-cli` restant (le délai
    minimal des réglages est 10 s : passé par le moteur).
- **Organisation** :
  - `processes.py` (nouveau) : `run` (comme `subprocess.run`, sans shell, plus `cancel`),
    `kill_tree`, `Interrupted` ; sous Windows `taskkill` par son chemin (`%SYSTEMROOT%`), ailleurs
    une session (`start_new_session`) et `killpg`. Tous les lancements y passent : outils de
    lockfile (`lockfiles._spawn`), git (`forges.git._spawn`, `update.git`, `git ls-files` de
    `sources.local`), `gh` (`github._run`) ;
  - `update/lockfiles.py` : `regenerate(cancel=)`, `_Context.cancel` ; interrompue, elle remet
    le groupe en cours **et les manifestes des groupes pas encore lancés** (`_undo_written` ;
    avant, ils restaient réécrits sans leur lockfile) ; `local.apply(cancel=)`,
    `forge.deliver(cancel=)` ; `web/jobs.py` : `Jobs.stopping`, levé par `close` ;
  - `update/writers` : `write` remet aussi les fichiers déjà écrits sur Ctrl+C (`_put_back`) ;
    le BOM reste, les emplacements se placent dans le texte sans lui ; UTF-16 refusé ;
  - `detect/manifests.py` : `decode_text`, `text_encoding`, `BOM` ; `find_projects(notices=)` ;
  - `sources/local.py` : `_Listing` (plafond, jonctions, sous-modules), `_is_junction` ;
    `Source.notices` ; `models.Report.notices` (JSON : champ ajouté, `schema_version` reste 1) ;
    `report/` : « Remarques sur la source » (terminal, Markdown) ;
  - `net/http.py` : `ssl_context` (truststore + `SSL_CERT_FILE`/`SSL_CERT_DIR`),
    `_certificate_error` (par `__cause__` et `__context__`, sans reboucler), pas de reprise ;
  - `web/app.py` : `_break_as_interrupt` ; `cli.py` : « interrompu : ce qui n'était pas fini est
    remis comme avant » (code 2) ;
  - front : l'alerte « Analyse partielle : la source n'a pas été lue en entier » (écran 4, comme
    l'arborescence tronquée d'une forge) et ces remarques en tête de « Remarques »
    (`SourcePlace` : « Le dossier analysé » pour `.`) ; `design-system/ECRANS.md` le dit.
- **Tranché** :
  - **`truststore`** (justification de la dépendance, décidée à la session 29) : sans lui, un
    proxy d'entreprise qui déchiffre le trafic fait tout échouer (son autorité est dans le
    magasin du système, pas dans `certifi`), et `SSL_CERT_FILE` seul casse les autres hôtes ;
    c'est ce que fait pip (par défaut depuis 24.2). Pur Python, sans dépendance, MIT, déjà dans le
    `uv.lock` (par `httpx2`, en dev) ; 0.10.5 publié le 2026-10-12. Sous Linux, truststore suit
    OpenSSL, qui lit lui-même `SSL_CERT_FILE` à la place de son magasin (dit dans la doc) ;
  - un certificat refusé n'est pas réessayé (rien n'y changerait) et l'hôte est abandonné,
    comme un hôte injoignable ; le message dit « derrière un proxy d'entreprise, donner son
    autorité par SSL_CERT_FILE » ;
  - le proxy des réglages de Windows (WinINet, PAC) n'est pas lu : comme uv, `HTTPS_PROXY`
    seulement (pour la doc) ;
  - **une mise à jour interrompue garde ce qui est fini** : les groupes dont l'outil a tourné
    restent (cohérents : manifeste et lockfile) ; le groupe en cours et ceux qui n'ont pas
    tourné sont remis, comme pour l'échec d'un outil ;
  - **l'arrêt du serveur tue l'outil en cours** (`Jobs.stopping`) au lieu d'attendre sa fin :
    c'était déjà le cas par Ctrl+C sous Windows (la console l'atteint) ; ailleurs, l'outil est
    dans sa propre session et Ctrl+C ne l'atteint plus : c'est `cancel` qui le tue. Les
    commandes git d'un envoi ne reçoivent pas `cancel` : E31 (arrêt pendant un envoi) ;
  - le BOM ne compte pas dans les colonnes (comme dans un éditeur) ; les parseurs JSON gardent
    leur `removeprefix(BOM)` (sans effet désormais) ;
  - une source peut dire ce qu'elle n'a pas pu lister (`Source.notices`) ; les sources des forges
    n'en ont pas encore (un sous-module d'un dépôt est une entrée `commit` de l'arborescence,
    sautée sans rien dire : ajouté à E31) ;
  - pas d'essai derrière un vrai proxy d'entreprise : aucun sous la main ; un proxy `CONNECT` et
    une autorité de test l'ont remplacé (l'installation d'un mitmproxy n'a pas été demandée).
- **Trouvé** : le heredoc mange toujours les barres obliques inverses (deux fois) : les scripts
  sont écrits avec l'outil d'écriture ; l'outil d'écriture change bien `﻿` en caractère
  (écrire `\N{ZERO WIDTH NO-BREAK SPACE}`) ; respx relève l'exception d'un `side_effect` depuis
  la sienne (`SideEffectError`), ce qui écrase sa cause et fait **reboucler la chaîne** :
  `_certificate_error` tournait sans fin (le test se bloquait) ; il ne voit plus chaque
  exception qu'une fois, et le test passe par `HttpClient._send` ; le test du vrai `_spawn` de
  `test_lockfiles.py` utilisait `monkeypatch.undo()` (interdit) : il prend la fonction à
  l'import ; le test Playwright « vider le cache » attendait « vide » juste après le
  vidage : une analyse d'un autre test (serveur partagé) y avait déjà remis une réponse ; il
  compare désormais au nombre d'avant.
- **Tests** : `test_processes.py` (8 : un arbre Python dont le petit-enfant tient la sortie ;
  délai, `cancel`, sans shell, `taskkill` du système) ; `test_robustness.py` (décodage, **chaque
  fichier de dépendances des mini-projets en BOM et en UTF-16**, la réécriture avec BOM et en
  UTF-16, Ctrl+C pendant l'écriture et pendant un outil, `cancel`, l'arrêt du serveur pendant
  un outil, les remarques sur la source dans les trois rapports et le JSON) ; dans
  `test_sources.py` (jonctions, boucle de jonction, sous-modules, plafond avec et sans git,
  encodages), `test_net_http.py` (contexte TLS, `SSL_CERT_FILE` illisible, certificat refusé
  sans reprise, chaîne qui reboucle), `test_web_server.py` (Ctrl+Break, Windows : sans la
  correction, pytest sort en code 3), `test_cli.py` (Ctrl+C pendant `update`),
  `test_lockfiles.py`. Front : `ReportView.test.tsx` (la source lue en partie) ; les trois
  rapports d'exemple ont `notices`. 4 761 tests Python verts (plus 21 réseau, avec les vrais
  outils, tous lancés par `processes.run`), 163 Vitest, 67 Playwright ; la suite Python prend
  4 min 26 au calme (4 min 24 au début de la session : rien de lent n'a été ajouté, sauf les
  délais réels de `test_processes.py`, 2 à 3 s chacun ; le plus long, 4,2 s :
  `test_endoflife_down_is_inconclusive`). Vérifié aussi dans le navigateur (le serveur hors
  ligne des tests, le clone au sous-module vide) : l'alerte en clair et en sombre, à 1440 et
  375 px, sans débordement ni erreur de console.
- **Limites** (pour la doc, E35) : au-delà de 200 000 fichiers, la source est coupée (dans
  l'ordre de git, ou du parcours) ; un fichier en UTF-16 se lit mais ne se réécrit pas ; un
  descendant d'un outil qui sort de son arbre (un démon) n'est pas tué ; le proxy des réglages
  de Windows n'est pas lu ; sous Linux, `SSL_CERT_FILE` remplace le magasin du système
  (OpenSSL) ; un fichier qui n'est pas de l'UTF-8 se lit, ses octets illisibles remplacés, mais
  ne se réécrit pas.

### E31 — Forges : robustesse

Venue de E30, découpée à la session 30 avec l'accord de l'utilisateur (E31 à E35 de départ
deviennent E32 à E36).

- [x] Depuis E16 :
  - tokens GitHub qui expirent : **tranché avec l'utilisateur (session 29) : ils restent sans expiration** (décision n°13, comme `gh`) ; la doc le dit (E35). Pour mémoire, les faire expirer demanderait de garder le `refresh_token` (8 h pour le token, 6 mois sans usage pour le `refresh_token`), de le renouveler une seule fois à la fois, et de traiter `bad_refresh_token` ;
  - le trousseau sous Linux sans Secret Service (serveur, WSL) : **tranché avec l'utilisateur (session 31) : la doc seulement**, pas de repli à nous. La connexion est refusée avec la raison (`keyring` dans `GET /api/accounts`), qui dit désormais aussi `PYTHON_KEYRING_BACKEND` ; la doc (E35) dit comment installer un Secret Service, ou choisir un autre trousseau par le mécanisme de keyring (voir les notes).
- [x] Depuis E18 (les PR) :
  - un arrêt du serveur pendant un envoi : **tranché avec l'utilisateur : il l'arrête aussitôt** (l'outil et git tués, les dépôts qui restent ne partent pas, la console le dit) ; une branche poussée sans sa PR est reprise par l'envoi suivant (testé) ; les dossiers laissés par un arrêt brutal sont effacés au démarrage (`web/workdirs.py`, nouveau : tout ce que le serveur range est dans son dossier verrouillé) ;
  - une PR fermée sans fusion : **tranché avec l'utilisateur : le récapitulatif le demande** (la dernière PR de forceupdate, fermée sans fusion : signalée, avec sa date et son lien, et le dépôt pas coché ; l'envoyer en ouvre une nouvelle). `Forge.closed_request`, rien de gardé sur la machine ;
  - `url.<base>.insteadOf` : **ignoré pour nos commandes** (une règle de l'adresse vers elle-même, et `pushInsteadOf`), et le token ne va qu'à l'hôte attendu, en `https`.
- [x] Depuis E20 (Bitbucket) :
  - un refresh token inutilisé pendant 3 mois : **pas reproductible** (et pas dans la spécification d'Atlassian) ; un refresh token refusé passait déjà le compte en `problem` (« se reconnecter », la raison dite) ; chaque usage le renouvelle (2 h). Rien de plus à faire : une carte ne se voit que serveur lancé, et la lancer renouvelle (voir les notes) ;
  - les droits d'écriture par un groupe : la spécification dit que `…/permissions/repositories` rend la permission **effective**, sans distinguer les droits explicites et implicites ; pas vérifiable en vrai (un seul compte, propriétaire de son seul workspace) : noté pour la recette (E36) et la doc (E35) ;
  - le coût du `fetch` de `git.remote_tree` : **mesuré** (cpython, Bitbucket) ; une branche faite sur une branche par défaut plus ancienne n'est plus lue (son contenu diffère : on pousse sans le `fetch`, le plus coûteux).
- [x] Depuis E30 :
  - un sous-module d'un dépôt (entrée `commit` de l'arborescence) : dit (`Tree.submodules`, `ForgeSource.notices`, « sous-module git : pas analysé (un autre dépôt, à analyser à part) »), aussi dans un clone (`ClonedSource`) ;
  - les commandes git d'un envoi reçoivent `cancel` (`Forge.cancel`, posé par `forges.client` : `Jobs.stopping`), avec la première case de E18.

**Fini quand** : chaque case a ses tests, ou une décision notée (la doc, E35) ; vérifié avec
les dépôts de test des forges, sans toucher à leurs PR et MR (recette, E36).

**Notes** (session 31) :

- **Commit d'abord** : E30 commitée seule (`a4f500a`, `E30 : robustesse et performance`), avec
  l'accord de l'utilisateur. **Trois décisions posées à l'utilisateur** avec options et
  recommandation, avant d'écrire : le trousseau sous Linux (**la doc seulement** : pas de fichier
  à nous ; en clair comme `gh --insecure-storage`, ou chiffré avec une phrase de passe, refusés),
  une PR fermée sans fusion (**le demander dans le récapitulatif**, plutôt que retenir le refus
  par version comme Dependabot, ou ne rien faire), l'arrêt pendant un envoi (**arrêter tout de
  suite**, plutôt que finir le dépôt en cours). Décision n°14 du brief complétée.
- **Vérifié en vrai** avant d'écrire (2026-11-02, Windows 11, git 2.52) :
  - `git config --get-regexp url\.` : rien chez l'utilisateur. Avec une configuration globale de
    test (`GIT_CONFIG_GLOBAL` dans le scratchpad) et un dépôt « bare » local : une règle
    `insteadOf` qui réécrit le début de notre adresse la détourne (« Please make sure you have
    the correct access rights ») ; `-c url.<adresse>.insteadOf=<adresse>` (vers elle-même) la
    neutralise, la plus longue gagnant, sans boucle ; le push suit `pushInsteadOf` (la règle
    `insteadOf` seule ne le neutralise pas) : il faut les deux ; une règle de la personne sur
    l'adresse exacte gagne à égalité (la première lue). Sur GitHub (dépôt public, en lecture) :
    avec `url."git@github.com:".insteadOf https://github.com/`, `ls-remote --get-url` donne
    `git@github.com:octocat/Hello-World.git` et échoue (SSH en `BatchMode`) ; avec nos règles,
    il passe en HTTPS. D'où aussi le helper qui ne donne le token qu'à `protocol=https` et à
    l'hôte de l'adresse (`git credential fill` : rien pour `mirror.example`, ni en `http` ; le
    port compris pour une instance) ;
  - **les sous-modules** : GitHub (`boostorg/boost`, `git/trees/master?recursive=1`, 446 entrées
    dont 173 `type: commit`, `mode: 160000`, sans adresse) ; GitLab (`inkscape/inkscape`,
    `repository/tree?path=share` : `type: commit`, `mode: 160000`) ; Bitbucket : l'attribut
    `subrepository` d'un `commit_file` (spécification ; pas de dépôt public à sous-module sous la
    main). Les trois forges simulées des tests les avaient déjà ;
  - **le `fetch` de `git.remote_tree`** (clone `--depth 1`, puis `fetch --depth 1` d'un commit,
    dépôts publics de GitHub, en lecture) : django (13 Mo) : 38 objets et ~140 Ko à 5 commits de
    `main`, ~5 Mo à 300 commits ; cpython (37 Mo, clone en 4,0 s) : 0,9 s et 480 Ko à 5 commits,
    2,4 s et 20 Mo à 300. Le coût suit ce qui a changé depuis la base de la branche : faible quand
    on relance sans que `main` ait bougé, lourd quand il a avancé (le cas courant d'une relance),
    et inutile alors (le contenu diffère forcément). Sur le dépôt de test de Bitbucket : clone
    2,8 s, `fetch` 1,3 s (surtout la latence) ;
  - **Bitbucket** : la spécification OpenAPI d'Atlassian (téléchargée) ne dit rien de la durée
    d'un refresh token ni de 3 mois (seule la page « refresh tokens » : « Our access tokens
    expire in one hour », 2 h en vrai depuis E20) ; un fil de la communauté (2022) dit qu'ils
    n'expirent pas. `/user/workspaces/{ws}/permissions/repositories` : « for each repository the
    caller has explicit access to … their effective permission — the highest level … does not
    distinguish between explicit and implicit privileges » ; `role=contributor` : « explicit write
    access ». Une PR n'a pas de `closed_on` ; `pullrequests` accepte plusieurs `state=` ;
  - **le trousseau sans Secret Service** : pas de Linux sous la main (WSL n'a que la distribution
    de Docker Desktop, arrêtée ; pas démarrée). Lu dans keyring 25.7 : sans backend, `fail.Keyring`
    lève `NoKeyringError` (« No recommended backend was available… »), que `Accounts.unavailable`
    attrape ; essayé avec `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring` : le message de
    refus sort. keyring choisit son backend par `PYTHON_KEYRING_BACKEND` ou `keyringrc.cfg` ;
  - **le dossier temporaire de l'utilisateur** : 773 dossiers `forceupdate-*` (127 Mo), dont 662
    `forceupdate-depot-*` qui n'ont plus que `clone/.git/objects/pack/*` en lecture seule :
    `Jobs._remove` (`shutil.rmtree(ignore_errors=True)`) les sautait sous Windows. Toute analyse
    clonée d'un dépôt (arborescence tronquée) laissait son clone, en vrai aussi.
- **Organisation** :
  - `forges/git.py` : `_HELPER` lit `protocol=` et `host=` sur son entrée, ne répond que pour
    `https` et `FORCEUPDATE_GIT_HOST` (l'hôte de l'adresse, port compris) ; `_git(remote=,
    cancel=)` ajoute `url.<adresse>.insteadOf` et `pushInsteadOf` vers elle-même ; `clone`,
    `push`, `remote_tree` prennent `cancel` ; `parents` (nouveau) ; `Workspace(parent=)` ;
  - `processes.run` : `cancel` déjà levé, rien n'est lancé (un push local finissait avant
    `taskkill`) ;
  - `forges/base.py` : `Tree.submodules`, `ChangeRequest.closed_at`, `BranchCommit.parents`,
    `Forge.cancel`, `Forge.closed_request` (11e méthode abstraite) ; `forges.client(cancel=)` ;
    GitHub, GitLab, Bitbucket : `closed_request` (la dernière PR de la branche, tous états, si
    fermée sans fusion), les sous-modules de `tree`, `cancel` à git ; Bitbucket : `branch_tree`
    ne fait plus le `fetch` d'une branche qui ne part pas du même commit que le clone ;
  - `sources/forge.py` : `SUBMODULE`, `ForgeSource.notices`, `ClonedSource.SUBMODULE` ;
    `sources/local.py` : `LocalSource.SUBMODULE`, `_Listing(submodule=)` ;
  - `update/forge.py` : `INTERRUPTED`, `deliver` attrape `processes.Interrupted` ;
    `web/proposals.py` : `Proposed.closed` (pas coché), `_existing` cherche la PR fermée sans
    PR ouverte, `_send` s'arrête avec `Jobs.stopping` (les dépôts restants : `INTERRUPTED`),
    `closing` (la console) ; `web/jobs.py` : `Jobs.workdirs`, `temp_dir`, le balayage dans un
    thread au démarrage, `in_updates` lève `Interrupted` une fois l'arrêt lancé, `_remove` par
    `git.remove_tree` (qui ignore un fichier déjà parti), `Worker._close` attend les threads de
    sa boucle (`SHUTDOWN_WAIT`) ; `web/workdirs.py` (nouveau) : `Workdirs` (un dossier
    `forceupdate-ui-*` verrouillé, `msvcrt.locking` ou `flock`), `sweep` ; `web/app.py` :
    `Settings.temp_dir`, `proposals.closing()` à l'arrêt ; `routes/files.py` : l'envoi dans le
    dossier du serveur ; `web/schemas.py` : `ProposedRepository.closed` ; `web/repositories.py` :
    les forges du serveur ont `cancel=jobs.stopping` ; `forges/accounts.py` : le message du
    trousseau dit `PYTHON_KEYRING_BACKEND` ;
  - front : l'écran 8 (`ProposalPage.tsx`) : le badge d'avertissement « PR #3 fermée sans
    fusion », la phrase avec la date, le lien sur sa ligne ; `design-system/ECRANS.md` le dit.
- **Tranché** :
  - **pas de repli à nous pour le trousseau** (avec l'utilisateur) : un fichier chiffré a besoin
    d'une clé, posée à côté (du masquage) ou demandée à chaque lancement (ce que fait déjà
    `keyrings.cryptfile`, maintenu) ; keyring sait déjà prendre un autre backend
    (`PYTHON_KEYRING_BACKEND`, `keyringrc.cfg`) : `uv tool install forceupdate --with
    keyrings.cryptfile`. Pour la doc (E35) ;
  - **l'arrêt pendant un envoi** (avec l'utilisateur) : tout est tué (outil, clone, `fetch`,
    push) ; un push tué en route a poussé, ou pas (la forge change la branche d'un coup) ; le
    dépôt en cours échoue avec `INTERRUPTED`, ceux qui restent aussi, sans partir ; le
    `logger.warning` « envoi des PR en cours : interrompu… » sort sur la console (le même chemin
    que celui d'une mise à jour locale à E30). Les analyses clonées s'arrêtent de même ;
  - **une PR refusée** (avec l'utilisateur) : la **dernière** PR de forceupdate du dépôt (vers la
    branche par défaut, du dépôt même) décide : fermée sans fusion, on demande ; fusionnée ou
    ouverte depuis, plus rien. Une requête de plus par dépôt au récapitulatif, seulement sans PR
    ouverte ; si la forge ne répond pas, rien n'est signalé (comme la PR ouverte). La branche,
    restée sur la forge, est reprise telle quelle (même contenu : rien poussé) ;
  - **`insteadOf`** : neutralisé plutôt que dit (le cas courant, GitHub par SSH, aurait bloqué les
    développeurs qui l'utilisent) ; la configuration de la personne reste gardée pour le reste
    (proxy, certificats) ;
  - **le dossier de travail du serveur** : un seul, `forceupdate-ui-*`, où vont les fichiers des
    analyses de dépôts (`depot-*`), les fichiers envoyés (`envoi-*`) et les clones des PR
    (`pr-*`) ; verrouillé tant que le serveur tourne (le système relâche le verrou à sa mort, même
    brutale), effacé à l'arrêt ; au démarrage, ceux dont personne ne tient le verrou sont effacés,
    dans un thread (il peut y en avoir beaucoup) ; un dossier sans verrou de moins de 60 s est
    laissé (un serveur qui naît), un fichier encore ouvert le laisse pour le démarrage suivant.
    Jamais celui d'un autre serveur qui tourne. Les anciens dossiers `forceupdate-depot-*`,
    `forceupdate-pr-*` et `forceupdate-<x>` (d'avant E31) ne sont pas balayés : seules des
    versions de développement en ont fait (la 0.1.0 publiée n'a pas `ui`), et `forceupdate-<x>`
    est aussi le préfixe des dossiers d'une commande `update` qui tourne peut-être ;
  - **Bitbucket, refresh token** : rien de plus. Le dire « avant » dans la carte n'a pas de sens
    (la carte ne se voit que serveur lancé, et l'afficher renouvelle le token) ; renouveler « de
    temps en temps » non plus (serveur arrêté, rien ne tourne) ; refusé, le compte dit déjà
    « Bitbucket ne renouvelle plus le token (accès retiré à forceupdate, ou resté trop longtemps
    sans servir) : se reconnecter » ;
  - **le `fetch` de Bitbucket** : gardé quand la branche part du même commit que le clone (le
    seul cas où le contenu peut être le même ; cher seulement si les fichiers changés sont gros),
    sauté sinon. Si Bitbucket ne rend pas tous les commits de la branche (`ahead` au-delà de
    30), on ne sait pas d'où elle part : le `fetch` reste.
- **Trouvé** : un heredoc a encore mangé les barres obliques inverses d'un script (CLAUDE.md le
  dit) ; le garde-fou git des tests prenait une valeur de `-c` (`url.file:///…insteadOf=…`) pour
  une adresse : il saute désormais les valeurs de `-c` (l'adresse est aussi un argument à part) ;
  dans `deliver`, le clone a déjà le commit de forceupdate quand on lit l'arbre de la branche :
  c'est le parent de `HEAD` qu'il faut comparer (`git.parents`), pas `HEAD` (un test l'a vu) ;
  un balayage qui échoue sur un fichier ouvert efface d'abord le `.lock` : le dossier attend
  alors 60 s ; **une course à l'arrêt**, vue par la suite complète (pas seule) : la tâche d'envoi
  annulée laissait le nettoyage de son clone tourner dans un thread pendant que
  `Workdirs.close` effaçait le même dossier (`WinError 2`, le dossier restait) : l'arrêt de la
  boucle des analyses attend ses threads (`shutdown_default_executor`, 30 s au plus), et
  `remove_tree` ignore un fichier déjà parti ; **axe-core** a refusé le lien de la PR fermée
  placé dans la phrase (`link-in-text-block` : il ne s'en distinguait que par sa couleur) : il est
  sur sa propre ligne, comme les autres liens externes ; une suppression `rm -rf "$VAR/run"` a été refusée
  par le contrôle de sécurité de l'outil (chemin non résolu) : un chemin écrit en entier.
- **Tests** : `test_forges_git.py` (le token pour le seul hôte, ni `http` ni un autre hôte, le port
  d'une instance ; `insteadOf` et `pushInsteadOf` d'une configuration globale de test ignorés
  pour le clone, le `fetch` et le push ; `cancel` : rien lancé, rien poussé) ;
  `test_forges_requests.py`, `test_forges_gitlab.py`, `test_forges_bitbucket.py` (`closed_request`
  : jamais, fermée, puis fusionnée ou ouverte depuis ; le clone arrêté par `Forge.cancel` ;
  Bitbucket : la branche faite sur un `main` plus ancien n'est pas lue, sur le même `main` elle
  l'est) ; `test_forges_github.py` (la 11e méthode, `client(cancel=)` pour les trois) ;
  `test_sources_forge.py` (un sous-module dit, pour les trois forges, pas sous `vendor/`) ;
  `test_sources.py` (le sous-module d'un clone : la remarque de la forge) ;
  `test_update_forge.py` (la branche poussée sans PR reprise ; l'arrêt pendant le clone et
  pendant l'outil : rien poussé, `INTERRUPTED`) ; `test_web_proposals.py` (la PR fermée sans
  fusion dite et pas cochée, l'envoyer en ouvre une nouvelle ; **Ctrl+C pendant un envoi, de bout
  en bout** : npm tué, rien poussé, le deuxième dépôt pas parti, la console le dit, le dossier de
  travail effacé ; les forges du serveur ont `stopping`) ; `test_web_workdirs.py` (nouveau :
  verrou et effacement, **le dossier d'un vrai processus Python mort balayé, celui d'un vivant
  gardé**, un dossier sans verrou jeune ou vieux, le balayage au démarrage et l'effacement à
  l'arrêt, un fichier envoyé dans le dossier du serveur, un clone en lecture seule effacé, un
  fichier ouvert laissé pour plus tard) ; `test_forges_accounts.py` (le message du trousseau).
  **Huitième garde-fou** (`conftest.py`, `server_temp`) : le serveur ne range ni ne balaie rien
  dans le dossier temporaire de la personne. Front : `Proposals.test.tsx` (la PR fermée : badge,
  date, lien, pas cochée, l'envoyer) ; Playwright : `forges.spec.ts` (écran 8 avec une PR
  fermée, la réponse du vrai serveur retouchée en route, axe-core en clair et en sombre à 1440 et
  375 px). 4 789 tests Python verts (plus 21 réseau, avec les vrais outils), aussi sous 3.11 pour les nouveaux ; 164 Vitest ; 71 Playwright (4 de plus), sans erreur de console. La suite Python a pris 13 min 22 sur une machine chargée (un autre programme, très gourmand, tournait) ; ses tests les plus longs comme à E30 (4,5 s au plus) : rien de lent n'a été ajouté. Vérifié aussi à l'œil : la carte de la PR fermée en clair et en sombre, à 1440 et 375 px (captures).
- **Vérifié avec les vrais comptes** (lecture seule ; rien poussé ; la PR #1 et la MR !1 pas
  touchées) : les trois dépôts de test : la PR (MR) ouverte trouvée, `closed_request` à `None`
  (la dernière est ouverte), la requête acceptée par les trois forges (`state=all`, tris,
  plusieurs `state=` chez Bitbucket), aucun sous-module ; des PR fermées sans fusion de dépôts
  publics trouvées avec leur date (`cli/cli` #14837, GitHub ; `gitlab-org/gitlab-runner` !7695,
  GitLab) ; Bitbucket : le premier commit de la branche a pour parent le `main` actuel, l'arbre lu
  (`branch_tree` 1,6 s, `fetch` seul 1,3 s, clone 2,8 s) ; le dépôt privé de GitHub cloné par le
  token malgré `url."git@github.com:".insteadOf` (git seul aurait pris
  `git@github.com:Pauzzle-ozz/forceupdate-demo.git`) ; `boostorg/boost` lu par l'API : 173
  remarques de sous-modules. Les tokens de GitLab et de Bitbucket ont été renouvelés au passage
  (rangés dans le trousseau, comme à l'usage). **Avec l'accord de l'utilisateur**, les 773
  dossiers `forceupdate-*` d'avant E31 effacés de son dossier temporaire (89 Mo de fichiers) ;
  restent les `forceupdate-e2e-*` du serveur des tests de bout en bout (case de E35).
- **Limites** (pour la doc, E35) : une règle `insteadOf` de la personne sur l'adresse exacte du
  dépôt l'emporte (git va ailleurs, sans le token : échec « la forge refuse le token ») ; un
  sous-module n'est pas analysé (l'analyser à part) ; une PR refusée n'est signalée que si c'est
  la dernière de la branche, et que la forge répond ; les droits d'écriture par un groupe sur
  Bitbucket ne sont vus que d'après la spécification ; un envoi interrompu ne se voit qu'à la
  console (les récapitulatifs ne survivent pas au serveur) ; le dossier d'un arrêt brutal reste
  jusqu'au démarrage suivant (et un fichier encore ouvert par un git orphelin, jusqu'au
  suivant) ; sous Linux sans Secret Service, pas de compte sans un autre trousseau.

### E32 — Mise à jour : le npm du projet, Python, NuGet, Go

- [x] Depuis l'essai de l'utilisateur (une PR sur un de ses dépôts, après E23) : **le lockfile est régénéré par le npm de la machine, pas par celui qu'attend le projet**. npm 11 (Node 24, sur la machine) n'écrit plus certains paquets facultatifs (`ws`, `zod`, `devtools-protocol` de puppeteer ; `@emnapi/*` de Tailwind) que npm 10 exige : `npm ci` de la CI du dépôt (Node 22, npm 10) a refusé les deux lockfiles de la PR (« Missing: … from lock file »), avant tests et lint ; vérifié sur la branche : `npm ci` passe avec npm 11, échoue avec npm 10. À faire :
  - lire la version attendue, dans cet ordre : `packageManager` (`npm@10.9.0`), `devEngines.packageManager`, `engines.npm` ; sinon la version de Node du projet (depuis E27, dans `Project.runtimes` : `checks.runtimes.project_runtime`, plutôt que de relire `engines.node`, `.nvmrc`, `.node-version`) puis la `node-version` de `actions/setup-node` dans `.github/workflows/*.yml` (la plus basse s'il y en a plusieurs), traduite en npm par la version livrée avec Node (Node 18 et 20 : npm 10 ; Node 22 : npm 10 ; Node 24 : npm 11 ; table à revérifier sur nodejs.org le jour venu) ; rien de tout cela : ne rien dire ;
  - comparer à la majeure du npm installé (`npm --version`, une fois par plan, comme `_poetry_major`) ; si elle diffère : le dire dans le plan (« npm 11 ici, le projet attend npm 10 : le lockfile risque d'être refusé par `npm ci` de la CI »), et régénérer avec la version attendue (`npx -y npm@10 install --package-lock-only --ignore-scripts…`, sans toucher au npm de la machine), avec l'accord de la personne : une case dans le plan, **cochée d'office (décidé avec l'utilisateur, session 29)** ;
  - après la régénération, vérifier avec le npm attendu (`npx -y npm@10 ci --dry-run --ignore-scripts`) : un refus est dit dans le résultat, avec la commande qui le reproduit ;
  - la même question pour pnpm et Yarn (`packageManager`, corepack les lance déjà à la bonne version : le vérifier), et pour les PR des forges (le clone a la CI du dépôt : même lecture) ;
  - un test qui reproduit le cas (un `package.json` et une CI en Node 22, un npm 11 simulé : l'avertissement, puis `npx npm@10`), et un test `network` avec les deux vrais npm.
- [x] Workspace npm (venu de la robustesse) : une indirecte d'un membre, retenue par une version forcée de la racine. E11 lance `npm update x --workspaces --include-workspace-root` et la relecture dit si la cible n'est pas atteinte, mais le cas n'a pas pu être reconstitué : le vérifier sur un vrai workspace.
- [x] `requirements.txt` générés sans `.in` à côté (`uv export`, `poetry export`, `pdm export`, `pip-compile pyproject.toml`) : depuis E03, ils restent des manifestes et tous leurs paquets sortent comme directes. Les reconnaître (en-tête « autogenerated by pip-compile / uv », commentaires `# via`) et les traiter comme des lockfiles du manifeste du projet.
- [x] Une ligne de `requirements` à empreintes (`--hash`) : depuis E10, la réécriture la refuse, mais le planificateur ne le sait pas et pré-coche quand même l'option. Le marquer à l'analyse, pour que l'option soit `manual` (jamais pré-cochée, avec la raison).
- [x] Depuis E26 : une indirecte NuGet en faille ne monte pas en régénérant (NuGet prend la plus basse version qui convient) : l'option est « à la main ». L'appliquer : ajouter au projet la `PackageReference` (ou, avec la gestion centrale, la `PackageVersion` et `CentralPackageTransitivePinningEnabled`), une réécriture qui insère un élément, relue comme les autres.
- [x] Depuis E22 (Go) : `vendor/` n'est pas refait après `go mod tidy` (le plan le dit) : proposer `go mod vendor`, avec de quoi remettre `vendor/` en cas d'échec.
- [x] Depuis E23 (PHP) : avec Composer 2.9, le blocage des versions à faille ne se lève que par `config.audit.block-insecure` : le dire dans le plan quand le Composer installé est un 2.9 (`composer --version`).

**Fini quand** : sur une copie d'un projet dont la CI est en Node 22, une mise à jour faite avec
npm 11 installé donne un lockfile que `npm@10 ci` accepte ; les autres cases ont leurs tests et
sont vérifiées avec le vrai outil.

**Notes** (session 32) :

- **Commit d'abord** : E31 était déjà commitée (`44d5183`) ; `PROCHAINE_SESSION.md`, corrigé après
  ce commit, part avec E32.
- **Vérifié en vrai** avant d'écrire (2026-11-02), tout dans le scratchpad (caches de npm, uv, PDM,
  Poetry, NuGet, Go et Composer compris) :
  - **la table Node → npm** (`nodejs.org/dist/index.json`) : Node 22 → npm 10 (10.9.9 pour la
    22.23.4), Node 24 → npm 11 (11.19.1), Node 26 → npm 11 ; la majeure change en cours de ligne
    pour Node 16 (npm 8 dès la 16.11), 18 (npm 9 dès la 18.14, npm 10 dès la 18.19), 19, 20 (npm 10
    dès la 20.7) ; Node 27 n'a que des pré-versions (npm 12). Et **la LTS 26 a maintenant un nom :
    « Lithium »** (ajouté à `NODE_CODENAMES` ; le test `network` de la table reste à E34) ;
  - **`npx -y npm@10`** télécharge le dernier npm 10 (10.9.9) dans le cache de npx et le lance sous
    le Node de la machine (Node 24 : 11 s la première fois) ; npm 8 et 9 tournent aussi sous Node 24 et
    gardent un lockfile v3, mais **npm 7 le réécrit au format 2, npm 6 au format 1** (d'où
    `MIN_NPM = 8`) ;
  - **`npm ci --dry-run`** relit vraiment le lockfile (« Missing: zod@3.25.76 from lock file » sur un
    lockfile où l'on a retiré une entrée), sans rien installer (pas de `node_modules`) ; ses lignes
    « Missing » viennent avant l'aide de la commande (gardées en entier) ;
  - **l'élagage de npm 11 n'a pas pu être reproduit** sur des projets neufs (puppeteer, Tailwind 4,
    Vite 8, openai, Angular 20, un lockfile de npm 10 mis à jour par npm 11) : les rapports publiés
    (des PR de Dependabot) le décrivent pour des pairs facultatifs **imbriqués**, écrits par npm 10 puis
    retirés par npm 11, et **npm 11.6.2 (celui de la machine) élague même ce qu'exige npm 11.16** ;
    en revanche, **npm 11 ajoute des `"peer": true` que npm 10 retire** (devtools-protocol, vite,
    picomatch) : deux npm différents se disputent le fichier, et c'est le témoin du test `network` ;
  - **pnpm 12.15** (installé à part, pas par corepack) lance de lui-même la version de
    `packageManager` (« Done … using pnpm v9.15.9 ») ; sans `packageManager`, il garde le format
    `9.0` d'un lockfile de pnpm 9 (fichier identique) ; **corepack** lance `yarn@4.18.1` et
    `yarn@1.22.22` d'après `packageManager`, et refuse pnpm dans un projet Yarn. Rien à faire pour
    eux. (Un essai de pnpm a échoué sous un `PNPM_HOME` du scratchpad : 316 caractères de chemin,
    plus que les 260 de Windows ; un lecteur `subst` l'a contourné, retiré ensuite) ;
  - **les en-têtes** : `uv export` et `uv pip compile` (« autogenerated by uv via the following
    command », la commande telle que tapée : `--frozen` y passerait, `UV_FROZEN` non),
    `pip-compile` (« autogenerated by pip-compile with Python 3.12 … by the following command »),
    PDM (« @generated by PDM », sans la commande, dépendances de dev comprises par défaut),
    **Poetry : aucun en-tête** (des marqueurs `python_version` et des empreintes ; le groupe principal
    seul par défaut ; `poetry export` demande le plugin poetry-plugin-export à Poetry 2) ; les quatre
    refaits par forceupdate sans toucher à leur en-tête ;
  - **NuGet** (SDK 10.0.403) : la `PackageVersion` et `CentralPackageTransitivePinningEnabled` ajoutées
    donnent `CentralTransitive` 4.5.1 à System.Text.Encodings.Web ; sans gestion centrale, une
    `PackageReference` ajoutée donne `Direct` 4.7.2 ; le lockfile de l'autre projet du
    `Directory.Packages.props` n'a pas changé ici (mais l'épinglage le peut : il est régénéré) ;
  - **`go mod vendor`** (Go 1.27.3) : 141 fichiers pour le mini-projet `go`, sans rien compiler ; après
    `go mod tidy`, `go build` refuse (« inconsistent vendoring ») jusqu'à `go mod vendor` ;
  - **Composer 2.9.8** (le `composer.phar` de getcomposer.org, SHA-256 vérifiée, dans le scratchpad
    seulement) : `COMPOSER_POLICY_ADVISORIES_BLOCK=0` est ignoré (twig 3.4.3 refusé, « affected by
    security advisories »), seul `config.audit.block-insecure: false` le lève ;
  - **le workspace npm** : reconstitué (un membre tire minimist par mkdirp 0.5.5, la racine force
    minimist 1.2.5) : version forcée pour tout l'arbre et imbriquée (`"mkdirp": {"minimist": …}`),
    toutes deux réécrites et atteintes (minimist 1.2.8) ; **par référence (`"$minimist"`)**,
    l'indirecte était dite « à réécrire à la main » alors qu'elle suit la directe de la racine,
    proposée à côté : le message le dit maintenant.
- **Organisation** :
  - `update/project_npm.py` (ajouté : `NODE_NPM`, `MIN_NPM`, `Expected`, `declared`, `expected`,
    `npm_of_node`) ;
  - `parsers/runtimes.py` : `ci` (les workflows de GitHub Actions : `actions/setup-node`, `matrix`
    et `include`, `env`, `container` ; `.gitlab-ci.yml` et `bitbucket-pipelines.yml` : leurs `image`,
    les `variables` de GitLab) ; `detect/manifests.py` : `CI_FILES`, `CI_NAMES`, `ci_base` (un
    fichier de CI vaut pour tous les projets de son dossier) ;
  - `update/lockfiles.py` : `ExtraKind`, `Extra`, `Verified`, `decline` ; `Job.extra`, `accepted`,
    `launcher`, `doing`, `refreshes` ; `Regenerated.verified` ; `_Probes` (les versions d'outils,
    une fois par plan) ; `_project_npm`, `_go_vendor`, `_SavedFolders` (`vendor/` copié, remis sur
    un échec) ; `_Context.shown`, `verify`, `_execute` ; `_npm_complaint` ; `LockKind.UV_EXPORT`,
    `POETRY_EXPORT`, `PDM_EXPORT`, `_exports`, `_export`, `_uv_export_options`, `_exported_dev`,
    `_export_job` et leurs pilotes ; `_compiles_a_manifest` ; `_composer_warnings` selon la version ;
    `_readers` (une version centrale ajoutée) ; `_installed` (l'indirecte devenue directe) ;
  - `parsers/python.py` : `Generated`, `generated`, `MANIFEST_SOURCES`, `HASHED`,
    `_generated_requirements`, `_as_lockfile`, `_exports_lock` ; `models.Dependency.manual` ;
    `update/planner.py` : `Dependency.manual`, le `$` des versions forcées, `EditKind.REFERENCE`,
    `_msbuild_project`, `REFERENCE_WARNING` ;
  - `parsers/xml_spans.py` : `Element.end_line` ; `parsers/nuget.py` : `Item.end_line`,
    `Property.line` et `end_line`, `MsBuildFile.end_line`, `Central`, `central_management` ;
    `update/writers/` : `Target.insert` et `expects`, `nuget.reference_targets`, `_verify_inserted`,
    `_inserted_lines`, `_unranked`, `_key` ;
  - `update/local.py` : `Prepared.declining`, `touched` avec `vendor/` ; `update/git.py` : un dossier
    dans le garde-fou ; `update/forge.py` : `committable` avec `vendor/`, la description de la PR
    (le npm du projet, `vendor/`, la relecture) ; `sources/forge.py` : `ForgeSource.has`, le
    `vendor/modules.txt` d'un module Go téléchargé ; `cli.py` : `--no-extras` ; `report/` : la case
    et la relecture dans le terminal, « ajoutée en » ;
  - `web/` : `LockJob.extra` et `accepted`, `LockExtra` (avec la commande la case décochée),
    `LockResult.verified`, `ApplyRequest.declined`, `Plan.planned` et `decline` ; `openapi.json`,
    `schema.d.ts` ;
  - front (avec le skill `ui-ux-pro-max`) : écran 5, la case dans la carte d'un lockfile (étape
    Vérifier, `--primary-soft` cochée, le détail en `aria-describedby`, la commande qui suit la case),
    la relecture dans le résultat (`Verified` : accepté en vert, refusé en alerte avec la commande),
    « ajoutée en » à l'étape Choisir ; écran 8, la case dite sans être proposée, un lockfile refusé
    par la relecture parmi ceux à reprendre.
- **Tranché** :
  - **le npm attendu** : `packageManager` décide s'il est là (un autre gestionnaire : rien) ; puis
    `devEngines.packageManager` et `engines.npm`, des plages (le npm installé qui les respecte
    convient, sinon la plus haute majeure qu'elles acceptent) ; puis **le plus ancien Node choisi**
    (`.nvmrc`, `volta`, `.tool-versions`, `FROM node`, la CI : un lockfile qu'accepte le npm le plus
    ancien est accepté des autres ; une version partielle vaut la dernière de sa ligne, comme
    `actions/setup-node`) ; `engines.node`, une borne basse, ne compte qu'en dernier, et seulement si
    le Node installé ne la respecte pas (sinon `>=14` ferait lancer npm 6). `npm --version` n'est
    demandé que si le projet dit quelque chose (aucun appel de plus pour les autres) ;
  - **la CI est un runtime du projet** (E27) : elle sert aussi aux fins de vie et aux versions
    écartées (une CI en Node 18 écarte une version qui demande Node 20, comme `npm install` dans
    cette CI). Seul Node est lu dans les workflows de GitHub (`setup-python`, `setup-go`… : case à
    E34), **et pour un projet npm seulement** : chaque workflow est une requête de plus à la source
    d'une forge (60 par heure sans token) ; les `image` de GitLab et Bitbucket (un fichier chacun)
    donnent tous les runtimes connus, à tous les projets, comme un `FROM` ;
  - **la case est cochée d'office** (décision de la session 29) ; décochée à l'écran 5
    (`declined`) ou par `--no-extras` ; **pour une PR, elle est toujours faite** (c'est la CI du dépôt
    qui reçoit le lockfile), l'écran 8 la dit sans la proposer ;
  - **la relecture n'est pas un échec** : un refus de `npm ci` laisse le lockfile régénéré (par le
    npm qu'attend le projet, c'est le meilleur qu'on ait), dit une fois (`Regenerated.verified`), avec
    la commande qui le reproduit ;
  - **`go mod vendor` est une case du même genre**, cochée d'office : sans lui, `go build` refuse ;
    `vendor/` est copié avant (dans un dossier temporaire) et remis si une commande du groupe échoue ;
    il compte dans le garde-fou git et dans le commit d'une PR ;
  - **les `requirements.txt` générés** : `pip-compile` / `uv pip compile` d'un manifeste
    (`pyproject.toml`, `setup.cfg`) en sont le lockfile (versions lues, recompilés par `-P`) ; un export
    (`uv export`, `pdm export`, ou un fichier sans en-tête aux versions toutes figées du lockfile du
    projet : Poetry) suit son lockfile, n'est pas relu, et se refait après lui par la commande de
    l'outil, dans le même groupe (un échec remet les deux) ; un export sans son lockfile reste un
    `requirements` écrit à la main (dit) ;
  - **`--hash`** : `Dependency.manual` dès l'analyse ; la réécriture garde son refus ;
  - **une indirecte NuGet** : une option applicable (`EditKind.REFERENCE`), pré-cochable comme une
    autre correction (avec l'avertissement), dans le projet MSBuild du dossier de son lockfile ; avec
    la gestion centrale, l'épinglage transitif est ajouté sous `ManagePackageVersionsCentrally`, et
    les lockfiles de tous les projets qui lisent ce `Directory.Packages.props` sont régénérés ;
    l'élément va après le dernier de sa sorte, à son indentation et avec les fins de ligne du
    fichier ; la relecture compare tout le reste et exige ce qui est ajouté ; une `PackageVersion`
    déjà là, ou pas de place : à la main ;
  - **Composer 2.9** : dit dans le plan d'après `composer --version` ; avant 2.9, rien ne bloque
    (rien n'est dit).
- **Trouvé** : la relecture d'une indirecte NuGet devenue directe la disait « plus trouvée »
  (corrigé) ; le texte de la case était illisible à l'écran (parenthèses imbriquées, « npx -y »
  coupé en fin de ligne : reformulé, vu sur des captures en clair et en sombre, 1440 et 375 px) ;
  `ForgeSource` ne téléchargeait rien d'un dossier écarté (`vendor/`), même demandé ; le test
  `network` du vrai GitHub (`pallets/markupsafe`, un projet Python) passait de 6 à 10 requêtes à
  cause de ses workflows (lus maintenant pour un projet npm seulement) ; les
  dataclasses de `web/schemas.py` ne supportent pas un type défini plus bas.
- **Tests** : `test_project_npm.py` (33, plus 1 `network` : la table, chaque source, le plan, la
  régénération par `npx`, la relecture acceptée ou refusée, la case décochée, rien de demandé sans
  attente, npx absent, npm 6 ; le test `network` : un vrai npm 11, une CI en Node 22, `npm@10 ci`
  accepte, et npm 11 avec `--no-extras` remet ses `"peer": true`) ; `test_requirements_exports.py`
  (13, sur le mini-projet `exports` fait par les vrais outils) ; `test_nuget_references.py` (8, plus 1
  `network` avec le vrai `dotnet`) ; dans `test_lockfiles.py` (`vendor/`, Composer 2.9),
  `test_planner.py` (`--hash`, `$minimist`), `test_parsers_python.py`, `test_nuget_projects.py`,
  `test_sources_forge.py` (la CI et `vendor/` téléchargés), `test_web_api.py` (la case et `declined`) ;
  Vitest (la case, la relecture, « ajoutée en ») ; Playwright (`update.spec.ts` : une CI en Node 22 ;
  `a11y.spec.ts` : la case et la relecture passent axe-core en clair et en sombre, 1440 et 375 px).
- **Vérifié à la main**, sur des copies dans le scratchpad : `forceupdate update` sur un projet à CI
  en Node 22 (npm 11 de la machine) : régénéré par npm 10, relu par `npx -y npm@10 ci --dry-run`
  (accepté), contre-épreuve indépendante, puis `--no-extras` (npm 11, ses `"peer": true`) ; les exports
  de uv, PDM et Poetry et `pip-compile pyproject.toml` refaits par les vrais outils (lanceurs `uvx`
  du scratchpad), en-têtes intacts ; une `PackageReference` ajoutée puis restaurée par le vrai
  `dotnet`.
- **Limites** (pour la doc, E35) : l'élagage propre à npm 11.6.2 (refusé par npm 11.16 aussi) n'est
  pas vu, la majeure étant la même ; une CI à plusieurs projets (un `working-directory`) donne son
  Node à tous ; `node-version-file` n'est pas suivi (le `.nvmrc` est déjà lu) ; un `packageManager`
  pnpm ou Yarn est laissé à l'outil (pnpm 9.7+ et corepack le suivent) ; `poetry export` exige son
  plugin (sinon la régénération échoue, tout est remis) ; un export avec d'autres groupes que `dev`
  (Poetry) ou d'autres options (PDM : il n'écrit pas sa commande) se refait autrement ; une
  `PackageVersion` déjà là pour une indirecte (sans référence) est à faire à la main ; un `-c
  constraints.txt` à `--hash` n'est refusé qu'à la réécriture.

### E33 — Registres et dépôts privés

Un paquet d'un registre privé est aujourd'hui demandé au registre public (introuvable, ou un
homonyme). Le demander à son registre, avec ses identifiants (jamais envoyés ailleurs), ou dire
« privé : non vérifié ».

- [x] Depuis E22 (Go) : un module privé (`GOPRIVATE`, `GONOPROXY`, lus dans l'environnement et dans `go env -w`) est demandé au proxy public et à OSV, et le proxy cherche lui-même son hôte : ne pas les demander (« module privé : non vérifié »), comme `go` ; de même pour un paquet npm d'un registre privé (`.npmrc`, `@scope:registry`).
- [x] Depuis E23 (PHP) : un dépôt `composer` de `repositories` (Satis, Private Packagist) : ses paquets sont cherchés sur Packagist ; les demander à ce dépôt (son `packages.json`, `metadata-url`), avec `auth.json`.
- [x] Depuis E25 (Java) : les dépôts Maven déclarés (`<repositories>`, miroirs de `~/.m2/settings.xml`, `repositories { }` de Gradle) ne sont pas lus : leurs artefacts sont cherchés sur Maven Central (un privé y est introuvable) ; les lire, avec leurs identifiants.
- [x] Depuis E26 (.NET) : les flux privés de `nuget.config` (ses sources, leurs identifiants) pour les versions publiées.
- [x] Depuis E28 (Python) : `[tool.uv] index` d'un script (un autre index que PyPI) ; de même pour un projet (`[[tool.uv.index]]`, `--index-url` d'un `requirements`) : à vérifier.
- [x] Ajouté en route (E24, Ruby) : la source globale d'un `Gemfile` (`source "https://gems.corp…"` hors d'un bloc) n'était pas distinguée : ses gems étaient demandées à rubygems.org ; elles sont maintenant « non vérifiées » (lire ce serveur : case ajoutée à E34).

**Fini quand** : pour chaque écosystème, un paquet d'un registre privé déclaré est demandé à ce
registre (testé avec un registre simulé), ou dit « privé : non vérifié » ; jamais au registre
public.

**Notes** (session 33) :

- **Commit d'abord** : E32 commitée (`41f2fc8`), avec l'accord de l'utilisateur.
- **Décidé avec l'utilisateur (les identifiants)** : forceupdate **lit les identifiants dans les
  fichiers de la personne**, comme son outil le ferait, et un identifiant ne part que vers l'hôte
  exact (et le port, et le chemin quand ils sont dits) pour lequel il est déclaré, en https — ou en
  http vers la machine elle-même (`localhost`, `127.0.0.1`, `::1` : rien ne quitte la machine ;
  ajouté pour un Verdaccio ou un index local) ; jamais lors d'une redirection vers une autre
  origine ; jamais dans le cache, un rapport, un journal, l'API ni le navigateur ; les variables
  (`${NOM}`, `%NOM%`) d'un fichier du projet ne sont jamais développées (un dépôt pourrait faire
  partir un secret de l'environnement vers l'adresse de son choix) ; jamais un paquet privé demandé
  au registre public.
- **Vérifié en vrai** avant d'écrire (2026-11-02, dans le scratchpad) :
  - **Go 1.27.3** : `go env GOENV` vaut `%APPDATA%\go\env` ; `go env -w` y écrit `CLÉ=valeur` ;
    l'environnement l'emporte sur le fichier ; `GONOPROXY` et `GONOSUMDB` valent `GOPRIVATE` s'ils
    ne sont pas donnés (`none` : aucun) ; `GOAUTH` vaut `netrc` ; **proxy.golang.org va chercher
    lui-même un module chez son hôte** (`git ls-remote` vers GitHub : 404 « could not read
    Username » ; un hôte d'entreprise : « no such host ») ;
  - **npm 11.6.2** : `npm config list` (le `.npmrc` du projet, puis celui de la personne,
    `NPM_CONFIG_USERCONFIG`), valeurs entre guillemets, commentaires `;` et `#`, `${NOM}` ; les
    identifiants sont « protected » ;
  - **Composer 2.11.0** avec un dépôt servi en local (`packages.json`, `metadata-url`,
    `available-packages`) : `packages.json` puis `p2/acme/private.json` ; il demande **aussi**
    `p2/acme/private.json` à Packagist (404 : le blocage des failles de Composer 2.9+ y cherche les
    avis) ; forceupdate, non ;
  - **SDK .NET 10.0.403** (`dotnet nuget list source`) : le `nuget.config` le plus proche d'abord,
    puis ceux des dossiers parents, puis celui de la personne ; `<clear />` écarte tout le reste,
    celui de la personne compris ;
  - **uv 0.10.11** avec un index local qui exige un identifiant : `Accept` du JSON (PEP 691) puis
    du HTML ; `UV_INDEX_<NOM>_USERNAME` et `_PASSWORD` rattachés au nom de l'index ; un essai sans
    identifiant, puis un avec ; `uv.lock` note le registre de chaque paquet ;
  - **Maven et Gradle ne sont pas installés** (choix de l'utilisateur) : leurs formats sont lus
    d'après leur documentation (« Settings Reference », « Guide to Mirror Settings », « Declaring
    repositories »), sans vérification par l'outil ;
  - la personne n'a ni `~/.npmrc`, ni `auth.json`, ni `settings.xml`, ni fichier `GOENV`, ni
    `.netrc` : seulement le `NuGet.Config` par défaut (nuget.org).
- **Organisation** :
  - `userfiles.py` (ajouté : `home`, `config_home`, `xdg_config_home`, `environ`, `env`, `read`,
    `expand`, `unexpanded`) : les fichiers et l'environnement de la personne, tout passe par lui ;
  - `net/auth.py` (ajouté : `Credential` lié à son adresse, `Credentials.for_url`, `bound_to`,
    `bound_or_none`, `split_userinfo`, `bearer`, `basic`, `is_loopback`, `origin`) ;
    `net/http.py` : `auth=` (l'identifiant de chaque requête ; les redirections suivies à la main,
    `MAX_REDIRECTS`, sans identifiant vers une autre origine) ;
  - `registries/base.py` : `AccessRefused`, `Registry.declared`, `auth`, `label`, `_url`
    (asynchrone), `_get` ; `registries.declared` (la classe d'un registre déclaré par écosystème et
    sorte) et `for_ecosystem(…, auth=)` ; `registries/composer.py` (ajouté : `ComposerRepository`,
    `packages.json`, `metadata-url`, `available-packages`, `includes`) ; `nuget.py` : `NuGetFeed`
    (l'index de services, `RegistrationsBaseUrl/3.6.0`…) ; `pypi.py` : `SimpleIndex` (JSON, sinon
    HTML : `simple_html_files`) ; `packagist.py` : `Packagist.info`, `abandoned_message(…, where)` ;
  - `routing/` (ajouté) : `__init__.py` (`Declared`, `Route`, `PUBLIC`, `Reading`, `User`,
    `Routing`, `read`, `apply`, `Clients` : la chaîne des registres), `npm.py` (`.npmrc`,
    `.yarnrc.yml`), `go.py`, `netrc.py`, `composer.py`, `nuget.py`, `python.py`, `maven.py`
    (Maven et Gradle), `ruby.py` ;
  - `engine.py` : `analyze` lit l'aiguillage (`routing.read`), `check(…, routes=)` ; une clé par
    route (`_Key`) ; `_private_notices` ; la seconde requête à OSV (versions proposées) sans les
    paquets privés ; `sources/forge.py` : `_requested` lit l'aiguillage (une forge télécharge
    `.npmrc`, `nuget.config`, `uv.toml`… comme les manifestes) ;
  - `parsers/python.py` : `attached_index`, `requirements_options` ; `parsers/maven.py` :
    `pom_chain` ;
  - tests : neuvième garde-fou (`conftest.user_files` : un dossier personnel et un environnement
    propres au test, toute lecture hors des dossiers des tests refusée) ; `e2e_server.py` de même.
- **Tranché** :
  - **trois cas**, d'après la configuration de l'outil : un registre **qui remplace** le public (un
    miroir : `registry=`, `--index-url`, un `<mirror>`, un autre `GOPROXY`) : ses paquets lui sont
    demandés, et à OSV ; des registres **en plus** (`--extra-index-url`, un dépôt `composer`, des
    `<repositories>`, les sources de NuGet) : demandés d'abord, dans l'ordre, le premier qui a le
    paquet l'emporte (comme uv et Composer), le public ensuite ; un paquet **privé par son nom**
    (portée npm, `GOPRIVATE`, `index =` de uv, `source =` de Poetry, `index =` de Pipfile,
    `include_packages` de PDM, `only` de Composer, `packageSourceMapping` de NuGet, `includeGroup`
    et `exclusiveContent` de Gradle) : son registre seul, **jamais le public ni OSV** ;
  - **un refus (401, 403) ou une erreur d'un registre déclaré arrête la chaîne** : le public n'est
    pas demandé à sa place (le registre pourrait avoir le paquet). « Registre privé : non vérifié :
    … refuse l'accès » ; jamais mis en cache. Sans registre à qui demander : « Privé : non vérifié »
    (GOPRIVATE) ou « Non vérifié : … » (GOPROXY=direct, `--no-index`, un flux NuGet v2, la source
    privée d'un `Gemfile`) ;
  - **OSV** : seuls les paquets privés par leur nom n'y vont pas (une remarque par fichier :
    « Failles non cherchées pour le paquet privé ») ; ceux d'un miroir ou d'un registre en plus y
    vont (un miroir sert des paquets publics : Nexus, Private Packagist) ;
  - **un identifiant rattaché à un nom** (`<server id>` de Maven, une source de NuGet,
    `UV_INDEX_<NOM>_*`, `http-basic.<nom>` de Poetry) ne part que vers l'adresse que donne à ce nom
    un fichier de la personne ; sinon, une remarque le dit. Les identifiants d'un dépôt Gradle (des
    propriétés lues par le script) ne sont pas lus ; ceux de Poetry (son trousseau, `auth.toml`) non
    plus ;
  - **les registres publics reçoivent aussi un identifiant déclaré pour leur hôte** (un paquet
    privé hébergé sur npmjs.com) ; `.netrc` vaut pour tous les ports d'un hôte, comme pip, uv et Go ;
  - **les messages citent l'hôte, jamais l'adresse** (une adresse peut porter un jeton dans son
    chemin : Gemfury) ; les identifiants écrits dans une adresse (`https://nom:secret@hôte`) en
    sont retirés partout (la clé du cache est l'adresse) ;
  - **Python** : l'outil du projet décide (un script ou uv, Poetry, PDM, Pipenv, sinon pip) ; un
    paquet rattaché à un index reste « venu de l'index … » pour le parseur, l'aiguillage le rend
    vérifiable (`Route.attached`) ; une source `primary` de Poetry retire PyPI ;
  - **NuGet** : sans `packageSourceMapping`, les sources autres que nuget.org d'abord, la première
    qui a le paquet l'emporte (NuGet les réunit) ; un flux v2 n'est pas lu ; un dossier local non
    plus ;
  - **l'interface ne change pas** : constats et remarques existants (le skill `ui-ux-pro-max` n'a
    pas été chargé) ; ni le format JSON ni l'API.
- **Trouvé** : la seconde requête à OSV (les versions proposées) emportait les noms privés
  (corrigé) ; le client public ne recevait aucun identifiant (corrigé, voir plus haut) ; un heredoc
  a encore abîmé un script (CLAUDE.md le dit : les scripts passent par l'outil d'écriture).
- **Tests** (122) : `test_routing.py` (31 : le socle, identifiants, `HttpClient` et redirections,
  `userfiles` et son garde-fou, la chaîne), `test_routing_npm.py` (16), `test_routing_go.py` (23),
  `test_routing_composer.py` (8), `test_routing_nuget.py` (9), `test_routing_python.py` (14),
  `test_routing_maven.py` (18), `test_routing_ruby.py` (3), de bout en bout par le moteur avec des
  registres simulés (respx) ; `test_sources_forge.py` (les fichiers de configuration téléchargés).
- **Vérifié à la main** : `forceupdate scan` sur six mini-projets du scratchpad, un dossier
  personnel factice (`USERPROFILE`, `APPDATA`) et six registres privés servis sur 127.0.0.1, qui
  exigent un identifiant : npm (jeton de `~/.npmrc`, `${ACME_NPM_TOKEN}`), index Python (HTML,
  `.netrc`), dépôt Composer (`auth.json`), proxy Go (`go env -w`, `.netrc`), flux NuGet
  (`NuGet.Config`, `packageSourceMapping` du projet), Maven (profil et serveur de `settings.xml`) :
  chacun demandé avec son identifiant, les versions privées dans le rapport, les publiques venues
  du vrai registre, aucun secret dans le rapport ; sans le jeton npm : « Registre privé : non
  vérifié » et la remarque sur la variable absente.
- **Limites** (pour la doc, E35) : Composer, la configuration globale (`config.json` de
  `COMPOSER_HOME`) et `canonical: false` ne sont pas lus ; un dépôt `providers-url` seul non plus ;
  NuGet, un `Password` chiffré (DPAPI), un dossier local, un flux v2 ; Maven, un mot de passe
  chiffré de `settings.xml`, `${env.…}` d'un `pom.xml`, `<httpHeaders>` d'un serveur ; Gradle,
  les identifiants et un dépôt dont l'adresse est calculée ; Go, la suite de `GOPROXY` après le
  public (un `,` qui retomberait sur un autre proxy) ; npm, `cafile` et `strict-ssl` (un certificat
  refusé est dit, `SSL_CERT_FILE`), le `resolved` d'un lockfile (un paquet installé depuis un
  autre registre sans configuration) ; Python, le trousseau (`keyring`), les identifiants de
  Poetry, `--find-links` ; Ruby et Rust : voir E34.

### E34 — Compléments d'analyse

- [x] Depuis E33 (registres privés) :
  - Ruby : la source globale d'un `Gemfile` et ses blocs `source "…" do` : demander ce serveur (son
    index compact, `/info/{gem}`) avec les identifiants de Bundler (`BUNDLE_<HÔTE>` de
    l'environnement, `~/.bundle/config`), au lieu de « non vérifié » ;
  - Rust : `registry = "…"` (`.cargo/config.toml` du projet et de la personne, `[registries]`,
    l'index « sparse », `credentials.toml`), au lieu de « non vérifiable ».

- [x] Depuis E21 (Rust) : la version « permise » d'une contrainte Cargo est la plus haute qu'elle accepte ; le résolveur 3 (édition 2024, `resolver = "3"`) préfère celles dont le `rust-version` convient au projet (celui de `[package]`, sinon la version de `rustc`) : l'index donne `rust_version` de chaque version, le prendre en compte.
- [x] Depuis E22 (Go) :
  - dans un workspace `go.work`, la version construite est la plus haute que demandent ses membres : la calculer (sélection minimale sur leurs `go.mod`) au lieu de garder celle du `go.mod` du membre ;
  - la majeure suivante d'un module qui a des `+incompatible` de la même majeure sous un chemin `/vN` (v2.0.0+incompatible et `…/v2`) : chercher aussi ces chemins, au prix d'une requête par majeure.
- [x] Depuis E23 (PHP) :
  - les avis de la base FriendsOfPHP qui manquent à OSV ne sont pas vus (twig 3.4.1 : 15 failles sur les 17 de `composer audit`) : lire aussi ceux de Packagist (`security-advisories` des métadonnées `p2`, détail par `https://packagist.org/api/security-advisories/`), réunis à ceux d'OSV par leurs CVE ;
  - `prefer-stable` et `minimum-stability` du projet : les passer à la version permise (aujourd'hui, seulement les stables ou un drapeau de la contrainte).
- [x] Depuis E25 (Java) :
  - une version gérée par un parent ou un BOM distant (Spring Boot) est « non vérifiable » : lire le
    `pom` du parent ou du BOM (`…/{version}/{artefact}-{version}.pom`) pour connaître la version qu'il
    impose, et la vérifier (la mise à jour reste celle du parent ou du BOM) ;
  - un artefact déplacé (`<relocation>` dans le `pom` de ses dernières versions : mysql-connector-java
    → com.mysql:mysql-connector-j) : le dire comme une dépréciation, avec le remplaçant ;
  - les verrous de Gradle (`gradle.lockfile`) : les lire pour les versions installées ; les
    régénérer demande Gradle, qui exécute les scripts du projet (le dire, comme Bundler) ;
  - `settings.gradle(.kts)` (`pluginManagement`, `dependencyResolutionManagement`, d'autres
    catalogues), `buildSrc`, les versions riches des scripts (`version { strictly(…) }`) ;
  - un constat de faille cite la version corrigée d'OSV même d'une autre variante (Guava :
    `32.0.0-android` pour qui a `-jre`) ; citer celle de la variante utilisée (la plus petite
    publiée qui n'est plus concernée).
- [x] Depuis E26 (.NET) : `Directory.Build.targets` (`PackageReference Update=`).
- [x] Depuis E27 (fins de vie) :
  - ce qui n'est pas lu : les images Docker non officielles (`bitnami/…`, `openjdk`, dépréciée), `mise.toml`, le `required_ruby_version` d'un `.gemspec`, un `TargetFramework` défini sous condition, le Java réel de la machine (un `pom.xml` se juge d'après Eclipse Temurin) ;
  - `checks.eol.FRAMEWORKS` et `parsers.runtimes.NODE_CODENAMES` se tiennent à la main : un test `network` qui compare la table aux `purl` d'endoflife.date (`/api/v1/products/full`) et dit les produits nouveaux, et les noms des LTS de Node.js à ceux de `nodejs.org/dist/index.json` (« Lithium » pour la 26, ajouté à E32) ; de même `update.project_npm.NODE_NPM` (la majeure de npm livrée avec chaque ligne de Node, relevée à E32) ;
  - depuis E32 : les workflows de GitHub Actions ne donnent que Node (`actions/setup-node`, `container`) ; lire aussi `actions/setup-python`, `setup-go`, `setup-java` (et sa `distribution`), `setup-dotnet`, `ruby/setup-ruby`, `shivammathur/setup-php` (leur version dans la `matrix`), pour les fins de vie et les versions écartées (lus aujourd'hui pour un projet npm seulement : les lire pour tous coûte une requête par workflow à la source d'une forge, à peser).
- [x] Depuis E28 (fichier de code isolé) :
  - les imports `npm:` et `jsr:` de Deno (avec leur version : un vrai manifeste), les alias de
    `tsconfig.json` (`paths`, `baseUrl` : `src/x` n'est pas le paquet `src`) ;
  - les imports d'un `.ipynb` (ses cellules de code), d'un `.vue` ou d'un `.svelte` (son
    `<script>`) ; `importlib.import_module` et `__import__` d'un nom écrit ;
  - un paquet d'espace de noms local (un dossier voisin sans `__init__.py`) pris pour un paquet ;
  - `[tool.uv] exclude-newer` (script ou `pyproject.toml`) : ne pas proposer de version publiée
    après, ou le dire ;
  - la table `IMPORT_PACKAGES` se tient à la main : un test `network` qui vérifie que chaque paquet
    existe sur PyPI (et, si possible, qu'il fournit l'import : `top_level.txt` de sa dernière roue).

**Fini quand** : chaque case a ses tests et a été vérifiée en vrai ; les limites qui restent sont
écrites, pour la documentation (E35).

**Notes** (session 34) :

- **Commit d'abord** : E33 commitée (`598468e`), avec l'accord de l'utilisateur. **Découpage
  proposé, refusé** : l'utilisateur a voulu E34 entière en une session (« 1 étape, fais tout d'un
  coup ») ; la documentation et la recette restent E35 et E36.
- **Vérifié en vrai** avant d'écrire (2026-11-02 et 03, dans le scratchpad, dossiers personnels
  factices) :
  - **Bundler 4.0.20** avec un serveur de gems local à index compact qui exige un identifiant :
    `/versions` puis `/info/{gem}` à chaque source ; une gem d'un bloc `source … do` demandée à ce
    serveur seul, même s'il ne l'a pas ; Bundler 4 refuse deux sources globales ; les identifiants
    (`bundle config set --global`) : la clé de l'adresse exacte (`BUNDLE_HTTP://127__0__0__1:8808/
    PRIVATE/`), sinon celle de l'hôte (`BUNDLE_127__0__0__1`, tous les ports), ceux écrits dans
    l'adresse du `Gemfile` d'abord ; l'ordre : `.bundle/config` du projet, l'environnement,
    `~/.bundle/config` ; un miroir (`mirror.https://rubygems.org`) remplace la source, le lockfile
    garde `remote: https://rubygems.org/` ; RubyGems relit une valeur telle quelle entre ses
    guillemets, coupée à un `#` ;
  - **cargo 1.99.1** avec un registre « sparse » local qui exige un jeton : `config.json` sans
    jeton, 401, puis `Authorization: <jeton>` (sans « Bearer ») ; Cargo 1.99 exige le fournisseur
    `cargo:token` (`[registry] global-credential-providers`) ; `CARGO_REGISTRIES_<NOM>_INDEX` ;
    `replace-with` vers un registre de `[registries]` (avec son jeton) ou une `[source.x] registry`
    (sans : Cargo refuse d'y envoyer un jeton) ; le lockfile garde la source de crates.io ; **le
    résolveur 3** (`resolver = "3"`, édition 2024) préfère les versions dont le `rust_version`
    convient au `rust-version` du projet et se replie sur la plus haute sinon ; le résolveur 2
    l'ignore, sauf `[resolver] incompatible-rust-versions = "fallback"` ; l'édition 2024 exige
    `rust-version` ≥ 1.85 ; `rust-version.workspace = true` suivi ;
  - **Go 1.27.3** : dans un `go.work`, un membre est construit avec la version d'un autre
    (`golang.org/x/text` v0.3.0 et v0.14.0 : v0.14.0 pour les deux ; v0.3.0 avec `GOWORK=off`) ; le
    vrai proxy : `github.com/russross/blackfriday` a `v2.0.0+incompatible` et v2.1.0 sous `…/v2`
    (`/v3` : 404) ;
  - **Composer 2.11.0** : `composer audit` sur twig 3.4.1 dit 17 failles ; OSV en connaît
    maintenant 15 (2 à E23) ; les deux autres (CVE-2026-46627, CVE-2026-46636) n'ont pour source que
    FriendsOfPHP ; l'API de Packagist (`api/security-advisories/?packages[]=`) et le
    `security-advisories` des métadonnées `p2` ; huit choix de `composer update` selon
    `minimum-stability`, `prefer-stable` et les drapeaux (`>=3.0` en `alpha` : v4.0.0-alpha1 ; avec
    `prefer-stable` : v3.30.0 ; `^4.0` en `stable` : refusé ; `>=3.0@stable` en `alpha` : v3.30.0 ;
    en `dev` : la branche `4.x-dev`) ;
  - **Maven Central** : le `pom` de mysql-connector-java 8.0.33 (et 8.0.32) a une `<relocation>`
    vers `com.mysql:mysql-connector-j`, avec un `<message>` ; spring-boot-starter-parent 3.2.0 →
    spring-boot-dependencies 3.2.0 (39 BOM importés, `jackson-bom` par `${jackson-bom.version}`,
    lui-même fils de `jackson-parent` 2.15) ; **Maven et Gradle ne sont pas installés** (choix de
    l'utilisateur) : `gradle.lockfile`, les versions riches et `versionCatalogs` d'après la
    documentation de Gradle (« Locking dependency versions », « Declaring Rich Versions »,
    « Version Catalogs ») ;
  - **SDK .NET 10.0.403** (`dotnet restore`, `project.assets.json`) : un `PackageReference
    Update=` de `Directory.Build.targets` l'emporte sur la version du projet ; celui de
    `Directory.Build.props` est sans effet (lu avant le projet) ; une propriété de
    `Directory.Build.targets` vaut pour les versions du projet et l'emporte ; un `Include` de
    `.targets` ajoute la référence ;
  - **endoflife.date** : Rust y est (chaque version suivie six semaines) ; `/api/v1/products/full`
    (489 produits, 204 à `purl`) ; nodejs.org/dist/index.json (`lts`, `npm`) ;
  - **uv 0.10.11** : `exclude-newer` (horodatage, date, durée, durée ISO 8601) ; `uv lock` sous
    `exclude-newer = "2024-01-01T00:00:00Z"` prend requests 2.31.0.
- **Organisation** :
  - `routing/ruby.py` (réécrit : `BundlerSettings`, `parse_settings`, `settings_key`, miroirs,
    identifiants) ; `parsers/ruby.py` : `read_gemfile`, `Gemfile.sources` et `global_sources`,
    `GemfileLock.remotes` ; `registries/rubygems.py` : `GemServer` (l'index compact d'un serveur
    déclaré ; sans `/versions`, « non concluant ») ;
  - `routing/cargo.py` (ajouté : `CargoConfig`, `[registries]`, `[source.crates-io] replace-with`,
    `credentials.toml`, `CARGO_HOME`) ; `parsers/rust.py` : `registry_of` ; `registries/crates.py` :
    `rust_version` ; `parsers/runtimes.py` : le runtime `rust` (`rust-version`, `rust-toolchain`) ;
    `checks/runtimes.py`, `checks/outdated.py` (le repli de Cargo) ; `checks/eol.py` :
    `WITHOUT_LIFECYCLE` ; le format du cache des versions passe à 3 ;
  - `parsers/go.py` : la version construite dans un workspace (`_members`, `built`) ;
    `registries/goproxy.py` : `_major_latest`, chaque majeure à `+incompatible` ;
  - `advisories/packagist.py` (ajouté : `PackagistAdvisories`, `parse_advisory`, `ranges`) ;
    `advisories/osv.py` : `Advisory.link` ; `versions/composer.py` : `resolved`,
    `package_stability` ; `models.Project.resolution` (ajouté au format JSON et à l'API :
    `openapi.json`, `schema.d.ts`) ;
  - `managed.py` (ajouté : les versions gérées par un parent ou un BOM distant) ;
    `registries/maven.py` : `pom`, `pom_url`, `relocation`, `_complete` ; `net/cache.py` :
    `CacheKind.FILES` (7 jours) ; `engine.check(…, read_text=)` ; `parsers/gradle.py` : versions
    riches, `SETTINGS`, `_other_catalogs`, `read_lockfile`, `_with_locks` ; `checks/vulns.py` :
    `_variant_fix` ;
  - `parsers/nuget.py` : `BUILD_TARGETS`, `_updated` (les `Update=` dans l'ordre de MSBuild),
    `target_frameworks` sous condition ;
  - `parsers/runtimes.py` : images (`openjdk`, `bitnami/…`, `cimg/…`, `circleci/…`,
    `devcontainers`, copies de la bibliothèque), `_mise`, `required_ruby_version`, `_SETUPS` ;
    `detect/manifests.py` : `settings.gradle(.kts)`, `mise.toml`, `rust-toolchain(.toml)` ;
  - `parsers/code.py` : `notebook_imports`, `component_scripts`, `_deno`, `_TsConfig`, `_jsonc`,
    `without_local_namespaces` ; `parsers/imports.py` : `visit_Call` (importlib) ;
    `detect/code.py` : `.ipynb`, `.vue`, `.svelte` ; `sources/base.py` : `Source.is_directory` ;
    `parsers/python.py` : `exclude_newer_cutoff`, `_exclude_newer` ; `engine._without_newer` ;
  - front : « Rust » dans `RUNTIME_LABEL` (avec le skill `ui-ux-pro-max`).
- **Tranché** :
  - **Ruby** : une gem d'un bloc, d'une option `source:` ou d'une autre section `GEM` du lockfile
    que celle de la source globale est privée par son nom (jamais rubygems.org ni OSV) ; une source
    globale qui n'est pas rubygems.org (ou un miroir) la remplace, avec OSV ; un identifiant par
    hôte vaut pour tous les ports, comme Bundler, en https (ou vers la machine elle-même) ;
  - **Cargo** : un jeton est rattaché à un nom de registre ; celui de la personne ne part que vers
    l'adresse que donne à ce nom un fichier de la personne (son `config.toml`,
    `CARGO_REGISTRIES_<NOM>_INDEX`) ; un index git n'est pas lu ; des fichiers locaux à la place de
    crates.io (`cargo vendor`) : crates.io est demandé ;
  - **`rust-version`** : une version qu'il ne fait pas tourner n'est jamais proposée (quel que soit
    le résolveur : la promesse du projet), et la version permise se replie sur la plus haute comme
    le résolveur 3 ; sous le résolveur 2, cargo prendrait la plus haute (dit dans
    `checks.runtimes`) ; Rust n'a pas de constat de fin de vie (une version suivie six semaines) ;
  - **Go** : la version permise ne descend jamais sous la version construite (un workspace, ou les
    verrous de Gradle) ;
  - **Packagist** : ses avis sont ajoutés à ceux d'OSV et réunis par leurs identifiants (CVE,
    GHSA) ; un paquet privé n'y est jamais envoyé ; une erreur laisse ceux d'OSV et le dit ;
  - **`minimum-stability`** : la version permise suit Composer ; forceupdate ne propose toujours
    que des versions stables ;
  - **Maven** : une version gérée hors du dépôt devient vérifiable, sa mise à jour « à la main »
    (celle du parent ou du BOM) ; `<relocation>` est une dépréciation ; la version corrigée est
    celle de la variante utilisée (et une version Maven non publiée, `33.7.2` de Guava, devient
    `33.7.2-jre`) ;
  - **Gradle** : les verrous donnent les versions installées et les indirectes, jamais régénérés
    (Gradle n'est jamais lancé : une remarque le dit) ;
  - **les workflows de GitHub** sont lus pour tous les projets (une requête de plus par workflow à
    la source d'une forge) ;
  - **un `jsr:`** est non vérifiable (forceupdate ne lit pas le registre JSR) ; un `npm:` est le
    paquet npm, sa contrainte à réécrire à la main ;
  - **`exclude-newer`** : les versions publiées après ne sont pas proposées (y compris pour corriger
    une faille), une remarque le dit ; un paquet qu'un projet sans ce réglage utilise aussi garde
    toutes ses versions.
- **Trouvé** :
  - `routing.apply` efface la raison d'une dépendance rattachée avant que le moteur ne redemande sa
    route : l'aiguillage de Cargo, qui la lisait, l'envoyait à crates.io (corrigé : lu à la lecture
    du projet, comme Python) ;
  - `record.py` n'avait pas suivi E33 (`_Recording.get` sans `auth=`) ;
  - respx remplace une route au même motif (un test qui voulait un 503 prenait la réponse
    enregistrée) ;
  - trois heredocs ont encore abîmé des `\\n` (CLAUDE.md le dit) : les scripts passent par l'outil
    d'écriture.
- **Tests** : `test_routing_ruby.py` (22), `test_routing_cargo.py` (14), `test_rust_version.py`
  (5), `test_advisories_packagist.py` (8), `test_managed.py` (4), `test_exclude_newer.py` (13),
  `test_tables_network.py` (5 réseau), et dans `test_parsers_go.py`, `test_registries_goproxy.py`,
  `test_php_projects.py`, `test_versions_composer.py`, `test_parsers_php.py`,
  `test_registries_maven.py`, `test_java_projects.py`, `test_parsers_gradle.py`,
  `test_parsers_nuget.py`, `test_parsers_runtimes.py`, `test_parsers_code.py`,
  `test_code_files.py`, `test_routing_maven.py` ; réponses enregistrées : `maven/poms/` (22 `pom`,
  `record.py maven-poms`), `packagist-advisories.json` (`record.py packagist-advisories`),
  blackfriday (proxy Go), jackson-databind et maven-surefire-plugin (Maven), deux versions de plus
  dans `osv/queries.json` (`OSV_EXTRA`) ; Vitest : « Rust » (`lib/report.test.ts`).
- **Vérifié à la main** (`forceupdate scan`, vrais registres sauf les privés, servis en local) :
  Ruby (deux gems demandées à leur serveur avec l'identifiant de `~/.bundle/config`, aucun secret
  dans le rapport) ; Rust (le jeton refusé sans déclaration de la personne, envoyé avec) ; Go (le
  workspace, blackfriday) ; twig 3.4.1 (les 17 CVE de `composer audit`) ; Spring Boot 3.2.0
  (jackson-databind 2.15.3 et ses failles, le starter et le plugin en 3.2.0, mysql-connector-java
  déplacé) ; Gradle (le plugin de `settings.gradle.kts`, le catalogue `deps`, guava d'après les
  verrous) ; .NET (les versions de `dotnet restore`) ; un carnet, un `main.ts` de Deno, uv et
  `exclude-newer` (2.31.0, comme `uv lock`) ; les tests réseau des tables.
- **Limites** (pour la doc, E35) : Ruby, un serveur sans index compact (seulement
  `/api/v1/dependencies`) est « non concluant », `BUNDLE_APP_CONFIG` relatif lu dans le projet, la
  sonde d'un miroir (`fallback_timeout`) ignorée ; Rust, les jetons des autres fournisseurs
  (`cargo:wincred`, `cargo:libsecret`…), un index git, `[resolver] incompatible-rust-versions` et
  la version de `rustc` sans `rust-version` ni `rust-toolchain` (forceupdate ne lance pas rustc) ;
  Go, les `go.mod` des dépendances (une indirecte peut être construite plus haut encore) ; PHP,
  les branches (`dev-main`, `4.x-dev`) que Composer prend en `dev` ; Maven, `${project.version}`
  d'un BOM importé est celle du BOM, les profils d'un `pom` distant (jamais lus, même actifs par défaut),
  120 `pom` au plus par analyse ; Gradle, les verrous `buildscript-gradle.lockfile` et `gradle/dependency-locks/`, les
  accesseurs des autres catalogues dans les scripts (leurs entrées sont `runtime`), les constantes
  de `buildSrc`, un catalogue publié ; .NET, un `Update="@(…)"` ; fins de vie, le Java réel de la
  machine (un `pom.xml` se juge d'après Eclipse Temurin), un `openjdk` lu comme Temurin, une date
  d'`exclude-newer` lue en UTC (uv prend le fuseau de la machine) ; code, `extends` d'un
  `tsconfig.json`, un `import_module` d'un nom calculé, `top_level.txt` de `IMPORT_PACKAGES` pas
  vérifié.

### E35 — Documentation, packaging, CI

- [x] `README.md` : à quoi ça sert, installation, démarrage (`ui`), captures d'écran, la ligne de commande, les limites par écosystème.
- [x] Docs :
  - `docs/USAGE.md` : l'interface écran par écran, et toutes les commandes et options. Dire que sous PowerShell 5.1, `>` recode la sortie d'un programme (en UTF-16, via le codage de la console) : y préférer `--output` (E07). Depuis E27 : les fins de vie (où chaque runtime est lu, la table des frameworks, le cycle conseillé, les versions écartées parce que le runtime du projet ne les fait pas tourner, Java jugé d'après Eclipse Temurin) ;
  - `docs/JSON_FORMAT.md` : à jour ;
  - `docs/FORGES.md` : connexion à GitHub, GitLab et Bitbucket, droits nécessaires, ce que contient une PR, comment enregistrer l'outil auprès de chaque forge. Depuis E16 : les quatre façons de se connecter, ce que dit « droits non vérifiés » (token fine-grained : Contents et Pull requests en écriture, Metadata en lecture), où est le token (trousseau du système) et ce qui est révoqué à la déconnexion ; enregistrer sa propre OAuth App GitHub (« Redirect URIs » `http://127.0.0.1/oauth/github/callback`, Device Flow coché, « Expire user access tokens » décoché) et la passer par `FORCEUPDATE_GITHUB_CLIENT_ID` / `…_SECRET` ;
  - `CHANGELOG.md`.
  - Depuis E28 : dans `docs/USAGE.md`, un fichier de code (la remontée jusqu'au manifeste de son
    écosystème et ses arrêts, le bloc PEP 723 et son `script.py.lock`, les imports lus par langage,
    la table import → paquet, « version non fixée »).
  - Depuis E29 et E30 : les limites notées à E29 (configuration lue à la racine seulement…) ; un
    « Réseau d'entreprise » (`HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE` et `SSL_CERT_DIR`, le
    magasin du système par truststore, sous Linux `SSL_CERT_FILE` à la place du magasin ; le
    proxy des réglages de Windows non lu) ; les fichiers en UTF-16 lus mais pas réécrits ; le
    plafond de 200 000 fichiers ; Ctrl+C et l'arrêt de `ui` pendant une mise à jour (ce qui
    n'était pas fini est remis) ; les autres limites des notes de E30.
  - Depuis E32 : dans `docs/USAGE.md`, « le npm du projet » (d'où il se lit : `packageManager`,
    `devEngines`, `engines`, le Node choisi, la CI ; la case cochée d'office, `--no-extras`, toujours
    faite pour une PR ; la relecture par `npm ci --dry-run`) ; la CI comme runtime (fins de vie,
    versions écartées) ; les `requirements.txt` générés (ce qui les reconnaît, comment ils sont
    refaits ; `poetry export` et son plugin) ; une ligne à `--hash` ; l'indirecte NuGet ajoutée au
    projet (et l'épinglage transitif) ; `go mod vendor` ; Composer 2.9 ; les limites des notes de E32.
  - Depuis E33 et E34 : dans `docs/USAGE.md`, « Registres et dépôts privés » (par écosystème : ce
    qui est lu, où sont les identifiants, la règle des identifiants rattachés à un nom — Maven,
    NuGet, uv, Cargo —, « privé : non vérifié ») ; les serveurs de gems et Bundler, les registres
    de Cargo ; `rust-version` et le résolveur 3 ; la version construite d'un workspace Go ; les
    avis de Packagist ; `minimum-stability` ; les versions gérées par un parent ou un BOM distant
    (« à la main »), `<relocation>`, `gradle.lockfile`, `settings.gradle(.kts)`, les versions
    riches ; `Directory.Build.targets` ; les images, `mise.toml`, les actions `setup-*` ; les
    fichiers de code (carnets, `.vue`, `.svelte`, Deno, `tsconfig.json`, `importlib`,
    `exclude-newer`) ; les limites des notes de E33 et de E34 ; `Project.resolution` dans
    `docs/JSON_FORMAT.md` (fait à E34).
- [x] Depuis E20 : dans `docs/FORGES.md`, Bitbucket : enregistrer son propre « OAuth client » (Workspace settings → OAuth clients ; « Authorization code » et « Refresh token », jamais « Client credentials » ; Account Read et Email, Repositories et Pull requests en écriture ; adresse de retour `http://127.0.0.1/oauth/bitbucket/callback`) et le passer par `FORCEUPDATE_BITBUCKET_CLIENT_ID` / `…_SECRET` ; le token d'API Atlassian (`id.atlassian.com`, application Bitbucket, ses six portées), les app passwords qui ne marchent plus ; pas de révocation (« Retirer l'accès » dans `bitbucket.org/account/settings/app-authorizations/`) ; pas d'adresse `noreply` (l'adresse principale du compte signe les commits) ; Bitbucket Data Center hors V1.
- [x] Depuis E18 : dans `docs/FORGES.md`, ce que fait une PR (branche `forceupdate/dependencies` remplacée à chaque envoi, un commit au nom du compte avec son adresse `noreply`, marqué `Generated-by: forceupdate` ; jamais par-dessus le commit d'un autre ; ce que dit la description ; un lockfile dont l'outil manque sur l'ordinateur) et qu'il faut git ; dans le README, une capture de l'écran 8 et d'une PR.
- [x] Depuis E31 : dans `docs/FORGES.md` :
  - **le trousseau sous Linux** (serveur, WSL) : sans Secret Service, aucun compte ne se connecte (la raison est dite) ; en installer un (GNOME Keyring : `gnome-keyring` et `dbus`, `dbus-run-session -- sh -c 'echo -n "<phrase>" | gnome-keyring-daemon --unlock; forceupdate ui'` sur un serveur sans session graphique : à vérifier sur une vraie machine le jour venu), ou choisir un autre trousseau par keyring : `uv tool install forceupdate --with keyrings.cryptfile`, puis `PYTHON_KEYRING_BACKEND=keyrings.cryptfile.cryptfile.CryptFileKeyring` (sa phrase de passe demandée dans le terminal, ou `KEYRING_CRYPTFILE_PASSWORD`) ; jamais de fichier en clair par forceupdate (décision de la session 31) ;
  - les tokens GitHub sans expiration (comme `gh`) ; ceux de GitLab et Bitbucket (2 h) renouvelés à chaque usage ; un refresh token de Bitbucket qui ne marche plus : « se reconnecter » ;
  - une PR fermée sans fusion : le récapitulatif la signale et ne coche pas le dépôt (l'envoyer en ouvre une nouvelle ; la branche restée sur la forge est reprise) ;
  - Ctrl+C pendant un envoi : tout s'arrête aussitôt (la console le dit), relancer l'envoi ; une branche déjà poussée sans sa PR est reprise ;
  - `url.<base>.insteadOf` de la configuration git (GitHub par SSH…) : ignoré pour les commandes de forceupdate, qui passent par HTTPS avec le token ; seule une règle sur l'adresse exacte d'un dépôt l'emporte (échec « la forge refuse le token ») ;
  - un sous-module n'est pas analysé (le rapport le dit) : l'analyser comme un dépôt à part ;
  - Bitbucket : un dépôt où le compte écrit par un groupe est vu d'après la permission effective que donne Bitbucket (non vérifié en vrai) ;
  - le dossier de travail du serveur (`forceupdate-ui-*` du dossier temporaire) : effacé à l'arrêt, ou au démarrage suivant après un arrêt brutal.
- [x] Packaging :
  - le front est construit avant `uv build`, et le paquet le contient : fait à E14 (`publish.yml`, `artifacts` de hatchling, vérifié dans le wheel) ;
  - `uv tool install .` testé sous Windows (Linux via la CI), sur une machine sans node ;
  - version `1.0.0` : `1.0.0rc1` d'abord (décision de l'utilisateur, session 35 : la 1.0.0 après
    la recette, E36) ;
  - licence MIT : le fichier `LICENSE` est bien inclus dans le paquet.
- [x] CI GitHub Actions :
  - ruff + pytest, sur Ubuntu, Windows et macOS, avec Python 3.11 et 3.14 ;
  - lint, tests et build du front : job « Front » ajouté à E14 (Ubuntu, node 24 ; types, oxlint, Vitest, build, Playwright) ; y ajouter Windows ;
  - un job hebdomadaire avec les tests `network`.
- [x] Depuis E15 : le serveur des tests de bout en bout (`tests/e2e_server.py`) laisse son dossier temporaire (`forceupdate-e2e-*`) quand Playwright l'arrête en fin de série : le faire effacer (par exemple, les vieux dossiers au démarrage, ou un `globalTeardown` de Playwright).
- [x] Publication sur PyPI (décision n°19 du brief) :
  - un workflow GitHub Actions publie le paquet quand on pousse un tag `v*` (Trusted Publishing, sans mot de passe stocké) : fait à E09 (`.github/workflows/publish.yml`), avec la construction du front depuis E14 ;
  - publier la `1.0.0`, avec l'accord de l'utilisateur : la `1.0.0rc1` publiée à la session 36
    (étiquette `v1.0.0rc1` sur `b9aacaf`), la `1.0.0` à E36 ;
  - vérifier `uv tool install forceupdate` depuis PyPI, sur une machine sans node : fait pour
    `forceupdate==1.0.0rc1` (session 36).

**Fini quand** : `uv tool install forceupdate` depuis PyPI, dans un dossier vierge,
marche ; la CI est verte.

**Notes** (session 35) :

- **Commit d'abord** : E34 commitée (`34b4c4f`), avec l'accord de l'utilisateur. **Découpage
  proposé, refusé** : E35 entière en une session. **Décidé avec lui** : publier d'abord la
  `1.0.0rc1` (une pré-version : `uv tool install forceupdate` ne la prend pas sans `==` ou
  `--prerelease allow`), la `1.0.0` au tag de la recette (E36), pour qu'un écart trouvé à la
  recette ne coûte pas une `1.0.1` ; commit en deux parties, la première poussée tout de suite pour
  lancer la CI (accord de l'utilisateur).
- **Trouvé : `main` n'avait pas été poussé depuis E13** (22 commits), et la CI de E13 échouait
  déjà : sous Windows, un clone (`core.autocrlf`) mettait les mini-projets en CRLF ; sous Ubuntu, la
  racine `/` de l'écran 2 n'avait pas de nom. **La suite tournée sous Linux** (Docker, image
  `ghcr.io/astral-sh/uv:python3.14-bookworm`, utilisateur non root ; la méthode est dans CLAUDE.md) :
  311 échecs, presque tous d'une cause : `sources/local.py` (E30) lisait
  `stat.IO_REPARSE_TAG_MOUNT_POINT`, qui n'existe que sous Windows — **toute analyse d'un dossier
  plantait sous Linux et macOS**. Corrigé, puis 5 103 tests verts sous Linux. `.gitattributes`
  (`* text=auto eol=lf`) : les fichiers du dépôt en LF partout ; l'index l'était déjà.
- **Documentation** : `README.md` réécrit (aussi la page PyPI : liens et images en adresses
  absolues de GitHub), `docs/USAGE.md` (2 550 lignes : installation et données, l'interface écran
  par écran, `scan` et `update` option par option, codes de retour, PowerShell 5.1, lire un
  rapport, configuration, les huit écosystèmes et leurs limites, particularités de la mise à jour,
  fins de vie et runtimes, fichier de code, registres privés, réseau d'entreprise, robustesse),
  `docs/FORGES.md` (705 lignes : toutes les puces de E16, E18, E20, E31), `CHANGELOG.md`,
  `docs/JSON_FORMAT.md` vérifié par un script (chaque clé des rapports des mini-projets et chaque
  propriété d'`openapi.json` cherchée dans la doc : `advised_blocked` manquait). Quatre sections
  rédigées par des agents à partir des notes **et du code** (le code a gagné partout où ils
  divergeaient), relues et assemblées ; les ancres vérifiées par un script.
- **Captures** (`docs/images/`, 1440 px) : le serveur de `tests/e2e_server.py` (réponses
  enregistrées, forges simulées), une copie de `vulnerable` nommée `boutique`, son chemin montré
  `C:/Projets/boutique` (comme `--source`) ; le rapport, l'écran 5, mes dépôts en sombre, le
  récapitulatif des PR (écran 8) ; « une PR » : la description de la vraie PR #1 du dépôt de test,
  rendue par l'API Markdown de GitHub (lecture seule), dans une page à son titre et ses branches.
- **Trouvé en relisant le code pour la doc, corrigé** : un identifiant écrit dans l'adresse d'un
  dépôt Gradle (`maven("https://nom:secret@…")`) restait dans l'adresse (la clé du cache) et
  partait même en http (deux tests ; le second voit le défaut) ; le conseil du token fine-grained
  de GitHub donné pour toute forge (un test) ; « (injoignable) » à la déconnexion quand la
  révocation échoue faute de secret ; l'avertissement de `nuget.config` et trois docstrings
  périmés depuis E33 ; **le proxy des réglages du système est lu** (httpx passe par
  `urllib.request.getproxies` : sous Windows le proxy réglé à la main, sans ses exceptions ; ni PAC
  ni détection automatique), contrairement à ce que disaient E30 et la docstring. Les autres écarts
  relevés vont à E36 (« Depuis E35 »).
- **Packaging** : `uv build` (wheel et sdist : l'interface, `LICENSE` dans `dist-info/licenses/`) ;
  `uv tool install .` sous Windows **sans node dans le `PATH`**, dans des dossiers d'outils à part
  (`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`) : `--version`, un vrai `scan` (28 failles de `vulnerable`), `ui`
  qui sert l'interface.
- **CI** : macOS en plus (Python 3.11 et 3.14), le job « Front » sous Ubuntu et Windows (`bash`
  partout) ; `network.yml` le lundi et à la demande : Node 24 et pnpm, Go, Rust, PHP 8.5 et
  Composer, Ruby 4.0, .NET 10 installés par leurs actions (versions des actions vérifiées sur
  GitHub ; `ruby/setup-ruby` n'a pas d'étiquette `v1`, d'où `v1.336.0`), `pytest --run-network -m
  network` ; un outil absent fait sauter son test.
- **Le dossier `forceupdate-e2e-*`** : `workdirs.Workdirs` et `sweep` prennent un préfixe ; le
  serveur de bout en bout garde son dossier verrouillé, y range celui de `ui`, et balaie au
  démarrage ceux des séries d'avant (18 effacés au premier démarrage).
- **La CI, première fois sur les trois systèmes** (commit `be210cd`) : Ubuntu et Windows verts ;
  macOS, un échec sur 5 103 — le chemin du dossier temporaire (`/private/var/folders/…`) dépassait
  les 120 colonnes d'un rapport terminal écrit dans un fichier, et rich le coupait : la ligne
  « Source » n'est plus repliée (`soft_wrap`, un test) ; le front sous Ubuntu, un test Playwright
  (le second envoi d'une MR) au-delà de 30 s, vert à la relance : les trois tests à deux envois
  ont `test.slow()` et 60 s. À revérifier sur le commit de la doc.
- **Pas publié dans cette session** (choix de l'utilisateur) : **il veut d'abord essayer l'outil
  lui-même**, installé depuis le dépôt (`uv tool install .`), sur ses projets et ses comptes. La
  prochaine session commence par ses retours (chaque défaut corrigé, ou porté au plan), puis la
  publication (étiquette `v1.0.0rc1` après une CI verte, avec son accord, puis
  `uv tool install forceupdate==1.0.0rc1` depuis PyPI sans node).
- **La CI du commit de la doc** (`7a6a670`) : Python vert sur les trois systèmes (macOS compris),
  front vert sous Ubuntu ; sous Windows, deux variantes sur quatre de « ses imports seulement »
  (`e2e/code.spec.ts`) n'ont pas vu l'analyse finir en 30 s (vert au commit d'avant, rien de
  changé sur ce chemin) : job relancé, **même échec** (une variante sur quatre). Pas reproduit en
  local. **Première hypothèse, fausse** : les deux workers de la CI se disputant le serveur
  partagé ; un seul worker en CI (`739a3c8`) et le même test échoue sous Ubuntu, seul sur le
  serveur. **La trace, gardée cette fois** (`actions/upload-artifact@v7` de
  `frontend/test-results/`, 14 jours ; la durée de chaque test dans le journal, `list` en plus de
  `github`), a donné la vraie cause : la page disait « L'analyse a échoué — Le serveur n'a pas
  donné de raison », alors que le serveur avait fini l'analyse **en 6 ms**, au statut `done`.
  `POST /api/scans` répondait déjà `done` (un fichier de code seul, sans projet : presque rien à
  lire), et le front rangeait ce résumé comme l'analyse, `report: null` (`opened`,
  `hooks/useScanActions.ts`) ; une analyse finie n'étant jamais relue (`staleTime: Infinity`),
  la page restait sur « finie, sans rapport », qu'elle dit échouée. **Un vrai défaut**, qu'une
  personne pouvait voir sur un fichier seul. Corrigé : le résumé n'est rangé que pour une
  analyse en cours, sinon la page demande l'analyse entière (un test Vitest le reproduisait
  avant). Le worker unique retiré (la cause n'était pas là), les traces et les durées gardées. **CI verte** sur les huit jobs au commit `0425828` (Python sous Ubuntu, Windows et macOS, 3.11 et 3.14 ; le front sous Ubuntu et Windows).
- **Tests** : 5 110 tests Python (plus 28 réseau, pas relancés), verts sous Windows et sous Linux
  (Docker) — sauf les quelques-uns que chaque système saute (liens symboliques, droits POSIX) ;
  168 Vitest, 72 Playwright.

**Notes** (session 36) :

- **Les essais de l'utilisateur, faits ensemble** : il ne les avait pas faits seul ; il a voulu être
  guidé, étape par étape (la commande, puis ce qu'il doit voir). L'outil installé depuis le dépôt
  (`uv tool install .`, le front construit vérifié à jour), dans un PowerShell hors de VS Code (le
  `.venv` activé y prendrait la version de développement). Huit étapes, toutes conformes :
  - `ui` (le jeton échangé contre un cookie, le thème, le menu replié) ;
  - l'analyse de forceupdate et d'Argos (`the good guy`) : les mêmes chiffres que `scan` ;
  - la mise à jour d'une copie d'Argos (un clone dans le scratchpad, son chemin collé à
    l'accueil) : 21 cochées sur 27, `anthropic` majeure ajoutée à la main ; `pyproject.toml`
    réécrit sur sa seule ligne, `uv.lock` (les 16 paquets choisis, plus `botocore` et
    `pydantic-core`), `package-lock.json` par npm 10 via `npx` (la case du npm du projet) ;
  - un fichier de code : `server.js` de radar-pros, lu via son `package.json` (Node.js 20 en fin de
    vie d'après `engines.node = ">=20.3"`, une borne basse : voulu, E27) ; `pep723.py` déposé, mis
    à jour, téléchargé (seule la ligne de flask change) ;
  - les trois forges connectées par OAuth ; 11 dépôts (10 analysés, 1 vide), 466 failles, les
    chiffres de forceupdate et de sechunter identiques au local ; les trois `forceupdate-demo`
    envoyés : la même PR #1 (et MR !1), contenu inchangé depuis le 29 octobre, donc rien de
    poussé et la description refaite (« forceupdate 1.0.0rc1 ») ;
  - les réglages : une valeur refusée, un dépôt exclu, un paquet ignoré (aussi en ligne de
    commande) ; le vrai fichier, qui n'existait pas, effacé après ;
  - `scan` en terminal, Markdown, JSON ; `--fail-on` (1, 1, 2 : un fichier du dépôt est lu via
    le `pyproject.toml` de forceupdate, ma consigne attendait 0 à tort) ; `update --security-only`
    (non, oui, puis le garde-fou git, code 2).
- **Un défaut, corrigé** : le terminal et le Markdown (donc la description d'une PR) ne disaient
  pas pourquoi une version plus récente n'est pas proposée quand le runtime du projet ne la fait
  pas tourner (vitest 5.1.0 demande Node 22, Argos est en Node 20 : « Permise » vide, « mineure »,
  sans raison) ; seule l'interface montrait le message. `Finding.blocked` (la version écartée et
  pourquoi ; un champ ajouté au JSON, `schema_version` inchangé) ; `report.details` écrit sous le
  tableau, en plus des autres, un constat « plus récente » ou « version non fixée » qui en a un.
  Tests dans `test_eol_project.py` (django 6.1.2, p-limit 7.3.3 : terminal, Markdown, champ) et
  la liste des clés de `test_report.py` ; `openapi.json`, `schema.d.ts`, `JSON_FORMAT.md`,
  `USAGE.md`. **Les rapports d'exemple du front** (`frontend/src/test/fixtures/`) étaient périmés
  depuis E34 (`manual`, `resolution` manquaient ; aucun test ne le voit) : régénérés, en LF, celui
  de `imports.py` depuis une copie hors du dépôt (sinon il est lu via le `pyproject.toml` de
  forceupdate).
- **L'outil d'édition écrit en CRLF** sous Windows tout fichier qu'il touche : repassés en LF
  (`sed -i 's/\r$//'`) ; git les aurait normalisés au commit (`.gitattributes`).
- **Les retours de l'utilisateur**, après les huit étapes (avec l'accord de l'utilisateur, le
  premier commit de la session est fait avant, `bdb1b05`, pas poussé) :
  - « le bouton Ouvrir n'ouvre rien » (écran 2) : il attendait la fenêtre de choix d'un dossier du
    système ; **décidé avec lui** : la fenêtre Windows (et celles des autres systèmes), portée à E36
    (« Depuis la session 36 ») ;
  - **son dépôt `mew`** : PR #2 ouverte et fusionnée, puis analysé de nouveau ; restaient 5 failles
    d'indirectes dont la correction est une majeure (minimatch 11.0.1, basic-ftp 6.2.1, zod 4.6.6) ;
    il les a cochées, envoyé la PR : « rien à faire sur la branche par défaut telle qu'elle est :
    rien n'est poussé », et les failles restaient. **La cause** (reproduite sur un clone, en ligne
    de commande) : leurs parents demandent l'ancienne majeure (`nodemon` : `minimatch ^10.2.1`,
    `get-uri` : `basic-ftp ^5.0.2`, `chromium-bidi` : `zod ^3.24.1`, eslint 9 : `minimatch
    ^3.1.2`) ; npm régénère à l'identique, rien à commiter. La ligne de commande disait « retenue
    par nodemon 3.1.14 » ; l'écran du résultat des PR ne le disait pas (les données y étaient :
    `results[].installed[].held_by`). **Corrigé** : `heldUpdates` (`lib/proposals.ts`), la phrase
    « aucune mise à jour n'a pu se faire : d'autres paquets retiennent les versions choisies ; rien
    n'est poussé », l'icône d'avertissement, la liste « Mises à jour retenues » et quoi faire, le
    total « 1 dépôt aux mises à jour retenues » ; un test Vitest (le cas de mew) ; `USAGE.md`
    (pourquoi une indirecte est retenue, quoi faire), `FORGES.md`, `ECRANS.md`. Le prévoir dès
    l'écran 5 (le lockfile dit la plage de chaque parent) : porté à E36 ;
  - **un test Vitest instable trouvé en route** : « la colonne PR, le compteur des PR ouvertes »
    échouait à chaque fois une fois mon test ajouté, et passait seul. La préparation
    (`/pr?depots=…`) montre « Préparer les PR », puis passe à `/pr/{id}`, qui rend un nouveau titre :
    le `findByRole` tenait l'ancien, détaché avant le `expect`. Une course d'avant, que le minutage
    révélait ; les trois tests qui passent par là attendent par `waitFor` (`prepared()`).
- **Pour E36** (ajouté à « Depuis la session 36 ») : deux détails du tableau de « Mes dépôts »,
  la déconnexion pas essayée, les autres écosystèmes sur de vrais projets, la fenêtre de choix
  d'un dossier, l'indirecte retenue dite d'avance.
- **Commits et CI** (accord de l'utilisateur pour chacun) : `bdb1b05` (le rapport dit la version
  que le runtime écarte) commité seul d'abord, puis `b9aacaf` (le résultat des PR) ; les deux
  poussés : **CI verte sur les huit jobs** (Python 3.11 et 3.14 sous Ubuntu, Windows et macOS ;
  le front sous Ubuntu et Windows). Avant : 5 107 tests Python (31 sautés), 170 Vitest, 72
  Playwright, verts en local.
- **Publié** (accord explicite de l'utilisateur, après la CI verte) : l'étiquette annotée
  `v1.0.0rc1` sur `b9aacaf`, le workflow « Publication » vert à chaque étape (l'étiquette égale la
  version, ruff, pytest, le front testé et construit, la wheel porte `web/static/index.html`,
  `uv publish`). Sur PyPI : `forceupdate-1.0.0rc1-py3-none-any.whl` (975 Ko) et le sdist
  (2,6 Mo) ; la page (le README, ses cinq captures en adresses absolues : 200), licence MIT,
  « Development Status :: 4 - Beta ».
- **Vérifié depuis PyPI**, sous Windows, dans des dossiers d'outils à part (`UV_TOOL_DIR`,
  `UV_TOOL_BIN_DIR` dans le scratchpad) et un `PATH` **sans node** :
  `uv tool install --refresh forceupdate==1.0.0rc1`, `--version` (1.0.0rc1), un `scan` d'une copie
  de `vulnerable` (28 failles, code 0), `ui --no-browser` (la page, son script de 657 Ko, l'API :
  200 avec le cookie, 401 sans) ; le front publié contient les correctifs de la session. Linux :
  par la CI (le paquet est le même, pur Python). L'outil de l'utilisateur
  (`~/.local/bin/forceupdate`) reste celui installé depuis le dépôt (`uv tool install .`).
- **Le test final de l'utilisateur** (avec la 1.0.0rc1 de PyPI) : une PR sur quatre de ses dépôts
  GitHub, toutes les majeures cochées ; relues par `gh` (commit, fichiers, description, CI) ;
  TITIrelire (sans CI) vérifiée sur un clone (tsc de TypeScript 7, 524 tests, build), fusionnée
  par lui. Défauts relevés, portés à E36 (« Depuis la session 36 ») : une majeure incompatible
  fait tomber tout son lockfile, le message du commit qui compte une version retenue, un chemin
  de l'ordinateur dans une description. **Le quatrième, corrigé tout de suite** (à sa demande :
  « il faut régler le pb de la PR de forceupdate ») : la PR #1 de `forceupdate` portait un
  `package-lock.json` que `npm ci` refuse (sa CI du front échouait). Reproduit : npm 11.6.2 en
  « lockfile seul » n'écrit que 4 des 6 dépendances embarquées de
  `@tailwindcss/oxide-wasm32-wasi` 4.3.4 ; une seconde passe n'y change rien ; retirer les entrées
  à la main est refusé (un lockfile est écrit par son outil) ; npm 12 ne fait rien d'utile ; **une
  vraie installation** (`npm install --ignore-scripts`) écrit exactement le même lockfile, plus
  les deux entrées. D'où : tout `package-lock.json` est relu (`npm ci --dry-run`, pas seulement le
  npm du projet par `npx`) ; refusé, refait par une vraie installation, relu, et c'est dit (un
  avertissement, aussi dans la description d'une PR) ; les `node_modules` qu'elle crée sont effacés
  (ceux d'avant restent) ; toujours refusé, régénéré et dit (comme à E32) ; un arrêt pendant que
  npm finit garde le lockfile sans le relire (sinon la relecture lèverait l'arrêt et défaisait un
  npm fini). Vérifié en vrai sur un clone de forceupdate (refusé, refait, accepté ; un `npm ci`
  à part l'accepte aussi). Onze tests mis à jour (la relecture de plus), deux nouveaux.
- **Deux demandes de l'utilisateur, faites dans la session** (« voilà le travail que tu fais ») :
  - **télécharger le rapport** depuis l'interface : le Markdown, le JSON, et **les dépendances à
    mettre à jour en CSV** pour un tableur (`report/spreadsheet.py` : une ligne par paquet, une
    par runtime en fin de vie, sans version non fixée ni non vérifiable ni non concluant ;
    points-virgules, BOM dans un fichier pour Excel ; la version qui corrige toutes les failles) ;
    `GET /api/scans/{id}/download?format=md|json|csv` (le serveur nomme le fichier), le groupe
    « Télécharger » sous les badges du rapport (empilé à 375 px) ; `scan --format csv` ;
    `Row.dependencies` (les déclarations d'un paquet : la portée et les fichiers exacts) ;
  - **« Parcourir… »**, la fenêtre de choix du système (`web/picker.py`) : `POST /api/fs/pick` ;
    Tk (`askdirectory`, `askopenfilename`) dans un programme à part, le même Python (`-I -c`),
    au premier plan (`-topmost`) ; une seule fenêtre à la fois (409) ; sans affichage ou sans Tk,
    la raison (503) ; l'arrêt du serveur la ferme ; une demi-heure au plus. L'écran 2 : « Aller »
    (l'ancien « Ouvrir », discret) et « Parcourir… » ; la page dit que la fenêtre peut être
    derrière le navigateur. Tk 8.6 vérifié dans le Python de l'outil installé ; **la vraie
    fenêtre n'a pas été ouverte par moi** (elle s'ouvrirait sur l'écran de l'utilisateur) : à
    essayer par lui, et sous macOS et Linux à E36.
  Tests : `tests/test_downloads.py` (16 : le CSV, `--format csv`, la route, le nom du fichier, la
  fenêtre simulée, le script sans Tk, la route et ses erreurs), 3 Vitest de l'écran 2, 1 du
  rapport. Captures vérifiées (serveur de `e2e_server.py`) : écrans 2 et 4, clair et sombre,
  1440 et 375 px. Doc : `USAGE.md` (écrans 2 et 4, le CSV, `--format csv`, la relecture npm),
  `FORGES.md`, `JSON_FORMAT.md` (les deux routes), `ECRANS.md`, `CHANGELOG.md` (« Non publié »),
  le README.
- **Fin de session** : la CI de `7109460` verte sous Ubuntu, Windows et pour le front ; ses jobs
  macOS (et ceux de `3007959`) annulés par GitHub, faute de machines (« The job was not acquired by
  Runner … capacity constraints ») : relancés, verts (CI verte sur les huit jobs). L'outil de l'utilisateur réinstallé depuis le dépôt :
  le premier essai a échoué (son `ui` tournait : Windows verrouille l'outil, qui est resté à moitié
  démonté), le second a réutilisé la construction en cache de la même version (sans le nouveau
  code) ; `uv tool install . --force --reinstall --refresh-package forceupdate` l'a fait (noté dans le
  prompt). **Ménage** (accord de l'utilisateur) : les 34 scratchpads des sessions passées, ses
  « Récents », `~/go` (`go clean -modcache`), `~/.virtualenvs` (vide), les oracles Maven et NuGet de
  `~/sdk` (CLAUDE.md dit d'où les reprendre) ; le cache de forceupdate laissé (son `ui` le tient
  ouvert : « Vider le cache » de l'écran 9) ; `~/sdk` et Rust gardés jusqu'à la fin de E36.

### E36 — Recette finale

- [x] Dérouler « Le livrable », case par case, dans l'interface :
  - un vrai projet local par écosystème disponible ;
  - un fichier de code isolé, et un fichier glissé-déposé ;
  - les comptes GitHub, GitLab et Bitbucket de l'utilisateur : analyse de tous les dépôts, puis une PR / MR sur un dépôt de test de chaque forge (`Pauzzle-ozz/forceupdate-demo` sur GitHub et sur gitlab.com, `pauzzle/forceupdate-demo` sur Bitbucket ; leur PR #1 et MR !1 y sont déjà) ; les supprimer ensuite, avec l'accord de l'utilisateur.
- [x] Revue finale avec le skill `ui-ux-pro-max` : accessibilité, clair et sombre, petites et grandes fenêtres.
- [x] Corriger les écarts. Un écart trop gros pour cette session devient une nouvelle étape (E37…) dans ce plan.
- [x] Depuis E35 (relevé en écrivant la doc ; chaque point est dit dans `docs/USAGE.md` ou
  `docs/FORGES.md`, à mettre à jour s'il change) :
  - un identifiant écrit dans le **chemin** d'une adresse de registre (`https://pypi.fury.io/<jeton>/…`)
    fait partie de la clé du cache (SQLite) : contraire à « jamais dans le cache » (E33) ; le
    retirer de la clé (une empreinte de l'adresse), ou le dire comme une limite (fait à E35) ;
  - `UV_INDEX_<NOM>_USERNAME` / `_PASSWORD` ne partent jamais (la doc dit d'utiliser `~/.netrc`),
    et la remarque parle d'une adresse « d'un fichier du projet » même quand l'index vient du
    `uv.toml` de la personne : les envoyer vers l'adresse qu'un fichier de la personne donne au nom,
    comme Cargo, ou corriger la remarque ;
  - un registre déclaré en http sur une autre machine est demandé (sans identifiant) ; la docstring
    de `routing/__init__.py` dit « https seulement » : trancher (refuser, ou le dire), seul Bundler
    le signale ;
  - « Privé : non vérifié : l'index « X » n'est pas déclaré » (`routing/python.py`) ne peut pas
    sortir (c'est « Non vérifiable : vient de l'index … ») : le retirer ou le brancher ;
  - `include-tests` du projet ne peut pas valoir `false` contre les réglages (un OU) : le dire
    (fait dans USAGE.md) ou faire primer le projet, comme pour le reste ;
  - `.tool-versions` : `java 17` sans distribution n'est pas lu (il l'est dans `mise.toml`) ;
  - le plan affiche pour Yarn 2+ la commande `yarn install --mode=update-lockfile` mais lance
    `yarn up -R` (et npm `--no-audit --no-fund` en plus) : aligner la commande « à la main » ;
  - `forceupdate --help` redirigé (un tube) sous Windows sort en cp1252 ; l'aide de typer dit
    « Show this message and exit. » en anglais.
- [x] Depuis la session 36 (les essais de l'utilisateur) — faits à la session 37, sauf ce qui est
  porté à E37 (la version du parent qui accepterait la correction, les autres lockfiles que
  `package-lock.json`, le refus prévu d'après le registre, « Parcourir… » sous macOS) :
  - « Mes dépôts » sur un grand écran (2 560 px) : l'en-tête « PR / MR » se coupe sur deux lignes,
    le cadenas et le lien d'un nom long (`Pauzzle-ozz/forceupdate-demo`) passent à la ligne ; le
    tableau reste étroit (le conteneur) : à revoir avec la revue ui-ux-pro-max ;
  - « Se déconnecter… » : pas essayé en vrai (les trois comptes de l'utilisateur sont connectés) ;
  - le fichier de réglages écrit par l'écran 9 finit par une table `[selection]` vide : sans effet,
    la retirer quand elle n'a rien ;
  - ~~**choisir un dossier par la fenêtre du système**~~ **fait à la fin de la session 36** (à sa
    demande : « Parcourir… », `web.picker`, Tk dans un programme à part) ; reste à l'essayer sous
    macOS et Linux. Le texte d'avant : (décision de l'utilisateur) : sur l'écran 2,
    un bouton (« Parcourir… ») ouvre la fenêtre « Sélectionner un dossier » de Windows (celles de
    macOS et de Linux de même : `osascript`, `zenity` ou `kdialog`, sinon tkinter), ouverte par le
    serveur local, qui tourne sur l'ordinateur de la personne ; le dossier choisi s'ouvre dans la
    liste. Le bouton « Ouvrir » d'aujourd'hui ne fait que suivre un chemin collé dans le champ
    « Dossier ouvert » (vide, rien de visible) : la personne attendait cette fenêtre. Points à
    trancher : la fenêtre au premier plan (elle peut s'ouvrir derrière le navigateur), sans
    affichage (serveur, WSL : le bouton absent ou désactivé, avec la raison), les tests (la
    fenêtre simulée). Peut devenir une étape à part (E37) si E36 est trop grosse ;
  - **une indirecte que son parent retient, dite d'avance** : le lockfile dit la plage que chaque
    paquet demande (`nodemon` 3.1.14 : `minimatch ^10.2.1`) ; une correction hors de toutes ces
    plages (minimatch 11.0.1) ne se fera pas par le lockfile seul. Le dire dès l'écran 5 et le
    récapitulatif des PR (« nodemon demande ^10.2.1 : npm la gardera en 10.x ; monter nodemon
    d'abord ») au lieu de « devra peut-être monter aussi », ne plus la compter dans « failles
    corrigées », et proposer le parent s'il a une version qui accepte la correction (ou dire
    qu'aucune ne l'accepte). Pour npm d'abord (pnpm, Yarn, uv, Poetry : leurs lockfiles le disent
    aussi). Le résultat le dit déjà (session 36) ;
  - **une majeure incompatible fait tomber tout son lockfile** (les PR de l'utilisateur, fin de la
    session 36, toutes les majeures cochées) : `sechunter` #661, `redis` 8.1.0 que `arq` refuse
    (`redis<6`) : `uv lock` échoue, les 20 mises à jour Python tombent, dont les failles de pyasn1
    et pypdf ; `argos-ops` #98, `pillow` 13 que `fastembed` refuse (`<13`) : 41 tombent ;
    `forceupdate` #1, `typescript` 7 que `openapi-typescript` refuse (peer `^5`) : les 15 du front
    tombent. Les fichiers remis et la description honnête (« pas faite : lockfile en échec », la
    sortie de l'outil) sont justes, le résultat est mauvais. Sur un échec, **réessayer sans les
    majeures** (les correctifs, mineures et failles partent), puis isoler celle qui bloque et la
    dire (« redis 8.1.0 : arq 0.28.0 demande redis<6 ») ; voir aussi si les métadonnées du registre
    (`peerDependencies` de npm, `requires_dist` de PyPI) le prévoient avant de lancer l'outil ;
    Au renvoi (l'utilisateur a décoché redis 8, pillow 13, typescript 7, coché d'autres majeures),
    le même mal ailleurs : `sechunter`, `python-dateutil` 4.0.0 que `botocore` refuse (`<3`) ;
    `argos-ops`, `@types/react-dom` 19 sans `@types/react` 19 (peer) : le front, qui était dans la
    PR au premier envoi, en sort (la branche est refaite à chaque envoi) — le dire aussi (« cette
    PR perd … ») ;
  - ~~**un lockfile npm toujours relu par `npm ci --dry-run`**~~ **fait à la fin de la session 36**
    (relu toujours ; refusé, refait par une vraie installation sans les scripts, puis relu) : la relecture n'est faite que pour le
    npm du projet lancé par `npx` (E32). `forceupdate` #1 : npm 11.6.2 (celui de l'ordinateur, le
    bon) a écrit un `package-lock.json` que `npm ci` refuse (« Missing: @emnapi/wasi-threads@1.2.3
    from lock file » : les paquets embarqués de `@tailwindcss/oxide-wasm32-wasi`, tailwindcss
    4.3.4) ; une seconde passe de `npm install --package-lock-only` n'y change rien ; la CI du
    front de la PR échoue (« Dépendances »). Relire toujours, et sur un refus : le dire, ne pas
    l'envoyer tel quel (le remettre, comme un échec), chercher ce qui le répare ;
  - **le message du commit compte une version retenue comme faite** : `sechunter` #661 dit
    « minimatch 10.2.6 → 11.0.1 », le lockfile a gardé 10.2.6 (retenue par eslint 10.14.0, la
    description le dit bien) : `forge._done` ne doit garder que ce que le lockfile a atteint
    (`EXACT`, `ABOVE`), ou dire « retenue » ;
  - **un chemin de l'ordinateur dans la description d'une PR** : l'erreur de npm cite
    `C:\Users\<nom>\AppData\Local\npm-cache\_logs\…` (la PR #1 du dépôt public `forceupdate`) :
    remplacer le dossier personnel par `~` (et le dossier de travail par le chemin du dépôt) dans
    la sortie d'un outil avant de l'écrire sur une forge.
- [x] Cocher « Le livrable ». Passer à la version `1.0.0` (`pyproject.toml`, `uv lock`, `uv run python
  -m forceupdate.web.openapi`, classifieur « Development Status :: 5 - Production/Stable », le
  README et `docs/USAGE.md` sans la phrase de la pré-version, `CHANGELOG.md`), CI verte, puis taguer
  `v1.0.0` avec l'accord de l'utilisateur : `publish.yml` publie sur PyPI ; vérifier
  `uv tool install forceupdate` (sans `==`) depuis PyPI, sur une machine sans node.

**Fini quand** : toutes les cases de « Le livrable » sont cochées.

**Notes** (session 37) :

- **Début** : rien à commiter ; CI de `7109460` et `4faf460` verte sur les huit jobs (macOS relancé
  à la session 36). Retours de l'utilisateur : « Parcourir… » s'ouvre **devant** le navigateur
  (Windows), le CSV s'ouvre bien dans Excel. **Découpage proposé, refusé** : toute E36 dans la
  session. Ordre choisi (dit à l'utilisateur) : les écarts connus d'abord, la recette ensuite sur
  l'outil corrigé, pour que la 1.0.0 soit la version recettée.
- **La PR #1 de `forceupdate` renvoyée avec l'utilisateur** (l'outil installé contient la
  correction de la session 36) : npm a de nouveau écrit un lockfile que `npm ci` refusait, refait,
  relu, accepté, et la description le dit ; l'étape « Dépendances » de la CI passe. Deux autres
  causes sont alors apparues, dans **notre** code, pas dans l'outil : oxlint 1.91.0 (une mise à jour
  de la PR) ajoute la règle `react(immutability)`, qui refusait `closed = true` dans le nettoyage
  de `useScanEvents` et `usePlanEvents` (un `AbortController` ; commit `06d9c3c`, poussé avec
  l'accord de l'utilisateur) ; puis un test Vitest de la session 36 (« Parcourir… » pour un
  fichier) lisait le champ avant le changement d'adresse (une course sous Ubuntu, en CI : elle a
  aussi fait échouer le front de `main` à `06d9c3c`, sans les dépendances de la PR ; vérifié sur un
  worktree de la PR : Vitest 3 fois, Playwright 72, types, lint ; commit `153c67d`, poussé, CI de
  `main` verte). Troisième envoi (un premier essai : GitHub « Partially Degraded Service »,
  clone en échec, bien dit) : **CI de la PR verte sur les huit jobs** (macOS relancé, encore faute
  de machines chez GitHub).
- **Une majeure que l'outil refuse ne fait plus tomber tout le lockfile** (`lockfiles._retry`) :
  sur un échec d'un groupe, ses fichiers remis, l'outil est relancé sans les majeures du groupe ;
  s'il réussit, chaque majeure est rajoutée une à une (`MAX_ALONE` = 6), gardée si l'outil
  l'accepte ; les refusées vont dans `Regenerated.dropped` (`Dropped` : la mise à jour, l'option,
  la raison de l'outil). Chaque essai part des fichiers d'avant la mise à jour (les emplacements
  des réécritures sont ceux de l'analyse) ; le dernier essai réussi est remis (`_put`). Pas pour un
  groupe qui refait `vendor/`. Une seule majeure : pas d'essai de plus (elle et les autres, c'est
  le premier essai). La raison (`_why`) : la phrase « Because … » d'uv, Poetry, PDM ; « Could not
  resolve dependency » et « Conflicting peer dependency » de npm ; sinon les trois dernières
  lignes ; tirée de **toute** la sortie (le message d'échec n'en garde que 12 lignes, un ERESOLVE
  en fait 27). **Vérifié en vrai** (vrai uv, vrai PyPI) sur un clone de `sechunter` (`the good
  guy`), toutes les majeures : 19 mises à jour faites, failles de pyasn1 et pypdf comprises ;
  `redis` 8.1.0 (« Because only the following versions of arq are available … arq>0.26.0
  depends on redis[hiredis]>=4.2.0,<6 ») et `python-dateutil` 4.0.0 (botocore `<3`) retirées,
  leurs contraintes intactes. Affiché : le terminal (« pas faite, uv refuse 8.1.0 : … »), la
  description de PR (« pas faite : uv la refuse (…) », « régénéré sans redis 8.1.0, qu'il
  refuse »), le commit (sans elles), l'écran 5 (alerte « Appliquée, sauf une majeure que l'outil
  de lockfile refuse », une ligne par majeure retirée), l'écran 8 (« Majeures refusées »), l'API
  (`LockResult.dropped`). Pas fait : prévoir le refus d'après les métadonnées du registre
  (`peerDependencies`, `requires_dist`) avant de lancer l'outil (« voir aussi si » du plan).
- **L'indirecte retenue dite d'avance** (npm) : `LockedPackage.requires` (la plage que chaque
  paquet demande, lue dans `package-lock.json`, v1 compris), `Dependency.required_by`
  (`Requirement` : nom, version, plage ; vide ailleurs et pour une directe), `UpdateOption.held_by`
  (les parents dont la plage refuse la version) ; l'avertissement « nodemon 3.1.14 demande ^10.2.1
  : le lockfile seul ne la fera pas monter ; monter nodemon d'abord. » (« une de ses copies
  restera en dessous » si un seul la retient) remplace « devra peut-être monter aussi » quand les
  plages sont connues ; jamais pré-cochée (`choose`) ; ses failles pas comptées (récapitulatif de
  l'écran 5, « Corrigerait 2 failles, mais … la retiendra » ; rapport ; récapitulatif des PR :
  « retenue par … : monter ce paquet d'abord », `ProposedUpdate.held_by`). Vérifié sur le front de
  forceupdate : minimatch 5.1.9 (`@redocly/openapi-core` demande **5.1.9** exactement) et 10.2.6
  (`@ts-morph/common` `^10.0.1`). **Pas fait** : proposer la version du parent qui accepte la
  correction (il faudrait lire chaque version du parent au registre : dit comme limite dans
  USAGE.md) ; pnpm, Yarn, uv et Poetry (seul `package-lock.json` donne les plages).
- **Les écarts « Depuis E35 »** : la clé du cache est l'empreinte SHA-256 de l'adresse (format 2,
  la base au format 1 est vidée à l'ouverture) ; `UV_INDEX_<NOM>_USERNAME`/`_PASSWORD` envoyés à
  l'index que la personne déclare à ce nom (son environnement, son `uv.toml` : `Index.personal`),
  comme Cargo, jamais à celui du projet (remarque corrigée) ; un registre en http hors de la
  machine : **tranché, le dire** (demandé sans identifiant, comme l'outil ; une remarque pour tout
  identifiant lié à une adresse en http, `routing._over_http` ; docstring corrigée) ; « Privé : non
  vérifié : l'index … n'est pas déclaré » retiré (la route `private=True` reste : le nom ne part pas
  chez OSV) ; `include-tests` : **tranché, le dire** (déjà dans USAGE.md : faire primer le projet
  demanderait une case à trois états dans l'interface) ; `java 17` de `.tool-versions` lu
  (Temurin, comme `mise.toml`) ; la commande Yarn 2+ « à la main » est `yarn up -R` (toutes les
  mises à jour) ; npm : ses `--no-audit --no-fund` en plus, dits dans USAGE.md (n'affectent que
  l'affichage) ; `forceupdate --help` redirigé en UTF-8 (`cli.run`, le nouveau point d'entrée de
  `[project.scripts]` et de `python -m forceupdate`) et « Affiche cette aide et quitte. »
  (`_FrenchHelp`).
- **« Depuis la session 36 », aussi** : le message du commit ne compte plus une version retenue
  (`Reach.BELOW`) ni retirée ; la sortie des outils sans chemin de l'ordinateur (`_redact` : le
  dossier de la source devient `.`, `userfiles.tilde` : le dossier personnel `~` ; aussi l'erreur
  de git) ; plus de table `[selection]` vide ; « Mes dépôts » (pas de capture de l'utilisateur :
  corrigé d'après le code) : l'en-tête des PR insécable, la colonne du dépôt de 240 px au moins dès
  1 024 px, le cadenas et le lien suivent le nom dans la ligne. Le conteneur reste à 1 280 px
  (MASTER, et `container-width` du skill).
- **Relevé en renvoyant la PR, corrigé** : l'écran du résultat des PR ne disait pas qu'un lockfile
  avait été refait (« En route », les avertissements d'un lockfile régénéré) ; « Versions exactes
  refusées : … a échoué (code 1) : » sans la raison (`_Failed.reason`) ; `@vitejs/plugin-react`
  6.2.1 « une version plus basse reste » : npm la refuse (ERESOLVE, `@babel/core` 8 par
  `@rolldown/plugin-babel`), ce que l'avertissement dit maintenant ; deux lignes `minimatch`
  identiques dans « Mises à jour retenues » (une ligne par paquet) ; le titre « Envoi terminé : 1
  en échec » avec une coche verte (l'icône dit l'échec) ; « Relancer » sans bouton : **« Renvoyer le
  dépôt en échec »** (le serveur renvoie les dépôts `failed` d'un récapitulatif fini, même
  sélection) ; le dossier de travail du serveur dans l'erreur de clone (`~`).
- **Commit `d96a71f`** (accord de l'utilisateur) : 5 150 tests Python, 178 Vitest, 72 Playwright,
  ruff ; **CI verte sur les huit jobs**.
- **La recette, guidée** (l'outil réinstallé depuis le dépôt, `forceupdate ui` arrêté d'abord) :
  - un clone de `sechunter` analysé dans l'interface (12 failles, 2 fins de vie, 7 majeures…),
    mis à jour avec `redis` 8.1.0 et `python-dateutil` 4.0.0 cochées : « Appliquée, sauf 2
    majeures » ; vérifié sur le clone (redis 5.3.1, dateutil 2.9.0.post0, pyasn1 0.6.5, pypdf
    6.21.4, le reste monté) ;
  - « Mes dépôts » : l'analyse de tous les dépôts ;
  - les trois `forceupdate-demo` : rien de pré-coché (leurs PR #1 fusionnées le 3 novembre, il ne
    reste que des majeures : juste) ; **ajouté** : le lien « choisir les mises à jour » d'un dépôt
    sauté pour « aucune mise à jour cochée ». Majeures cochées : **PR #2 (GitHub) et MR !2
    (gitlab.com) ouvertes**, `flask` 3.1.3 et `werkzeug` 3.1.9 retirées par la reprise (`uv pip
    compile` : Python ≥ 3.9 ; werkzeug < 1.0 pour flask 0.12.5) — **la reprise marche aussi pour
    pip-compile** ; le texte disait « l'outil de requirements.txt la refuse » : il nomme l'outil
    (`DroppedUpdate.tool`, d'après les lockfiles du récapitulatif). **Bitbucket : un vrai défaut**,
    « Can only update an open pull request » : avec `q` (BBQL), Bitbucket **ignore** le paramètre
    `state`, et `find_open_request` prenait la PR #1 fusionnée pour l'ouverte (la branche, elle,
    était poussée). Corrigé (`state="OPEN"` dans la requête BBQL, et l'état vérifié sur chaque PR) ;
    le faux Bitbucket des tests appliquait `state` même avec `q` (d'où le défaut invisible) : il
    l'ignore maintenant, comme le vrai ; un test. Renvoyé après réinstallation, par le nouveau lien :
    **PR #2 ouverte** ;
  - **« Se déconnecter… » en vrai** (GitLab, OAuth) : déconnecté, révoqué, puis reconnecté ;
  - **un vrai projet par écosystème**, par moi, en ligne de commande, avec l'outil installé : des
    clones publics (`sharkdp/hexyl`, `spf13/cobra`, `symfony/demo`, `rubygems/rubygems.org`,
    `jasontaylordev/CleanArchitecture`, `spring-projects/spring-petclinic`) : analyses sans
    « non concluant » (12, 11, 47, 30, 22, 37 à mettre à jour ; NuGet par
    `Directory.Packages.props` ; `org.eclipse.m2e:lifecycle-mapping` non vérifiable : juste),
    plans à blanc, puis **vraies mises à jour** Rust (Cargo), Go (`go.mod`, `go.sum`), PHP
    (Composer), Java (`pom.xml`, `build.gradle` : seules les versions changent). Pas Ruby
    (`bundle lock` exécute le Gemfile d'un projet inconnu) ni .NET (MSBuild évalue le projet).
- **Revue d'interface** (ui-ux-pro-max, checklist de MASTER) des nouveaux états : le résultat des
  PR avec une majeure refusée, « En route », un dépôt en échec et « Renvoyer » (un test Playwright
  temporaire : la réponse de l'API enrichie) : axe-core sans violation et aucun défilement
  horizontal, clair et sombre, 375 et 1 440 px ; captures relues. « Mes dépôts » à 2 560, 1 440 et
  1 024 px : l'en-tête et les noms tiennent.
- **Commits et publication** (accord de l'utilisateur pour chacun) : `cd096ff` (la recette,
  Bitbucket, le lien des sautés), `9c37b39` (la 1.0.0 : `pyproject.toml`, `uv lock`,
  `openapi.json`, classifieur « 5 - Production/Stable », README et USAGE sans la phrase de la
  pré-version, CHANGELOG « 1.0.0 — 2026-11-04 »), avant eux 5 151 tests Python, 179 Vitest, 72
  Playwright verts ; **CI verte sur les huit jobs** ; l'étiquette annotée **`v1.0.0`** sur
  `9c37b39`, le workflow « Publication » vert à chaque étape. **Sur PyPI** : le wheel (991 Ko) et le
  sdist (2,6 Mo), « Production/Stable ».
- **Vérifié depuis PyPI, sans node** : sous Windows (dossiers d'outils à part, `PATH` sans node),
  `uv tool install --refresh forceupdate` **sans `==`** : 1.0.0, un scan de `vulnerable` (27
  failles, 29 à mettre à jour, code 0), `ui --no-browser` (la page, l'API : 200 avec le cookie,
  401 sans). **Piège** : le premier essai, quelques minutes après la publication, a installé la
  **0.1.0** (celle de E09, qui réservait le nom) : le CDN de PyPI servait encore l'ancien index ;
  avec l'index relu (`--refresh`), la 1.0.0. Sous **Linux** (Docker, `ghcr.io/astral-sh/uv:python3.14-
  bookworm`, utilisateur non root, ni node ni affichage ; dans cette image, `UV_TOOL_DIR` et
  `UV_TOOL_BIN_DIR` sous `HOME`, sinon uv vise `/usr/local/bin`) : `uv tool install forceupdate`,
  1.0.0, le même scan (27 failles), `ui` (page, 200, 401), et **« Parcourir… » sans affichage :
  503**, « Pas de fenêtre de choix : pas d'affichage sur l'ordinateur où tourne forceupdate (un
  serveur, WSL). Choisir dans la liste, ou coller le chemin. » macOS : par la CI seulement.
- **Décisions de l'utilisateur en fin de session** : les PR #2 (GitHub, Bitbucket) et la MR !2
  (gitlab.com) des `forceupdate-demo` **restent ouvertes** ; `~/sdk` et Rust **gardés** (le scratchpad
  seul est vidé) ; les quatre points non faits de E36 deviennent **l'étape E37** (la 1.1.0).
- **Pour plus tard** : retirer (« yank ») la 0.1.0 sur PyPI éviterait qu'un index pas encore à jour
  la donne à la place de la dernière (la page du projet, « Options », par l'utilisateur ;
  réversible).

---

## Phase I — Après la 1.0.0

### E37 — Indirectes retenues et majeures refusées, plus loin (1.1.0)

Ce que E36 a laissé (session 37, décidé avec l'utilisateur) ; la 1.0.0 est livrée sans.

- [x] **La version du parent qui accepte la correction** d'une indirecte retenue (`held_by`) : lire
  au registre les versions du paquet qui la tire et la plage que chacune demande (le document npm
  du paquet : `dependencies` de chaque version) ; la proposer (« monter nodemon en 4.0.1, qui
  accepte minimatch 11 »), ou dire qu'aucune ne l'accepte. Écran 5, récapitulatif des PR, terminal.
- [x] **Les indirectes retenues dites d'avance pour pnpm, Yarn (1 et 2+), uv et Poetry** : leurs
  lockfiles disent la plage de chaque parent (`LockedPackage.requires`, aujourd'hui rempli pour
  `package-lock.json` seulement) ; chaque parseur, ses tests, les mini-projets.
- [x] **Prévoir le refus d'une majeure avant de lancer l'outil** : les `peerDependencies` de npm, les
  `requires_dist` de PyPI (`redis` 8 que `arq` refuse, `typescript` 7 que `openapi-typescript`
  refuse) ; le dire dès l'écran 5, à côté de la reprise de `lockfiles._retry` (qui reste).
- [ ] **« Parcourir… » sous macOS** (une personne avec un Mac : `osascript` ou Tk) et sous Linux avec
  un affichage ; corriger ce qui doit l'être.
- [ ] Doc (`USAGE.md` : les limites retirées), CHANGELOG, puis la **1.1.0** : CI verte, l'étiquette
  `v1.1.0` avec l'accord de l'utilisateur, vérifiée depuis PyPI.

**Fini quand** : les quatre points sont faits (ou décidés avec l'utilisateur) et la 1.1.0 publiée.

**Notes** (session 38) :

- **Début** : rien à commiter ; CI de `d170147` verte. Les tests `network` du lundi (le premier
  passage planifié de `network.yml`) échouaient sur deux tests restés en arrière, en local aussi :
  `test_the_real_npm_of_the_project` attendait un lockfile du npm de l'ordinateur non relu (il
  l'est depuis la session 36) et des `"peer": true` que npm 11.19 n'écrit plus ici (le test vérifie
  maintenant que c'est le npm de l'ordinateur qui relit) ; `test_a_real_public_repository`
  comptait 6 requêtes au plus pour `pallets/markupsafe`, qui a maintenant 5 workflows (lus depuis
  E32) : une requête par fichier lu, plus le dépôt et l'arborescence. **Décisions de
  l'utilisateur** : toute E37 dans la session (découpage proposé, refusé) ; les PR #2 (GitHub,
  Bitbucket) et la MR !2 (gitlab.com) des `forceupdate-demo` **fermées sans fusion**, à sa demande
  (gh, et l'API avec les comptes du trousseau) ; le « yank » de la 0.1.0 : expliqué (il ne savait
  pas ce que c'était), à faire par lui sur pypi.org ; « Parcourir… » sous macOS : « tu testes
  toi » (pas de Mac : la CI). Le skill `ui-ux-pro-max` est rangé dans
  `~/.claude/skills-archive/ui-ux-pro-max-v2.5.0` (plus chargé comme skill) : son `SKILL.md` lu là.
- **Trouvé en lisant le code** : `uv.lock` et `pnpm-lock.yaml` **n'écrivent pas les plages** (uv :
  les noms seulement ; pnpm : les versions résolues, et les plages des pairs) ; seuls
  `package-lock.json`, `yarn.lock` (1 et 2+) et `poetry.lock` les donnent. D'où une base commune
  aux trois premiers points : **ce que demande chaque version d'un paquet, lu au registre**
  (`registries.Requires`, `PackageVersion.requires`, `Registry.requires`, `Clients.requires`) :
  npm, dans le document du paquet déjà téléchargé (`dependencies`, `optionalDependencies`,
  `peerDependencies` sans les optionnelles ; pour les versions stables seulement : les canaris de
  `next` gonfleraient le cache), rangé au format 4 du cache (chaque ensemble distinct une fois) ;
  PyPI, par l'API JSON d'une version (`/pypi/{nom}/{version}/json`, `requires_dist` : les lignes
  d'un même paquet réunies par `||`, ou fusionnées quand elles ne diffèrent que par leur borne
  basse, `fastembed` 0.8.0 et `pillow`), une requête par version, cache `FILES` (7 jours) ;
  seulement sur pypi.org (un index déclaré n'a pas cette API : on n'en sait rien).
- **Les lockfiles** (`parsers/lockfiles.required_by`, public) : `LockedPackage.peers`,
  `Lockfile.ranges` (faux pour uv et pnpm : chaque lien donne un `Requirement` sans plage) ;
  `Requirement.peer` ; une dépendance pair que le lockfile ne relie pas (Yarn 2+) va aux copies du
  paquet de ce nom ; ni le projet ni un membre du workspace (leurs plages sont les contraintes des
  manifestes, réécrites) ; **les directes aussi** (`with_required_by`, pour le refus prévu). Pas de
  nouveau mini-projet : ceux de E04 et E03 (npm, Yarn 1, Yarn 4, pnpm 9, Poetry, uv, faits par les
  vrais outils) couvrent tout (`tests/test_required_by.py`).
- **La passe `update/blockers.constrain`** (après `planner.audit`, puis `planner.reselect`) : le
  planner ne calcule plus l'indirecte retenue lui-même. Pour chaque option npm ou PyPI : les
  plages inconnues lues au registre (la version installée du paquet qui la tire) ; **retenue**
  (`held_by`) pour une indirecte par le lockfile seul quand l'outil la monte « aussi haut que
  possible » (npm, pnpm, Yarn, Poetry, PDM, pipenv : `MOVES_UP`) ; **refusée** (`refused_by`,
  nouveau) sinon : une directe, ou une indirecte que uv et pip-compile visent exactement
  (`--upgrade-package x==V`), refusée par une plage en Python (une version pour tout le projet),
  par une dépendance pair seulement en npm (une dépendance ordinaire : une copie à part) ; une
  version forcée (`overrides`) passe outre. npm, en plus : **la dépendance pair que la version
  visée demande** et que l'installée ne satisfait pas (`Blocker.companion`), sauf si la version
  utilisée la demandait déjà (le projet vit avec : `vite` et `yaml`, faux positif trouvé sur
  `sechunter`, corrigé avec les pairs optionnels). Pour chacun, **la plus basse version publiée
  qui l'accepterait** (`Blocker.accepting`, `checked`) : tout le document npm ; PyPI, la dernière
  puis par dichotomie (`MAX_LOOKUPS` = 8). « Dépendance indirecte : … devra peut-être monter
  aussi » est retiré quand les plages sont connues. Jamais pré-cochée (`choose`), failles pas
  comptées ; `_retry` reste.
- **Affichage** : les avertissements disent tout (« … ; monter d'abord nodemon en 4.0.1 (la
  première version qui l'accepte). », « … : uv la refusera, et aucune de ses versions publiées ne
  l'accepte. », « Demande @types/react ^19.3.0 (dépendance pair), et @types/react 18.3.28 est
  installée : npm la refusera, sauf si @types/react monte aussi (19.3.0 au moins). ») : écran 5 et
  terminal sans nouveau composant ; « Corrigerait …, mais X la fera refuser » ; le récapitulatif des
  PR (`ProposedUpdate.refused_by`, `blockers` ; `blockedText` : « retenue par … : monter d'abord …
  en … », « refusée à cause de … ») ; la description de PR et le terminal après la mise à jour
  (« retenue en … par … (nodemon 4.0.1 l'accepte) », `report.option_unblock`). API : `Blocker`,
  `UpdateOption.refused_by`, `blockers` ; `schema_version` reste 1 (des champs en plus).
- **Vérifié en vrai** (vrais registres, l'outil du dépôt) : le front de forceupdate (`typescript`
  7.0.2 refusée, `openapi-typescript` 7.13.0 demande `^5.x` en pair, aucune version ne l'accepte ;
  `minimatch` 11.0.1 retenue par `@ts-morph/common` 0.27.0, aucune ne l'accepte : vérifié avec
  `npm view`) ; un clone de `sechunter` (`redis` 8.1.0 et `python-dateutil` 4.0.0, les deux
  majeures que la reprise retirait à la session 37, dites d'avance ; `minimatch` du front) ; un
  clone d'`argos-ops` (`pillow` 13.0.0, `fastembed` 0.9.1 l'accepterait ; `@types/react` et
  `@types/react-dom`, `react` et `react-dom`, `vite` 8 et `@vitejs/plugin-react` et `esbuild`).
  Une analyse prend quelques secondes de plus (les requêtes de PyPI vont dans le cache).
- **« Parcourir… »** (`web.picker`) : macOS par `osascript` (`choose folder`, `choose file`, la
  fenêtre du Finder, sans Tk ; le titre et le dossier de départ en arguments ; annuler = -128) ;
  Linux : rien sans `DISPLAY` ni `WAYLAND_DISPLAY`, sinon `zenity`, `kdialog`, puis Tk ; Windows :
  Tk, inchangé. **Vérifié sous Linux** avec une vraie fenêtre (Docker, Xvfb, `xdotool` qui la
  remplit comme une personne) : `zenity` rend le dossier choisi, l'annulation `None`, Tk aussi.
  `tests/picker_desktop.py` et le workflow **« Fenêtre de choix »** (`picker.yml`, à la demande :
  macOS devant Safari, Linux avec `zenity`, Linux avec Tk ; captures en artefacts) : le seul Mac à
  portée est celui de la CI.

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
| 13 | 2026-10-28 | E13 | Fait, validé par l'utilisateur. Commit de E11 et E12 d'abord (accord de l'utilisateur). Avec le skill `ui-ux-pro-max` : `design-system/MASTER.md` (style « Data-Dense Dashboard », clair et sombre, accent bleu, couleurs de sens réservées et toujours doublées d'une icône et d'un mot, IBM Plex Sans + JetBrains Mono embarquées et sans ligatures, contrastes calculés dans les deux thèmes, composants shadcn/ui, accessibilité), `ECRANS.md` (les 9 écrans, leurs états, leurs adresses), 4 pages d'écran, maquettes statiques des écrans 1, 4, 5 et 7 (`mockups/`, sans ressource extérieure, état et thème au choix) avec les données réelles de `vulnerable` passées par l'API (analyse, plan, puis application sur une copie). Tranché : pile React + TypeScript + Vite + Tailwind 4 + shadcn/ui + Lucide (confirmée) ; clin d'œil limité à la « lame », la devise, un message de chargement et la page introuvable. Trouvé : les ligatures de JetBrains Mono déforment les commandes ; Lucide n'a plus de logos de marque ; Edge sans fenêtre ne descend pas sous 492 px. Vérifié : captures en clair et en sombre, 1440 et 375 px, contrôle d'accessibilité des 5 pages ; rien dans `src/`, 1706 tests verts, ruff propre. Cases ajoutées à E14, E15, E16, E17, E18, E29 |
| 14 | 2026-10-28 | E14 | Fait. API d'abord : `summary` dans la liste des analyses, `recent` en `{path, kind}`, et (ajouté) la répartition par gravité du résumé (`severities`, `vulnerabilities`) pour ne rien recompter dans le navigateur. `frontend/` : React 19 + TypeScript 5.9 (la 7 n'a pas l'API qu'utilise openapi-typescript) + Vite 8 + Tailwind 4 + shadcn/ui (base Radix, composants aux mesures des maquettes) + Lucide, polices latines embarquées ; tokens de MASTER, clair / sombre / système ; types générés depuis `openapi.json` (un test le vérifie). Coquille et écrans 1 à 4 avec leurs états, SSE fermé à `end`, annonces limitées, tableau trié et filtré, cartes sous 768 px, virtualisé au-delà de 50 lignes, panneau de détail à l'adresse. CSP gardée telle quelle : trouvé que Radix Dialog et Sonner injectent un `<style>`, d'où un `<dialog>` natif. Front construit dans `web/static/`, ignoré par git, embarqué dans le paquet (wheel et sdist vérifiés), construit par `publish.yml` ; job « Front » dans la CI. 48 tests Vitest, 7 Playwright sur un serveur hors ligne (`tests/e2e_server.py`) dont axe-core sans violation en clair et en sombre ; vérifié à la main sur `vulnerable` et sur ce dépôt (542 dépendances), de 375 à 1440 px. 1706 tests Python verts, ruff propre. Cases ajoutées à E15, E30 |
| 15 | 2026-10-28 | E15 | Fait. Commit de E14 d'abord (accord de l'utilisateur). Écran 5 dans `frontend/src/screens/update/` : Choisir (`/analyses/{id}/mise-a-jour` : cartes groupées par lockfile, case du paquet et radios des options, au plus une cochée, pré-cochage de l'API, option `manual` grisée, faille apportée en rouge, notes, « Sélection proposée », « Tout décocher », récapitulatif collant ou barre collante sous 1024 px, `?paquet=` et `?plan=`), Vérifier (`/plans/{id}` : ce qui sera fait, options sautées, diffs, lockfiles avec outil trouvé ou commande à copier, garde-fou git, « Appliquer quand même… » confirmé par un `<dialog>` natif, hors ligne, plan échoué ; fichier envoyé : « Télécharger »), Appliquer (SSE, lame, pas d'annulation), Résultat (statut par lockfile, versions exactes, plus hautes ou retenues, aussi changé, fichiers remis, sortie de l'outil, relancer l'analyse). Pas de logique métier : la sélection envoyée est `{Update.id: version}`, le récapitulatif se compte sur la sélection affichée. Ajouté : npm et uv simulés par le serveur de test. 74 tests Vitest, 16 Playwright (dont l'application sur une copie de `vulnerable`, le garde-fou, le téléchargement, axe-core sur l'écran 5 en clair et en sombre). Vérifié à la main avec les vrais npm et uv sur une copie de `vulnerable` (trois versions exactes) et sur ce dépôt. 1706 tests Python verts, ruff propre. Case ajoutée à E30 |
| 16 | 2026-10-28 | E16 | Fait. Commit de E15 d'abord (accord de l'utilisateur). OAuth App GitHub enregistrée par l'utilisateur, guidé pas à pas (le formulaire de GitHub a changé : « Redirect URIs », expiration des tokens décochée). Tranché avec lui : OAuth App, portées `repo` et `read:org`, logos de Simple Icons en une couleur. `forges/` : interface `Forge` (8 méthodes, types, erreurs), client GitHub (pagination `Link`, requêtes restantes, 401/403/404 clairs, droits d'un token, « non vérifiés » pour un fine-grained), OAuth avec `state` et PKCE, device flow, révocation, token de `gh` ; comptes (token dans le trousseau, le reste dans `accounts.json`, verrou). API des comptes (lister, OAuth, device flow, token collé, `gh`, vérifier, déconnecter) et adresse de retour hors de `/api`, seule exception du garde : une page renvoie vers `/comptes` (une redirection HTTP resterait « d'un autre site », sans cookie). Écran 6 (cartes, device flow en grand, token masqué, droits, déconnexion confirmée ; GitLab et Bitbucket « bientôt ») ; l'accueil montre les comptes. 5e garde-fou des tests (trousseau en mémoire, `gh` absent), GitHub simulé dans le serveur de test (page d'autorisation sur un autre site). Trouvé : sous Windows, `os.replace` échoue si le fichier est lu ou écrit en même temps (le compte disparaissait de l'écran). Vérifié avec le vrai compte : OAuth, device flow, token collé, déconnexion. 1851 tests Python verts, 98 Vitest, 25 Playwright. Cases ajoutées à E17, E18, E19, E20, E29, E30 |
| 17 | 2026-10-29 | E17 | Fait. Commit de E16 d'abord (accord de l'utilisateur). GitHub : `list_repos` (dépôts du compte, de ses collaborations et de ses organisations, drapeaux archivé, vide — vérifié pour ceux de taille nulle —, fork, privé, droit de push), `repository` (même d'un autre compte, sans token pour un public), `restrictions` (organisations qui restreignent l'accès des applications OAuth, ou exigent le SSO), `tree` (au commit de la branche par défaut) et `read_file` (contenu brut, au-delà de 1 Mo). `sources/forge.py` : seuls les fichiers que lisent les parseurs sont téléchargés (manifestes, lockfiles, puis `-r`, workspace uv, `pnpm-workspace.yaml`, tour par tour), puis le pipeline local inchangé ; les 14 mini-projets lus par l'API donnent le même inventaire qu'en local. API des dépôts (liste gardée le temps de la session, analyses groupées 4 à la fois par le même `Worker`, annulation, synthèse et état de chaque dépôt calculés par le serveur, requêtes consommées et restantes, dépôt public par son nom ou son adresse) ; un plan sur un dépôt est refusé jusqu'à E18. Écran 7 (comptes, alertes, synthèse filtrante, analyse groupée, tableau trié et filtré, cartes sous 768 px, sélection, dépôt public), rapport d'un dépôt, étape « Téléchargement », accueil avec le nombre de dépôts. Trouvé et corrigé : débordement de la vue d'ensemble du rapport à 375 px. Vérifié avec le vrai compte : 7 dépôts analysés en 15 s (32 requêtes), rapports de `sechunter` et `forceupdate` identiques à l'analyse locale du même commit. 1941 tests Python verts (plus 9 réseau), 113 Vitest, 32 Playwright. Cases ajoutées à E18, E19 |
| 18 | 2026-10-29 | E18 | Fait. Commit de E17 d'abord (accord de l'utilisateur). `forges/git.py` (adapté d'Argos : token par un credential helper éphémère, jamais dans les arguments ni dans une adresse, sorties masquées ; clone superficiel ; commit au nom du compte ; push avec `--force-with-lease` ; dossier de travail effacé), GitHub : `clone`, `branch`, `push_branch` (jamais la branche par défaut), PR trouvée, ouverte ou mise à jour. `update/forge.py` : `deliver` (clone, sélection préparée de nouveau sur le clone, réécriture, lockfiles, commit des seuls fichiers changés, push, PR décrite par ce qui a été fait puis le rapport Markdown). Tranché : récapitulatif sans clone (sur les fichiers de l'analyse) ; branche remplacée à chaque envoi, jamais par-dessus un commit d'un autre (décision n°22 du brief) ; même contenu : rien poussé ; un dépôt à la fois, outils dans le thread des mises à jour. Arborescence tronquée : analysée sur un clone. API `/api/proposals` (récapitulatif, envoi, suivi) ; écran 8 ; écran 7 (colonne PR, « PR ouvertes », « Préparer N PR ») ; « Préparer la PR » sur le rapport d'un dépôt et l'écran 5 pour un dépôt. Sixième garde-fou des tests (git local seulement), dépôts « bare » dans le GitHub simulé et le serveur de test. Vérifié avec le vrai compte sur `Pauzzle-ozz/forceupdate-demo` (créé pour l'essai) : PR #1 ouverte (vrais npm et uv, versions exactes), relancée : même PR, rien poussé ; `main` avancé : branche refaite, même PR. 1998 tests Python verts (plus 9 réseau), 127 Vitest, 37 Playwright. Cases ajoutées à E19, E20, E29, E30 |
| 19 | 2026-10-29 | E19 | Fait. Commit de E18 d'abord (accord de l'utilisateur) ; décision n°22 confirmée ; dépôt de test GitHub gardé pour E31. Application OAuth gitlab.com enregistrée par l'utilisateur, guidé (non confidentielle, PKCE, portée `api`, retour sur 127.0.0.1 tout port). `forges/gitlab.py` (projets des groupes et sous-groupes, droit de push par `min_access_level`, arborescence paginée sans tailles, fichiers bruts, clone et push avec `oauth2`, branche et arbre recalculé `tree_id`, MR ouverte ou mise à jour, OAuth PKCE sans secret, refresh token, révocation) ; `OAuthFlow` commune ; tokens d'OAuth de GitLab (2 h) renouvelés, un seul renouvellement à la fois par compte ; un compte par forge et par hôte (`?host=`), instance auto-hébergée par adresse + token ; lots et récapitulatifs à plusieurs forges (`RepositoryKey`) ; écrans 6 (carte GitLab, instances), 7 (« PR / MR », « Préparer 1 PR et 1 MR ») et 8 (PR et MR mêlées). GitLab simulé `tests/fake_gitlab.py`. Vérifié en vrai sur `Pauzzle-ozz/forceupdate-demo` (gitlab.com, créé pour l'essai) : MR !1 ouverte, relancée sans rien pousser, puis refaite sur un `main` avancé ; trouvé le 400 de `/personal_access_tokens/self` pour un token d'OAuth (corrigé). 2068 tests Python, 134 Vitest, 43 Playwright. |
| 20 | 2026-10-29 | E20 | Fait. Commit de E19 d'abord (accord de l'utilisateur). L'utilisateur, sans compte Bitbucket, guidé pour le créer (workspace `pauzzle`), puis pour enregistrer l'« OAuth client » (le formulaire a changé : « OAuth clients », onglets Details, Authorization, Scopes ; public, sans « Client credentials »). Recherche sur l'API de 2026, puis vérifiée en vrai (deux écarts trouvés : 404 et non 410 pour l'ancienne liste, `sort` refusé sur `/user/workspaces`). `forges/bitbucket.py` (workspaces puis leurs dépôts, droits, arborescence en largeur avec tailles, fichiers bruts, clone et push par `x-token-auth`, PR trouvée, ouverte ou mise à jour avec ses relecteurs, OAuth par `Basic` et formulaire, refresh token renouvelé à chaque usage, pas de révocation ; token d'API Atlassian collé). Trouvé : **un token de Bitbucket fait 2 775 caractères, Windows refuse un secret de plus de 1 280** : secrets découpés dans le trousseau ; l'API ne donne pas l'arbre d'un commit : lu par git (`Forge.branch_tree`) ; pas d'adresse `noreply` : l'adresse principale du compte. Écran 6 (carte Bitbucket, token d'API, déconnexion sans révocation et son lien), écrans 7 et 8 sans changement de fond. Bitbucket simulé `tests/fake_bitbucket.py`. Vérifié en vrai sur `pauzzle/forceupdate-demo` (créé par l'utilisateur) : PR #1 ouverte, relancée sans rien pousser, puis refaite sur un `main` avancé. 2114 tests Python, 138 Vitest, 49 Playwright. Cases ajoutées à E29, E30, E31 |
| 21 | 2026-10-30 | E21 | Fait. Commit de E20 d'abord (accord de l'utilisateur) ; cargo installé avec son accord (rustup, cargo 1.99.1). `parsers/rust.py` (repris de `reference/` : `Cargo.toml` en toutes ses formes, plateformes, renommages, git, chemins, autres registres, `workspace = true` lu dans `[workspace.dependencies]` de la racine via `resolved_constraint`, membres et `exclude` ; `Cargo.lock` 1 à 4 en graphe, dépendances de build figées), `versions/cargo.py` (le crate `semver` de Cargo réécrit : **26 choix de cargo reproduits**), `registries/crates.py` (index « sparse », `yanked`, `pubtime`), OSV `crates.io` (RUSTSEC et GHSA, versions corrigées justes), styles de contrainte Cargo, `writers/rust.py` (la racine réécrite comme un catalogue pnpm), pilote cargo. Trouvé en vrai : **`--precise` ignoré quand la contrainte réécrite n'accepte plus la version figée** (directe épinglée `=V` le temps d'un `cargo update --workspace`, `--precise` pour une indirecte) ; `build.rs` ne tourne pas, mais `rustc -vV` oui avec le résolveur 3 (`RUSTC`, `RUSTC_WRAPPER` vide) ; rustup installe et lance la chaîne d'outils d'un `rust-toolchain.toml` (dit dans le plan). Corrigé en route : le récapitulatif de l'écran 5 citait le manifeste d'un catalogue au lieu du fichier réécrit (pnpm aussi). Mini-projets `cargo` et `cargo-workspace` (lockfiles de cargo). Vérifié à la main avec le vrai cargo : `scan`, `update` et `ui` sur des copies, versions exactes. 2377 tests Python (plus 11 réseau), 139 Vitest, 49 Playwright. Cases ajoutées à E29 et à la phase F |
| 22 | 2026-10-30 | E22 | Fait. E21 déjà commitée. Go installé avec l'accord de l'utilisateur (winget bloqué par une autre installation : l'archive officielle de Go 1.27.3, vérifiée, dans `~/sdk`). `versions/go.py` (semver à `v`, pseudo-versions, `+incompatible`, chemins de majeure ; l'ordre de `golang.org/x/mod` reproduit), `parsers/go.py` (un lexer comme celui de `modfile` : `require` en ligne et en bloc avec emplacements, `// indirect`, `replace` local ou vers un module, `exclude`, `retract`, dépréciation ; `go.work` et ses membres), `registries/goproxy.py` (liste, `go.mod` de la dernière pour les retraits et la dépréciation, `@latest`, chemins encodés, 404/410, majeure suivante sous son chemin), OSV `Go`, `writers/go.py`, pilote `go mod tidy`. Tranché : la version de `go.mod` est la version utilisée (une contrainte n'accepte qu'elle) ; une indirecte se réécrit dans `go.mod` ; une majeure est un autre module, proposée « à la main » avec `go get …/vN` ; `go mod tidy` plutôt que `go get` (vérifié : `go get` pour descendre retire d'autres modules). Trouvé en vrai : tidy relève la directive `go` (et l'écrit, à la version installée, s'il n'y en a pas) ; `GOTOOLCHAIN=auto` télécharge un autre Go (`local` passé) ; `GOFLAGS=-modfile=` détourne tidy (neutralisé) ; un `vendor/` devient périmé (dit) ; une version exclue fait sauter tidy à la dernière (jamais proposée). Corrigé en route : la « dernière » ignore les versions exclues ; deux libellés de l'écran 5 (avec le skill `ui-ux-pro-max`) ; un double point de `forceupdate update` depuis E10. Mini-projets `go` et `go-workspace` (faits par `go`). Vérifié à la main avec le vrai `go` : `scan`, `update` (versions exactes, `go build`, `go mod tidy -diff` sans rien à changer) et `ui` sur des copies. 2551 tests Python (plus 13 réseau), 141 Vitest, 49 Playwright. Cases ajoutées à E29 |
| 23 | 2026-10-30 | E23 | Fait. Commit de E22 d'abord (accord de l'utilisateur) ; PHP 8.5.12 et Composer 2.11.0 installés avec son accord (archives officielles vérifiées, dans `~/sdk`). `versions/composer.py` (`VersionParser` de composer/semver et l'ordre de `version_compare` réécrits : **aucun écart** sur 1 282 versions, 19 600 paires et 99 contraintes ; **22 choix de `composer update` reproduits**), `parsers/php.py` (repris de `reference/` : contraintes telles qu'écrites et emplacements, noms en minuscules, paquets « plateforme », branches, `replace`/`provide`, `conflict`, dépôts `path` et autres d'après le lockfile ; `composer.lock` en graphe), `registries/packagist.py` (`p2` minifié, `abandoned` et son remplaçant), OSV `Packagist`, styles de contrainte (`~1.2` jusqu'à 2.0), `writers/php.py`, pilote `composer update x:V… -W --no-install --no-scripts --no-plugins`. Trouvé en vrai : `update --lock` garde une version que la contrainte n'accepte plus (jamais utilisé) ; `-W` nécessaire, `COMPOSER_MINIMAL_CHANGES` pour rien d'autre ; scripts et plugins lancés sans `--no-scripts`/`--no-plugins` (témoins) ; `COMPOSER_PREFER_LOWEST` fait descendre (retiré) ; **Composer 2.9+ refuse toute version qui garde une faille** : tranché avec l'utilisateur, levé pour les failles seules (`COMPOSER_POLICY_ADVISORIES_BLOCK=0`) sauf réglage du projet ou de la personne. `Dependency.excluded` devient des contraintes (`is_excluded`) ; corrigé en route : la version permise ignorait les versions exclues. Mini-projet `composer` (lockfile de Composer). Vérifié à la main avec le vrai Composer : `scan`, `update` (versions exactes, `composer validate` propre) et `ui` sur des copies. 2838 tests Python (plus 15 réseau), 141 Vitest, 49 Playwright. Cases ajoutées à E27, E29 |
| 24 | 2026-11-01 | E24 | Fait. E23 déjà commitée. Ruby 4.0.9 (RubyGems et Bundler 4.0.20) installé avec l'accord de l'utilisateur (RubyInstaller, archive vérifiée, dans `~/sdk`). `versions/rubygems.py` (`Gem::Version` et `Gem::Requirement` réécrits : **aucun écart** sur 6 013 versions, 90 926 paires et 221 contraintes ; **25 choix de `bundle lock` reproduits**), `parsers/ruby_spans.py` (un lexer de Ruby : le `Gemfile` n'est jamais exécuté), `parsers/ruby.py` (`Gemfile` et `gems.rb` : groupes, plateformes, sources, git, chemins, `gemspec`, conditions et variables dites ; `.gemspec` ; `Gemfile.lock` repris de `reference/` et réécrit d'après le `LockfileParser` de Bundler : toutes les sections, versions à plateforme, graphe ; une gem `path:` résolue dans le lockfile du `Gemfile` qui la cite), `registries/rubygems.py` (l'index compact, huit fois plus léger que l'API v1), styles `~>` (précision gardée, plancher `, >= V`), réécriture en plusieurs chaînes (`written_target`), pilote `_Bundler` (vérifié en vrai : Bundler ne vise pas une version, donc `= V` le temps d'un `bundle lock`, une ligne `gem` pour une indirecte ; il exécute le `Gemfile` et tous les `.gemspec` (quatre témoins) ; `BUNDLE_GEMFILE` et `BUNDLE_LOCKFILE` remplacés ; la plateforme qu'il ajoute sous Windows retirée). Mini-projet `bundler` fait par le vrai Bundler, 23 gems enregistrées, 51 avis OSV ajoutés. 3133 tests Python verts (plus 17 réseau, vrai Bundler compris), 141 Vitest, 49 Playwright ; vérifié à la main en ligne de commande et dans l'interface (11 versions exactes). Pas encore commitée. |
| 25 | 2026-11-01 | E25 | Fait. Commit de E24 d'abord (accord de l'utilisateur) ; ni Maven ni Gradle installés (son choix), seul le jar `maven-artifact` 3.9.16 téléchargé avec son accord (SHA-1 vérifiée) pour l'oracle, lancé par Nashorn (`jjs`, le JRE 8 n'a pas de `javac`). `versions/maven.py` (`ComparableVersion` et `VersionRange` réécrits : **aucun écart** sur 9 102 versions et 4 980 600 comparaisons, 45 spécifications ; trois mutations le voient ; `ComparableVersion` n'est pas transitif, comme Maven), `parsers/xml_spans.py` (expat, positions du texte, DTD refusée), `parsers/maven.py` (`pom.xml` : propriétés, parents du dépôt, `dependencyManagement`, BOM, plugins, profils, modules du build), `parsers/gradle_spans.py` et `parsers/gradle.py` (catalogue `libs.versions.toml`, `build.gradle(.kts)` lus en jetons, jamais exécutés, variables et `gradle.properties`), `registries/maven.py` (Maven Central, Google Maven, portail des plugins Gradle ; `<release>` peut être une pré-version), `update/writers/java.py`. Tranché : une version est située là où elle est écrite (propriété, `[versions]`, variable) et plusieurs dépendances partagent son emplacement (dit dans le plan) ; une version nue est la version utilisée (`installed`) ; les variantes (`-jre`/`-android`) ne se mélangent pas ; pas de lockfile (« Aucun lockfile à régénérer »). Log4Shell vérifié (2.15.0, 2.16.0, 2.17.0, 2.17.1). Mini-projets `maven` et `gradle`, 18 artefacts enregistrés, 19 versions ajoutées pour OSV. 3801 tests Python verts (plus 18 réseau), 141 Vitest, 49 Playwright ; vérifié à la main en ligne de commande et dans l'interface. |
| 26 | 2026-11-01 | E26 | Fait. Commit de E25 d'abord (accord de l'utilisateur) ; NuGet.Versioning 7.9.0 (l'oracle, chargé par PowerShell 5.1) et le SDK .NET 10.0.403 installés avec son accord (empreintes SHA-512 vérifiées, dans `~/sdk`). `versions/nuget.py` (`NuGetVersion`, `VersionComparer`, `VersionRange` et ses versions flottantes réécrits d'après le source : **aucun écart** sur 17 866 versions, 158 838 576 comparaisons implicites, 141 contraintes et 30 189 vérifications de `Satisfies` et `FindBestMatch` ; six mutations le voient), `parsers/xml_spans.py` (positions des attributs), `parsers/nuget.py` (`packages.config` repris de `reference/`, projets MSBuild, `Directory.Build.props` en chaîne, gestion centrale, `VersionOverride`, `GlobalPackageReference`, conditions dites, projets de tests, `packages.lock.json` en graphe par framework, `CentralTransitive`), `registries/nuget.py` (l'API « registration », ses pages, non listées, dépréciation et remplaçant), OSV `NuGet` sans la casse. Tranché : **NuGet prend la plus basse version qui convient** (`VersionScheme.lowest`, `reaches`, `chosen`) : une mise à jour réécrit la borne basse, une indirecte est à la main, la version permise est l'utilisée. Pilote `dotnet restore --force-evaluate -noAutoResponse -p:RestoreLockedMode=false`, vérifié en vrai (version centrale réécrite suffisante, flottante seulement avec `--force-evaluate`, une cible de `Directory.Build.targets` s'exécute, `Directory.Build.rsp` écarté, version non listée restaurée) ; le lockfile d'un autre projet qui lit une version centrale réécrite est régénéré aussi ; un `dotnet` sans SDK est un outil absent. Mini-projet `nuget` (lockfiles du vrai `dotnet restore`), onze paquets enregistrés (compressés), 38 versions ajoutées pour OSV. Les huit écosystèmes sont gérés : les tests « pas encore géré » retirent NuGet des tables. 4268 tests Python verts (plus 20 réseau, vrai dotnet compris), 141 Vitest, 49 Playwright ; vérifié à la main en ligne de commande et dans l'interface. Cases ajoutées à E27, E29 |
| 27 | 2026-11-01 | E27 | Fait. Commit de E26 d'abord (accord de l'utilisateur). endoflife.date vérifié en vrai (forme v1 : `isEol` booléen, `eolFrom` date ou `null`, `isLts`/`ltsFrom`, `latest`, 404 en HTML, un alias en 301 ; l'ancienne forme pas demandée) : `endoflife.py` (cache 24 h, une erreur est « non concluant »). `parsers/runtimes.py` : la version des runtimes sans rien exécuter (`requires-python`, Poetry, `Pipfile`, `setup.cfg` ; `engines.node`, `volta` ; `go`, `toolchain` ; `ruby` du `Gemfile`, `RUBY VERSION` ; `require.php`, `config.platform.php` ; propriétés Maven, Gradle ; `TargetFramework(s)` ; `.python-version`, `runtime.txt`, `.nvmrc` avec `lts/…`, `.node-version`, `.ruby-version`, `.tool-versions`, `global.json`, les `FROM` des `Dockerfile` avec leurs `ARG`), rattachés aux projets (`Project.runtime_files`, `Project.runtimes`). `checks/eol.py` : la table des frameworks (tirée des `purl` d'endoflife.date, 56 produits vérifiés), le cycle d'une version, le cycle conseillé (plus récent, maintenu, LTS d'abord : Django 3.2 → 5.2, Node.js 16 → 26), un constat si la fin est passée ou dans moins de 6 mois, à la date du jour que les tests fixent. Les versions qu'un runtime du projet ne fait pas tourner ne sont plus proposées (`checks/runtimes.py` : `engines.node`, `require.php`, `ruby:`, `requires-python` gardés par les registres ; symfony/console v6.4.49 sous PHP 8.1, comme `composer outdated`), et c'est dit ; la dernière version du cycle conseillé d'un framework proposée (`SUPPORTED_CYCLE`). Les SDK de projet MSBuild (`Sdk="Nom/Version"`, `<Sdk>`, `msbuild-sdks` de `global.json`) vérifiés et réécrits. Écran 4 : la section « Fins de vie » (date, source, cycle conseillé, LTS, version conseillée bloquée par le runtime), les runtimes dans la carte du projet. Mini-projet `eol` (Python 3.8, Django 3.2, Node.js 16) : trois constats datés, dans l'interface et en ligne de commande. 4441 tests Python verts (plus 21 réseau), 146 Vitest, 53 Playwright ; vérifié à la main en vrai (scan, update à blanc, interface en clair et en sombre). Cases ajoutées à E29, E30 |
| 28 | 2026-11-02 | E28 | Fait. Commit de E27 d'abord (accord de l'utilisateur). Vérifié en vrai : uv 0.10 et PEP 723 (bloc n'importe où, jusqu'au dernier `# ///`, refusé s'il n'est pas fermé, invisible derrière un BOM ; `uv lock --script` écrit `x.py.lock` ; un script à bloc ignore le projet autour), les 72 modules intégrés de Node 24.12 (4 seulement avec `node:`), le proxy Go (404 pour un sous-paquet ; `go mod tidy` rattache `golang.org/x/text/language` à `golang.org/x/text`). Un fichier de code dans un projet : la remontée jusqu'au premier manifeste de son écosystème (arrêt à la racine git, du disque, ou avant le dossier personnel), la source est le dépôt git, « analysé via `<manifeste>` ». Seul : le bloc PEP 723 (vrai manifeste, réécrivable, `requires-python` en runtime, `script.py.lock` lu et régénéré par `uv lock --script`), sinon ses imports (`ast` ; des lexers pour JS/TS et Go ; table import → paquet, espaces de noms et modules Go rattachés à la vérification). Nouveau constat `unpinned` (« version non fixée, dernière X »), remarque « failles non vérifiables ». Interface : écran 2 (fichiers de code, dépôt), écran 4 (lecture du fichier, compteur et alerte, badges). 4587 tests Python verts, 151 Vitest, 59 Playwright ; vérifié à la main en ligne de commande et dans l'interface (un débordement à 375 px trouvé et corrigé). |
| 29 | 2026-11-02 | E29 | Fait. Commit de E28 d'abord (accord de l'utilisateur). E29 de départ découpée avec lui en cinq étapes (E29 configuration et Réglages, E30 robustesse et performance, E31 mise à jour : le npm du projet, Python, NuGet, Go, E32 registres et dépôts privés, E33 compléments d'analyse ; documentation E34, recette E35). Décidé avec lui pour la suite : tokens GitHub sans expiration, `truststore`, `npx npm@10` coché d'office. Vérifié en vrai : rustup 1.29 (`rustup default`, `RUSTUP_TOOLCHAIN` devant `rust-toolchain.toml`, sans rien installer). `config.py` : `forceupdate.toml` ou `[tool.forceupdate]` (paquets et versions ignorés dans une syntaxe commune aux huit écosystèmes, dossiers exclus, dossiers de tests, sélection par défaut par écosystème), valeurs fausses dites et écartées ; un paquet ignoré n'est ni vérifié ni mis à jour mais ses failles restent dites, une version ignorée est retirée de ce que dit le registre. `preferences.py` : les réglages de la personne (le même format, dans son dossier de configuration ; dépôts exclus, délais des outils et du clone, chaîne d'outils Rust), lus par la ligne de commande (`--include-tests`, `--level` sinon le projet puis les réglages) et le serveur (`GET`/`PUT /api/settings`, `DELETE /api/cache`, `Cache.stats`). Le projet prime. Écran 9 (sélection, ignorés, analyse, dépôts exclus, outils, cache confirmé, thème) ; le rapport dit la configuration. Septième garde-fou des tests (`user_settings`). Trouvé par Playwright : une règle générale égale aux valeurs par défaut faisait dire « sélection réglée » (écartée). 4667 tests Python verts (plus 21 réseau), 162 Vitest, 67 Playwright ; vérifié à la main en ligne de commande et dans l'interface (vrai réseau, 375 px). Suite Python : 4 min 24 au calme (7 min à la fin de E28). Pas encore commitée. |
| 30 | 2026-11-02 | E30 | Fait. Commit de E29 d'abord (accord de l'utilisateur) ; E30 découpée avec lui : les cases des forges font E31 (« Forges : robustesse »), E31 à E35 deviennent E32 à E36. Vérifié en vrai : l'arbre de `npm.CMD` (`subprocess.run` rend un délai de 3 s après 25,8 s, ou laisse node tourner ; `taskkill /T` tue les quatre processus), Ctrl+Break (code 3), une jonction (suivie par `os.walk` et par `git ls-files`), un sous-module non initialisé (`RecursionError`), le BOM sur chaque fichier des mini-projets (TOML, requirements, go.mod, yarn.lock… cassés) et l'UTF-16 de PowerShell 5.1, httpx avec truststore, `SSL_CERT_FILE` (httpx seul remplace certifi : pypi.org refusé) et un proxy `CONNECT`. `processes.py` (tout outil, git et `gh` : l'arbre tué au délai, à Ctrl+C, à l'arrêt du serveur), `decode_text` (BOM, UTF-16), `_Listing` (200 000 fichiers au plus, jonctions, sous-modules), `Report.notices` (« Analyse partielle » dans l'interface), `ssl_context` (truststore, ajouté aux dépendances), un certificat refusé dit sans reprise, Ctrl+C pendant l'écriture ou un outil et l'arrêt du serveur : ce qui n'était pas fini est remis (`_undo_written`, `Jobs.stopping`), Ctrl+Break comme Ctrl+C. **Mesure** : Argos, cache vide, 3,2 s (86 directes, 569 à OSV), 7,4 s avec `--transitive` (570 vérifiées), aucun non concluant ; un vrai npm au délai de 0,3 s tué, fichiers remis en 0,5 s. Suite Python : 4 min 26. 4 761 tests Python verts (plus 21 réseau), 163 Vitest, 67 Playwright. E30 pas encore commitée. |
| 31 | 2026-11-02 | E31 | Fait. Commit de E30 d'abord (`a4f500a`, accord de l'utilisateur). Trois décisions de l'utilisateur : le trousseau sous Linux, la doc seulement ; une PR fermée sans fusion, le demander au récapitulatif ; l'arrêt pendant un envoi, tout de suite. Vérifié en vrai : `insteadOf` (configuration globale de test : détourne une adresse en argument, neutralisé par une règle vers elle-même, `pushInsteadOf` à part, l'adresse exacte gagne à égalité), les sous-modules dans l'arborescence (GitHub, GitLab : `type: commit`), le coût du `fetch` (cpython : 0,9 s et 480 Ko quand la branche part du `main` actuel, 2,4 s et 20 Mo à 300 commits), la spécification de Bitbucket (rien sur la durée d'un refresh token ; permission effective), keyring sans backend ; 662 clones d'analyses laissés dans le dossier temporaire (objets git en lecture seule). `web/workdirs.py` (le dossier du serveur, verrouillé, balayé au démarrage), `Forge.cancel` et `cancel` jusqu'à git, `processes.run` qui ne lance rien si l'arrêt est demandé, `Forge.closed_request` et l'écran 8 (badge, date, lien), le helper git qui ne donne le token qu'à l'hôte, `insteadOf` neutralisé, `Tree.submodules` et `ForgeSource.notices`, le `fetch` de Bitbucket sauté quand il est inutile. Huitième garde-fou des tests (`server_temp`). Trouvé : une course à l'arrêt (le nettoyage d'un clone et celui du dossier du serveur), le lien dans une phrase refusé par axe-core. Vérifié avec les vrais comptes, en lecture seule (PR #1 et MR !1 pas touchées). 4 789 tests Python verts (plus 21 réseau), 164 Vitest, 71 Playwright. |
| 32 | 2026-11-02 | E32 | Fait. E31 déjà commitée (`44d5183`). Vérifié en vrai, dans le scratchpad : la table Node → npm (nodejs.org : Node 22 → npm 10, Node 24 et 26 → npm 11 ; la LTS 26 s'appelle « Lithium »), `npx -y npm@10` (npm 6 et 7 réécriraient le lockfile dans un format plus ancien), `npm ci --dry-run` qui relit vraiment, pnpm 12 et corepack qui suivent `packageManager`, les en-têtes de `uv export`, `pip-compile`, PDM (Poetry n'en écrit pas), `dotnet restore` après une `PackageVersion` épinglée ou une `PackageReference` ajoutée, `go mod vendor`, Composer 2.9.8 (qui ignore `COMPOSER_POLICY_ADVISORIES_BLOCK`), le workspace npm (trois formes de version forcée). L'élagage de npm 11 n'a pas pu être recréé ; npm 11 et 10 se disputent les `"peer": true` (le témoin du test `network`). `update/project_npm.py` (le npm qu'attend le projet), la CI comme runtime (`parsers/runtimes.ci`), `Job.extra` : une case cochée d'office (le npm du projet par `npx`, relu par son `npm ci --dry-run` ; `go mod vendor`, `vendor/` remis sur un échec), décochée par l'écran 5 (`declined`) ou `--no-extras`, toujours faite pour une PR ; les `requirements.txt` générés en lockfiles (refaits après le leur : `uv export`, `pdm export`, `poetry export`), `Dependency.manual` (`--hash`), l'indirecte NuGet ajoutée au projet (`EditKind.REFERENCE`, une réécriture qui insère, relue), Composer 2.9 dit, `$x` des versions forcées npm. Écrans 5 et 8 (avec le skill `ui-ux-pro-max`), mini-projet `exports` fait par les vrais outils. Critère de fin vérifié : une copie à CI en Node 22, mise à jour avec le npm 11 de la machine, donne un lockfile que le vrai `npm@10 ci` accepte. 4 864 tests Python verts (plus 23 réseau), 167 Vitest, 72 Playwright. Pas encore commitée. |
| 33 | 2026-11-02 | E33 | Fait. Commit de E32 d'abord (`41f2fc8`, accord de l'utilisateur). Décidé avec lui : les identifiants des registres privés sont lus dans les fichiers de la personne et ne partent que vers l'hôte exact (https, ou la machine elle-même), jamais dans le cache, un rapport, un journal, l'API ni le navigateur ; les variables d'un fichier du projet ne sont jamais développées. Vérifié en vrai : `go env -w` et `GOENV`, le proxy public qui va chercher un module chez son hôte, `npm config`, un dépôt Composer local (Composer demande aussi Packagist), `dotnet nuget list source` et `<clear />`, uv et un index local à identifiants ; Maven et Gradle d'après leur documentation. `userfiles.py`, `net/auth.py` (un identifiant lié à son adresse ; `HttpClient` suit les redirections sans lui vers une autre origine), `routing/` (npm et `.yarnrc.yml`, Go, `.netrc`, Composer, NuGet, Python, Maven et Gradle, Ruby), `ComposerRepository`, `NuGetFeed`, `SimpleIndex` (JSON ou HTML) ; un paquet privé par son nom n'est jamais demandé au registre public ni à OSV ; un refus arrête la chaîne. Neuvième garde-fou des tests (`user_files`). Ajouté en route : la source globale d'un `Gemfile` (non vérifiée) ; à E34 : Ruby et Rust privés. Vérifié à la main : `forceupdate scan` contre six registres privés locaux, chacun avec son identifiant, aucun secret dans le rapport. Interface inchangée. 4987 tests Python verts (plus 23 réseau ; ceux des registres relancés), 167 Vitest, 72 Playwright. |
| 34 | 2026-11-03 | E34 | Fait. Commit de E33 d'abord (`598468e`, accord de l'utilisateur) ; découpage proposé, refusé : E34 entière en une session. Vérifié en vrai : Bundler 4.0.20 et un serveur de gems local à identifiant (index compact, clés de `bundle config`, miroir), cargo 1.99.1 et un registre « sparse » local à jeton (`credentials.toml`, `replace-with`, résolveur 3 et `rust-version`), Go 1.27.3 (`go.work`), le proxy (blackfriday), `composer audit` (twig 3.4.1 : 17 failles, 15 chez OSV) et huit choix de `minimum-stability`, Maven Central (`<relocation>`, Spring Boot), le SDK .NET (`Directory.Build.targets`), endoflife.date et nodejs.org, uv (`exclude-newer`) ; Maven et Gradle d'après leur documentation. `routing/ruby.py` (réécrit), `routing/cargo.py`, `GemServer`, le runtime `rust` (sans fin de vie), la version construite d'un workspace Go, chaque majeure à `+incompatible`, `advisories/packagist.py`, `ComposerVersions.resolved` et `Project.resolution` (format JSON et API), `managed.py` (parent et BOM distants, « à la main »), `Maven.pom` et `CacheKind.FILES`, `gradle.lockfile`, `settings.gradle(.kts)`, versions riches, la variante de Guava, `Update=` de MSBuild, images, `mise.toml`, `required_ruby_version`, `setup-*`, les tests `network` des tables, carnets, `.vue`, `.svelte`, Deno, `tsconfig.json`, `importlib`, espace de noms local, `exclude-newer` ; « Rust » au front. Trouvé : l'aiguillage de Cargo lisait une raison que `routing.apply` efface (il renvoyait à crates.io). 5 103 tests Python verts (plus 28 réseau), 168 Vitest, 72 Playwright. Pas encore commitée. |
| 35 | 2026-11-03 | E35 | En cours (reste la publication, après les essais de l'utilisateur). Commit de E34 d'abord (`34b4c4f`, accord de l'utilisateur) ; découpage proposé, refusé. Décidé avec lui : la `1.0.0rc1` d'abord, la `1.0.0` à la recette ; pas de publication dans cette session. Trouvé : `main` pas poussé depuis E13, la CI de E13 en échec ; la suite sous Linux (Docker) : **toute analyse d'un dossier plantait hors Windows** (`stat.IO_REPARSE_TAG_MOUNT_POINT`, E30), corrigé ; `.gitattributes` (LF partout). Doc : `README.md` (cinq captures, dont l'écran 8 et une vraie PR), `docs/USAGE.md`, `docs/FORGES.md`, `CHANGELOG.md`, `docs/JSON_FORMAT.md` vérifié par script. En relisant le code pour la doc : un identifiant dans l'adresse d'un dépôt Gradle partait en http et restait dans la clé du cache (corrigé), le proxy des réglages du système est lu (dit), d'autres écarts portés à E36. Packaging : version `1.0.0rc1`, `uv tool install .` sans node vérifié, `LICENSE` dans le wheel. CI : macOS, Front sous Windows, `network.yml` hebdomadaire ; premier passage : un chemin coupé sous macOS (corrigé) ; un test Playwright qui échouait par intermittence cachait un vrai défaut du front, trouvé par sa trace (les traces sont maintenant gardées) : une analyse finie en quelques millisecondes se disait « échouée » (corrigé, un test). Le serveur e2e balaie ses vieux dossiers. 5 110 tests Python (plus 28 réseau), 169 Vitest, 72 Playwright. Commits `be210cd`, `7a6a670`, `739a3c8` et le correctif du front, poussés. |
| 36 | 2026-11-03 | E35 | Fait. Les essais de l'utilisateur, faits ensemble, guidés étape par étape (installé depuis le dépôt) : lancement, analyse de forceupdate et d'Argos (mêmes chiffres qu'en ligne de commande), mise à jour d'une copie d'Argos (uv, npm 10 par npx), un fichier de code et un fichier déposé, les trois forges connectées par OAuth, 11 dépôts analysés, la PR #1 et la MR !1 mises à jour (sans nouvelle PR), les réglages, `scan` et `update` en ligne de commande, Ctrl+C. Deux défauts corrigés : le terminal et le Markdown (donc les PR) ne disaient pas pourquoi une version plus récente n'est pas proposée quand le runtime ne la fait pas tourner (`Finding.blocked`) ; l'écran de résultat des PR disait « rien à faire » quand npm avait gardé les versions choisies (des indirectes retenues par leur parent, le dépôt `mew` de l'utilisateur), il dit maintenant lesquelles et par qui. Une course dans trois tests Vitest de l'écran 8, révélée en route, corrigée ; les rapports d'exemple du front régénérés (périmés depuis E34). Portés à E36 (décidé avec l'utilisateur) : la fenêtre de choix d'un dossier du système, l'indirecte retenue dite d'avance, deux détails de « Mes dépôts », la déconnexion. Commits `bdb1b05` et `b9aacaf`, poussés, CI verte sur les huit jobs ; **la 1.0.0rc1 publiée sur PyPI** (accord de l'utilisateur), vérifiée depuis PyPI sans node. Puis son test final (une PR sur quatre de ses dépôts, relues par `gh`) : un lockfile npm que `npm ci` refuse partait tel quel (corrigé : toujours relu, refait par une vraie installation) ; trois défauts portés à E36. À sa demande : télécharger le rapport (Markdown, JSON, les dépendances à mettre à jour en CSV ; `scan --format csv`) et « Parcourir… », la fenêtre de choix du système (Tk). Commits `bdb1b05`, `b9aacaf`, `3007959` et celui de la fin, poussés. 5 125 tests Python, 174 Vitest, 72 Playwright. |
| 37 | 2026-11-03 → 04 | E36 | Fait. **La 1.0.0 est publiée sur PyPI** et vérifiée depuis PyPI, sans node, sous Windows et sous Linux (Docker) ; « Le livrable » coché. Découpage proposé, refusé. La PR #1 de `forceupdate` renvoyée avec l'utilisateur : le lockfile refait par npm passe ; deux causes de plus dans notre code (la règle `react(immutability)` d'oxlint 1.91, une course dans un test Vitest), corrigées, CI de la PR verte. **Une majeure que l'outil refuse ne fait plus tomber tout le lockfile** (relancé sans les majeures, puis avec chacune ; celles qu'il refuse retirées avec sa raison) : vérifié avec le vrai uv sur `sechunter` (redis 8, python-dateutil 4) et sur les dépôts de test (pip-compile : flask 3, werkzeug 3). **L'indirecte retenue dite d'avance** (`package-lock.json` : `Dependency.required_by`, `UpdateOption.held_by`). Les huit écarts de E35, les points de la session 36 (commit, chemins `~`, `[selection]`, « Mes dépôts »), le résultat des PR (renvoyer un dépôt en échec, « En route », l'icône). Trouvé à la recette : Bitbucket prenait une PR fusionnée pour l'ouverte (le paramètre `state` ignoré avec `q`), corrigé ; un lien pour choisir les mises à jour d'un dépôt sauté. Recette guidée (clone de `sechunter`, les trois forges, PR #2 / MR !2 / PR #2, la déconnexion), un vrai projet par écosystème (six projets publics ; vraies mises à jour Rust, Go, PHP, Java), revue d'interface (axe-core, clair et sombre, 375 et 1 440 px). Ajoutée : E37 (la 1.1.0). Commits `06d9c3c`, `153c67d`, `d96a71f`, `cd096ff`, `9c37b39`, étiquette `v1.0.0`. 5 151 tests Python, 179 Vitest, 72 Playwright. |
