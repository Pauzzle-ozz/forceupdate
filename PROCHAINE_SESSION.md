# Session 38 — Étape E37 : Indirectes retenues et majeures refusées, plus loin (1.1.0)

Contexte : **la 1.0.0 est publiée sur PyPI** (session 37, étiquette `v1.0.0` sur `9c37b39`) et
vérifiée depuis PyPI, sans node, sous Windows et sous Linux ; toutes les cases de « Le livrable »
sont cochées. La session 37 a ajouté la reprise d'un lockfile qu'une majeure fait échouer
(`lockfiles._retry` : relancé sans les majeures, puis avec chacune ; `Regenerated.dropped`) et
l'indirecte retenue dite d'avance, pour `package-lock.json` seulement (`LockedPackage.requires`,
`Dependency.required_by`, `UpdateOption.held_by`). E37 reprend les quatre points que E36 a laissés,
pour une 1.1.0. 5 151 tests Python, 179 Vitest, 72 Playwright.

Lis CLAUDE.md, puis l'étape E37 de PLAN.md, et les notes de E36 (session 37), surtout « L'indirecte
retenue dite d'avance » et « Une majeure que l'outil refuse ».
**Charge d'abord le skill ui-ux-pro-max** (les écrans 5 et 8 changent), puis lis
`design-system/MASTER.md` et l'écran 5 et l'écran 8 de `design-system/ECRANS.md`.

À faire :
- **D'abord** : `git status` (doit être propre), `gh run list` (la CI du dernier commit) ; demander
  à l'utilisateur s'il a retiré (« yank ») la 0.1.0 sur PyPI (proposé à la fin de la session 37 :
  un index pas encore à jour l'a donnée à la place de la 1.0.0), et s'il a fusionné ou fermé les
  PR #2 / MR !2 des `forceupdate-demo` (laissées ouvertes, à sa demande).
- Proposer un découpage si l'étape paraît grosse (les quatre points sont indépendants).
- **La version du parent qui accepte la correction** d'une indirecte retenue (`held_by`) : lire au
  registre les versions du paquet qui la tire et la plage de chacune ; la proposer, ou dire
  qu'aucune ne l'accepte (écran 5, récapitulatif des PR, terminal).
- **Les indirectes retenues pour pnpm, Yarn (1 et 2+), uv et Poetry** : remplir
  `LockedPackage.requires` dans leurs parseurs (`parsers/npm.py`, `parsers/python.py`), avec tests
  et mini-projets.
- **Prévoir le refus d'une majeure d'après le registre** (`peerDependencies` de npm,
  `requires_dist` de PyPI), avant de lancer l'outil ; la reprise `_retry` reste.
- **« Parcourir… » sous macOS** (avec une personne qui a un Mac) et sous Linux avec un affichage.
- Doc (`USAGE.md` : les limites retirées), CHANGELOG (section « Non publié »), puis la **1.1.0**.

Attention :
- **L'utilisateur préfère être guidé** pour les essais : une étape à la fois, la commande exacte,
  puis ce qu'il doit voir ; calculer d'avance ce qu'il verra, vérifier ensuite (git diff d'un clone,
  `gh`). Ses projets réels : `the good guy` (sechunter), `argos-ops`, `outils de scrap google` ;
  toujours un clone dans le scratchpad (`git clone --no-hardlinks`), jamais son vrai dossier.
- **Installer l'outil depuis le dépôt** : `npm run build` si le front a changé, **arrêter son
  `forceupdate ui`** d'abord, puis `uv tool install . --force --reinstall --refresh-package
  forceupdate`.
- **Publier est irréversible** : la 1.1.0 seulement avec l'accord explicite de l'utilisateur, après
  une CI verte ; vérifier ensuite depuis PyPI avec `--refresh` (le CDN de PyPI tarde : voir
  CLAUDE.md, « Vérifier une version publiée »).
- Le faux Bitbucket des tests ignore maintenant `state` avec `q`, comme le vrai : un faux qui fait
  plus que la forge cache des défauts (session 37).
- Les rapports d'exemple du front (`frontend/src/test/fixtures/`) se refont par
  `tests/e2e_server.py --report` (en LF) ; celui de `imports.py` depuis une copie qui garde
  `helpers.py` à côté. Un champ ajouté au JSON : `test_web_server.py` liste les champs requis de
  `Dependency`.
- L'outil d'édition écrit en CRLF sous Windows : repasser en LF (`sed -i 's/\r$//'`) ; un heredoc
  de l'outil Bash réduit `\\` à `\` (et `\n` dans une chaîne Python devient un vrai saut de ligne) :
  écrire les scripts dans le scratchpad avec l'outil d'écriture.
- `~/sdk` (Go, PHP, Composer, Ruby, .NET) et Rust sont gardés (choix de l'utilisateur).

Fini quand : les quatre points de E37 sont faits (ou décidés avec l'utilisateur) et la 1.1.0
publiée. Vérifier avec : `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans
`frontend/` : `npm test`, `npm run typecheck`, `npm run lint`, `npm run test:e2e` ; `gh run list`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
