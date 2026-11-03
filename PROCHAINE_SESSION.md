# Session 37 — Étape E36 : Recette finale

Contexte : E01 à E35 sont faites. **La 1.0.0rc1 est publiée sur PyPI** (session 36, étiquette
`v1.0.0rc1` sur `b9aacaf`), vérifiée depuis PyPI sans node. À la session 36, l'utilisateur a fait
ses essais, guidé étape par étape (interface, analyse, mise à jour locale, fichier de code, forges,
réglages, ligne de commande), puis un **test final** : une PR sur quatre de ses dépôts GitHub,
toutes les majeures cochées (`Omnividens-argos/argos-ops` #98, `Omnividens-argos/sechunter` #661,
`Pauzzle-ozz/forceupdate` #1 ouvertes ; `Pauzzle-ozz/TITIrelire` #1 fusionnée). Corrigé dans la
session : la raison d'une version écartée par le runtime (terminal, Markdown, `Finding.blocked`) ;
le résultat des PR qui disait « rien à faire » quand npm gardait des indirectes retenues par leur
parent ; **un `package-lock.json` que `npm ci` refuse n'est plus envoyé tel quel** (toujours relu ;
refusé, refait par une vraie installation sans les scripts). Ajouté à la demande de l'utilisateur :
**télécharger le rapport** (Markdown, JSON, et les dépendances à mettre à jour en CSV pour un
tableur ; `scan --format csv`) et **« Parcourir… »**, la fenêtre de choix du système (Tk,
`web/picker.py`, `POST /api/fs/pick`). Dernier commit de code : `7109460`, **CI verte sur les huit
jobs** (les jobs macOS, d'abord annulés par GitHub faute de machines, ont passé à la relance). Rien de publié
après la 1.0.0rc1 : ces ajouts partiront avec la 1.0.0. 5 125 tests Python, 174 Vitest, 72
Playwright.

Lis CLAUDE.md, puis dans PLAN.md : « Le livrable » (en tête), l'étape E36 (toutes ses cases, dont
« Depuis E35 » et « Depuis la session 36 ») et les notes de E35 (sessions 35 et 36).
**Charge d'abord le skill ui-ux-pro-max** et lis `design-system/MASTER.md` (sa « Checklist avant
livraison »), puis `design-system/ECRANS.md` pour chaque écran touché.

À faire :
- **D'abord** : `git status` (les fichiers de suivi ont pu rester à commiter) et `gh run list`.
  Puis **demander à l'utilisateur** comment se sont passés
  « Parcourir… » (la fenêtre de Windows : devant ou derrière le navigateur ?), les téléchargements
  (le CSV dans Excel), et s'il a renvoyé la PR #1 de forceupdate avec l'outil corrigé (le résultat
  doit dire « npm refusait le lockfile … refait par … », et la CI du front de la PR passer).
- **E36 est grosse** (la recette, la revue, huit écarts « Depuis E35 », les points « Depuis la
  session 36 », la 1.0.0) : proposer d'abord un découpage à l'utilisateur, par exemple E36 = les
  écarts et les fonctions (l'indirecte retenue dite d'avance ; le lockfile qui ne tombe plus pour
  une majeure), E37 = la recette, la revue et la 1.0.0. S'il refuse, tout dans l'ordre du plan.
