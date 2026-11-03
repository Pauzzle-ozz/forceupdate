# Session 37 — Étape E36 : Recette finale

Contexte : E01 à E35 sont faites. **La 1.0.0rc1 est publiée sur PyPI** (session 36, étiquette
`v1.0.0rc1` sur `b9aacaf`), vérifiée depuis PyPI sans node. À la session 36, l'utilisateur a fait
ses essais, guidé étape par étape (interface, analyse, mise à jour locale, fichier de code, forges,
réglages, ligne de commande) : deux défauts corrigés (la raison d'une version écartée par le runtime
dans le terminal et le Markdown ; l'écran de résultat des PR qui disait « rien à faire » quand npm
gardait des indirectes retenues par leur parent), et des points portés à E36 (« Depuis la session
36 »), dont deux fonctions décidées avec lui. CI verte sur les huit jobs. 5 107 tests Python, 170
Vitest, 72 Playwright. **Test final de l'utilisateur**, avec la 1.0.0rc1 de PyPI : une PR sur
quatre de ses dépôts GitHub, toutes les majeures cochées — `Omnividens-argos/argos-ops` #98,
`Omnividens-argos/sechunter` #661, `Pauzzle-ozz/forceupdate` #1, `Pauzzle-ozz/TITIrelire` #1 :
ouvertes, propres (un commit, `Generated-by`, branche `forceupdate/dependencies`), CI vertes ;
TITIrelire (sans CI) vérifiée sur un clone (tsc de TypeScript 7, 524 tests sous vitest 4, build).
TITIrelire #1 fusionnée par lui. Défauts relevés : **un lockfile npm refusé par `npm ci` envoyé
tel quel** (forceupdate #1, sa CI du front en échec) — **corrigé à la fin de la session 36**
(toujours relu ; refusé, refait par une vraie installation) ; portés à E36 : une majeure
incompatible fait tomber tout son lockfile (redis 8, pillow 13, typescript 7, puis
python-dateutil 4, @types/react-dom 19 : des dizaines de mises à jour perdues, dont des failles),
le message du commit qui compte une version retenue comme faite, un chemin de l'ordinateur dans
une description de PR. **Faits aussi à la fin de la session 36, à sa demande** : télécharger le
rapport (Markdown, JSON, et les dépendances à mettre à jour en CSV ; `scan --format csv`) et
« Parcourir… » (la fenêtre de choix du système, Tk, `web/picker.py`). Poussés, CI à vérifier
(`gh run list`) ; l'outil de l'utilisateur réinstallé depuis le dépôt. Rien de publié après la
1.0.0rc1 : ces ajouts partiront avec la 1.0.0.

Lis CLAUDE.md, puis dans PLAN.md : « Le livrable » (en tête), l'étape E36 (toutes ses cases, dont
« Depuis E35 » et « Depuis la session 36 ») et les notes de E35 (sessions 35 et 36).
**Charge d'abord le skill ui-ux-pro-max** et lis `design-system/MASTER.md` (sa « Checklist avant
livraison »), puis `design-system/ECRANS.md` pour chaque écran touché.

À faire :
- **Demander d'abord à l'utilisateur** comment s'est passé « Parcourir… » chez lui (la fenêtre de
  Windows : au premier plan ? derrière le navigateur ?) et les téléchargements (le CSV dans Excel),
  et s'il a renvoyé la PR #1 de forceupdate avec l'outil corrigé (son lockfile doit passer `npm ci`
  et la CI du front).
- **E36 est grosse** (la recette, la revue, huit écarts « Depuis E35 », les points « Depuis la
  session 36 », la 1.0.0) : proposer d'abord un découpage à l'utilisateur, par exemple E36 = les
  écarts et les fonctions (l'indirecte retenue dite d'avance ; le lockfile qui ne tombe plus pour
  une majeure), E37 = la recette, la revue et la 1.0.0. S'il refuse, tout dans l'ordre du plan.
- Les quatre PR du test final sont ouvertes sur ses dépôts : ne rien y pousser ni les fermer sans
  son accord ; une fois le lockfile corrigé, les renvoyer (avec lui) met à jour les mêmes PR, et
  c'est la meilleure recette de la correction.
