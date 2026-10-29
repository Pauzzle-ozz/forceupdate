# Session 20 — Étape E20 : Bitbucket Cloud

Contexte : E01 à E19 sont faites. GitHub et GitLab marchent de bout en bout : connexion (OAuth,
token collé ; GitLab : PKCE sans secret, tokens de 2 h renouvelés, instances auto-hébergées par
adresse + token), dépôts analysés sans les cloner, une PR (MR) par dépôt, idempotente. Un compte
se désigne par forge et hôte ; lots et récapitulatifs peuvent mêler les forges. Vérifié avec le
vrai compte sur `Pauzzle-ozz/forceupdate-demo` (gitlab.com) : MR !1 ouverte, relancée sans rien
pousser, puis refaite sur un `main` avancé. 2068 tests Python verts (plus 9 réseau), 134 Vitest,
43 Playwright. E19 n'est pas commitée : à proposer d'abord.

Lis CLAUDE.md, puis l'étape E20 de PLAN.md (et les « Notes » de E16 à E19, surtout « Depuis
E19 »), `docs/BRIEF.md` (décisions n°13, 14, 16 et 22, « Forges » dans les pièges, GitLab
« constaté à E19 »), `docs/JSON_FORMAT.md` (« Comptes des forges », « Dépôts des forges », « PR
des dépôts »), le code de `src/forceupdate/forges/` (`base.py` : `Forge`, `OAuthFlow`, `Grant`,
`Renew` ; `github.py`, `gitlab.py` comme modèles ; `git.py`, `accounts.py` : `renewer` ;
`__init__.py`), `web/connections.py` (`apps`, `renew`), `web/routes/accounts.py`
(`SCOPES`, `TOKEN_URLS`, `APPLICATIONS_URLS`, `_methods`), `web/routes/oauth.py`,
`web/repositories.py`, `web/proposals.py`, et `tests/fake_gitlab.py` (le modèle du Bitbucket
simulé). **Charge d'abord le skill `ui-ux-pro-max`** (écrans 6, 7 et 8 pour Bitbucket), puis
`design-system/MASTER.md` (« Fait à E14 » à « Fait à E19 »), les écrans 6, 7 et 8 de
`design-system/ECRANS.md` et `design-system/pages/depots.md`.

À faire :
- Prérequis, avec l'utilisateur (le guider pas à pas, le formulaire d'Atlassian a pu changer) :
  créer un « OAuth consumer » Bitbucket (dans un workspace de l'utilisateur : Workspace settings →
  OAuth consumers), adresse de retour `http://127.0.0.1/oauth/bitbucket/callback` (vérifier que
  Bitbucket accepte n'importe quel port sur 127.0.0.1 : un fil de la communauté Atlassian dit
  qu'ils l'ont corrigé, à vérifier en vrai ; sinon trouver comment faire), permissions : compte
  (lecture), dépôts (écriture), pull requests (écriture). Le consumer a un secret (privé) : le
  garder comme celui de GitHub (public de fait, `FORCEUPDATE_BITBUCKET_CLIENT_ID`/`…_SECRET`).
- Connexion : OAuth (authorization code ; PKCE si Bitbucket l'accepte) ; en repli, un token d'API
  Atlassian (les « app passwords » sont en fin de vie : vérifier ce qui les remplace et comment
  on s'authentifie à l'API et à git avec) ; **les tokens d'OAuth de Bitbucket expirent (2 h, refresh
  token)** : `OAuthFlow.refresh`, `forges.client(…, renew=)` ; `forges.FORGES` (Bitbucket
  `available`), l'adresse de retour dans `RETURN_PATHS` et son test de refus, la révocation (si
  Bitbucket en a une, sinon le dire).
