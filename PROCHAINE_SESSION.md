# Session 35 — Étape E35 : Documentation, packaging, CI

Contexte : E01 à E34 sont faites. E34 (compléments d'analyse, faite en une session à la demande de
l'utilisateur) : registres privés de Ruby (serveurs de gems, configuration de Bundler) et de Rust
(`[registries]`, `credentials.toml`), `rust-version` et le résolveur 3, la version construite d'un
workspace Go et les majeures à `+incompatible`, les avis de Packagist (FriendsOfPHP) et
`minimum-stability`, les versions Maven gérées par un parent ou un BOM distant (`managed.py`),
`<relocation>`, `gradle.lockfile`, `settings.gradle(.kts)`, les versions riches, la variante de
Guava, `Directory.Build.targets`, de nouvelles sources de runtimes (images, `mise.toml`,
`required_ruby_version`, `setup-*`), les tests `network` des tables tenues à la main, et pour les
fichiers de code les carnets, `.vue`, `.svelte`, Deno, `tsconfig.json`, `importlib`, un paquet
d'espace de noms local et `exclude-newer`. Détail dans les notes de E34.
5 103 tests Python verts (plus 28 réseau), 168 Vitest, 72 Playwright.
**E34 n'est pas commitée : à proposer d'abord.**

Lis CLAUDE.md, puis l'étape E35 de PLAN.md (toutes ses cases), et les notes qu'elle cite : E16 à
E20 (forges), E27 à E34 (les limites de chaque étape, pour la documentation), docs/BRIEF.md
(décision n°19 : PyPI), docs/JSON_FORMAT.md.
Pour les captures d'écran du README : charge d'abord le skill ui-ux-pro-max, et lis
design-system/MASTER.md.

À faire (les cases de E35) :
- `README.md` : à quoi ça sert, installation, démarrage (`ui`), captures d'écran (dont l'écran 8 et
  une PR), la ligne de commande, les limites par écosystème ;
- `docs/USAGE.md` (l'interface écran par écran, toutes les commandes et options, et tout ce que
  listent les puces « Depuis E… » de E35, dont celle de E33 et E34), `docs/FORGES.md` (les puces de
  E16, E18, E20, E31), `docs/JSON_FORMAT.md` à jour, `CHANGELOG.md` ;
- packaging : `uv tool install .` sous Windows sur une machine sans node, version `1.0.0`, `LICENSE`
  dans le paquet ;
- CI : macOS en plus, le job « Front » aussi sous Windows, un job hebdomadaire avec les tests
  `network` (dont `tests/test_tables_network.py`) ;
- le dossier `forceupdate-e2e-*` que laisse le serveur des tests de bout en bout ;
- publication sur PyPI (Trusted Publishing, `v1.0.0`) : **avec l'accord de l'utilisateur**, puis
  `uv tool install forceupdate` depuis PyPI sur une machine sans node.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E34 (message « E34 : compléments d'analyse »,
  un résumé comme pour E32 et E33).
- E35 est grosse elle aussi : proposer de la découper (par exemple la documentation, puis
  packaging, CI et publication), sans découper seul.
- La documentation décrit l'outil tel qu'il est : relire le code ou essayer la commande avant
  d'écrire une option ou une limite ; les limites sont dans les notes de chaque étape (« Limites »).
- Publier sur PyPI est irréversible (un numéro de version ne se réutilise pas) : jamais sans
  l'accord de l'utilisateur, et après une CI verte.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc ni par
  `python -c` avec des `\n` dans une chaîne (l'outil Bash les transforme) ; `python -I -X utf8`.

Fini quand : `uv tool install forceupdate` depuis PyPI, dans un dossier vierge, marche ; la CI est
verte. Vérifier avec : `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans
`frontend/` : `npm test`, `npm run typecheck`, `npm run lint`, `npm run test:e2e`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
