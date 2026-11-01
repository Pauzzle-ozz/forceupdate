# Session 28 — Étape E28 : Fichier de code isolé

Contexte : E01 à E27 sont faites. E27 a ajouté le type 3 du brief, la fin de vie : la version des
runtimes lue sans rien exécuter (`parsers/runtimes.py` : manifestes, `.python-version`, `.nvmrc`,
`global.json`, `FROM` des `Dockerfile`… ; `Project.runtimes`), le client d'endoflife.date
(`endoflife.py`, cache 24 h), les constats datés avec le cycle conseillé (`checks/eol.py`, une table
des frameworks), les versions qu'un runtime du projet ne fait pas tourner écartées
(`checks/runtimes.py` : `engines.node`, `require.php`, `ruby:`, `requires-python`), les SDK de projet
MSBuild, la section « Fins de vie » de l'écran 4 ; le mini-projet `tests/projects/eol`. 4441 tests
Python verts (plus 21 réseau), 146 Vitest, 53 Playwright. **E27 n'est pas commitée : à proposer
d'abord.** E28 : choisir un fichier de code (pas un manifeste) donne un résultat utile.

Lis CLAUDE.md, puis l'étape E28 de PLAN.md, les notes de E27 (comment un comportement a été vérifié
en vrai avant d'être écrit), et `docs/BRIEF.md` : « Les sources » (un fichier de code dans un
projet, sans projet, glissé-déposé ; le bloc PEP 723), décisions n°2 et 11. Puis le code qui sert
de modèle : `sources/local.py` (un fichier seul, analysé avec ses lockfiles voisins),
`detect/manifests.py` (`match_dependency_file`, `find_projects`), `parsers/python.py` (le
`pyproject.toml` : PEP 621, `string_spans` de `toml_spans.py` pour les emplacements),
`parsers/runtimes.py` (un bloc PEP 723 a aussi un `requires-python`), `checks/` (« non concluant »
d'une version inconnue, `checks/base.current_version`), `engine.inventory`, `web/jobs.py` et
`web/app.py` (le fichier envoyé : analysé, téléchargé réécrit, jamais appliqué), `update/writers/`
(la réécriture vérifiée par le parseur). **L'interface change** (le fichier glissé-déposé, « analysé
via `<manifeste>` », « version non fixée ») : charger d'abord le skill `ui-ux-pro-max`, puis lire
`design-system/MASTER.md`, les écrans 2 et 4 dans `design-system/ECRANS.md` et `design-system/pages/`.

À faire :
- Fichier dans un projet : remonter les dossiers jusqu'au premier manifeste (arrêt à la racine git ou
  du disque) ; analyser ce projet, en disant « analysé via `<manifeste>` ».
- Fichier seul :
  - Python : bloc PEP 723 (`# /// script`), un vrai manifeste (contraintes, emplacements,
    réécrivable ; son `requires-python` est un runtime) ; sinon les imports (module `ast`), sans la
    bibliothèque standard (`sys.stdlib_module_names`), avec une table import → paquet (`yaml` →
    `PyYAML`, `cv2` → `opencv-python`, `PIL` → `Pillow`, `sklearn` → `scikit-learn`, `bs4` →
    `beautifulsoup4`…) ;
  - JS / TS : `import` et `require` de paquets (scopés compris), sans `node:` ni modules intégrés ;
  - Go : imports, rattachés à leur module.
- Sans version : le constat est « version non fixée, dernière = X » ; les failles ne sont pas
  vérifiables sans version, et le rapport le dit.
- Mise à jour d'un fichier seul : seulement le bloc PEP 723.
- Marche aussi par glisser-déposer dans l'interface.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E27 (message « E27 : fin de vie des runtimes et
  frameworks », un résumé comme pour E25 et E26).
- Vérifier en vrai avant d'écrire : ce que `uv run` lit d'un bloc PEP 723 (et ce qu'il refuse), la
  liste des modules intégrés de Node (`require('module').builtinModules`), un import Go d'un
  sous-paquet (`golang.org/x/text/language` → le module `golang.org/x/text`, par le proxy).
- Un fichier de code n'est jamais exécuté, ni importé : `ast.parse` seulement, et un lexer pour JS
  et Go. Un import relatif (`./util`, `.module`) ou d'un paquet du projet n'est pas une dépendance.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache
  de l'utilisateur ; `reference/` n'est jamais importé par `src/`. Les fins de vie se jugent au jour
  de l'enregistrement d'endoflife.date (`record.RECORDED_ON`, fixture `_fixed_today`).
- Les SDK et outils sont hors du `PATH` des outils (`~/sdk/…`, cargo) : la ligne de CLAUDE.md pour
  les tests `network`.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture (un heredoc a encore mangé des
  barres obliques inverses à E27) ; `python -I` ignore `PYTHONIOENCODING` (`-X utf8`) ; jamais
  `node -e "…"` avec des accents graves ; un argument qui commence par `/` sous Git Bash :
  `MSYS_NO_PATHCONV=1`. Un dossier de test nommé `build/` est écarté par la découverte. Pour piloter
  la vraie interface : un script Playwright en `.cjs` dans le scratchpad, qui `require` le
  Playwright de `frontend/node_modules` (`ui --no-browser` en arrière-plan, l'adresse lue dans sa
  sortie, le serveur arrêté ensuite par son port) ; attendre le titre exact du rapport
  (`exact: true`). `toHaveTextContent` de Testing Library ramène les espaces insécables à des
  espaces : y écrire des espaces simples.

Fini quand : les trois cas (fichier dans un projet, script PEP 723, script avec seulement des
imports) donnent un rapport juste, en ligne de commande et dans l'interface (glisser-déposer
compris). Vérifier avec : `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans
`frontend/` : `npm test`, `npm run typecheck`, `npm run lint`, `npm run test:e2e` ; à la main,
`uv run forceupdate scan` sur chaque cas dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
