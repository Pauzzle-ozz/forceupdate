# Session 16 — Étape E16 : Interface `Forge` commune, connexion GitHub

Contexte : E01 à E15 sont faites. Le parcours local est complet dans l'interface (jalon de la
phase D) : `forceupdate ui` choisit un dossier ou un fichier, analyse, montre le rapport, puis
l'écran 5 fait cocher, voir le diff, appliquer (lockfiles régénérés par les vrais outils) et
lire le résultat ; un fichier déposé se télécharge mis à jour. 1706 tests Python verts (plus
8 réseau), 74 tests Vitest, 16 Playwright. E15 n'est pas commitée : à proposer d'abord.
Commence la phase E (forges) : rien n'existe encore dans `src/forceupdate/forges/`.

Lis CLAUDE.md, puis l'étape E16 de PLAN.md (et l'introduction de la phase E, les « Notes » de
E12 pour la sécurité du serveur et de E13 pour l'écran 6), `docs/BRIEF.md` (décision n°13,
« Forges » dans les pièges, le tableau des forges, « Ce qu'on a déjà »), et dans Argos
(`~/Desktop/the good guy`) `sechunter/dashboard/api/routes/oauth_sso.py` et le client git (le
token jamais dans les arguments ni les logs). **Charge d'abord le skill `ui-ux-pro-max`** pour
l'écran 6, puis `design-system/MASTER.md` (« Fait à E14 », « Fait à E15 ») et l'écran 6 de
`design-system/ECRANS.md`.

À faire :
- `forges/base.py`, interface `Forge` : `whoami` ; `list_repos`, `tree`, `read_file` ; `clone`,
  `push_branch` ; `find_open_request`, `open_or_update_request` (E16 n'en implémente que ce que
  demande la connexion ; le reste est pour E17 et E18, mais l'interface est fixée ici).
- Avec l'utilisateur, une seule fois : enregistrer l'outil comme OAuth App GitHub (adresse de
  retour `http://127.0.0.1/…`, Device Flow activé) ; récupérer le client id (et le secret,
  admis pour une application installée, comme `gh`). Le guider pas à pas.
- Connexion GitHub depuis l'écran « Comptes » : « Se connecter avec GitHub » (autorisation sur
  github.com, retour sur le serveur local ; vérifier qu'un retour vers `127.0.0.1` sur n'importe
  quel port est accepté), `state` anti-CSRF ; repli device flow (le code en grand, « Copier »,
  attente) ; autres options : coller un token, reprendre celui de `gh`. Portée `repo`, à
  confirmer.
- `forges/accounts.py` : tokens dans le trousseau (`keyring`), jamais affichés, jamais dans les
  logs, jamais envoyés au navigateur ; se déconnecter les efface.
- `forges/github.py` : client REST (pagination `Link`, limites de débit, messages clairs pour
  401, 403, 404) ; `whoami` avec ce que permet le token (lecture seule, ou écriture et PR ;
  « droits non vérifiés » pour un token fine-grained, sans `X-OAuth-Scopes`).
- API des comptes (lister, connecter par OAuth, device flow, token collé ou `gh`, déconnecter,
  droits), `web/openapi.json` et `docs/JSON_FORMAT.md` refaits, types du front régénérés.
- Écran 6 (Comptes) pour GitHub, selon ECRANS.md et ses états ; la carte de GitLab et de
  Bitbucket « bientôt » (E19, E20).
- Tests : API GitHub et OAuth simulés (respx), keyring simulé ; Vitest pour l'écran 6 ; e2e.

Attention :
- **Le retour d'OAuth et le garde du serveur** (`web/security.py`) : le retour de github.com est
  une navigation venue d'un autre site. Le cookie de session est `SameSite=Strict` : il **n'est
  pas envoyé** sur cette navigation (401), et `Sec-Fetch-Site: cross-site` est refusé (403).
  Concevoir la route de retour pour ça (hors de `/api`, vérifiée par le `state` gardé côté
  serveur, qui renvoie vers `/comptes` en navigation de même site), sans affaiblir le garde pour
  le reste. Le tester comme les autres refus (`tests/test_web_security.py`).
- Aucun test ne touche le vrai trousseau ni le vrai GitHub : ajouter un garde-fou automatique à
  `tests/conftest.py` (comme les quatre autres), et faire de même dans `tests/e2e_server.py`
  (trousseau en mémoire, GitHub simulé). Les tests réseau, s'il y en a, sont marqués `network`.
- `gh auth token` : trouvé par `shutil.which`, lancé sans shell, avec un délai ; le token ne
  passe jamais par les arguments d'une commande ni par les logs (BRIEF, « Forges »).
- À trancher avec l'utilisateur : OAuth App (prévu) ou GitHub App ; les logos des forges (le nom
  en texte avec une icône neutre, ou les logos officiels de Simple Icons, CC0, selon les chartes).
- Front : sous la CSP (`default-src 'self'`), pas d'avatar chargé de github.com (servi par le
  serveur local, ou pas d'avatar) ; réutiliser `Command` (le code du device flow, « Copier »),
  `ConfirmDialog` (« Se déconnecter », bouton risqué), `Blade` (attente), `useScan`/`usePlan`
  comme modèle pour les requêtes ; un bouton dont le nom porte un texte réservé aux lecteurs
  d'écran : `aria-label`.
- Le scratchpad pour les essais à la main ; jamais `python - <<EOF` (les accents s'abîment, et
  `write_text` sous Windows écrit en CRLF) : écrire le script dans un fichier.

Fini quand : depuis l'interface, l'utilisateur connecte son vrai compte GitHub, le voit dans
« Comptes », puis se déconnecte. Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`,
`npm run lint`, `npm run test:e2e` ; à la main, `uv run forceupdate ui` avec le vrai compte de
l'utilisateur (OAuth, puis device flow, puis token collé), en clair et en sombre, à 375 et
1440 px.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
