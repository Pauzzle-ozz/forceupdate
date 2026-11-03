# Session 36 — Étape E35 (fin) : les essais de l'utilisateur, la publication de la 1.0.0rc1, puis E36

Contexte : E01 à E34 sont faites ; E35 (documentation, packaging, CI) l'est sauf sa dernière case,
la publication sur PyPI : **l'utilisateur a voulu d'abord essayer l'outil lui-même**, installé
depuis le dépôt (`uv tool install .`), sur ses projets et ses comptes. Fait à E35 :
`README.md` réécrit (aussi la page PyPI) avec cinq captures, `docs/USAGE.md` (la doc utilisateur
complète), `docs/FORGES.md`, `CHANGELOG.md`, `docs/JSON_FORMAT.md` vérifié ; la version
`1.0.0rc1` (décision de l'utilisateur : une pré-version d'abord, la 1.0.0 au tag de la recette) ;
la CI sur Ubuntu, Windows et macOS (Python 3.11 et 3.14), le front sous Ubuntu et Windows,
`network.yml` chaque lundi ; `.gitattributes` (LF partout). En faisant tourner la suite sous
Linux, trouvé et corrigé un plantage de toute analyse hors Windows (E30). Poussé : `be210cd`,
`7a6a670`, `739a3c8` et `0425828` (CI verte sur les huit jobs) ; la case CI de PLAN.md, cochée
après, peut ne pas être commitée (`git status`).
5 110 tests Python (plus 28 réseau), 169 Vitest, 72 Playwright.

Lis CLAUDE.md, puis dans PLAN.md : la case « Publication sur PyPI » de E35 et les notes de E35,
puis l'étape E36 (toutes ses cases, dont « Depuis E35 ») et « Le livrable » (en tête).

À faire :
0. **Les retours de l'utilisateur** sur ses essais : les lui demander s'il ne les donne pas.
   Chaque défaut est reproduit, corrigé avec son test (et la doc si elle change), ou, trop gros,
   porté au plan (E36 ou une nouvelle étape) ; rien n'est publié avant que l'utilisateur dise que
   c'est bon.
1. **Finir E35** :
   - vérifier la CI du dernier commit poussé (`gh run list`) : verte sur les trois systèmes et pour
     le front ; sinon, corriger d'abord (la suite sous Linux se lance en local par Docker :
     CLAUDE.md, « La suite sous Linux, sans pousser » ; macOS seulement par la CI). Un test
     Playwright qui échouait par intermittence (`e2e/code.spec.ts`) cachait un vrai défaut du front
     (une analyse finie en quelques millisecondes dite « échouée »), trouvé par sa trace et corrigé
     à la fin de la session 35 ; la CI garde les traces d'un test en échec (l'artefact
     `traces-playwright-<os>` du job) : si un test échoue encore, lire sa trace
     (`npx playwright show-trace`) avant toute autre chose, et ne jamais relancer jusqu'au vert ;
   - **avec l'accord de l'utilisateur**, pousser l'étiquette `v1.0.0rc1` sur ce commit :
     `publish.yml` vérifie que l'étiquette est la version, teste, construit le front et publie par
     Trusted Publishing ; suivre le workflow « Publication » ;
   - vérifier `uv tool install forceupdate==1.0.0rc1` **depuis PyPI**, dans des dossiers d'outils à
     part (`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR` dans le scratchpad) et un `PATH` sans node : `--version`,
     un `scan`, `ui` qui sert l'interface ; regarder la page PyPI (le README, ses images) ;
   - cocher la case, E35 « fait », une ligne au journal.
2. **Puis E36, avec l'accord de l'utilisateur** (une étape par session : lui proposer de la faire
   dans cette session ou la suivante) : dérouler « Le livrable » dans l'interface installée depuis
   PyPI, la revue finale avec le skill ui-ux-pro-max, les écarts « Depuis E35 », la 1.0.0.

Attention :
- **Publier est irréversible** (un numéro de version ne se réutilise pas) : jamais sans l'accord
  de l'utilisateur, et seulement après une CI verte. Si la publication échoue après l'étiquette,
  ne pas réutiliser `v1.0.0rc1` : comprendre, puis `1.0.0rc2` avec son accord.
- La CI a eu un délai dépassé une fois sous Ubuntu (Playwright, le second envoi d'une MR) : les
  tests à deux envois ont maintenant `test.slow()` ; si un test reste instable, le dire plutôt que
  de relancer jusqu'au vert.
- Pour E36, charger d'abord le skill ui-ux-pro-max et lire design-system/MASTER.md (sa
  « Checklist avant livraison ») ; les PR #1 et MR !1 des dépôts de test existent déjà : les
  supprimer en fin de recette **avec l'accord de l'utilisateur** (jamais un autre dépôt).
- La doc décrit l'outil tel qu'il est : un écart corrigé change aussi `docs/USAGE.md`,
  `docs/FORGES.md` ou le README.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc ni par
  `python -c` avec des `\n` dans une chaîne ; `python -I -X utf8`. Jamais de `git stash` sur
  l'arbre de travail pendant qu'une suite de tests tourne.

Fini quand (E35) : `uv tool install forceupdate==1.0.0rc1` depuis PyPI, dans un dossier vierge,
marche ; la CI est verte. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`,
`npm run lint`, `npm run test:e2e` ; `gh run list`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
