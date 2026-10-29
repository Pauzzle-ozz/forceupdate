# Session 19 — Étape E19 : GitLab

Contexte : E01 à E18 sont faites. GitHub marche de bout en bout : connexion (E16), dépôts analysés
sans les cloner (E17), et depuis E18 une PR par dépôt (récapitulatif sans clone, envoi : clone
superficiel, mise à jour sur le clone, commit au nom du compte, push avec bail de
`forceupdate/dependencies`, PR ouverte ou mise à jour ; écran 8). Vérifié avec le vrai compte sur
`Pauzzle-ozz/forceupdate-demo` : PR #1 ouverte, puis mise à jour en relançant. 1998 tests Python
verts (plus 9 réseau), 127 Vitest, 37 Playwright. E18 n'est pas commitée : à proposer d'abord.

Lis CLAUDE.md, puis l'étape E19 de PLAN.md (et les « Notes » de E16, E17 et E18), `docs/BRIEF.md`
(décisions n°13, 14, 16 et 22, « Forges » dans les pièges), `docs/JSON_FORMAT.md` (« Comptes des
forges », « Dépôts des forges », « PR des dépôts »), le code de `src/forceupdate/forges/`
(`base.py`, `github.py`, `git.py`, `accounts.py`, `__init__.py`), `update/forge.py`,
`web/connections.py`, `web/routes/accounts.py`, `web/routes/oauth.py`, `web/repositories.py`,
`web/proposals.py`, et `tests/fake_forge.py`. Pour le clone avec `oauth2:<token>` :
`~/Desktop/the good guy/sechunter/core/repo/git_client.py` (déjà adapté dans `forges/git.py`).
**Charge d'abord le skill `ui-ux-pro-max`** (écrans 6, 7 et 8 pour GitLab), puis
`design-system/MASTER.md` (« Fait à E14 » à « Fait à E18 »), les écrans 6, 7 et 8 de
`design-system/ECRANS.md` et `design-system/pages/depots.md`.

À faire :
- Prérequis, avec l'utilisateur (le guider pas à pas, le formulaire de GitLab a pu changer) :
  enregistrer forceupdate comme application OAuth sur gitlab.com, **non confidentielle** (PKCE,
  pas de secret), portée `api`, retour `http://127.0.0.1/oauth/gitlab/callback` (vérifier que
  GitLab accepte n'importe quel port sur 127.0.0.1, sinon trouver comment faire).
- Connexion : gitlab.com par OAuth avec PKCE ; une instance auto-hébergée par son URL et un token
  personnel ; token collé. `forges.FORGES` (GitLab `available`), `forges.client`, l'adresse de
  retour dans `web.routes.oauth.RETURN_PATHS` et son test de refus ; les façons de se connecter
  (`methods`) et la révocation, aujourd'hui propres à GitHub (`web/routes/accounts.py`,
  `web/connections.py` : `github.revoke`, `github.start_oauth`…), à faire passer par la forge ;
  plusieurs comptes GitLab (gitlab.com et une instance) : le trousseau a déjà la clé
  `forge:hôte`, l'API désigne un compte par sa seule forge (à revoir, ou à limiter en le disant).
- `forges/gitlab.py` : `whoami` (et ses droits, `Identity.email` : l'adresse `noreply` de GitLab),
  `list_repos` (`membership=true`, groupes et sous-groupes), `repository`, `tree` (paginée),
  `read_file` (brut), `clone` (`forges.git`, nom `oauth2`), `branch` (`repository/compare`),
  `push_branch` (bail `expected`, jamais la branche par défaut), `find_open_request` et
  `open_or_update_request` (MR depuis `forceupdate/dependencies` vers la branche par défaut,
  mise à jour plutôt que doublée). Une adresse git par forge (`GIT_URL` est propre à
  `forges.github`).
- `forges.parse_repository` : le chemin complet d'un projet GitLab (sous-groupes), pas deux
  segments.
- Écrans : la carte GitLab de l'écran 6 (aujourd'hui « Bientôt ») ; l'écran 7 avec deux forges
  (filtre par forge, colonne « PR / MR », compteur « PR et MR ouvertes », « Préparer N PR et
  M MR » : un récapitulatif par forge, ou un récapitulatif à plusieurs forges —
  `ProposalRequest.forge`, `propose` de `RepositoriesPage.tsx`) ; l'écran 8 dit « MR » et `!12`
  (déjà prévu par `lib/proposals.ts`).
- Tests : GitLab simulé comme `tests/fake_forge.py` (dépôts « bare » où git pousse, MR), API,
  Vitest, e2e (le serveur de test sert déjà GitHub, `tests/e2e_server.py`).

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E18 ; puis s'il confirme la décision n°22 du
  brief (la branche remplacée à chaque envoi, jamais par-dessus le commit d'un autre), prise
  pendant E18 ; ce qu'il veut faire du dépôt de test `Pauzzle-ozz/forceupdate-demo` et de sa PR
  #1 (les garder pour la recette E31, ou les supprimer) ; quel projet gitlab.com utiliser pour
  l'essai (en créer un exprès, comme à E18, copie de `tests/projects/vulnerable`), jamais un
  projet réel sans son accord.
- **Le token** : jamais dans `argv`, une URL, un message ou un journal ; `forges.git` le fait déjà
  (credential helper éphémère, `credential.helper=` vidé avant). Sous GitLab, le nom est
  `oauth2`.
- **Qui parle à la forge d'où** (E17, E18) : la liste et le récapitulatif dans la boucle du
  serveur (client des comptes) ; analyses et envois dans la boucle du `Worker`, avec une forge
  créée sur **son** client (`Repositories.worker_forge`) ; git et outils de lockfile dans le
  thread des mises à jour (`Jobs.in_updates`) ; l'état modifié seulement dans la boucle du
  serveur (`Jobs.post`).
- Tests : jamais de vrai GitLab ni de vrai trousseau (garde-fous de `conftest.py`, dont le
  sixième : git ne parle qu'à des dépôts locaux) ; jamais `monkeypatch.undo()` (il défait ces
  garde-fous : `monkeypatch.context()`) ; pour un registre muet, un 503, pas une coupure
  (`ConnectError` fait abandonner l'hôte 60 s pour toutes les analyses). Les tests qui lancent
  git : sur des dossiers temporaires, avec `-c user.name=… -c user.email=…`.
- Front : un bouton dont le nom porte un texte réservé aux lecteurs d'écran prend un
  `aria-label` ; `\s` dans les motifs (espaces insécables) ; `getByText` et les noms de Playwright
  cherchent une sous-chaîne (`exact: true`) ; une grille sans `minmax(0, 1fr)` déborde à 375 px ;
  une région `aria-live` double le texte qu'elle annonce (`getAllByText`). Les tests e2e des
  forges sont dans `e2e/forges.spec.ts`, en série.
- Scripts : écrire les scripts dans le scratchpad avec l'outil d'écriture (un heredoc abîme les
  accents et les `\\`) ; jamais `node -e "…"` avec des accents graves.

Fini quand : sur un projet de test gitlab.com, depuis l'interface : connexion, analyse, MR
ouverte, puis mise à jour de la même MR. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`,
`npm run lint`, `npm run test:e2e` ; à la main, `uv run forceupdate ui` avec le vrai compte
GitLab (et GitHub toujours connecté), en clair et en sombre, à 375 et 1440 px.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
