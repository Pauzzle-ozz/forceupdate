# Session 18 — Étape E18 : GitHub : une PR par dépôt

Contexte : E01 à E17 sont faites. Depuis E17, l'écran 7 (« Mes dépôts ») liste tous les dépôts du
compte GitHub connecté et les analyse sans les cloner (arborescence et fichiers de dépendances par
l'API, puis le pipeline local) : analyses groupées, synthèse calculée par le serveur, dépôt public
par son nom. Vérifié avec le vrai compte (7 dépôts en 15 s). Il ne manque que les PR : un plan sur
un dépôt est refusé (409), le rapport d'un dépôt n'a pas « Mettre à jour ». 1941 tests Python
verts (plus 9 réseau), 113 Vitest, 32 Playwright. E17 n'est pas commitée : à proposer d'abord.

Lis CLAUDE.md, puis l'étape E18 de PLAN.md (et les « Notes » de E12, E15, E16 et E17),
`docs/BRIEF.md` (décisions n°11, 14 et 18, « Forges » dans les pièges, le tableau des forges),
`docs/JSON_FORMAT.md` (« L'API de l'interface web », « Plan de mise à jour », « Dépôts des
forges »), le code de `src/forceupdate/forges/`, `src/forceupdate/sources/forge.py`,
`src/forceupdate/update/` (`local.py`, `writers/`, `lockfiles.py`, `git.py`),
`src/forceupdate/report/markdown.py`, `src/forceupdate/web/jobs.py` et `web/repositories.py`, et
dans Argos (`~/Desktop/the good guy`) `sechunter/core/repo/git_client.py`, `workspace.py`,
`github_app.py`.
**Charge d'abord le skill `ui-ux-pro-max`** pour l'écran 8, puis `design-system/MASTER.md`
(« Fait à E14 » à « Fait à E17 »), les écrans 7 et 8 de `design-system/ECRANS.md` et
`design-system/pages/depots.md`.

À faire :
- `forges/git.py` : adapter `git_client.py` d'Argos (token donné à git par un credential helper
  éphémère, jamais dans `argv` ni dans un message ; sans `target_validator`) ; clone superficiel
  de la branche par défaut ; le même mécanisme pour le push. Dossier de travail temporaire nettoyé
  à la sortie (adapter `workspace.py`). `GitHub.clone`, `push_branch`, `find_open_request`,
  `open_or_update_request` (aujourd'hui `NotImplementedError`).
- Pour chaque dépôt : clone ; sélection (E09), réécriture (E10), lockfiles (E11 : `lockfiles.plan`
  puis `regenerate`, sur le clone ; outil absent ou en échec : la PR le dit, avec la commande ou
  l'erreur, et les fichiers remis comme avant ne sont pas commités) ; branche
  `forceupdate/dependencies`, commit (auteur : l'utilisateur du token), push ; PR avec en
  description le rapport Markdown du dépôt.
- Idempotence : PR déjà ouverte → pousser la branche à jour et mettre à jour sa description, sans
  en ouvrir une autre ; rien à faire → rien poussé.
- Garde-fous : jamais de push sur la branche par défaut ; archivés et sans droit de push sautés et
  signalés ; un récapitulatif avant d'envoyer (N dépôts, M PR, le détail par dépôt), rien de poussé
  sans validation.
- Écran 8 (`/pr`) selon ECRANS.md : récapitulatif par dépôt (PR existante mise à jour ou nouvelle,
  sélection, lockfiles et commandes, sautés et pourquoi), envoi suivi dépôt par dépôt, résultat
  avec les liens (`#41`).
- Écran 7 : la colonne « PR / MR » (numéro, lien), le compteur « PR ouvertes » de la synthèse
  (calculé par le serveur, `RepositorySynthesis`, `find_open_request` par dépôt), « Préparer N PR »
  en action principale de la barre de sélection (« Analyser ces N dépôts » devient secondaire) ;
  sur le rapport d'un dépôt, l'action qui remplace « Mettre à jour » (et le lien du panneau de
  détail, `DependencyDetail` reçoit `scanId={null}` pour un dépôt).
- Une arborescence tronquée (`ForgeSource.truncated`) : analyser sur le clone superficiel.
- API : le récapitulatif (plans par dépôt), l'envoi en tâche de fond, sa progression, le
  résultat ; `web/openapi.json` et `docs/JSON_FORMAT.md` refaits, types du front régénérés.
- Tests : un dépôt git local « bare » sert de remote ; l'API GitHub simulée
  (`tests/fake_forge.py` à compléter : branches, PR ouvertes, création et mise à jour) ; Vitest
  pour l'écran 8 ; e2e (le serveur de test sert déjà des dépôts simulés, `tests/e2e_server.py`).

Attention :
- **Le token** : jamais dans `argv`, une URL, un message ou un journal (git l'écrirait dans
  `.git/config` avec une URL `https://x-access-token:…@`). Credential helper éphémère comme dans
  Argos ; masquer le token dans toute sortie de git rapportée.
- **Qui parle à GitHub d'où** (E17) : les tâches de fond tournent dans la boucle du `Worker`, avec
  une forge créée sur **son** client (`Repositories._worker_forge`, `RepositoryTarget`) ; le token
  se lit par `Repositories._token` (dans un thread). Les outils de lockfile (plusieurs minutes)
  tournent hors de toute boucle, une mise à jour à la fois (thread des mises à jour de `Jobs`). Un
  401 : `Accounts.refused`. Un 403 sur push ou PR avec un token fine-grained (droits « non
  vérifiés ») doit le dire.
- Jamais de vrai GitHub ni de vrai trousseau dans les tests (garde-fous de `conftest.py`) ; jamais
  de vrai `git push` vers GitHub : un dépôt « bare » local. Les tests qui lancent git : sur des
  dossiers temporaires, avec `-c user.name=… -c user.email=… -c commit.gpgsign=false`.
- **Fichiers d'état écrits depuis plusieurs threads** : sous Windows, `os.replace` échoue si le
  fichier est lu ou écrit en même temps (trouvé à E16). Même précaution pour tout nouveau fichier.
- Les dépôts du compte de l'utilisateur sont réels : pour l'essai à la main, **demander quel dépôt
  de test utiliser** (en créer un exprès, par exemple une copie de `tests/projects/vulnerable`),
  jamais un dépôt réel sans son accord. Relancer doit mettre à jour la même PR.
- Front : un bouton dont le nom porte un texte réservé aux lecteurs d'écran prend un `aria-label` ;
  Testing Library ramène les espaces insécables à des espaces dans les textes, pas dans les noms
  accessibles (`\s`) ; `getByText` et les noms de Playwright cherchent une sous-chaîne
  (`exact: true`) ; une grille sans `minmax(0, 1fr)` déborde à 375 px. Les tests e2e des forges
  sont dans `e2e/forges.spec.ts`, en série (compte du serveur partagé).
- Le scratchpad pour les essais à la main ; jamais `python - <<EOF` avec des accents graves ni de
  `node -e "…"` avec des accents graves : écrire le script dans un fichier.

Fini quand : depuis l'interface, une PR s'ouvre sur un dépôt de test de l'utilisateur ; relancer
met à jour la même PR. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` ; à la main, `uv run forceupdate ui` avec le vrai compte (connecté, token dans
le trousseau), en clair et en sombre, à 375 et 1440 px.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
