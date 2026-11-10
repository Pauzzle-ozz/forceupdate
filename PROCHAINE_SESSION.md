# Session 40 — Étape E39 : Entretien après la 1.1.1

Contexte : **le projet est livrable, et la 1.1.1 est publiée sur PyPI** (session 39, étiquette
`v1.1.1` sur `7fff3e6`), vérifiée depuis PyPI, sans node, sous Windows et sous Linux. La 0.1.0 et
la 1.0.0rc1 sont retirées (« Remiser »). E38 est faite : « Aller » de l'écran 2 n'est plus
désactivé pendant un chargement (il faisait perdre Entrée : la cause du test Playwright instable) ;
« Parcourir… » sous macOS prend le clavier sans clic ni autorisation (`osascript` se déclare
programme « accessory », AppKit), vérifié sur le Mac de la CI. E39 n'est que de l'entretien, quand
l'utilisateur le veut : aucune nouvelle fonction prévue. 5 192 tests Python, 183 Vitest,
72 Playwright.

Lis CLAUDE.md, puis l'étape E39 de PLAN.md, et les notes de E38 (session 39). Si tu touches à
l'interface : charge d'abord le skill `ui-ux-pro-max` (il est rangé dans
`~/.claude/skills-archive/ui-ux-pro-max-v2.5.0/.claude/skills/ui-ux-pro-max/SKILL.md`), puis
`design-system/MASTER.md`, l'écran dans `design-system/ECRANS.md` et sa page dans
`design-system/pages/` s'il en a une.

À faire :
- **D'abord** : `git status` (doit être propre), `gh run list` (la CI du dernier commit, et les
  derniers passages de `network.yml`, le lundi : regarder sur quel commit ils ont tourné,
  `gh run view <id> --json headSha`, avant de corriger quoi que ce soit) ; demander à
  l'utilisateur ce qu'il a vu en se servant de la 1.1.1.
- Les tests `network` du lundi : corriger ce qu'un registre ou un outil a changé.
- Ce que l'utilisateur rapporte : le reproduire par un test qui échoue d'abord, puis le corriger.
- Une 1.1.2 seulement si une correction le demande, avec l'accord de l'utilisateur.

Attention :
- **L'utilisateur préfère être guidé** pour les essais et pour ce qui se fait sur un site (PyPI) :
  une étape à la fois, la commande ou le clic exact, puis ce qu'il doit voir ; il répond par une
  capture. Ses projets réels toujours en clone dans le scratchpad (`git clone --no-hardlinks`),
  jamais son vrai dossier. La page de gestion de PyPI est en français (« Remiser » pour « Yank »).
- **Un test instable** : lire la trace Playwright gardée par la CI (artefact
  `traces-playwright-<os>`, `gh run download <id> -n …`) : ses requêtes (`*.network`) et ses
  actions (`test.trace`), avec leurs heures, avant d'allonger une attente.
- **Installer l'outil depuis le dépôt** : `npm run build` si le front a changé, **arrêter son
  `forceupdate ui`** d'abord, puis `uv tool install . --force --reinstall --refresh-package
  forceupdate`. Depuis PyPI : `uv tool install --refresh --force forceupdate`.
- **Publier est irréversible** : une version seulement avec l'accord explicite de l'utilisateur,
  après une CI verte ; vérifier ensuite depuis PyPI avec `--refresh` (Windows : des
  `UV_TOOL_DIR` et `UV_TOOL_BIN_DIR` à part ; Linux : Docker, utilisateur non root ; Docker
  Desktop est à démarrer). Un `forceupdate.exe` arrêté par `kill` laisse tourner son Python :
  l'arrêter par son PID (vu par son port), et effacer son dossier `forceupdate-ui-*`.
- **« Parcourir… » sous macOS** : l'essayer par le workflow « Fenêtre de choix »
  (`gh workflow run picker.yml --ref <branche>`, captures en artefacts). Sous macOS, System Events
  dit toujours le navigateur au premier plan, même quand la fenêtre a le clavier : seules les
  frappes le prouvent. Sous Linux, l'essai de `zenity` ouvre la fenêtre dans le dossier à choisir
  et clique « OK » (Entrée n'y valide pas sous GTK 4).
- Les heredocs de l'outil Bash abîment les antislashs et parfois les apostrophes : écrire les
  scripts dans le scratchpad avec l'outil d'écriture, puis les lancer. L'outil d'édition écrit en
  CRLF sous Windows : repasser en LF (`sed -i 's/\r$//'`).
- Les rapports d'exemple du front (`frontend/src/test/fixtures/`) se refont par
  `tests/e2e_server.py --report` (celui de `imports.py` depuis une copie qui garde `helpers.py`
  à côté).
- `~/sdk` (Go, PHP, Composer, Ruby, .NET) et Rust sont gardés (choix de l'utilisateur).

Fini quand : les points de E39 sont faits ou décidés avec l'utilisateur. Vérifier avec :
`uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; `gh run list`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
