# Design system — forceupdate (MASTER)

> **Logique** : pour un écran, lire d'abord `design-system/pages/<écran>.md` s'il existe :
> ses règles priment sur ce fichier. Sinon, ce fichier seul. Les écrans, leur contenu et
> leurs états sont dans [ECRANS.md](ECRANS.md) ; les maquettes dans [mockups/](mockups/)
> (ouvrir `mockups/index.html`).

- **Projet** : forceupdate, l'interface web locale (`forceupdate ui`).
- **Pile** (confirmée à E13) : React + TypeScript + Vite + Tailwind 4 + shadcn/ui, icônes
  Lucide. Le front construit est servi par le serveur local, sous la CSP
  `default-src 'self'` : aucune ressource extérieure (ni police, ni script, ni image).
- **Langue** : français partout dans l'interface.

## Provenance

Généré le 2026-10-28 par le skill `ui-ux-pro-max` :

```bash
python search.py "developer tool dashboard dependency security scanner sober readable data-dense" \
  --design-system --persist -p "forceupdate"
```

(Le script écrit dans `design-system/forceupdate/MASTER.md` ; le fichier a été rangé ici,
comme le prévoit le plan.) Le skill a proposé le style **Data-Dense Dashboard**, la
palette « Developer Tool / IDE » (ardoise sombre, accent vert), les polices Fira Code et
Fira Sans, le motif de page « Real-Time / Operations Landing ». Recherches
complémentaires : `--domain product "developer tool devops security"` (« Dark syntax
theme colors + Blue focus »), `--domain typography` (paire « Developer Mono »),
`--domain ux` (tableaux, états vides, accessibilité), `--stack shadcn`.

Ce qui a été changé, et pourquoi :

