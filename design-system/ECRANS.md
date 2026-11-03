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
| `/analyses/{id}/mise-a-jour` | 5. Mise à jour, étape Choisir (`?plan=<id>` : la sélection de ce plan ; `?paquet=<Update.id>` : le focus sur la carte de ce paquet) |
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
  `parent`), puis les dossiers, les fichiers de dépendances reconnus (`file`, icône
  `file-code` en couleur de lien) et les fichiers de code (`code`, E28 : `app.py`,
  `index.ts`… ; icône `file`, atténuée), icône et nom ; le décompte les sépare (« 1 fichier
  de dépendances, 2 fichiers de code ») ; les cachés repliés derrière « Afficher les éléments cachés »
  (`hidden`) ; filtre par nom au clavier ; « liste coupée à 5000 entrées » si `truncated`.
- Clavier : flèches pour parcourir, Entrée pour ouvrir un dossier, Retour arrière pour
  remonter ; le chemin courant est aussi un champ éditable (coller un chemin).
- Action principale : « Analyser ce dossier » (le dossier courant) ou « Analyser ce
  fichier » (un fichier choisi). Les options d'analyse, repliées, comme à l'accueil.
- Zone de dépôt et « Choisir un fichier » (`<input type="file">`) : un fichier envoyé, pas
  un chemin (son lockfile voisin n'est pas lu, il ne s'applique pas : il se télécharge
  réécrit). Un fichier de code Python, JavaScript, TypeScript ou Go s'envoie aussi (E28) : il
  est lu seul, par ses imports ou son bloc PEP 723.

