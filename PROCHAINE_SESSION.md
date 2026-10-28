# Session 15 — Étape E15 : Front, mise à jour locale

Contexte : E01 à E14 sont faites. Depuis E14, `forceupdate ui` sert l'interface (`frontend/`,
construite dans `src/forceupdate/web/static/`, ignoré par git, embarqué dans le paquet) : coquille,
écrans 1 à 4 (accueil, choisir, analyse en cours, rapport) avec leurs états, sous la CSP du serveur
gardée telle quelle. Le bouton « Mettre à jour » du rapport et le panneau de détail mènent à
`/analyses/{id}/mise-a-jour`, qui affiche encore « pas encore disponible ». 1706 tests Python verts
(plus 8 réseau), 48 tests Vitest, 7 Playwright. E14 n'est pas commitée : à proposer d'abord.

Lis CLAUDE.md, puis l'étape E15 de PLAN.md (et les « Notes » de E12, E13 et E14). **Charge d'abord le
skill `ui-ux-pro-max`**, puis lis `design-system/MASTER.md` (dont « Fait à E14 »), l'écran 5 de
`design-system/ECRANS.md`, `design-system/pages/mise-a-jour.md`, et ouvre la maquette
`mockups/mise-a-jour.html` (barre « MAQUETTE » : toutes ses variantes, clair et sombre). Dans
`docs/JSON_FORMAT.md` : les mises à jour du rapport et « Plan de mise à jour ».

À faire :
- Écran 5 aux adresses `/analyses/{id}/mise-a-jour` (étape Choisir) et `/plans/{id}` (Vérifier,
  Appliquer, Résultat), à la place de `UpdateSoon` (`frontend/src/App.tsx`) :
  - Choisir : les `updates` des projets, groupées par lockfile ; une carte par `Update` (case du
    paquet, boutons radio des `options`, au plus une cochée, pré-cochage `selected`), avertissements,
    failles corrigées / laissées / apportées, `note`, option `manual` grisée avec sa raison ;
    « Sélection proposée », « Tout décocher » ; récapitulatif en colonne collante (barre collante en
    bas sous 1024 px) ; `?paquet=<Update.id>` (lien du panneau de détail) ouvre cette carte ;
  - Vérifier : `POST /api/updates/plan` → diffs par fichier, `skipped` avec leur raison, lockfiles
    (outil trouvé ou commande à copier, avertissements), garde-fou git (`uncommitted` ; `null` hors
    de git) ;
  - Appliquer : `POST /api/updates/apply`, 409 → « Appliquer quand même… » confirmé (`force: true`) ;
    suivre `GET /api/updates/{id}/events` (`written`, `regenerating`), fermer l'`EventSource` à `end` ;
    pas d'annulation (le dire) ;
  - Résultat (`results`) : par lockfile, statut, versions obtenues (`reach`, `held_by`), « aussi
    changé », fichiers remis, erreur de l'outil ; « Relancer l'analyse ».
- Fichier envoyé : l'analyse marche déjà ; reste le plan (sans lockfile) et « Télécharger *nom* »
  (`GET /api/updates/{id}/files/{nom}`), à la place d'« Appliquer ».
- Toutes les variantes de la maquette : garde-fou, hors de git, outil absent, hors ligne, plan
  périmé (409 fichier changé), échec d'un outil, fichier envoyé, option `manual`, faille apportée,
  `note`, rien à mettre à jour.
- Tests : Vitest pour les composants (`src/test/api.tsx` : `mockApi`, `renderApp` ; `test/events.ts` :
  `FakeEventSource`) ; un test Playwright qui applique une mise à jour sur une copie d'un mini-projet.
- Revue avec la checklist de MASTER (axe-core est déjà dans `frontend/e2e/a11y.spec.ts` : y ajouter
  l'écran 5), clair et sombre, 375 à 1440 px.

Attention :
- **CSP** (`default-src 'self'`) : l'AlertDialog de Radix et Sonner injectent un `<style>`, refusé.
  Le dialogue de confirmation est un `<dialog>` natif, comme `components/ui/sheet.tsx` ; « Copié »
  (commande à copier) s'annonce par une région `aria-live`, pas par Sonner. Les tests e2e échouent
  sur toute erreur de console : c'est ce qui l'attrape.
- Pas de logique métier dans le front : la sélection envoyée est `{Update.id: version}` ; ce qui sera
  écrit, sauté, régénéré vient du plan ; les chiffres du récapitulatif se comptent sur la sélection
  affichée (déduction d'affichage), jamais en recalculant des versions.
- Le test e2e qui applique : `tests/e2e_server.py` tourne hors ligne avec un dossier temporaire ; y
  copier le mini-projet, et jamais de vrai npm ni uv (simuler les outils comme `FakeTools`, ou outil
  absent). Pour essayer à la main avec les vrais outils : sur une copie dans le scratchpad (CLAUDE.md).
- Réutiliser `screens/report/cells.tsx` (`VersionArrow`, `fixesText`), `components/badges.tsx`,
  `Blade`, `lib/format.ts` (`fr` pour les espaces insécables : les noms accessibles des rôles les
  gardent, les textes des tests non).
- Un bouton dont le nom porte un texte réservé aux lecteurs d'écran : `aria-label` (Chrome compte un
  `sr-only` comme un bloc et ajoute une espace).
- `npm run build` avant `uv run forceupdate ui` (sinon une ligne de texte) ; Playwright démarre lui-même
  le serveur de test (`npm run test:e2e`).

Fini quand : choisir → analyser → cocher → voir le diff → appliquer, sans quitter le navigateur, sur
un projet Python et un projet npm. Vérifier avec : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` (dans `frontend/`) ; `uv run forceupdate ui` sur une copie de
`tests/projects/vulnerable` dans le scratchpad (vrais npm et uv), en clair et en sombre, à 375 et
1440 px ; `uv run pytest` et `uv run ruff check` verts.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
