# Session 29 — Étape E29 : Configuration, page Réglages, robustesse

Contexte : E01 à E28 sont faites. E28 a rendu utile le choix d'un fichier de code : dans un projet,
la remontée jusqu'au premier manifeste de son écosystème (arrêt à la racine git, du disque, ou avant
le dossier personnel ; la source est le dépôt git, « analysé via `<manifeste>` ») ; un script à bloc
PEP 723 est son propre manifeste (réécrivable, `script.py.lock` régénéré par `uv lock --script`) ;
sans projet, ses imports (Python par `ast`, JS/TS et Go par des lexers ; table import → paquet ;
modules Go et espaces de noms Python rattachés à la vérification). Nouveau constat `unpinned`
(« version non fixée, dernière X »), et l'interface (écran 2 : fichiers de code, dépôt ; écran 4 :
lecture du fichier, compteur, alerte). 4587 tests Python verts (plus 21 réseau), 151 Vitest,
59 Playwright. **E28 n'est pas commitée : à proposer d'abord.** E29 : la configuration, la page
Réglages (écran 9), et la robustesse.

Lis CLAUDE.md, puis l'étape E29 de PLAN.md (toutes ses cases, et les « Depuis E… » venues des
étapes d'avant, dont « Depuis E28 »), les notes de E27 et E28 (comment un comportement a été
vérifié en vrai avant d'être écrit), et `docs/BRIEF.md` (décisions n°5, 12, 18 ; « Questions encore
ouvertes »). Puis le code qui sert de modèle : `engine.py` (`inventory`, `check`), `models.ScanOptions`,
`update/planner.py` (`Rules`, `select`), `cli.py` (les options de `scan` et `update`), `net/cache.py`
(`Cache.clear`), `web/` (`app.py`, `schemas.py`, les routes), `detect/manifests.py` (`find_projects`,
`include_tests`). **L'interface change** (écran 9, Réglages) : charger d'abord le skill
`ui-ux-pro-max`, puis lire `design-system/MASTER.md`, l'écran 9 dans `design-system/ECRANS.md` et ses
maquettes.

À faire :
- Configuration par projet : `forceupdate.toml` à la racine, ou `[tool.forceupdate]` dans
  `pyproject.toml` (paquets ou versions ignorés, sélection par défaut par écosystème, dossiers exclus,
  projets des dossiers de tests).
- Réglages de l'utilisateur (`platformdirs`) : sélection par défaut, dépôts exclus, cache (le vider) ;
  l'écran 9 pour les modifier (le thème y figure aussi).
- Les cases « Depuis E… » de E29 dans PLAN.md (E16, E18, E20 à E28 : `requirements.txt` générés,
  lignes à `--hash`, indirectes NuGet, fins de vie, npm attendu par le projet, PHP, Go, Rust, Java,
  Bitbucket, fichier de code isolé).
- Robustesse : gros dossiers, fichiers illisibles et encodages, jonctions et sous-modules, erreurs
  réseau partielles, proxy et certificats, Ctrl+C pendant une mise à jour, délais des outils sous
  Windows (tuer tout l'arbre).
- Performance : mesurer sur un gros dépôt (Argos : `~/Desktop/the good guy`), viser moins de 30 s
  cache vide pour environ 500 dépendances directes ; noter la mesure dans le journal.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E28 (message « E28 : fichier de code isolé », un
  résumé comme pour E26 et E27).
- **E29 est très grosse** : la découper avec l'accord de l'utilisateur (règle 4 de CLAUDE.md : une
  étape découpée, par exemple E29 configuration et Réglages, E30 robustesse et les « Depuis E… »,
  les suivantes renumérotées) avant de commencer, et noter le découpage dans PLAN.md.
- Décisions à demander à l'utilisateur : les tokens GitHub qui expirent (« Depuis E16 ») ; une
  dépendance de plus pour les certificats du système (`truststore`) ; régénérer un lockfile avec le
  npm qu'attend le projet (`npx npm@10`, une case dans le plan).
- Vérifier en vrai avant d'écrire, comme à E27 et E28 : ce que lit `uv`/`npm` d'une configuration,
  le comportement réel d'un outil sous Windows (arbre de processus de `npm.CMD`), un vrai proxy si
  possible.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache ni
  le trousseau de l'utilisateur, jamais ses réglages (un dossier de réglages propre au test, comme
  `_no_user_cache`) ; `reference/` n'est jamais importé par `src/`. Les fins de vie se jugent au jour
  de l'enregistrement d'endoflife.date (`record.RECORDED_ON`). Un fichier de code du dépôt
  s'analyse via le `pyproject.toml` de forceupdate : le copier ailleurs et fixer `local._home`.
- La suite Python a pris 7 minutes à la fin de E28, contre 3 au début : la même mesure sur le code de
  E27 (un `git worktree`) variait de 55 à 81 s selon la charge de la machine (Defender) ; à
  remesurer au calme, avec `--durations=25`.
- Les SDK et outils sont hors du `PATH` des outils (`~/sdk/…`, cargo) : la ligne de CLAUDE.md pour
  les tests `network`.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc (il mange les
  barres obliques inverses, et un `"\\n"` de code Python y devient un vrai saut de ligne) ; l'outil d'écriture change
  un `\uXXXX` en caractère (écrire `chr(0x…)`) ; `python -I` ignore `PYTHONIOENCODING`
  (`-X utf8`) ; un argument qui commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1`. Pour piloter
  la vraie interface : un script Playwright en `.cjs` dans le scratchpad, qui `require` le
  Playwright de `frontend/node_modules` (`ui --no-browser` en arrière-plan, l'adresse lue dans sa
  sortie, le serveur arrêté ensuite) ; attendre le titre exact du rapport (`exact: true`) ;
  mesurer le débordement horizontal à 375 px sur le vrai réseau aussi (une version longue l'a
  révélé à E28). `toHaveTextContent` ramène les espaces insécables à des espaces.

Fini quand : tests de robustesse verts, mesure de performance notée, réglages modifiables depuis
l'interface (ou, si E29 est découpée, le critère de la partie faite). Vérifier avec : `uv run pytest`,
`uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; à la main, `uv run forceupdate ui` (écran 9)
et une analyse d'un gros dépôt.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