| État | Ce qu'on voit |
|---|---|
| Vide | Dossier sans sous-dossier ni fichier de dépendances : « Rien à choisir ici » ; on peut quand même analyser le dossier (`find_projects` cherche en profondeur) |
| Chargement | Squelettes des lignes (un lecteur réseau lent) |
| Erreur | `400` (chemin relatif), `404` (n'existe plus), accès refusé : alerte au-dessus de la liste, le chemin reste éditable |
| Hors ligne | Rien ne change (lister ne demande pas de réseau) ; l'option « Hors ligne » est cochée |
| Non concluant | Sans objet (rien n'est vérifié ici) |

**Fait à la session 36** (les essais de l'utilisateur : « le bouton Ouvrir n'ouvre pas
l'explorateur ») : à droite du champ « Dossier ouvert », « Aller » (bouton discret, flèche : suit le
chemin collé, l'ancien « Ouvrir ») et « Parcourir… » (secondaire, `folder-search`), qui demande au
serveur la fenêtre de choix du système (`POST /api/fs/pick`) : le dossier choisi s'ouvre dans la
liste ; un fichier, dans son dossier, choisi. Pendant que la fenêtre est ouverte : le bouton
tourne, et « La fenêtre de choix … est ouverte : elle peut se trouver derrière le navigateur »
(`role=status`) ; sans fenêtre possible, la raison sous le champ (`role=alert`).

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

- En tête : nom et chemin de la source ; pour un fichier de code (`code`, E28), comment il est
  lu, icône `file-code` : « analysé via `pyproject.toml` (dans …), le premier manifeste Python
  au-dessus de lui », « son bloc `# /// script` tient lieu de manifeste », ou « sans projet
  autour : ses imports, sans version » ; date et durée, données des registres
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
  - Version non fixée (`unpinned`, E28) : utilisée « non fixée » (« un import, sans
    version »), contrainte « aucune : un import » et l'import (`import dateutil`), badge
    info `pin-off` « non fixée · dernière 4.0.0 ». Une alerte info « N versions non fixées »
    dit que les failles ne sont pas vérifiables sans version, avec « Voir les versions non
    fixées » ; jamais l'alerte « Rien à mettre à jour ».
- **Détail d'une dépendance** (panneau latéral) : versions (utilisée et d'où, contrainte et
  où, acceptée par la contrainte `wanted_version`, dernière), tous ses constats (gravité,
  identifiants, CVSS, titre de l'avis en anglais, corrigée en, lien osv.dev ; message
  pour les autres types, lien vers le registre), ses mises à jour possibles (options),
  ses déclarations (`dependencies` de l'`Update` : chaque fichier et ligne) ; action
  « Choisir la version » (→ écran 5, sur ce paquet).
- **Fichiers écartés** (`ignored_manifests`, replié) : la liste, et « Analyser aussi les
  dossiers de tests » (relance avec `include_tests`).
- **Remarques** (`notices`) : ce qui n'a pas pu être lu ou vérifié, par fichier ; en tête,
  celles sur la source (`Report.notices`, E30 : liste coupée, sous-module git non
  initialisé), dont le dossier racine (`.`) se dit « Le dossier analysé ». Elles font aussi
  une alerte d'avertissement en haut, « Analyse partielle : la source n'a pas été lue en
  entier » (comme une arborescence tronquée par une forge) : ce n'est pas « à jour ».

| État | Ce qu'on voit |
|---|---|
| Vide (rien à mettre à jour) | Alerte de réussite qui dit ce qui a été vérifié (et ce qui ne l'a pas été : versions des indirectes) ; compteurs à zéro |
| Vide (aucun projet) | « Aucun fichier de dépendances dans ce dossier », les manifestes écartés s'il y en a, « Analyser aussi les dossiers de tests », « Choisir un autre dossier » |
| Chargement | Squelettes des compteurs, de la barre et du tableau |
| Erreur | `failed` (« L'analyse a échoué » et `error`), `404` (« Cette analyse n'existe plus » : le serveur garde 20 analyses le temps de sa session), `cancelled` (« Analyse annulée ») |
| Hors ligne | Alerte : données du cache, la plus ancienne du … ; « Relancer en ligne » |
| Non concluant | Compteur violet « Non concluants » cliquable ; alerte qui dit lesquels et pourquoi, « ce n'est pas à jour » ; badges violets dans le tableau |

**Fait à la session 36** : sous les options en badges, le groupe « Télécharger » (icône
`download`, trois liens discrets) : « Le rapport (Markdown) », « Le rapport (JSON) », « Les
dépendances à mettre à jour (CSV) » (`GET /api/scans/{id}/download?format=`, le serveur nomme le
fichier).

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
   `held_by`), « aussi changé » (`changed` : « dans le lockfile », « dans go.mod » pour Go,
   dont les versions se relisent là), les avertissements. Actions : « Relancer
   l'analyse » (principale), « Revoir l'ancien rapport ».

Cas particuliers à montrer : option `manual` (grisée, raison), option avec `introduced`
(faille apportée, en rouge, jamais pré-cochée), `note` d'une `Update` (paquet malveillant :
pas d'option, retirer le paquet), indirecte (par le lockfile seul, avertissement « le
paquet qui la tire devra peut-être monter aussi » ; une indirecte Go se réécrit dans
`go.mod`), majeure Go publiée sous un autre module (`manual` : la commande `go get` et les
imports à changer). **Session 37** : une indirecte que son parent retiendra (`held_by`,
d'après les plages d'un `package-lock.json`) : l'avertissement le nomme (« nodemon 3.1.14
demande ^10.2.1 : le lockfile seul ne la fera pas monter ; monter nodemon d'abord. »), la
phrase des failles devient « Corrigerait 2 failles, mais nodemon 3.1.14 la retiendra »,
jamais pré-cochée, pas comptée dans « failles corrigées » du récapitulatif.

**Résultat, session 37** : une majeure que l'outil de lockfile refuse est retirée et le reste
se fait (`results[].dropped`) : l'alerte d'en tête devient un avertissement « Appliquée, sauf
une majeure que l'outil de lockfile refuse » (les noms, monter d'abord le paquet qui bloque),
et la carte du lockfile a une ligne par majeure retirée, badge « pas faite : uv la refuse »
(danger), la raison de l'outil en chasse fixe dessous (`lang="en"`).

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

**Fait à E16** (GitHub ; GitLab et Bitbucket en cartes « Bientôt ») :

- adresse `/comptes` ; `/comptes?connexion=<id>` au retour d'une autorisation OAuth, dont la
  carte montre l'issue ;
- non connectée : « Se connecter avec GitHub », puis « Autres façons de se connecter » :
  avec un code (device flow), avec GitHub CLI (seulement si `gh` est installé), token collé
  (lien « Créer un token sur github.com », portées pré-cochées) ;
- les droits sont relus auprès de la forge une fois à l'ouverture de l'écran (« Vérifié :
  maintenant ») et par « Vérifier les droits » : un token révoqué sur github.com se voit
  aussitôt (alerte, « Se reconnecter ») ; forge injoignable : « Droits non revérifiés », le
  compte reste ;
- pas d'avatar (il viendrait de github.com, refusé par la CSP ; le servir par le serveur
  local n'apportait rien) ;
- états : chargement (squelettes), erreur (« Comptes indisponibles », « Réessayer »),
  trousseau indisponible (alerte, connexions désactivées), hors ligne (connexions
  désactivées avec la raison), connexion refusée, expirée, annulée.
- l'accueil (écran 1) : la carte « Mes dépôts » montre les comptes connectés (logo, forge,
  `@identifiant`) et « Gérer les comptes ».

