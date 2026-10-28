# Les écrans de forceupdate

Ce que montre chaque écran, avec quoi (l'API de `docs/JSON_FORMAT.md`), et ses états.
Les règles visuelles sont dans [MASTER.md](MASTER.md) ; un écran qui s'en écarte a sa page
dans [pages/](pages/). Maquettes : écrans 1, 4, 5 et 7 dans [mockups/](mockups/)
(ouvrir `mockups/index.html`, choisir l'état dans la barre « MAQUETTE »).

Écrans 1 à 5 : E14 et E15. Écrans 6 à 8 : E16 à E20 (forges). Écran 9 : E29.

## États communs à tous les écrans

Chaque écran a ses états **vide**, **chargement**, **erreur**, **hors ligne** et
**non concluant** (décrits écran par écran plus bas). S'y ajoutent ceux de la coquille,
partout :

| État | Ce qu'on voit | Déclencheur |
|---|---|---|
| Serveur arrêté | Bandeau d'erreur sous l'en-tête : « Le serveur local ne répond plus » ; le relancer avec `forceupdate ui` puis ouvrir l'adresse qu'il affiche ; « Réessayer » | `fetch` qui échoue (erreur réseau vers 127.0.0.1), `EventSource` en erreur sans reprise |
| Session terminée | Bandeau : le serveur a redémarré, son jeton a changé ; ouvrir l'adresse affichée par `forceupdate ui`. Les analyses sont perdues, les chemins récents restent | Réponse `401` |
| Hors ligne | « Hors ligne » dans l'en-tête (icône et mot) ; bandeau sur l'accueil : l'analyse n'utilisera que le cache, l'option « Hors ligne » est cochée d'office | `navigator.onLine` faux (le serveur est sur la même machine : c'est son réseau) ; ou un rapport dont `options.offline` est vrai |
| Page introuvable | « Ce n'est pas la page que vous cherchez. » et un lien vers l'accueil | Adresse inconnue du front (le serveur rend `index.html` pour toute adresse) |
| Thème | Clair, sombre ou celui du système ; bouton dans l'en-tête | Préférence gardée dans le navigateur |

Les erreurs `400`, `404`, `409`, `413` de l'API ont un `detail` en français : il s'affiche
dans une alerte, près de ce qui l'a provoquée, avec quoi faire.

## Adresses

Chaque écran a son adresse (lien profond, retour du navigateur) :

| Adresse | Écran |
|---|---|
| `/` | 1. Accueil |
| `/choisir?mode=dossier` (ou `fichier`) | 2. Choisir |
| `/analyses/{id}` | 3. Analyse en cours tant que `status` vaut `running`, puis 4. Rapport (ou l'état échouée, annulée) |
| `/analyses/{id}/mise-a-jour` | 5. Mise à jour, étape Choisir |
| `/plans/{id}` | 5. Mise à jour, étapes Vérifier, Appliquer, Résultat (un plan se retrouve après un rechargement) |
| `/comptes` | 6. Comptes |
| `/depots` | 7. Mes dépôts ; le rapport d'un dépôt réutilise l'écran 4 (`/analyses/{id}`) |
| `/pr` | 8. PR / MR |
| `/reglages` | 9. Réglages |

---

## 1. Accueil

**But** : choisir quoi analyser, ou retrouver une analyse. Maquette : `mockups/accueil.html`.

- Trois cartes : **un dossier** (action principale « Choisir un dossier » → écran 2),
  **un fichier** (« Choisir un fichier » → écran 2, ou déposer un fichier n'importe où sur
  la page), **mes dépôts** (« Connecter un compte » → écran 6 ; connecté : le nombre de
  comptes et de dépôts → écran 7).
- **Donner un chemin** : champ pour coller un chemin absolu, « Analyser » ; **options
  d'analyse** repliées (dépendances de dev, versions des indirectes, dossiers de tests et
  d'exemples, hors ligne, cache : les `options` de `POST /api/scans`, mêmes valeurs par
  défaut que `scan`).
- **Analyses récentes** :
  - *Cette session* (`GET /api/scans`) : nom, chemin, état (en cours avec sa lame,
    terminée, échouée, annulée), et pour une analyse finie ses chiffres (failles, plus
    récentes, non concluants) ; « Ouvrir le rapport », « Suivre », « Relancer » ;
  - *Chemins récents* (`recent` de `GET /api/fs`, gardés d'une session à l'autre) : un
    clic relance l'analyse avec les options par défaut ;
  - une phrase le dit : les rapports ne vivent que le temps de la session, les chemins
    restent.
- **Glisser-déposer** : un voile sur toute la page pendant le glisser ; au dépôt,
  `POST /api/files?name=…` puis écran 3. Un fichier refusé (`400` : pas un manifeste ni un
  lockfile ; `413` : trop gros) : alerte avec la raison et les limites.

| État | Ce qu'on voit |
|---|---|
| Vide | Premier lancement : pas d'analyse ni de chemin récent ; « Aucune analyse pour l'instant », et les chemins seront proposés ici la fois suivante |
| Chargement | Squelettes de la liste (cartes et champ déjà là) |
| Erreur | Serveur arrêté ou session terminée (bandeaux communs) ; la liste dit « indisponible » |
| Hors ligne | Bandeau, option « Hors ligne » cochée |
| Non concluant | Une analyse de la session avec « N non concluants » (badge violet) à côté de ses failles |

## 2. Choisir un dossier ou un fichier

**But** : désigner un chemin de l'ordinateur ; le navigateur ne peut pas donner un chemin à
une page, c'est le serveur qui liste.

- Points de départ (`GET /api/fs` sans `path`) : le dossier personnel, les lecteurs, les
  **dossiers récents** (`recent`).
- Liste d'un dossier (`GET /api/fs?path=`) : fil des dossiers parents cliquables (et
  `parent`), puis les dossiers et les fichiers de dépendances reconnus (seuls fichiers
  listés), icône et nom ; les cachés repliés derrière « Afficher les éléments cachés »
  (`hidden`) ; filtre par nom au clavier ; « liste coupée à 5000 entrées » si `truncated`.
- Clavier : flèches pour parcourir, Entrée pour ouvrir un dossier, Retour arrière pour
  remonter ; le chemin courant est aussi un champ éditable (coller un chemin).
- Action principale : « Analyser ce dossier » (le dossier courant) ou « Analyser ce
  fichier » (un fichier choisi). Les options d'analyse, repliées, comme à l'accueil.
- Zone de dépôt et « Choisir un fichier » (`<input type="file">`) : un fichier envoyé, pas
  un chemin (son lockfile voisin n'est pas lu, il ne s'applique pas : il se télécharge
  réécrit).

| État | Ce qu'on voit |
|---|---|
| Vide | Dossier sans sous-dossier ni fichier de dépendances : « Rien à choisir ici » ; on peut quand même analyser le dossier (`find_projects` cherche en profondeur) |
| Chargement | Squelettes des lignes (un lecteur réseau lent) |
| Erreur | `400` (chemin relatif), `404` (n'existe plus), accès refusé : alerte au-dessus de la liste, le chemin reste éditable |
| Hors ligne | Rien ne change (lister ne demande pas de réseau) ; l'option « Hors ligne » est cochée |
| Non concluant | Sans objet (rien n'est vérifié ici) |

## 3. Analyse en cours

**But** : voir avancer l'analyse, pouvoir l'annuler. Page à part :
[pages/analyse-en-cours.md](pages/analyse-en-cours.md).

- `GET /api/scans/{id}/events` (SSE) ; l'`EventSource` est fermé à l'événement `end`.
- **Étapes** (liste de tâches) : lecture des fichiers (`reading`), projets trouvés
  (`projects_found`, « 2 projets »), vérification des paquets (`checking` puis
  `package_checked` : « 41 sur 64 », le paquet en cours avec son écosystème), failles
  (`vulnerabilities_checked`), terminé (`finished`). La lame suit `done` / `total`.
- **Par projet** : l'API ne le donne pas (les événements n'ont pas de projet). L'écran
  montre le nombre de projets trouvés, puis la progression par paquet : c'est assez.
- Temps écoulé (depuis `started_at`), source et options en tête.
- Action : « Annuler » (`DELETE /api/scans/{id}`), secondaire. À `end` : `done` → écran 4
  (même adresse) ; `failed` → l'erreur ; `cancelled` → « Analyse annulée ».

| État | Ce qu'on voit |
|---|---|
| Vide | Sans objet : une analyse commence toujours par `reading` |
| Chargement | La lame indéterminée et « Lecture des fichiers… » avant le premier événement |
| Erreur | `failed` : alerte avec `error`, « Relancer » et « Choisir un autre dossier » ; `404` : l'analyse n'existe plus |
| Hors ligne | Bandeau « analyse hors ligne : cache seulement » ; les paquets absents du cache sortiront non concluants |
| Non concluant | Sans objet pendant l'analyse ; le rapport le dira |

## 4. Rapport

**But** : comprendre ce qui est à mettre à jour, du plus grave au moins grave. Page à part :
[pages/rapport.md](pages/rapport.md). Maquette : `mockups/rapport.html`.

- En tête : nom et chemin de la source, date et durée, données des registres
  (`oldest_data`, surtout hors ligne), options en badges ; actions « Relancer l'analyse »
  (même chemin, mêmes options ; pour un fichier envoyé : le redéposer) et, principale,
  « Mettre à jour » avec le nombre de mises à jour pré-cochées (→ écran 5 ; absente s'il
  n'y en a pas).
- **Synthèse** : un compteur par type de constat (`summary.findings`), les failles avec
  leur répartition par gravité, les plus récentes par écart (`summary.outdated`) ; la
  barre des gravités de tous les constats ; la couverture : directes, indirectes,
  vérifiées (`checked`), auditées (`audited`).
- **Langages** (`languages`, du plus lourd au plus léger, avec leur écosystème) et
  **projets** (`projects` : dossier, écosystèmes, manifestes, lockfiles). Plusieurs
  projets : un filtre par projet dans le tableau.
- **Dépendances** : tableau filtrable (nom, directes / indirectes, écosystème, type de
  constat, projet) et triable (gravité par défaut, nom, version). Colonnes : paquet
  (écosystème, directe ou indirecte, scope si ce n'est pas `runtime`), utilisée
  (`installed`, ou la borne basse marquée « approximative »), contrainte (`constraint`,
  fichier et ligne ; « aucune : vient du lockfile » pour une indirecte), constats
  (badges), gravité la plus haute, mise à jour proposée (`selected` de l'`Update`, son
  écart, ce qu'elle corrige ; une majeure « proposée, pas cochée »).
  - Une dépendance sans constat : « à jour » si elle a été vérifiée ; pour une indirecte
    sans `options.transitive` : « aucune faille connue, version non vérifiée » (les
    failles sont toujours cherchées) ; une dev sans `options.dev` : « non vérifiée ».
  - Non vérifiable (`unverifiable_reason`) : badge et raison.
- **Détail d'une dépendance** (panneau latéral) : versions (utilisée et d'où, contrainte et
  où, acceptée par la contrainte `wanted_version`, dernière), tous ses constats (gravité,
  identifiants, CVSS, titre de l'avis en anglais, corrigée en, lien osv.dev ; message
  pour les autres types, lien vers le registre), ses mises à jour possibles (options),
  ses déclarations (`dependencies` de l'`Update` : chaque fichier et ligne) ; action
  « Choisir la version » (→ écran 5, sur ce paquet).
- **Fichiers écartés** (`ignored_manifests`, replié) : la liste, et « Analyser aussi les
  dossiers de tests » (relance avec `include_tests`).
- **Remarques** (`notices`) : ce qui n'a pas pu être lu ou vérifié, par fichier.

| État | Ce qu'on voit |
|---|---|
| Vide (rien à mettre à jour) | Alerte de réussite qui dit ce qui a été vérifié (et ce qui ne l'a pas été : versions des indirectes) ; compteurs à zéro |
| Vide (aucun projet) | « Aucun fichier de dépendances dans ce dossier », les manifestes écartés s'il y en a, « Analyser aussi les dossiers de tests », « Choisir un autre dossier » |
| Chargement | Squelettes des compteurs, de la barre et du tableau |
| Erreur | `failed` (« L'analyse a échoué » et `error`), `404` (« Cette analyse n'existe plus » : le serveur garde 20 analyses le temps de sa session), `cancelled` (« Analyse annulée ») |
| Hors ligne | Alerte : données du cache, la plus ancienne du … ; « Relancer en ligne » |
| Non concluant | Compteur violet « Non concluants » cliquable ; alerte qui dit lesquels et pourquoi, « ce n'est pas à jour » ; badges violets dans le tableau |

## 5. Mise à jour

**But** : choisir, voir exactement ce qui sera écrit, appliquer, savoir ce qui s'est
passé. Page à part : [pages/mise-a-jour.md](pages/mise-a-jour.md). Maquette :
`mockups/mise-a-jour.html`.

1. **Choisir** : les `updates` des projets, groupées par lockfile (ce qui sera régénéré
   ensemble). Une carte par `Update` : case du paquet et boutons radio des `options`
   (voir MASTER, « Groupe d'options »). Pré-cochage : `selected`. « Sélection proposée »,
   « Tout décocher ». Récapitulatif (colonne de droite ; barre collante en bas sous
   1024 px) : mises à jour cochées, failles corrigées et laissées, majeures cochées (avec
   un avertissement), fichiers réécrits, lockfiles régénérés. Action principale :
   « Vérifier le plan » → `POST /api/updates/plan` avec la sélection
   (`{id de l'Update: version}`).
2. **Vérifier** : le plan (`applied`, `skipped` avec leur raison, `files` et leurs diffs,
   `lockfiles` : outil trouvé ou non, commande, mises à jour portées, avertissements,
   `reason`), le garde-fou git (`uncommitted`). Action principale « Appliquer »
   (`POST /api/updates/apply`) ; « Modifier la sélection » revient à l'étape 1.
3. **Appliquer** : `GET /api/updates/{id}/events` : manifestes réécrits (`written`), puis
   un lockfile après l'autre (`regenerating` : `name`, `done` sur `total`), la lame.
   **Pas d'annulation** : la page le dit (si un outil échoue, ses fichiers sont remis) ;
   la mise à jour continue si la page se ferme.
4. **Résultat** (`results`) : par lockfile, son statut (`regenerated`, `tool_missing` avec
   la commande à copier, `failed` avec la sortie de l'outil et les fichiers remis,
   `undone` avec le lockfile qui a échoué), chaque version obtenue (`reach` : « version
   exacte », « plus haute que choisie » (Yarn, pipenv), « retenue par … » avec
   `held_by`), « aussi changé » (`changed`), les avertissements. Actions : « Relancer
   l'analyse » (principale), « Revoir l'ancien rapport ».

Cas particuliers à montrer : option `manual` (grisée, raison), option avec `introduced`
(faille apportée, en rouge, jamais pré-cochée), `note` d'une `Update` (paquet malveillant :
pas d'option, retirer le paquet), indirecte (par le lockfile seul, avertissement « le
paquet qui la tire devra peut-être monter aussi »).

**Fichier envoyé** : étapes Choisir et Vérifier seulement ; à la place d'« Appliquer »,
« Télécharger *nom* » (`GET /api/updates/{id}/files/{nom}`) ; pas de lockfile (le dire, et
qu'il faudra relancer l'outil du projet).

| État | Ce qu'on voit |
|---|---|
| Vide | « Rien à mettre à jour » et retour au rapport |
| Chargement | « Préparation du plan… » et squelettes des diffs (le plan réécrit à blanc et relit) |
| Erreur | `409` en appliquant : fichier changé depuis le plan (« rien n'a été écrit », relancer l'analyse), plan déjà appliqué ; `400` : sélection refusée ; échec d'un outil (étape 4) |
| Garde-fou | `uncommitted` non vide : alerte, « Appliquer quand même… » (bouton risqué, dialogue de confirmation, `force: true`) ; `uncommitted` vaut `null` (hors de git) : avertissement, rien ne permettra de revenir en arrière |
| Hors ligne | À l'étape Vérifier : les outils (npm, uv…) ont besoin du réseau, ils échoueront et les fichiers seront remis |
| Non concluant | Alerte : paquets sans mise à jour faute de données ; versions proposées non vérifiées par OSV (`notices`) |

---

## 6. Comptes (E16, E19, E20)

**But** : connecter ou déconnecter GitHub, GitLab, Bitbucket ; savoir qui est connecté et
ce que l'outil peut faire.

- Une carte par forge : non connectée (« Se connecter avec GitHub », action principale ;
  repli « Coller un token », « Reprendre le compte de `gh` » s'il est connecté ; GitLab
  auto-hébergé : URL de l'instance et token) ; connectée (identifiant, nom, avatar
  s'il est servi par le serveur local, droits : « lecture seule » ou « lecture et
  PR / MR », date de connexion, « Se déconnecter » en bouton risqué avec confirmation).
- Le device flow (repli GitHub) : le code à taper, en grand, en chasse fixe, avec
  « Copier » et le lien vers github.com, et l'attente (lame indéterminée).
- Rappel : le token reste dans le trousseau de l'ordinateur, il ne va jamais au
  navigateur.

| État | Ce qu'on voit |
|---|---|
| Vide | Aucune forge connectée : les trois cartes « non connectée » |
| Chargement | Squelettes des cartes ; pendant la connexion, l'étape en cours (autorisation dans l'onglet de la forge, retour) |
| Erreur | Autorisation refusée ou expirée, `state` invalide, token refusé (`401`), droits insuffisants : alerte sur la carte, « Réessayer » |
| Hors ligne | Connexion impossible : boutons désactivés avec la raison ; les comptes connectés restent affichés |
| Non concluant | Droits du token inconnus (token « fine-grained » de GitHub sans `X-OAuth-Scopes`) : « droits non vérifiés » |

## 7. Mes dépôts (E17, E19, E20)

**But** : tous les dépôts des comptes connectés, les analyser en groupe, choisir ceux à
mettre à jour. Page à part : [pages/depots.md](pages/depots.md). Maquette :
`mockups/depots.html` (données fictives).

- Comptes en tête (forge, identifiant, droits ; « Connecter Bitbucket »).
- **Synthèse multi-dépôts** : dépôts (analysés, sautés), failles (dont critiques, dans
  combien de dépôts), à mettre à jour, à jour, non concluants, PR / MR ouvertes ; requêtes
  d'API restantes.
- Alerte pour une organisation qui restreint l'accès des applications OAuth (« Demander
  l'accès »), au lieu de cacher ses dépôts.
- Tableau : case, dépôt (`owner/nom`, privé), forge, langages, dernier push, analyse
  (chiffres, en cours avec sa lame, non concluant avec la raison, « pas encore
  analysé », « aucun fichier de dépendances »), PR / MR existante (lien). Filtres : nom,
  forge, propriétaire, état ; archivés, forks et vides masqués par défaut, avec leur
  nombre et « Les afficher ». Lecture seule (pas de droit de push) : dit, pas de PR
  possible.
- Barre d'actions de la sélection : « Analyser de nouveau », et principale « Préparer
  N PR et M MR » (→ écran 8). Un dépôt ouvre son rapport (écran 4).
- Analyse groupée : progression d'ensemble (dépôts finis sur total), par dépôt dans le
  tableau, « Annuler ».

| État | Ce qu'on voit |
|---|---|
| Vide | Aucun compte : « Connecter un compte » ; un compte sans dépôt : « Aucun dépôt accessible » |
| Chargement | Squelettes du tableau (liste paginée des forges) |
| Erreur | Token refusé (`401`) : alerte sur le compte, « Reconnecter » ; limite d'API atteinte : quand elle se lève |
| Hors ligne | La liste du dernier chargement, datée ; analyses et PR en attente du réseau |
| Non concluant | Compteur et filtre « Non concluants », alerte « à relancer » |

## 8. PR / MR (E18, E19, E20)

**But** : envoyer les mises à jour en pull requests (merge requests sur GitLab), après un
récapitulatif, et retrouver les liens.

- **Récapitulatif** : « N dépôts, M PR » ; par dépôt : la sélection (par défaut, ou
  modifiée avec l'écran 5), les fichiers touchés, les lockfiles (outil trouvé ou commande
  qui sera écrite dans la description), « met à jour la PR #41 » si elle existe déjà ou
  « nouvelle PR », la branche `forceupdate/dependencies`, la branche visée (par défaut,
  jamais poussée directement). Sautés, avec la raison : archivé, lecture seule, rien à
  faire. Action principale : « Envoyer M PR » (rien ne part sans elle).
- **Envoi** : une ligne par dépôt (clone, mise à jour, lockfiles, push, PR), la lame
  d'ensemble.
- **Résultat** : par dépôt, le lien de la PR / MR (nouvelle ou mise à jour), ou l'erreur ;
  ce qui reste à faire (commande de lockfile écrite dans la description).

| État | Ce qu'on voit |
|---|---|
| Vide | Aucun dépôt sélectionné, ou rien à mettre à jour dans la sélection : retour à l'écran 7 |
| Chargement | Préparation du récapitulatif (plans par dépôt) : squelettes |
| Erreur | Par dépôt : push refusé, branche protégée, conflit, outil en échec (fichiers non commités) ; les autres dépôts continuent |
| Hors ligne | Envoi impossible : bouton désactivé avec la raison |
| Non concluant | Dépôts à l'analyse non concluante : signalés dans le récapitulatif, décochés par défaut |

## 9. Réglages (E29)

**But** : ce qui vaut pour toutes les analyses.

- Sélection par défaut (niveau : correctifs, mineures, majeures ; failles seulement),
  par écosystème ; paquets et versions ignorés (`lodash@<5`) ; dépôts exclus ; analyser
  les dossiers de tests ; délai des outils de lockfile ; cache (taille, date, « Vider le
  cache », confirmé) ; thème.
- Formulaire en sections, étiquettes visibles, aide sous les champs, enregistrement
  explicite (« Enregistrer », puis « Enregistré ») ; ce qui vient d'un
  `forceupdate.toml` de projet est dit (il prime).

| État | Ce qu'on voit |
|---|---|
| Vide | Valeurs par défaut, dites comme telles |
| Chargement | Squelettes des sections |
| Erreur | Valeur invalide : sous le champ, focus sur le premier ; enregistrement refusé : alerte |
| Hors ligne | Rien ne change (réglages locaux) |
| Non concluant | Sans objet |

---

## Ce que l'API n'a pas encore

Relevé en concevant les écrans ; ajouté au plan (E13 ne touche pas à l'API) :

| Besoin | Écran | Où |
|---|---|---|
| Les chiffres d'une analyse finie dans la liste des analyses (`GET /api/scans` : `summary` du rapport, `null` avant la fin), pour « 28 failles » sans charger chaque rapport | 1 | E14 |
| Dire si un chemin récent est un dossier ou un fichier (`recent` : `{path, kind}`), pour son icône | 1, 2 | E14 |
| Comptes : lister, connecter (OAuth, device flow, token, `gh`), déconnecter, droits | 6 | E16 |
| Dépôts : drapeaux (archivé, fork, vide, privé, droit de push), organisations qui restreignent l'accès, requêtes restantes ; analyses groupées avec progression par dépôt et annulation ; **synthèse multi-dépôts calculée par le serveur** | 7 | E17 |
| PR : récapitulatif avant envoi (par dépôt : PR existante, sélection, lockfiles), envoi suivi, liens | 8 | E18 |
| Réglages et vidage du cache | 9 | E29 (déjà prévu) |

Rien d'autre ne manque pour les écrans 1 à 5 : la progression par projet n'existe pas
dans l'API et n'est pas nécessaire (écran 3) ; hors ligne, durées et temps écoulé se
déduisent dans le navigateur (`navigator.onLine`, `started_at`, arrivée des
événements).
