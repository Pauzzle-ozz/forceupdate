# Session 17 — Étape E17 : GitHub : dépôts et analyse sans cloner

Contexte : E01 à E16 sont faites. Depuis E16, l'écran « Comptes » connecte un vrai compte
GitHub (OAuth avec retour sur `127.0.0.1`, device flow, token collé, `gh`) et le déconnecte ;
le token est dans le trousseau du système, jamais au navigateur. `forges/base.py` fixe
l'interface `Forge` ; `forges/github.py` a le client REST (`request`, `paginate`, `whoami`,
`rate_limit`), mais `list_repos`, `tree` et `read_file` lèvent encore `NotImplementedError`.
1851 tests Python verts (plus 8 réseau), 98 Vitest, 25 Playwright. E16 n'est pas commitée :
à proposer d'abord.

Lis CLAUDE.md, puis l'étape E17 de PLAN.md (et les « Notes » de E12, E14 et E16), `docs/BRIEF.md`
(décisions n°13 et 15, « Forges » dans les pièges, le tableau des forges),
`docs/JSON_FORMAT.md` (« L'API de l'interface web », « Comptes des forges »), et le code de
`src/forceupdate/forges/`, `src/forceupdate/sources/`, `src/forceupdate/web/jobs.py`.
**Charge d'abord le skill `ui-ux-pro-max`** pour l'écran 7, puis `design-system/MASTER.md`
(« Fait à E14 » à « Fait à E16 »), l'écran 7 de `design-system/ECRANS.md`,
`design-system/pages/depots.md` et la maquette `design-system/mockups/depots.html`.

À faire :
- `list_repos` : `/user/repos?affiliation=owner,collaborator,organization_member` (pagination
  `Link`) ; chaque dépôt marqué archivé, vide, fork, privé, avec ou sans droit de push ; les
  organisations qui restreignent l'accès des OAuth Apps signalées (`GET /user/orgs`, portée
  `read:org`, puis un 403 sur leurs dépôts), pas cachées.
- `sources/forge.py`, pour chaque dépôt : arborescence de la branche par défaut
  (`git/trees?recursive=1`) sans les dossiers ignorés (`detect.manifests.is_ignored_path`) ;
  langages (`detect_languages` sur les chemins et tailles) et projets (`find_projects`) ;
  `read_text` plafonné (`max_read_size`, 50 Mo pour un lockfile), qui sert aussi aux `-r` des
  `requirements.txt`, au `pyproject.toml` racine d'un workspace uv et à `pnpm-workspace.yaml`
  (rendre `None` sans erreur pour un fichier absent) ; télécharger seulement ces fichiers dans
  un dossier temporaire qui reproduit les chemins ; puis le pipeline local, inchangé.
- Cas particuliers : arborescence tronquée (le dire ; le clone superficiel est à E18), fichier
  de plus de 1 Mo (`Accept: application/vnd.github.raw`), dépôt vide (sauté, signalé).
- Concurrence bornée entre dépôts, cache des registres partagé, requêtes d'API consommées et
  restantes affichées.
- Analyser un dépôt public d'un autre compte : champ « `owner/repo` ou URL ».
- API : les dépôts et leurs drapeaux, les organisations restreintes, les requêtes restantes ;
  des analyses groupées (progression par dépôt, annulation) par le même `Worker`
  (`ScanSummary.kind` : `repository`) ; **la synthèse multi-dépôts calculée par le serveur**
  (compteurs par type et gravité, dépôts à jour, à mettre à jour, non concluants, sautés).
  `web/openapi.json` et `docs/JSON_FORMAT.md` refaits, types du front régénérés.
- Écran 7 (Mes dépôts) selon `pages/depots.md` et `depots.html` : liste, filtres, sélection,
  synthèse ; le rapport d'un dépôt réutilise l'écran 4. L'accueil : le nombre de dépôts dans
  la carte « Mes dépôts ».
- Tests : API GitHub simulée (respx), un `FakeGitHub` plus complet dans `tests/e2e_server.py`
  (dépôts, arborescences, fichiers) ; Vitest pour l'écran 7 ; e2e.

Attention :
- **Le token** : `Accounts.token(forge, hôte)` dans un thread (`asyncio.to_thread`), côté serveur
  seulement. Les analyses tournent dans la boucle du `Worker` : y créer la forge
  (`forges.client`) avec **son** `HttpClient`, pas celui de `web/connections.py` (qui vit dans la
  boucle du serveur). Un 401 pendant une analyse : `Accounts.refused` (l'écran 6 le montre).
- **Fichiers d'état écrits depuis plusieurs threads** : sous Windows, `os.replace` échoue
  (WinError 5 et 32) si le fichier est lu ou écrit en même temps (trouvé à E16, d'où le verrou
  d'`Accounts`). Même précaution pour tout nouveau fichier d'état.
- GitHub : 5 000 requêtes par heure ; arborescence tronquée au-delà de 100 000 entrées ;
  « contents » ne rend pas le contenu au-delà de 1 Mo ; les erreurs passent déjà par
  `GitHub.request` (`TokenRefused`, `AccessDenied` avec SSO, `NotFound`, `RateLimited`). Un dépôt
  privé inaccessible rend 404, pas 403.
- Aucun test ne touche le vrai GitHub ni le vrai trousseau (garde-fous `_no_network` et
  `keychain` de `conftest.py`) ; des réponses de vrais dépôts publics peuvent être enregistrées
  dans `tests/fixtures/` (comme `record.py`), les tests réseau marqués `network`.
- Pas de logique métier dans le front : la synthèse et les drapeaux viennent du serveur.
- Front : un bouton dont le nom porte un texte réservé aux lecteurs d'écran prend un
  `aria-label` ; un lien au milieu d'une phrase est souligné ; pas de `display: flex` sur un
  `<li>` numéroté ; `getByText` de Playwright cherche une sous-chaîne (`exact: true`).
- Le scratchpad pour les essais à la main ; jamais `python - <<EOF` : écrire le script dans un
  fichier. Dans bash, pas d'accents graves dans un `node -e "…"` (substitution de commande) :
  passer par l'éditeur ou un fichier.

Fini quand : dans l'interface, tous les dépôts du compte GitHub de l'utilisateur sont listés et
analysés ; le rapport est vérifié à la main sur 2 ou 3 dépôts. Vérifier avec : `uv run pytest`,
`uv run ruff check`, `uv run ruff format --check` ; dans `frontend/` : `npm test`,
`npm run typecheck`, `npm run lint`, `npm run test:e2e` ; à la main, `uv run forceupdate ui`
avec le vrai compte (le reconnecter : il a été déconnecté à la fin de E16), en clair et en
sombre, à 375 et 1440 px.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