**Fait à E19** (GitLab ; Bitbucket reste « Bientôt ») :

- la carte GitLab est une carte de forge comme celle de GitHub : « Se connecter avec GitLab »
  (OAuth avec PKCE, action principale), puis le token collé (« Un token d'accès personnel avec
  la portée api », « Créer un token sur gitlab.com », nom et portée pré-remplis) ; pas de code
  ni de `gh` ; droits « Lecture et MR » ; un token refusé sans OAuth possible dit « Se
  déconnecter, puis coller un nouveau token » ;
- dans la carte GitLab, un groupe « Instances auto-hébergées » : chaque instance connectée
  (son hôte en titre `h4`, « Connecté », ses droits relus à l'ouverture, « Vérifier les
  droits », « Se déconnecter… » confirmé), puis le formulaire « Adresse de l'instance »
  (`type="url"`, https seulement) et « Token de l'instance », le lien « Créer un token sur
  <hôte> » apparaissant quand l'adresse est lisible, « Connecter l'instance » ;
- chaque carte ne suit que les connexions de sa forge (le retour d'OAuth `?connexion=` est
  donné à toutes) ; l'intro dit « y ouvrir des PR (des MR sur GitLab) » ; l'accueil montre
  aussi les comptes des instances (« GitLab (hôte) »).

**Fait à E20** (Bitbucket) :

