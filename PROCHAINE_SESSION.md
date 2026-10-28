# Session 14 — Étape E14 : Front, socle et analyse locale

Contexte : E01 à E13 sont faites. Le serveur local de `forceupdate ui` (E12) a toute l'API du
parcours local ; E13 a produit le design system, validé par l'utilisateur : `design-system/`
(`MASTER.md`, `ECRANS.md`, `pages/`, et des maquettes HTML statiques des écrans 1, 4, 5 et 7
dans `mockups/`, à ouvrir par `mockups/index.html`). Pile confirmée : React + TypeScript + Vite
+ Tailwind 4 + shadcn/ui, icônes Lucide. Il n'y a pas encore de `frontend/` : `/` affiche une
ligne de texte. 1706 tests verts (plus 8 réseau). Tout est commité et poussé (E11 à E13).

Lis CLAUDE.md, puis l'étape E14 de PLAN.md (et les « Notes » de E12 et E13). **Charge d'abord le
skill `ui-ux-pro-max`**, puis lis `design-system/MASTER.md`, les écrans 1 à 4 de
`design-system/ECRANS.md`, `design-system/pages/analyse-en-cours.md` et `pages/rapport.md`, et
ouvre les maquettes `accueil.html` et `rapport.html` (barre « MAQUETTE » : tous les états, clair
et sombre). Dans `docs/JSON_FORMAT.md` : le rapport et « L'API de l'interface web ».

À faire :
- **API d'abord** (petit, avec tests) : `summary` du rapport (ou `null` avant la fin) dans
  `ScanSummary` de `GET /api/scans` ; `recent` en `{path, kind}` (dossier ou fichier). Refaire
  `web/openapi.json` (`uv run python -m forceupdate.web.openapi`) et `docs/JSON_FORMAT.md`.
- `frontend/` : React + TypeScript + Vite + Tailwind 4 + shadcn/ui + `lucide-react` ; polices
  `@fontsource-variable/ibm-plex-sans` et `@fontsource-variable/jetbrains-mono`, embarquées,
  ligatures coupées dans le code ; types générés depuis `src/forceupdate/web/openapi.json`
  (`operationId` : `start_scan`, `get_scan`…).
- Thème : les tokens de `design-system/mockups/assets/mockups.css` (référence exacte) dans
  `frontend/src/styles/tokens.css`, sous `:root` et `.dark`, branchés sur les variables de
  shadcn/ui (MASTER, « Pour E14 ») ; thème clair, sombre ou système, gardé dans le
  `localStorage`.
- Build : `npm run build` écrit dans `src/forceupdate/web/static/` (inclus dans le paquet
  Python) ; en dev, serveur Vite avec un proxy vers l'API qui réécrit `Host` et `Origin` vers
  l'adresse du serveur et porte le jeton (`Authorization: Bearer`, variable d'environnement de
  dev) — ne jamais affaiblir le garde.
- La coquille (en-tête, navigation, lien d'évitement, pied de page avec la devise) et ses états
  communs (serveur arrêté, session terminée `401`, hors ligne, page introuvable) ; les adresses
  de ECRANS.md.
- Écrans 1 à 4 (accueil, choisir un dossier ou un fichier, analyse en cours, rapport), chacun
  avec ses états (vide, chargement, erreur, hors ligne, non concluant), conformes aux maquettes ;
  SSE : fermer l'`EventSource` à `end`.
- Tests : Vitest + Testing Library pour les composants ; un test Playwright de bout en bout
  (choisir un mini-projet, voir le bon rapport).
- Revue avec la checklist de MASTER : accessibilité, états, clair et sombre, 375 à 1440 px.

Attention :
- CSP du serveur : `default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors
  'none'` (`web.security.SECURITY_HEADERS`). Rien d'un CDN ; pas de `<style>` ni d'attribut
  `style` dans le HTML servi (les styles posés par React via `element.style` passent). Vérifier
  le front construit sous elle, et n'assouplir qu'au strict nécessaire.
- Pas de logique métier dans le front : il affiche ce que rend l'API (ordre des constats,
  sélection par défaut, chiffres). Seules les déductions d'affichage sont permises (« non
  vérifiée » pour une indirecte sans `options.transitive`, gravité la plus haute d'une ligne).
- Le tableau des dépendances sous 768 px : une vraie liste de cartes, pas un tableau restylé.
- Annonces : l'étape en cours en `aria-live`, le nom du paquet au plus toutes les 5 s.
- Les tests Python ne doivent jamais lancer node ni ouvrir le navigateur (garde-fous de
  `tests/conftest.py`) ; les tests du front ont leurs propres commandes, à ajouter à CLAUDE.md
  (« Commandes ») et à la CI (E30 l'étend).
- Captures avec Edge sans fenêtre : sous Windows, sa fenêtre ne descend pas sous 492 px ; pour
  375 px, passer par un `iframe` (ou Playwright, qui fixe la vue).
- node : vérifier la version installée et la noter ; les dépendances du front se figent dans
  `frontend/package-lock.json` (versionné).

Fini quand : depuis `ui`, on analyse un vrai dossier ; le rapport est juste et conforme aux
maquettes. Vérifier avec : `uv run forceupdate ui`, un mini-projet (`tests/projects/vulnerable`)
puis un vrai dossier, en clair et en sombre, à 375 et 1440 px ; les tests du front ; `uv run
pytest` et `uv run ruff check` verts.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