- `forges/bitbucket.py` : `whoami` (droits, `Identity.email` : y a-t-il une adresse `noreply` ?),
  `list_repos` (workspaces, `role=member`, droit d'écriture), `repository`, `tree` (pas
  d'arborescence complète en un appel : parcours dossier par dossier avec `max_depth`, ou clone
  superficiel pour un gros dépôt ; un seul langage par dépôt : le détecteur de E02), `read_file`
  (`/src/{commit}/{chemin}`), `clone` (`x-token-auth`), `branch` (ses commits propres, l'arbre du
  dernier commit ou son recalcul comme `gitlab.tree_id`), `push_branch` (bail `expected`, jamais la
  branche par défaut), `find_open_request`, `open_or_update_request` (PR depuis
  `forceupdate/dependencies`, mise à jour plutôt que doublée).
- `forges.parse_repository` : `bitbucket.org/espace/depot` (déjà reconnu, à garder) ; Bitbucket
  Data Center : hors V1, l'écrire dans la doc.
- Écrans : la carte Bitbucket de l'écran 6 (aujourd'hui « Bientôt ») ; écrans 7 et 8 : « PR »
  (`#41`), rien d'autre à changer en principe (les mots viennent de `lib/proposals.ts`).
- Tests : Bitbucket simulé comme `tests/fake_gitlab.py` (dépôts « bare » où git pousse, PR, OAuth
  et refresh), API, Vitest, e2e (le serveur de test sert GitHub, gitlab.com et une instance ; la
  fausse page d'autorisation distingue les forges par son chemin).

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E19 ; puis quel dépôt Bitbucket utiliser
  pour l'essai (en créer un exprès, comme à E18 et E19, copie de `tests/projects/vulnerable`),
  jamais un dépôt réel sans son accord. Les dépôts de test GitHub et GitLab
  (`Pauzzle-ozz/forceupdate-demo`) sont gardés pour la recette E31 : ne pas y toucher.
- **Le token** : jamais dans `argv`, une URL, un message ou un journal ; `forges.git` le fait
  (credential helper éphémère, `credential.helper=` vidé avant). Sous Bitbucket, le nom est
  `x-token-auth`.
- **Vérifier en vrai ce que répond la forge** : à E19, gitlab.com répondait 400 là où on attendait
  401 ou 404 (`/personal_access_tokens/self` avec un token d'OAuth) ; le simulé doit répondre comme
  la vraie forge, sinon les tests passent et l'essai échoue.
- **Qui parle à la forge d'où** : la liste et le récapitulatif dans la boucle du serveur (client
  des comptes, `Repositories.forge(account, connections.http)`) ; analyses et envois dans la
  boucle du `Worker` (`Repositories.worker_forge_of`) ; git et outils de lockfile dans le thread
  des mises à jour (`Jobs.in_updates`) ; l'état modifié seulement dans la boucle du serveur
  (`Jobs.post`). Le renouvellement d'un token peut venir des deux boucles : `accounts.renewer` le
  sérialise déjà.
- Tests : jamais de vraie forge ni de vrai trousseau (garde-fous de `conftest.py`) ; jamais
  `monkeypatch.undo()` (`monkeypatch.context()`) ; pour un registre muet, un 503, pas une coupure.
  Les tests qui lancent git : sur des dossiers temporaires, avec `-c user.name=… -c user.email=…`.
- Front : un même `owner/nom` peut exister sur plusieurs forges (cas réel à E19) : les noms
  accessibles le disent déjà (`spokenName`) ; `\s` dans les motifs (espaces insécables, aussi
  avant `!` et `#`) ; Playwright : `exact: true`, et le premier élément d'une ligne peut être
  celui caché à cette largeur ; une région `aria-live` double le texte qu'elle annonce.
- Scripts : écrire les scripts dans le scratchpad avec l'outil d'écriture (un heredoc abîme les
  accents et les `\\`) ; jamais `node -e "…"` avec des accents graves.

Fini quand : sur un dépôt de test Bitbucket, depuis l'interface : connexion, analyse, PR ouverte,
puis mise à jour de la même PR. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`,
`npm run lint`, `npm run test:e2e` ; à la main, `uv run forceupdate ui` avec le vrai compte
Bitbucket (GitHub et GitLab toujours connectés), en clair et en sombre, à 375 et 1440 px.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