| Proposé | Retenu | Pourquoi |
|---|---|---|
| Accent vert `#22C55E`, texte blanc dessus | Accent bleu (`#2563EB` en clair, `#3B82F6` en sombre) | Blanc sur ce vert : 2,3:1, illisible. Et ici le vert veut dire « à jour » et le rouge « faille » : l'accent ne doit pas prendre une couleur de sens. Le bleu est celui que le skill donne pour les outils de développeur (« Blue focus »), et celui de la « lame » |
| Sombre seulement (ardoise `#0F172A`) | Clair **et** sombre, suivant le système, au choix | Le livrable l'exige ; le style Data-Dense Dashboard gère les deux |
| Fira Code + Fira Sans, par Google Fonts | IBM Plex Sans + JetBrains Mono (paire « Developer Mono » du skill), embarquées | Google Fonts est interdit par la CSP et ne marche pas hors ligne. Les deux existent en police variable sur npm (`@fontsource-variable/…`, licence OFL) : un fichier par famille |
| Titres en police à chasse fixe | Titres en IBM Plex Sans, chasse fixe réservée à ce qui se copie | Des titres français en chasse fixe se lisent mal ; la chasse fixe signale « ceci est du code » |
| Motif « Real-Time / Operations Landing » (hero, CTA d'essai) | Sans objet | Ce n'est pas un site à vendre : l'outil s'ouvre sur l'écran de travail |
| Cartes de la couleur du fond, ombres partout, survol qui soulève | Surfaces distinctes, bordures fines, ombres seulement pour ce qui flotte | Densité et sobriété ; pas de mouvement de mise en page au survol |

## Principes

1. **Le plus grave d'abord** : faille (par gravité) > fin de vie > retirée > dépréciée >
   majeure > mineure > correctif (décision n°8 du brief). L'ordre du rapport est respecté
   partout.
2. **Ne jamais dire plus qu'on ne sait** : « non concluant » se voit (violet, bord en
   pointillé, icône point d'interrogation) et n'est jamais confondu avec « à jour » ; une
   version approximative (borne basse) est marquée « approximative » ; une dépendance non
   vérifiée est dite « non vérifiée ».
3. **Rien n'est écrit sans validation** : on choisit, on voit le diff et les commandes, on
   applique. Les garde-fous (git, outil absent, majeure, faille apportée) sont visibles
   avant d'agir, pas après.
4. **Sobre** : une couleur d'accent, les autres réservées au sens ; pas de dégradés, pas de
   verre dépoli, pas d'illustrations. La densité d'un outil de développeur, sans
   entassement : de l'air entre les groupes, pas dans les lignes.
5. **Jamais la couleur seule** : chaque couleur de sens va avec une icône et un mot
   (« Élevée », « non concluant », `+`/`−` dans un diff).
6. **Une action principale par écran** (bouton plein). Les autres sont secondaires.

## Couleurs

Tokens sémantiques, jamais de valeur brute dans un composant. Contrastes calculés
(WCAG 2.x) : tout texte ≥ 4,5:1 sur son fond, toute bordure de composant ou anneau de
focus ≥ 3:1, dans les deux thèmes (script de vérification de la session 13 ; à refaire
si une valeur change).

### Neutres et accent

| Token | Clair | Sombre | Rôle |
|---|---|---|---|
| `--bg` | `#F8FAFC` | `#0B1120` | fond de page |
| `--surface` | `#FFFFFF` | `#131C2E` | cartes, tableaux, panneaux |
| `--surface-2` | `#F1F5F9` | `#1C2638` | en-têtes de tableau, code, survol |
| `--text` | `#0F172A` | `#F1F5F9` | texte (16–18:1) |
| `--text-muted` | `#475569` | `#A3B1C6` | texte secondaire (≥ 6,9:1 partout) |
| `--border` | `#E2E8F0` | `#273449` | séparateurs (décoratifs) |
| `--border-control` | `#7C8BA1` | `#6B7A90` | bord des champs, cases, boutons secondaires (≥ 3,3:1) |
| `--primary` | `#2563EB` | `#3B82F6` | action principale, sélection |
| `--primary-hover` | `#1D4ED8` | `#60A5FA` | survol |
| `--on-primary` | `#FFFFFF` | `#0B1120` | texte sur `--primary` (5,2:1 et 5,1:1) |
| `--primary-soft` | `#EFF6FF` | `#172554` | option choisie, ligne sélectionnée |
| `--link` | `#1D4ED8` | `#93C5FD` | liens |
| `--ring` | `#2563EB` | `#60A5FA` | anneau de focus |
| `--blade` | `#2563EB` | `#60A5FA` | la « lame » (progression, marque) |
| `--blade-glow` | aucun | lueur bleue | halo de la lame, en sombre seulement |

### Sens : gravités, états, diff

Texte de la couleur sur son fond teinté (badges, alertes) :

| Token | Clair (texte / fond) | Sombre (texte / fond) | Usage |
|---|---|---|---|
| `--critical` | blanc sur `#B91C1C` (plein) | blanc sur `#DC2626` | gravité critique : le seul badge plein |
| `--high` | `#B91C1C` / `#FEF2F2` | `#FCA5A5` / `#3A1519` | gravité élevée |
| `--medium` | `#C2410C` / `#FFF7ED` | `#FDBA74` / `#3A2213` | gravité moyenne |
| `--low` | `#854D0E` / `#FEFCE8` | `#FDE68A` / `#332A12` | gravité faible |
| `--info` | `#334155` / `#F1F5F9` | `#CBD5E1` / `#1C2638` | information |
| `--success` | `#15803D` / `#F0FDF4` | `#86EFAC` / `#11291D` | à jour, régénéré, version exacte |
| `--warning` | `#92400E` / `#FFFBEB` | `#FCD34D` / `#33270F` | majeure, hors de git, hors ligne, avertissements |
| `--danger` | `#B91C1C` / `#FEF2F2` | `#FCA5A5` / `#3A1519` | erreur, échec, faille apportée, action risquée |
| `--inconclusive` | `#6D28D9` / `#F5F3FF` | `#C4B5FD` / `#251E3D` | non concluant (avec bord en pointillé) |
| `--diff-add` | `#166534` / `#ECFDF3` | `#86EFAC` / `#11291D` | lignes ajoutées |
| `--diff-del` | `#991B1B` / `#FEF2F2` | `#FCA5A5` / `#3A1519` | lignes retirées |

Aplats des graphiques (barre des gravités), toujours avec légende et nombres :
`--chart-critical` `#7F1D1D` / `#F43F5E`, `--chart-high` `#DC2626` / `#EF4444`,
`--chart-medium` `#EA580C` / `#F97316`, `--chart-low` `#CA8A04` / `#EAB308`,
`--chart-info` `#94A3B8` / `#64748B`.

## Typographie

- **Texte** : IBM Plex Sans Variable (`@fontsource-variable/ibm-plex-sans`, sous-ensemble
  latin : il contient les accents et `œ`).
- **Ce qui se copie** — noms de paquets, versions, contraintes, chemins, commandes, diffs,
  identifiants de failles : JetBrains Mono Variable
  (`@fontsource-variable/jetbrains-mono`). **Ligatures coupées**
  (`font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0`) : sinon
  `--package-lock-only` s'affiche avec un tiret long et `==` en signe double, et une
  commande lue à l'écran ne serait plus celle à taper.
- Repli : `"Segoe UI", system-ui, sans-serif` et `"Cascadia Code", ui-monospace,
  Consolas, monospace`. `font-display: swap`.
- Échelle : 12 (badges, légendes : jamais moins), 14 (tableaux, aide), 16 (texte), 18,
  20 (titres de section), 24 (titre d'écran), 30 (chiffres des compteurs). Diff : 13 en
  chasse fixe.
- Graisses : 400 texte, 500 libellés et boutons, 600 titres et chiffres. Interligne 1,5
  (texte), 1,25 (titres), 1,55 (diff).
- Chiffres tabulaires (`tabular-nums`) dans les compteurs, les tableaux et les
  progressions.
- **Règles françaises** : guillemets « » ; espace insécable avant `:` `;` `!` `?` et à
  l'intérieur des guillemets (U+202F ou U+00A0, posée dans les chaînes de l'interface ;
  les messages de l'API arrivent avec des espaces simples, les afficher tels quels) ;
  virgule décimale (`CVSS 7,5`, déjà dans les messages de l'API) ; dates par
  `Intl.DateTimeFormat("fr-FR")` (« 28 oct. 2026 à 18:30 ») et durées relatives
  (« il y a 2 h ») ; accord du nombre (« 1 faille », « 28 failles »).

## Espacements, rayons, ombres, couches

- Espacements, base 4 px : 4, 8, 12, 16, 20, 24, 32, 40, 48. Dans un groupe 8–12, entre
  groupes 16–24, entre sections 32.
- Rayons : 4 (badges), 6 (boutons, champs), 8 (cartes, tableaux), 12 (dialogues).
- Ombres : aucune au repos. `--shadow-md` pour la barre d'actions collante, `--shadow-lg`
  pour les menus, le panneau latéral et les dialogues. En sombre, plus fortes et
  doublées d'une bordure.
- Couches (`z-index`) : 10 en-têtes collants, 20 barre d'actions, 40 panneau latéral et
  son voile, 50 menus, 100 dialogues, 1000 notifications.
- Voile derrière un panneau ou un dialogue : `rgba(15,23,42,.5)` en clair,
  `rgba(2,6,23,.7)` en sombre.

## Mouvement

- 150 ms (couleurs, survol), 200 ms (ouverture d'un menu, case qui se coche), 250 ms
  (panneau latéral, barre de progression). Entrée `cubic-bezier(.16,1,.3,1)`, sortie plus
  courte. Seulement `transform` et `opacity`, jamais la largeur ou la position (sauf la
  largeur de la barre de progression, qui porte l'information).
- `prefers-reduced-motion` : plus d'animation ni de transition ; la lame indéterminée
  devient une barre rayée immobile, les squelettes ne scintillent plus.
- Chargement de plus de 300 ms : squelettes (pas de toupie seule) ; tâche longue :
  progression avec ce qui se passe (étape, paquet, outil).

## Points de rupture et mise en page

- Conçu depuis 375 px : 640, 768 (le tableau devient une liste de cartes), 900 (la
  navigation passe dans un menu), 1024 (colonne latérale du récapitulatif), 1280, 1440.
  Aucun défilement horizontal de la page ; un diff ou une commande trop larges défilent
  dans leur propre cadre.
- Contenu : 1280 px au plus (rapport, dépôts), 1040 px (accueil, formulaires) ; marges
  16 px (mobile), 24 px (≥ 768), 32 px (≥ 1280).
- **Coquille** : en-tête collant de 56 px — la marque à gauche, la navigation principale
  (Analyser, Dépôts, Comptes, Réglages : icône et mot), à droite l'état du réseau (affiché
  seulement hors ligne) et le choix du thème. Sous 900 px, la navigation passe dans un
  menu. Un lien « Aller au contenu » en premier. Le pied de page : version, adresse du
  serveur local, la devise.
- Fil d'Ariane sur les écrans profonds : Analyser › `vulnerable` › Mise à jour.
- Chaque écran a une adresse (lien profond, retour arrière du navigateur) : voir
  ECRANS.md, « Adresses ».

## Icônes

- **Lucide** (`lucide-react`, licence ISC), trait de 2, coins arrondis ; tailles 16
  (dans un badge ou un texte), 20 (par défaut), 24 (tuiles), 40 (états vides). Jamais
  d'emoji.
- Une icône seule (bouton) a un `aria-label` ; à côté d'un mot, elle est `aria-hidden`.
- Correspondances fixes :

  | Sens | Icône |
  |---|---|
  | faille | `shield-alert` ; aucune faille connue : `shield-check` |
  | fin de vie | `hourglass` |
  | retirée | `package-x` |
  | dépréciée | `archive` |
  | plus récente | `circle-arrow-up` |
  | non vérifiable | `link-2-off` |
  | non concluant | `circle-help` |
  | critique · élevée · moyenne · faible · info | `octagon-alert` · `triangle-alert` · `circle-alert` · `circle-dot` · `info` |
  | majeure, avertissement | `triangle-alert` |
  | réussite, régénéré | `circle-check` ; version exacte : `check` |
  | erreur, échec | `circle-x` |
  | hors ligne | `wifi-off` ; serveur arrêté : `server-off` |
  | lockfile | `lock` ; diff : `file-diff` ; commande : `terminal`, `copy` |
  | dossier, fichier, dépôts | `folder` / `folder-open`, `file` / `file-code`, `folder-git-2` |
  | PR / MR | `git-pull-request` ; compte : `key-round` ; connecter : `plug` |
  | à faire à la main | `ban` ; paquet malveillant : `octagon-alert` |

- **Logos des forges** : Lucide n'en a plus (marques retirées en 1.0). À E16 : le nom de
  la forge en texte, avec une icône neutre (`git-branch`) ; ou leurs logos officiels
  (Simple Icons, CC0), en respectant les chartes de GitHub, GitLab et Bitbucket. À
  trancher à E16.

## Composants

Ceux de shadcn/ui quand ils existent (Button, Badge, Card, Table + TanStack Table,
Checkbox, RadioGroup, Switch, Select, Input, Sheet, Dialog, AlertDialog, Alert,
Progress, Skeleton, Tooltip, DropdownMenu, Collapsible, Sonner pour les
notifications), habillés par les tokens. Les maquettes en montrent le rendu.

- **Bouton** : principal (plein, un par écran), secondaire (contour), discret (sans
  fond), risqué (contour rouge : « Appliquer quand même… », toujours confirmé par un
  dialogue). Hauteur 40 px (44 au doigt : `pointer: coarse`), petit 32 px (44 au doigt).
  Désactivé : opacité .45 et `disabled`. Pendant une requête : désactivé, avec une
  toupie dans le bouton.
- **Badge** : gravité (icône + mot, critique plein, les autres teintés), type de constat,
  écart (« Correctif », « Mineure » en contour ; « Majeure » en avertissement avec
  icône), écosystème (`PyPI`, `npm`…), « directe » / « indirecte », « proposée »
  (pré-cochée), « non concluant » (bord pointillé).
- **Compteur** : libellé avec icône, chiffre (30 px), détail. Bordure gauche de 4 px
  quand il porte un sens (failles : rouge ; à jour : vert ; non concluant : violet
  pointillé). Un compteur cliquable filtre le tableau (`aria-pressed`). À zéro : chiffre
  atténué.
- **Barre des gravités** : une barre empilée de 12 px, une légende avec les nombres,
  un `aria-label` qui dit tout (« 0 critique, 13 élevées… »).
- **Alerte** : info, avertissement, erreur, réussite, non concluant ; icône, titre,
  texte, actions. Une erreur dit ce qui s'est passé **et** quoi faire. `role="alert"`
  pour une erreur qui arrive, `role="status"` sinon. En bandeau pleine largeur pour un
  état global (serveur arrêté, session terminée, hors ligne).
- **Tableau** : en-tête collant, tri par bouton dans l'en-tête (`aria-sort`), filtres
  au-dessus (recherche, segments, listes), nombre de lignes affichées annoncé
  (`aria-live`). Le nom du paquet est le bouton qui ouvre le détail. Sous 768 px : une
  carte par ligne, chaque valeur avec son libellé (à E14, une vraie liste plutôt qu'un
  tableau restylé : un tableau en `display: block` perd sa sémantique). Au-delà de 50
  lignes : virtualisé.
- **Panneau latéral** (Sheet) : le détail d'une dépendance, à droite, 600 px (plein
  écran sous 640 px) ; titre focalisé à l'ouverture, Échap ferme, le focus revient au
  bouton qui l'a ouvert.
- **Groupe d'options d'une mise à jour** : une case pour le paquet (le mettre à jour ou
  non) et des boutons radio pour la version, puisque **au plus une option** est choisie.
  Choisir une version coche le paquet ; décocher le paquet vide le choix ; le recocher
  reprend l'option `selected`. Chaque option : version, écart, raisons, failles
  corrigées et laissées, failles apportées (en rouge : jamais pré-cochée),
  avertissements, réécritures prévues (« `package.json` : 4.17.15 → 4.18.1 », ou
  « lockfile seul »). Une option `manual` est grisée, désactivée, avec la raison
  (`aria-describedby`). La `note` d'une mise à jour s'affiche sous son nom.
- **Fil d'étapes** (écran 5) : Choisir → Vérifier → Appliquer → Résultat, l'étape en
  cours en `aria-current="step"`. Retour en arrière possible tant que rien n'est écrit.
- **Diff** : un cadre par fichier (chemin, `+n −n`), numéros de ligne avant et après,
  `+` et `−` en plus de la couleur, défilement horizontal dans le cadre, focalisable au
  clavier.
- **Commande** : bloc en chasse fixe préfixé de `$`, bouton « Copier » qui devient
  « Copié » 2 s et l'annonce (`aria-live`).
- **La lame** : barre de progression fine (6 px), arrondie, en `--blade` ; en sombre,
  elle luit (`--blade-glow`). Déterminée (analyse, application) ou indéterminée (reflet
  qui glisse). `role="progressbar"` avec nom et valeurs.
- **Liste de tâches** : une ligne par étape (faite, en cours avec toupie, à venir,
  échouée), la durée à droite.
- **État vide** : icône 40 px, titre, une phrase, une action. Jamais un écran blanc.
- **Squelettes** : blocs gris aux dimensions du contenu attendu (pas de saut de mise en
  page à l'arrivée).
- **Zone de dépôt** : bord pointillé ; pendant un glisser, un voile sur toute la page
  dit quoi déposer et les limites (2 Mo, 50 Mo pour un lockfile). Toujours doublée d'un
  bouton « Choisir un fichier » (clavier).
- **Notification** (Sonner) : en bas à droite, 4 s, `aria-live="polite"`, jamais pour une
  erreur qui demande d'agir (celle-là est une alerte dans la page).

## Textes

- Impersonnel, phrases courtes, verbes à l'infinitif sur les boutons (« Analyser »,
  « Vérifier le plan », « Appliquer »). Le nom de ce qui sera fait plutôt que « OK »
  (« Appliquer quand même », « Relancer l'analyse »).
- Les termes établis restent : lockfile, diff, commit, PR (pull request), MR (merge
  request, sur GitLab seulement), CVE. On écrit « faille », « dépendance directe /
  indirecte », « correctif / mineure / majeure », « non concluant ».
- Les `message` de l'API (en français) s'affichent tels quels ; les `detail` des avis
  sont souvent en anglais : tels quels, avec `lang="en"`.
- Une erreur : ce qui s'est passé, puis quoi faire (« Le relancer avec
  `forceupdate ui` »). Jamais un code seul.

## Le clin d'œil

Le nom invite à Star Wars ; on reste discret, et jamais au détriment de la lisibilité :

- la **lame** : la marque (un trait bleu devant `forceupdate`) et la barre de
  progression, qui luisent en thème sombre ;
- la **devise** du brief en pied de page : « Que la Force soit avec tes dépendances. » ;
- **un** message de chargement, en ligne secondaire, sur l'écran d'analyse en cours
  (pages/analyse-en-cours.md) ;
- la page introuvable : « Ce n'est pas la page que vous cherchez. »

Jamais dans une erreur, un résultat, un constat ou un bouton. Aucun logo, image, police,
son ou nom de personnage repris.

## Accessibilité (priorité 1 du skill)

- Contrastes : vérifiés (voir « Couleurs ») ; à refaire à chaque nouveau token.
- Focus visible partout : anneau de 2 px `--ring`, décalé de 2 px ; jamais retiré (sauf
  sur un titre qui reçoit le focus par programme).
- Clavier : ordre de tabulation = ordre visuel ; boutons radio aux flèches ; Échap ferme
  panneaux et dialogues ; le focus est gardé dans un dialogue et rendu à la fermeture ;
  après un changement d'écran, le focus va au titre ou au contenu (`#contenu`).
- Lien d'évitement « Aller au contenu ».
- Noms : `aria-label` sur tout bouton à icône seule ; chaque champ a une étiquette
  visible (`label`), l'aide en `aria-describedby` ; jamais un placeholder pour étiquette.
- Titres sans saut de niveau, un seul `h1` par écran.
- Jamais la couleur seule (icône + mot, `+`/`−`).
- Progression annoncée (`role="progressbar"`, `aria-live="polite"` sur l'étape en cours,
  pas sur chaque paquet : une annonce toutes les 5 s au plus).
- Liens qui ouvrent un onglet : « (nouvel onglet) » pour les lecteurs d'écran,
  `rel="noreferrer"`.
- `lang="fr"` sur la page ; `lang="en"` sur les textes anglais des avis.
- Zoom permis (jamais `user-scalable=no`), texte agrandi à 200 % sans perte.
- Cibles : 40 px (souris), 44 px au doigt.
- Mouvement réduit respecté.

## Pour E14 : du design system au code

- `frontend/src/styles/tokens.css` : les tokens ci-dessus en variables CSS, sous `:root`
  (clair) et `.dark` (sombre ; classe posée d'après le choix enregistré, sinon d'après
  `prefers-color-scheme`). Les maquettes (`mockups/assets/mockups.css`) en sont la
  référence exacte.
- Variables de shadcn/ui : `--background` = `--bg`, `--foreground` = `--text`, `--card` =
  `--surface`, `--muted` = `--surface-2`, `--muted-foreground` = `--text-muted`,
  `--border` = `--border`, `--input` = `--border-control`, `--ring` = `--ring`,
  `--primary` / `--primary-foreground` = `--primary` / `--on-primary`, `--destructive` =
  `--danger`, `--radius` = 6 px ; plus les tokens de sens (`--critical`, `--high`…) dans
  le `@theme` de Tailwind 4.
- Polices : `@fontsource-variable/ibm-plex-sans` et `@fontsource-variable/jetbrains-mono`
  importées par le front, embarquées par Vite (servies par `'self'`).
- Le thème choisi (clair, sombre, système) est gardé dans le `localStorage` du
  navigateur (une préférence d'affichage, pas une donnée).
- CSP : pas de `<style>` ni d'attribut `style` dans le HTML servi ; les styles posés par
  React (`element.style`) sont permis. À vérifier avec le front construit (déjà noté à
  E14).

## Anti-motifs

- Couleur seule pour dire une gravité ou un état ; vert pour l'accent.
- Emoji en guise d'icône ; icônes de plusieurs familles.
- Police ou script chargés d'un CDN.
- Ligatures dans le code.
- Survol qui déplace la mise en page ; animation de largeur ou de position.
- Écran blanc pendant un chargement ou quand il n'y a rien ; « pas de faille » quand on
  ne sait pas.
- Toupie seule pour une tâche de plusieurs secondes.
- Majeure pré-cochée ; « Appliquer » sans diff ni récapitulatif.
- Tableau qui déborde de l'écran sur mobile.

## Checklist avant livraison (E14, E15, E31)

- [ ] Aucun emoji ; icônes Lucide seulement, tailles des tokens.
- [ ] `cursor: pointer` sur tout ce qui se clique ; survols de 150–300 ms.
- [ ] Contrastes : texte ≥ 4,5:1, composants ≥ 3:1, en clair **et** en sombre.
- [ ] Focus visible, ordre de tabulation, Échap, focus rendu.
- [ ] `prefers-reduced-motion` respecté.
- [ ] 375, 768, 1024, 1440 px : pas de défilement horizontal, rien sous l'en-tête collant.
- [ ] Chaque écran : vide, chargement, erreur, hors ligne, non concluant (ECRANS.md).
- [ ] Textes en français, règles typographiques, nombres accordés.
- [ ] Marche sous la CSP du serveur, sans réseau pour l'interface elle-même.
