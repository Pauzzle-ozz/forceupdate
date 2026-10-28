# Session 13 — Étape E13 : Conception de l'interface (skill ui-ux-pro-max)

Contexte : E01 à E12 sont faites. Depuis E12, `forceupdate ui` démarre un serveur local
(FastAPI, uvicorn, `127.0.0.1` seulement, jeton de session) dont l'API fait tout le parcours
local : lister les dossiers, analyser en tâche de fond avec la progression en direct (SSE),
annuler, préparer un plan (diffs, lockfiles à régénérer, garde-fou git), l'appliquer (manifestes
puis lockfiles, avec la progression par outil), analyser un fichier glissé-déposé et télécharger
sa version réécrite. Il n'y a pas encore d'interface : `/` affiche une ligne de texte. 1706 tests
verts (plus 8 réseau). E13 conçoit l'interface, sans la coder.

Lis CLAUDE.md, puis l'étape E13 de PLAN.md (et les « Notes » de E12). **Charge d'abord le skill
`ui-ux-pro-max`** et suis son déroulé. Lis docs/BRIEF.md (l'idée, « Le parcours », « Les trois
niveaux de mise à jour », les décisions n°10, 12, 17, et les pièges « Interface web »), et dans
docs/JSON_FORMAT.md le rapport et « L'API de l'interface web » : c'est ce que les écrans
montreront (constats, gravités, mises à jour et leurs options, plans, progression).

À faire :
- Avec le skill : analyser le besoin (outil de développeur, tableau de bord, sobre et lisible),
  générer le design system avec `--design-system --persist -p "forceupdate"` →
  `design-system/MASTER.md`, versionné ; une page `design-system/pages/<écran>.md` pour chaque
  écran qui s'écarte du master. Sous Windows, lancer les scripts du skill avec `python`, pas
  `python3`. Le clin d'œil à Star Wars : à doser (un détail, un message de chargement), sans
  nuire à la lisibilité ni reprendre de logo ou d'image protégés.
- Les 9 écrans du tableau de E13 (accueil, choisir un dossier ou un fichier, analyse en cours,
  rapport, mise à jour, comptes, mes dépôts, PR / MR, réglages), chacun avec ses états : vide,
  chargement, erreur, hors ligne, « non concluant ». Clair et sombre. Accessibilité : les règles
  de priorité 1 du skill.
- Maquettes HTML statiques des écrans 1, 4, 5 et 7 dans `design-system/mockups/`, ouvrables
  dans le navigateur, avec des données réalistes (le mini-projet `vulnerable` : 28 failles,
  lodash 4.17.15 → 4.18.1 pré-cochée, flask 0.12 → 0.12.5 pré-cochée et 3.1.3 majeure proposée,
  jinja2 indirecte par le lockfile seul, les deux lockfiles et leurs commandes). Les montrer à
  l'utilisateur.
- Confirmer avec l'utilisateur la pile du front (proposition : React + TypeScript + Vite +
  Tailwind + shadcn/ui) et les icônes (SVG, pas d'emoji).
- La case ajoutée par E12 : refléter ce que l'API permet (progression par étape et par
  lockfile, annulation d'une analyse mais pas d'une mise à jour, chemins récents gardés d'une
  session à l'autre mais pas les rapports, garde-fou git et « appliquer quand même », fichier
  envoyé qui se télécharge réécrit).

Attention :
- E13 ne code pas le front (c'est E14) et ne touche ni à `src/` ni à l'API ; si un écran a
  besoin de quelque chose que l'API n'a pas, l'ajouter au plan (E14 ou E15) plutôt que de la
  changer maintenant.
- Les maquettes sont des fichiers statiques : pas d'appel à l'API, pas de CDN qui chargerait du
  code tiers sans que l'utilisateur le sache ; tout en local dans `design-system/mockups/`.
- Ce que l'écran 5 doit montrer d'une mise à jour vient du modèle : une `Update` est un groupe
  d'options exclusives (une au plus cochée, `selected` pré-cochée), chaque option a `gap`,
  `reasons`, `fixes`, `unfixed`, `introduced`, `warnings`, `manual` (grisée, avec la raison) ;
  le plan a `files` (diffs), `skipped`, `lockfiles` (outil trouvé ou commande à lancer,
  avertissements), `uncommitted` ; après application, `results` (version obtenue, `reach`
  exacte/plus haute/retenue, fichiers remis, erreur de l'outil).
- Les travaux de E11 et E12 n'étaient pas commités à la fin de la session 12 : si l'utilisateur
  ne les a pas commités entre-temps, le lui proposer en début de session.
- Les écrans 6 à 8 (comptes, dépôts, PR) dépendent des forges (E16 à E20) : les concevoir
  maintenant quand même, pour un design system cohérent.

Fini quand : l'utilisateur a validé le design system et les maquettes. Vérifier avec : les
maquettes ouvertes dans le navigateur, en clair et en sombre, à petite et grande largeur ; la
checklist d'accessibilité du skill ; `uv run pytest` et `uv run ruff check` toujours verts (rien
de `src/` ne doit changer).

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
