# Session 31 — Étape E31 : Forges : robustesse

Contexte : E01 à E30 sont faites. À la session 30, E30 de départ a été découpée (accord de
l'utilisateur) : E30 robustesse et performance (faite), E31 forges : robustesse (les cases venues
de E16, E18, E20, et deux de E30) ; E31 à E35 de départ deviennent E32 à E36 (les mentions « E31 »
à « E35 » d'avant la session 30 désignent E32 à E36). E30 a fait `processes.py` (tout outil, git et
`gh` lancés sans shell, leur arbre tué au délai, à Ctrl+C ou à l'arrêt du serveur : `taskkill /T`,
`killpg`), les encodages (UTF-16, BOM), les jonctions, les sous-modules non initialisés,
`Report.notices` (« Analyse partielle » dans l'interface), truststore et `SSL_CERT_FILE`,
Ctrl+Break, les interruptions (ce qui n'était pas fini est remis). Argos, cache vide : 3,2 s
(7,4 s avec `--transitive`, 570 dépendances). 4 761 tests Python verts (plus 21 réseau), 163
Vitest, 67 Playwright ; la suite Python prend 4 min 26 au calme. **E30 n'est pas commitée : à proposer
d'abord.**

Lis CLAUDE.md, puis l'étape E31 de PLAN.md (toutes ses cases), les notes de E30 (le découpage,
`processes`, `Jobs.stopping`, ce qui a été vérifié en vrai), de E18, E19 et E20 (les PR, la branche
remplacée, Bitbucket : refresh token, droits), et `docs/BRIEF.md` (décisions n°13, 14, 22 ; « Pièges
connus », Forges). Puis le code qui sert de modèle : `update/forge.py` (`deliver`, `Step`),
`web/proposals.py` (l'envoi, ses étapes, `Workspace`), `forges/git.py` (`Workspace`, `_git`,
`remote_tree`, `_CONFIG`, `_environment`), `forges/accounts.py` (trousseau, morceaux,
renouvellement), `forges/bitbucket.py` (refresh token, `permissions`), `forges/github.py`
(`tree`, entrées `commit`), `forges/gitlab.py`, `sources/forge.py`, `web/jobs.py` (`close`,
`stopping`), `web/app.py` (démarrage). Si l'interface change (un message de carte de compte, le
récapitulatif des PR), charger d'abord le skill `ui-ux-pro-max` et lire `design-system/MASTER.md`,
l'écran dans `design-system/ECRANS.md` (6, 7, 8) et `design-system/pages/`.

À faire :
- Depuis E16 : le trousseau sous Linux sans Secret Service (serveur, WSL) : la connexion est refusée
  avec la raison ; le dire dans la doc (comment en installer un), ou un repli (fichier chiffré : à
  justifier). Les tokens GitHub restent sans expiration (tranché, rien à faire que la doc).
- Depuis E18 : un arrêt du serveur pendant un envoi (le dire, ou attendre la fin du dépôt en
  cours) ; les dossiers `forceupdate-pr-*` laissés par un arrêt brutal, effacés au démarrage ; une
  PR fermée sans fusion rouverte au prochain envoi (souvenir d'un refus par version, ou le
  demander) ; `url.<base>.insteadOf` de la configuration git de la personne.
- Depuis E20 (Bitbucket) : le refresh token inutilisé 3 mois ; les droits d'écriture par un
  groupe ; le coût du `fetch` de `git.remote_tree` (le mesurer).
- Depuis E30 : un sous-module d'un dépôt (entrée `commit` de l'arborescence) sauté sans rien dire :
  le dire comme en local (`Source.notices`) ; à l'arrêt du serveur, les commandes git d'un envoi
  ne reçoivent pas `cancel` (décider avec la case de E18).

Attention :
- **Demander à l'utilisateur** d'abord le commit de E30 (message « E30 : robustesse et
  performance », un résumé comme pour E28 et E29).
- Plusieurs cases demandent une décision de l'utilisateur (repli du trousseau sous Linux ; PR
  refusée : s'en souvenir ou demander ; arrêt pendant un envoi) : les lui poser avec les options
  et une recommandation, avant d'écrire.
- Vérifier en vrai avant d'écrire, comme à E27–E30 : `git config --get-regexp url\.` et un
  `insteadOf` posé dans un dépôt de test local (jamais dans la configuration globale de la
  personne sans son accord : `GIT_CONFIG_GLOBAL` vers un fichier du scratchpad) ; ce que rend
  l'arborescence de GitHub pour un sous-module (`type: commit`), sur un dépôt public, en lecture ;
  le refus de Bitbucket d'un refresh token expiré n'est pas reproductible (3 mois) : le dire.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E36 : y lire, ne rien y
  pousser sans l'accord de l'utilisateur, ne pas toucher à leur PR #1 et MR !1.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache,
  le trousseau ni les réglages de l'utilisateur (`user_settings`) ; git seulement vers des dépôts
  « bare » locaux (`fake_forge.make_remote`) ; dans un test, jamais `monkeypatch.undo()` (pour
  la vraie fonction d'un module remplacé par un garde-fou, la prendre à l'import, comme
  `REAL_SPAWN` de `test_lockfiles.py`). respx relève l'exception d'un `side_effect` depuis la sienne
  (la cause d'origine est perdue, la chaîne reboucle).
- Un test qui lance une vraie commande `ui` bloque la suite ; le test de Ctrl+Break
  (`test_web_server.py`) fait sortir pytest en code 3 si la correction disparaît.
- Les tests Playwright partagent le serveur et tournent en parallèle ; une expression régulière ne
  trouve pas un texte passé par `fr()` (espace insécable) : `\s`.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc (il mange
  les barres obliques inverses) ; l'outil d'écriture change un `\uXXXX` en caractère (écrire
  `\N{…}` ou `chr(0x…)`) ; `python -I` ignore `PYTHONIOENCODING` (`-X utf8`) ; un argument qui
  commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1`. Un script Python qui réécrit un fichier :
  `newline="\n"`.

Fini quand : chaque case a ses tests, ou une décision notée (la doc, E35) ; vérifié avec les dépôts
de test des forges, sans toucher à leurs PR et MR. Vérifier avec : `uv run pytest`,
`uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