- la carte Bitbucket est une carte de forge comme les autres (plus aucune carte « Bientôt ») :
  « Se connecter avec Bitbucket » (OAuth, action principale), puis le token collé : « Un token
  d'API Atlassian avec les portées » et ses six portées en chasse fixe, la précision « Create API
  token with scopes, application Bitbucket ; les app passwords ne marchent plus », le lien
  « Créer un token sur id.atlassian.com » ; pas de code, ni de `gh`, ni d'instance ; droits
  « Lecture et PR » ; un token d'API : « Droits non vérifiés », portées « non données par la
  forge (token d'API Atlassian) » ;
- **la déconnexion ne révoque pas** (Bitbucket ne le permet pas par son API) : la confirmation
  le dit (« Bitbucket ne permet pas de le révoquer d'ici : retirer ensuite l'accès de forceupdate
  dans ses réglages »), l'issue est un avertissement avec le lien « Retirer l'accès sur
  bitbucket.org » (bouton principal, nouvel onglet) ;
- le serveur dit, par forge, si un token se révoque (`revocable`), où retirer l'accès
  (`applications_url`) et les portées d'un token collé (`token_scopes`) : rien n'est écrit en dur
  dans le front pour une forge, sauf le début de la phrase d'aide de son token.

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

**Fait à E17** (GitHub ; `frontend/src/screens/repositories/`) :

- adresse `/depots` ; un dépôt ouvre son rapport (`/analyses/{id}`, écran 4 : fil d'Ariane
  « Mes dépôts », commit lu, « Voir sur GitHub », alerte d'arborescence tronquée ; pas de
  « Mettre à jour » avant les PR) ; l'écran 3 a une étape « Téléchargement des fichiers de
  dépendances » ;
- en tête : « Comptes », « Recharger la liste », « Analyser tous les dépôts » (ceux qui ne sont
  pas masqués) ; les comptes en pastilles ; les alertes : token refusé (« Reconnecter GitHub »),
  liste non rechargée (datée), organisation restreinte (« Demander l'accès sur GitHub ») ou
  exigeant le SSO, dépôts non concluants (« Relancer ces N dépôts », « Les voir ») ;
- synthèse du serveur : Dépôts (analysés, sautés), Failles (dont critiques, dans combien de
  dépôts ; « analyse en cours » tant qu'un dépôt tourne), À mettre à jour, À jour, Non
  concluants ; les quatre derniers filtrent le tableau ; requêtes d'API restantes (en
  avertissement sous 10 %) ;
- analyse groupée : sa carte (dépôts finis sur total, lame, 4 à la fois, requêtes utilisées,
  « Annuler »), puis son issue (terminée, annulée, échouées, vides sautés) ;
- tableau : case, dépôt (`owner/` atténué, cadenas « privé », lien vers la forge, badges
  archivé, fork, vide), forge, langages (trois au plus), dernier push (relatif, triable),
  analyse (chiffres en badges, « lecture seule », progression du téléchargement puis des
  vérifications, « en attente de son tour » sans lame, non concluant et sa raison, aucun
  fichier de dépendances, pas encore analysé, sauté et pourquoi) ; filtres nom,
  propriétaire, état (dont « Avec des failles »), forge s'il y en a plusieurs ; masqués
  comptés, « Les afficher » ; cartes sous 768 px ;
- barre de sélection : « N dépôts sélectionnés · M mises à jour cochées par défaut », « Tout
  désélectionner », « Analyser ces N dépôts » (principale, en attendant les PR de E18) ;
- « Analyser un autre dépôt » : un dépôt public, par `owner/nom` ou son adresse (aussi sans
  compte connecté) ;
- états : chargement (squelettes), erreur (« Dépôts indisponibles », « Réessayer »), sans
  compte (« Connecter un compte », et le champ du dépôt public), compte sans dépôt, hors
  ligne (bandeau, analyses désactivées avec la raison), filtres sans résultat.
- GitLab et Bitbucket : faits à E19 et E20 (ci-dessous).

**Fait à E18** : la colonne « PR » (`#41`, lien vers la forge, nouvel onglet ; « pas de droit de
push » pour un dépôt en lecture seule ; « — » sinon), sous 768 px une ligne « PR » de la carte ;
le compteur « PR ouvertes » de la synthèse (du serveur, `open_requests` ; il ne filtre pas) ; la
barre de sélection : « Préparer N PR » en action principale, « Analyser ces N dépôts » en
secondaire, hors ligne les deux désactivés avec la raison ; une arborescence tronquée est
analysée sur un clone (étape « Clone superficiel » de l'écran 3, « cloné » dans l'en-tête du
rapport) ; le rapport d'un dépôt a « Préparer la PR » (vers l'écran 5 pour ce dépôt), et le
panneau de détail son lien « Choisir la version ».

**Fait à E19** : les dépôts de tous les comptes (GitHub, gitlab.com, instances) dans la même
liste ; la forge dite « GitLab (hôte) » pour une instance (colonne, cartes, pastilles des
comptes, requêtes restantes) ; la colonne « PR / MR » (le nom d'après les forges listées ;
`!12` sur GitLab, nommé « MR !12 de groupe/app sur GitLab ») ; le compteur « PR et MR
ouvertes » ; la barre de sélection « Préparer 1 PR et 1 MR » (un seul récapitulatif, toutes
forges confondues), « Préparer la MR » pour un projet GitLab ; les badges « lecture et MR » ;
un même `owner/nom` sur deux forges : le nom accessible de sa case et de son lien dit la forge
(« Sélectionner octo/app (GitLab) ») ; les projets en sous-groupes gardent leur chemin
complet (`groupe/sous-groupe/` atténué). Le rapport d'un projet GitLab dit « Préparer la
MR », « Voir sur GitLab ».

**Fait à E20** : les dépôts Bitbucket dans la même liste, sans changement de fond (« Bitbucket »
dans la colonne Forge et le filtre, `#3` dans la colonne PR, nommé « PR #3 de espace/app sur
Bitbucket ») ; Bitbucket ne dit pas les requêtes restantes : pas de ligne pour lui ; le rapport
d'un dépôt Bitbucket dit « dépôt Bitbucket, lu par l'API sans le cloner », « Voir sur
Bitbucket », et une arborescence tronquée « trop de fichiers, ou de dossiers imbriqués ».

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
| PR refusée | La dernière PR de forceupdate fermée sans fusion : signalée (badge d'avertissement, date, lien), décochée par défaut (E31) |

**Fait à E18** (GitHub ; `frontend/src/screens/proposals/`) :

- adresses : `/pr?forge=github&depots=owner/a,owner/b` (depuis l'écran 7) prépare le
  récapitulatif, puis `/pr/{id}` le montre (le retour du navigateur ne le refait pas) ; sans
  dépôt, l'état vide renvoie à l'écran 7 ; un récapitulatif oublié (serveur redémarré) le dit ;
- l'écran 5 sait choisir pour un dépôt (`/analyses/{id}/mise-a-jour`, « Préparer la PR » au lieu
  de « Vérifier le plan ») ; « Modifier la sélection » d'un récapitulatif y mène avec `?pr=<id>`,
  et le nouveau récapitulatif garde les autres dépôts ;
- récapitulatif : « N dépôts, M PR à envoyer (dont K déjà ouvertes, mises à jour) » ; par dépôt
  prêt : la case, PR existante ou nouvelle, la branche et la branche visée, le commit analysé, les
  mises à jour (versions, écart, failles corrigées), les options qui ne seront pas appliquées, les
  diffs (repliés), les lockfiles (outil trouvé, ou commande écrite dans la description),
  « Modifier la sélection », « Voir le rapport » ; les sautés et pourquoi ; « Envoyer N PR »
  (désactivé sans case cochée, ou hors ligne, avec la raison) ;
- envoi suivi (relu chaque seconde) : un dépôt à la fois, l'étape en cours (clone, réécriture et
  lockfile en cours, push, PR) ; résultat : « 1 PR ouverte · 1 mise à jour · 1 en échec », le lien
  de chaque PR, « elle avait déjà ces changements, rien n'est poussé », l'erreur d'un dépôt, les
  lockfiles à reprendre, « Retour à mes dépôts ».
- **Fait à E19** : « MR » et `!12` pour GitLab ; **un récapitulatif peut mêler les forges** :
  l'adresse devient `/pr?depots=github:github.com/owner/a,gitlab:gitlab.com/groupe/sous/b`
  (forge, hôte du compte, chemin) ; le titre dit « Préparer les PR et MR » (ou « les MR »),
  le bouton « Envoyer 1 PR et 1 MR », le résultat « 1 PR ouverte · 1 MR ouverte » ; quand le
  récapitulatif mêle plusieurs comptes, chaque carte dit sa forge (logo et nom) ; la liste des
  sautés aussi, toujours ; un compte dont le token est refusé à l'envoi : ses dépôts en échec,
  et une alerte « Un compte refuse son token » qui mène à « Comptes ». L'écran 5 d'un projet
  GitLab dit « Préparer la MR de … ».
- **Fait à E20** : Bitbucket sans changement de fond : « PR » et `#1`, « met à jour la PR #1 »,
  « Voir la PR #1 sur Bitbucket » ; sa forge dite sur la carte quand le récapitulatif mêle les
  comptes.
- **Fait à E31** : la dernière PR de forceupdate d'un dépôt **fermée sans fusion** (et aucune
  ouverte) : sur sa carte, à côté de « nouvelle PR », le badge d'avertissement « PR #3 fermée sans
  fusion » (`triangle-alert`), et la phrase « La PR #3 a été fermée sans fusion le 30 oct. 2026 :
  l'envoyer en ouvre une nouvelle. Pas cochée par défaut. », puis sur sa propre ligne le lien
  « Voir la PR #3 sur GitHub » (dans la phrase, il ne se distinguait que par sa couleur : axe-core,
  `link-in-text-block`) ; le dépôt est prêt mais décoché, comme une analyse non concluante. Un envoi
  interrompu par l'arrêt du serveur : « Interrompu : forceupdate s'est arrêté. Relancer l'envoi ;
  une branche déjà poussée sera reprise. » (l'erreur du dépôt, si le navigateur relit le
  récapitulatif avant la fin de l'arrêt ; la console le dit toujours, les récapitulatifs ne
  survivent pas au serveur).
