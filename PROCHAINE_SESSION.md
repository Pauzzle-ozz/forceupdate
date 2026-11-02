# Session 30 — Étape E30 : Robustesse et performance

Contexte : E01 à E29 sont faites. À la session 29, E29 de départ a été découpée (accord de
l'utilisateur) : E29 configuration et Réglages, E30 robustesse et performance, E31 mise à jour (le
npm du projet, Python, NuGet, Go), E32 registres et dépôts privés, E33 compléments d'analyse ; la
documentation devient E34, la recette E35. E29 a fait la configuration d'un projet
(`forceupdate.toml`, `[tool.forceupdate]` : paquets et versions ignorés, dossiers exclus, dossiers de
tests, sélection par défaut par écosystème), les réglages de la personne (`preferences.py`, le
`forceupdate.toml` de son dossier de configuration : mêmes clés, dépôts exclus, délais des outils et
du clone, chaîne d'outils Rust), l'écran 9 et le vidage du cache. 4667 tests Python verts (plus 21
réseau), 162 Vitest, 67 Playwright ; la suite Python prend 4 min 24 au calme. **E29 n'est pas
commitée : à proposer d'abord.**

Lis CLAUDE.md, puis l'étape E30 de PLAN.md (toutes ses cases), les notes de E29 (le découpage, les
décisions déjà prises avec l'utilisateur, ce qui a été vérifié en vrai), et `docs/BRIEF.md`
(décisions n°5, 13 ; « Pièges connus »). Puis le code qui sert de modèle : `sources/local.py`
(`_walk`, `_git_paths`, `_list_dir`), `detect/manifests.py` (`DEFAULT_MAX_FILES`,
`safe_read_text`, `is_ignored_dir`), `net/http.py` (client, reprises, hôte abandonné),
`update/lockfiles.py` (`_spawn`, `_Context.run`, `regenerate`, `_restore`), `update/writers`
(`write`), `web/app.py` (`serve`, arrêt), `web/jobs.py` (`Jobs.close`), `forges/git.py`
(`Workspace`, `_git`), `web/proposals.py` (l'envoi), `forges/accounts.py` (trousseau),
`forges/bitbucket.py` (refresh token, droits). Pas d'écran nouveau ; si l'interface change (un
message, une alerte), charger d'abord le skill `ui-ux-pro-max` et lire `design-system/MASTER.md`.

À faire :
- Robustesse : dossiers énormes (plafonds, nombre maximal de fichiers) ; fichiers illisibles,
  encodages exotiques ; jonctions Windows et sous-modules git non initialisés ; erreurs réseau
  partielles (section « non concluant ») ; réseau d'entreprise (proxy `HTTPS_PROXY`, certificats :
  **`truststore`, décidé avec l'utilisateur**, à ajouter et justifier dans les notes, `SSL_CERT_FILE`
  toujours suivi) ; Ctrl+C pendant l'écriture des manifestes, navigateur fermé pendant une mise à
  jour ; Ctrl+Break sous Windows (code 3, sans « Interface arrêtée. ») ; délai d'un outil dépassé
  sous Windows : tuer tout l'arbre (`npm.CMD` → node ; `taskkill /T`, groupe de processus).
- Performance : mesurer sur Argos (`~/Desktop/the good guy`), viser moins de 30 s cache vide pour
  environ 500 directes, noter la mesure dans le journal ; et la suite de tests (`--durations=25`).
- Depuis E16 : le trousseau sous Linux sans Secret Service (refus avec la raison : le dire dans la
  doc, ou un repli à justifier). Les tokens GitHub restent sans expiration (tranché).
- Depuis E18 : un arrêt du serveur pendant un envoi (le dire, ou attendre la fin du dépôt en
  cours) ; les dossiers `forceupdate-pr-*` laissés par un arrêt brutal, effacés au démarrage ; une
  PR fermée sans fusion rouverte au prochain envoi (souvenir d'un refus, ou le demander) ;
  `url.<base>.insteadOf` de la configuration git de la personne.
- Depuis E20 (Bitbucket) : le refresh token inutilisé 3 mois ; les droits d'écriture par un
  groupe ; le coût du `fetch` de `git.remote_tree`.

Attention :
- **Demander à l'utilisateur** d'abord le commit de E29 (message « E29 : configuration et page
  Réglages », un résumé comme pour E27 et E28).
- E30 est encore grosse : si elle ne tient pas dans la session, la découper avec l'accord de
  l'utilisateur (par exemple les cases des forges dans une étape à part), et le noter dans PLAN.md.
- Vérifier en vrai avant d'écrire, comme à E27, E28 et E29 : l'arbre de processus de `npm.CMD`
  sous Windows (ce que tue `subprocess.run`, ce que tue `taskkill /T`), le comportement de httpx
  avec `HTTPS_PROXY` et `truststore` (un vrai proxy si possible : demander avant d'installer quoi
  que ce soit), une jonction (`mklink /J`) et un sous-module non initialisé, un fichier en UTF-16 ou
  en cp1252.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache,
  le trousseau ni les réglages de l'utilisateur (`user_settings`, septième garde-fou) ; dans un
  test, jamais `monkeypatch.undo()`. Les fins de vie se jugent au jour de l'enregistrement
  d'endoflife.date (`record.RECORDED_ON`).
- Les tests Playwright partagent le serveur et tournent en parallèle : un test qui enregistre des
  réglages ne doit rien changer aux rapports des autres. Une expression régulière ne trouve pas un
  texte passé par `fr()` (espace insécable) : `\s`.
- Pour essayer `forceupdate ui` en vrai : l'écran Réglages écrit le vrai
  `%LOCALAPPDATA%\forceupdate\forceupdate.toml` (l'effacer après un essai s'il n'existait pas), et
  « Vider le cache » vide le vrai cache (annuler le dialogue).
- Les SDK et outils sont hors du `PATH` des outils (`~/sdk/…`, cargo) : la ligne de CLAUDE.md pour
  les tests `network`.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E35 : ne pas y toucher.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture, jamais par un heredoc (il mange
  les barres obliques inverses : un `\s` d'expression régulière y devient `s`) ; l'outil d'écriture
  change un `\uXXXX` en caractère (écrire `chr(0x…)`) ; `python -I` ignore `PYTHONIOENCODING`
  (`-X utf8`) ; un argument qui commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1`. Un script
  Python qui réécrit un fichier : `newline="\n"` (sinon Windows écrit des CRLF).

Fini quand : tests de robustesse verts, mesure de performance notée dans le journal. Vérifier avec :
`uv run pytest`, `uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; à la main, une analyse d'Argos chronométrée
cache vide, et un outil de lockfile qui dépasse son délai sous Windows.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