- Les cases de E36 :
  - les écarts « Depuis E35 » (le jeton dans le chemin d'une adresse de registre et la clé du
    cache, `UV_INDEX_<NOM>_USERNAME`, un registre en http, « Privé : non vérifié » jamais émis,
    `include-tests` du projet, `java` de `.tool-versions`, la commande Yarn 2+ affichée, l'aide de
    `--help` en cp1252 et en anglais) ;
  - « Depuis la session 36 » : « Mes dépôts » sur un grand écran, « Se déconnecter… » en vrai, la
    table `[selection]` vide des réglages, la fenêtre de choix du système (faite : à essayer sous
    macOS et Linux), **l'indirecte retenue dite d'avance**
    (écran 5 et récapitulatif des PR : le lockfile dit la plage de chaque parent), **une majeure
    incompatible qui fait tomber tout son lockfile** (réessayer sans les majeures, puis dire
    laquelle bloque : le plus utile), le message du commit qui compte une version retenue, un
    chemin de l'ordinateur dans une description de PR ;
  - dérouler « Le livrable » dans l'interface (un vrai projet par écosystème disponible, un fichier
    de code et un fichier déposé, les trois forges : analyse de tous les dépôts, une PR / MR sur
    chaque dépôt de test) ; la revue finale ui-ux-pro-max (accessibilité, clair et sombre, 375 px et
    grand écran) ;
  - cocher « Le livrable » ; passer à la `1.0.0` (voir la dernière case de E36), CI verte, puis
    l'étiquette `v1.0.0` **avec l'accord de l'utilisateur** ; vérifier `uv tool install
    forceupdate` (sans `==`) depuis PyPI, sans node.

Attention :
- **L'utilisateur préfère être guidé** pour les essais : une étape à la fois, la commande exacte,
  puis ce qu'il doit voir ; il répond « fait » ou colle sa sortie. Calculer d'avance ce qu'il
  verra (lancer soi-même `scan` ou `update --dry-run` sur une copie), et vérifier ensuite (git diff
  d'une copie, `gh` pour les PR). Une consigne fausse de ma part est à dire comme telle.
- Ses projets réels sur le bureau : `the good guy` (Argos : Python + un front npm), `outils de scrap
  google` (radar-pros, Node), `argos-ops`. Pour une mise à jour : un clone dans le scratchpad
  (`git clone --no-hardlinks`), jamais son vrai dossier. Son dépôt GitHub `mew` (PR #2 de
  forceupdate fusionnée par lui) : ne rien y pousser sans son accord.
- L'outil installé chez lui (`~/.local/bin/forceupdate`) vient du dépôt (`uv tool install .`) :
  pour la recette « depuis PyPI », lui faire installer la version publiée
  (`uv tool install forceupdate==1.0.0rc1 --force`, puis la 1.0.0), dans un PowerShell hors de VS
  Code (le `.venv` activé y prendrait la version de développement). Après un changement du front :
  `npm run build` avant `uv tool install . --force`.
- **Publier est irréversible** : la 1.0.0 seulement avec l'accord explicite de l'utilisateur, après
  une CI verte ; si la publication échoue après l'étiquette, ne pas réutiliser `v1.0.0` (comprendre,
  puis `1.0.1` avec son accord).
- Les PR #1 (GitHub, Bitbucket) et la MR !1 (gitlab.com) des dépôts de test `forceupdate-demo`
  existent ; les supprimer en fin de recette **avec l'accord de l'utilisateur** (jamais un autre
  dépôt).
- L'outil d'édition écrit en CRLF sous Windows tout fichier qu'il touche : le repasser en LF
  (`sed -i 's/\r$//'`) ; les rapports d'exemple du front (`frontend/src/test/fixtures/`) se refont
  par `tests/e2e_server.py --report` (voir sa docstring), en LF (`tr -d '\r'`), `imports.py` depuis
  une copie hors du dépôt.
- Un test qui échoue seulement quand d'autres tournent : chercher la course (session 36 : un
  titre trouvé puis remplacé par un changement d'adresse), ne jamais relancer jusqu'au vert.
- La doc décrit l'outil tel qu'il est : un écart corrigé change aussi `docs/USAGE.md`,
  `docs/FORGES.md`, `docs/JSON_FORMAT.md` ou le README.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc ni par
  `python -c` avec des `\n` dans une chaîne ; `python -I -X utf8`.

Fini quand : toutes les cases de « Le livrable » sont cochées, la 1.0.0 est publiée et
`uv tool install forceupdate` l'installe depuis PyPI. Vérifier avec : `uv run pytest`,
`uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; `gh run list`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