- **Fait à la session 36** (les essais de l'utilisateur, sur son dépôt `mew`) : un dépôt où rien
  n'est poussé parce que l'outil de lockfile a gardé les versions choisies (des indirectes que
  leur parent ne laisse pas monter) ne dit plus « rien à faire » : l'icône `triangle-alert`
  (avertissement), « aucune mise à jour n'a pu se faire : d'autres paquets retiennent les
  versions choisies ; rien n'est poussé », la liste « Mises à jour retenues » (une ligne par
  paquet, comme les options non appliquées : « minimatch 10.2.6, pas 11.0.1 (backend) : retenue
  par nodemon 3.1.14 ») et une phrase sur quoi faire ; le total dit « 1 dépôt aux mises à jour
  retenues ». Une version retenue dans une PR qui part est listée de même.
- **Fait à la session 37** : une ligne par paquet retenu (deux `minimatch` installées, deux mises
  à jour : une ligne, leurs versions et leurs parents réunis) ; « Majeures refusées » : une
  majeure que l'outil de lockfile refusait, retirée pour que le reste parte (`triangle-alert`,
  « typescript 7.0.2 (frontend) : pas faite, l'outil de frontend/package-lock.json la refuse : »
  puis la raison de l'outil, et quoi faire) ; « En route » : ce qu'a dit l'outil d'un lockfile
  régénéré (`info`, « npm refusait le lockfile qu'il venait d'écrire … refait par … », que seule
  la description de la PR disait). Au récapitulatif, une indirecte que son parent retiendra dit
  « retenue par nodemon 3.1.14 : monter ce paquet d'abord » à la place de ses failles, qui ne
  sont pas comptées. Un résultat avec des dépôts en échec : l'icône du titre dit l'échec (`circle-x` rouge si
  tous, `triangle-alert` sinon), et « Renvoyer le dépôt en échec » (principale ; « Retour à mes
  dépôts » devient secondaire) les renvoie avec la même sélection (`POST /send` d'un
  récapitulatif fini : seulement ses dépôts en échec) ; hors ligne, désactivé avec la raison. Un
  dépôt sauté pour « aucune mise à jour cochée » a, dans « Sautés », le lien « choisir les mises à
  jour » (vers l'écran 5 de son analyse, `?pr=<id>`).

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

- **Fait à E29** (`frontend/src/screens/settings/`, `GET` et `PUT /api/settings`,
  `DELETE /api/cache`) : un formulaire, six sections titrées (`h2`) :
  - *Sélection par défaut* : trois boutons radio (« Correctifs », « Correctifs et mineures
    (par défaut) », « Correctifs, mineures et majeures », chacun avec son exemple en chasse fixe),
    l'interrupteur « Seulement les corrections de failles » ; replié, « Régler un écosystème à
    part » : une ligne par écosystème (« Python (PyPI) »…), deux listes déroulantes (« Comme les
    autres » par défaut), dépliée d'office s'il y en a un de réglé ;
  - *Paquets et versions ignorés*, *Dépôts exclus* : une zone de texte en chasse fixe, une valeur
    par ligne, l'aide avec des exemples ; une valeur refusée par le serveur se dit sous le champ
    avec sa ligne (« Ligne 3 : … »), le focus va au premier champ refusé ;
  - *Analyse* : « dossiers de tests et d'exemples » (l'option d'analyse de l'accueil et de
    l'écran 2 la suit tant qu'on n'y a pas touché) ;
  - *Outils* : les deux délais (champs numériques, en secondes), l'interrupteur Rust ;
  - en bas, « Enregistrer » (l'action principale), « Valeurs par défaut » (discret : remplit le
    formulaire, sans enregistrer), l'état (« Modifications non enregistrées. », puis
    « Enregistré : … », `role="status"`), le chemin du fichier ; un refus : une alerte au-dessus
    du bouton.
  Hors du formulaire : *Cache* (une carte : contenu, dates, fichier ; « Vider le cache… »,
  contour rouge, confirmé par un `<dialog>` natif, désactivé pour un cache vide) et *Thème*
  (trois boutons radio, appliqué tout de suite, gardé dans le navigateur comme le bouton de
  l'en-tête). Des réglages en partie illisibles : un avertissement en tête.
- **Le rapport (écran 4) le dit aussi** : sous la source, « Configuration du projet :
  `forceupdate.toml` : ignorés : … ; dossiers exclus : … ; sélection par défaut réglée. », un
  avertissement pour ses valeurs écartées, et « Réglages : ignorés : … » (lien vers l'écran 9)
  quand les réglages de la personne ont joué. Un paquet ignoré a sa remarque dans « Remarques ».

---

## Ce que l'API n'a pas encore

Relevé en concevant les écrans ; ajouté au plan (E13 ne touche pas à l'API) :

| Besoin | Écran | Où |
|---|---|---|
| Les chiffres d'une analyse finie dans la liste des analyses (`GET /api/scans` : `summary` du rapport, `null` avant la fin), pour « 28 failles » sans charger chaque rapport | 1 | fait (E14) |
| Dire si un chemin récent est un dossier ou un fichier (`recent` : `{path, kind}`), pour son icône | 1, 2 | fait (E14) |
| La répartition par gravité des failles (« 13 élevées · 14 moyennes ») et de tous les constats (la barre), sans recompter dans le navigateur (`summary.vulnerabilities`, `summary.severities`) | 4 | fait (E14) |
| Comptes : lister, connecter (OAuth, device flow, token, `gh`), déconnecter, droits | 6 | fait (E16) |
| Dépôts : drapeaux (archivé, fork, vide, privé, droit de push), organisations qui restreignent l'accès, requêtes restantes ; analyses groupées avec progression par dépôt et annulation ; **synthèse multi-dépôts calculée par le serveur** | 7 | fait (E17) ; les PR ouvertes : fait (E18) |
| PR : récapitulatif avant envoi (par dépôt : PR existante, sélection, lockfiles), envoi suivi, liens | 8 | fait (E18) |
| Réglages et vidage du cache | 9 | fait (E29) |

Rien d'autre ne manque pour les écrans 1 à 5 : la progression par projet n'existe pas
dans l'API et n'est pas nécessaire (écran 3) ; hors ligne, durées et temps écoulé se
déduisent dans le navigateur (`navigator.onLine`, `started_at`, arrivée des
événements).