- Les cases de E36 :
  - les écarts « Depuis E35 » (le jeton dans le chemin d'une adresse de registre et la clé du
    cache, `UV_INDEX_<NOM>_USERNAME`, un registre en http, « Privé : non vérifié » jamais émis,
    `include-tests` du projet, `java` de `.tool-versions`, la commande Yarn 2+ affichée, l'aide de
    `--help` en cp1252 et en anglais) ;
  - « Depuis la session 36 » : **une majeure incompatible qui fait tomber tout son lockfile**
    (redis 8, pillow 13, typescript 7, python-dateutil 4, @types/react-dom 19 : des dizaines de
    mises à jour perdues, dont des failles ; réessayer sans les majeures, puis dire laquelle
    bloque : le plus utile), **l'indirecte retenue dite d'avance** (écran 5 et récapitulatif des
    PR : le lockfile dit la plage de chaque parent), le message du commit qui compte une version
    retenue comme faite, un chemin de l'ordinateur dans une description de PR, « Mes dépôts » sur
    un grand écran, « Se déconnecter… » en vrai, la table `[selection]` vide des réglages, la
    fenêtre de choix du système à essayer sous macOS et Linux ;
  - dérouler « Le livrable » dans l'interface (un vrai projet par écosystème disponible, un fichier
    de code et un fichier déposé, les trois forges : analyse de tous les dépôts, une PR / MR sur
    chaque dépôt de test) ; la revue finale ui-ux-pro-max (accessibilité, clair et sombre, 375 px et
    grand écran) ;
  - cocher « Le livrable » ; passer à la `1.0.0` (voir la dernière case de E36 ; le CHANGELOG a une
    section « Non publié » à renommer), CI verte, puis l'étiquette `v1.0.0` **avec l'accord de
    l'utilisateur** ; vérifier `uv tool install forceupdate` (sans `==`) depuis PyPI, sans node.

Attention :
- **L'utilisateur préfère être guidé** pour les essais : une étape à la fois, la commande exacte,
  puis ce qu'il doit voir ; il répond « fait » ou colle sa sortie (parfois une capture). Calculer
  d'avance ce qu'il verra (lancer soi-même `scan` ou `update --dry-run` sur une copie), et vérifier
  ensuite (git diff d'une copie, `gh` pour les PR). Une consigne fausse de ma part est à dire comme
  telle.
- Ses projets réels sur le bureau : `the good guy` (Argos : Python + un front npm), `outils de scrap
  google` (radar-pros, Node), `argos-ops`. Pour une mise à jour : un clone dans le scratchpad
  (`git clone --no-hardlinks`), jamais son vrai dossier. Ses PR ouvertes (`argos-ops` #98,
  `sechunter` #661, `forceupdate` #1) et son dépôt `mew` : ne rien y pousser ni fermer sans son
  accord ; les renvoyer avec lui, une fois une correction faite, est la meilleure recette.
- **Installer l'outil depuis le dépôt** (`~/.local/bin/forceupdate`) : `npm run build` d'abord si
  le front a changé, **arrêter son `forceupdate ui`** (Windows verrouille l'outil qui tourne : une
  installation qui échoue le laisse à moitié démonté), puis
  `uv tool install . --force --reinstall --refresh-package forceupdate` : sans `--reinstall`, uv
  réutilise la construction en cache de la même version, sans le nouveau code. Pour la recette
  « depuis PyPI » : `uv tool install forceupdate==1.0.0rc1 --force`, puis la 1.0.0, dans un
  PowerShell hors de VS Code (le `.venv` activé y prendrait la version de développement).
- **Ménage fait à la fin de la session 36** (accord de l'utilisateur) : les scratchpads des
  sessions passées, ses « Récents », `~/go` (le cache des modules Go : retéléchargé au besoin),
  `~/.virtualenvs`, les oracles `~/sdk/maven-artifact` et `~/sdk/nuget-versioning-7.9.0` (CLAUDE.md
  dit d'où les reprendre). Gardés jusqu'à la fin de E36 : `~/sdk` (Go, PHP, Composer, Ruby, .NET)
  et Rust, pour essayer un vrai projet par écosystème ; après E36, lui proposer de les retirer.
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
  titre trouvé puis remplacé par un changement d'adresse), ne jamais relancer jusqu'au vert. Un job
  de CI annulé par GitHub (pas de machine) se relance, lui.
- `tests/test_web_server.py` liste toutes les routes de l'API : une route ajoutée s'y ajoute.
- La doc décrit l'outil tel qu'il est : un écart corrigé change aussi `docs/USAGE.md`,
  `docs/FORGES.md`, `docs/JSON_FORMAT.md` ou le README.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc ni par
  `python -c` avec des `\n` dans une chaîne ; `python -I -X utf8`.

Fini quand : toutes les cases de « Le livrable » sont cochées, la 1.0.0 est publiée et
`uv tool install forceupdate` l'installe depuis PyPI. Vérifier avec : `uv run pytest`,
`uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; `gh run list`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
