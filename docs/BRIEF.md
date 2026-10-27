# Brief — forceupdate

L'outil s'appelle **forceupdate** (« que la Force soit avec tes dépendances »). Le
dossier du projet garde son nom, `update-checker`.

## L'idée

On donne du code à l'outil. Il repère les langages utilisés, liste les
dépendances, dit lesquelles sont à mettre à jour, et sait faire ces mises à jour.
Tout se passe dans une **interface web**.

Deux sources, deux actions :

| | Analyser | Mettre à jour |
|---|---|---|
| **Local** : un dossier, ou un seul fichier | Langages, dépendances, ce qui est en retard, vulnérable ou en fin de vie | On coche les mises à jour, on voit le diff, l'outil réécrit les manifestes et régénère les lockfiles |
| **Forges** : tous les dépôts de la personne sur GitHub, GitLab et Bitbucket | La même analyse, dépôt par dépôt, sans rien cloner | Ouvre une pull request (une merge request sur GitLab) par dépôt |

D'autres sources pourront venir plus tard (archive zip, autre forge…). Elles
passeront par la même porte d'entrée (`Source`, ou `Forge` pour une forge) : le
reste de l'outil ne change pas.

## Le parcours

```
source ──► projets ──► langages + manifestes ──► dépendances ──► constats ──► rapport
(dossier,   (un dossier                          (directes,          ▲
 fichier,    avec un manifeste                    version            │
 forge)      = un projet)                         installée)    registres, OSV,
                                                                endoflife.date

mise à jour :  constats ──► sélection (cases cochées) ──► manifestes réécrits ──► lockfiles régénérés
                                                                                       │
                                                          forge : branche + commit + PR / MR
```

L'interface web et la ligne de commande pilotent le même moteur. Elles ne
contiennent pas de logique métier.

## Ce que « besoin de mise à jour » veut dire

Quatre choses différentes, qui ne s'appuient pas sur les mêmes sources :

| # | Type | Exemple | Source de données | Ce que fait la mise à jour |
|---|---|---|---|---|
| 1 | **Une version plus récente existe** | `flask 2.0.1`, dernière `3.1.x` | Le registre de chaque écosystème | Monte jusqu'à la version cochée |
| 2 | **La version utilisée a une faille connue** | `lodash 4.17.15` → CVE | OSV.dev | Monte au moins jusqu'à la version corrigée |
| 3 | **Le runtime ou le framework est en fin de vie** | Python 3.8, Node 16, Django 3.2 | endoflife.date | Runtime : signalé seulement, changer de runtime ne s'automatise pas. Framework : c'est une dépendance, sa montée passe par le type 1 |
| 4 | **Le paquet est abandonné, déprécié ou retiré** | npm `deprecated`, PyPI `yanked` | Le registre de chaque écosystème | Version retirée : remplacée par la plus proche non retirée. Paquet déprécié : signalé, le remplacer est un choix humain |

### Les trois niveaux de mise à jour

Un numéro de version se lit `MAJEUR.MINEUR.CORRECTIF`, par exemple `2.3.1` :

| Niveau | Exemple | Ce que ça change | Risque |
|---|---|---|---|
| Correctif | `2.3.1` → `2.3.4` | Des bugs corrigés | Quasi nul |
| Mineur | `2.3.1` → `2.9.0` | Des nouveautés, sans rien casser en principe | Faible |
| Majeur | `2.3.1` → `3.0.0` | Des changements qui peuvent casser le code (fonctions retirées ou renommées) | Il faut parfois adapter son code |

Dans l'interface, chaque mise à jour possible est une case à cocher. Les
correctifs, les mineures et les corrections de failles sont pré-cochés. Les
majeures sont proposées mais pas cochées, avec un avertissement. Rien n'est écrit
sans validation.

## Les sources

### Local

- **Un dossier** : parcouru en entier, en sautant `node_modules`, `.venv`, `dist`…
  et, dans un dépôt git, ce que `.gitignore` écarte (comme sur une forge).
  Un monorepo donne plusieurs projets (par exemple `backend/` en Python et
  `frontend/` en npm). Les mini-projets rangés dans des dossiers de tests ou
  d'exemples ne sont pas analysés par défaut : ils sont listés à part.
  - Un navigateur ne peut pas donner le chemin d'un dossier à une page web. C'est
    donc le serveur local de l'outil qui affiche les dossiers de l'ordinateur dans
    l'interface, pour qu'on choisisse.
- **Un fichier** :
  - un manifeste ou un lockfile : analysé seul, avec son lockfile voisin s'il y
    en a un ;
  - un fichier de code (`app.py`, `index.ts`…) : l'outil remonte les dossiers
    jusqu'au manifeste le plus proche et analyse ce projet ;
  - un fichier de code sans projet autour : analyse de ses imports, et du bloc
    PEP 723 pour un script Python. Sans version écrite nulle part, l'outil peut
    seulement dire « la dernière version est X » ;
  - un fichier glissé-déposé dans l'interface : analysé, et sa version mise à
    jour se télécharge (le navigateur ne laisse pas l'outil réécrire le fichier
    d'origine).

### Forges : GitHub, GitLab, Bitbucket

- **Connexion** : chaque personne connecte son propre compte depuis l'interface.
  Elle clique sur « Se connecter avec GitHub », GitHub lui demande si elle
  autorise l'outil, elle accepte, et elle revient dans l'outil, connectée.
  - Pour que GitHub affiche cette page, l'outil doit y être enregistré **une
    fois**, par son auteur : c'est sa « carte d'identité » auprès de GitHub (une
    OAuth App). Même chose chez GitLab et chez Bitbucket.
  - Repli : coller un token, ou reprendre celui de `gh` (GitHub CLI).
  - Le token est rangé dans le trousseau du système. Il ne quitte jamais
    l'ordinateur.
- **Périmètre** : tous les dépôts accessibles (les siens, ceux où on est
  collaborateur, ceux des organisations ou des groupes), avec des filtres. Les
  dépôts archivés et les forks sont sautés par défaut.
- **Analyse** : par l'API, sans cloner. L'arborescence du dépôt donne les
  langages et la liste des manifestes ; on ne télécharge que ces fichiers.
- **Mise à jour** : clone superficiel, même mise à jour qu'en local, puis branche
  `forceupdate/dependencies` et PR (MR sur GitLab).
  - Jamais de push sur la branche par défaut.
  - Relancer l'outil met à jour la PR déjà ouverte au lieu d'en ouvrir une autre.
- **Couverture V1** :
  - GitHub ;
  - GitLab (gitlab.com, et les instances auto-hébergées par token) ;
  - Bitbucket Cloud.

  Bitbucket Data Center (auto-hébergé) : hors V1.

## Décisions prises

Prises pour pouvoir planifier. Si l'une change : modifier ce tableau, puis les
étapes concernées de [PLAN.md](../PLAN.md).

| # | Question | Décision | Pourquoi |
|---|---|---|---|
| 1 | Quels types en V1 ? | Les quatre. Types 1 et 2 d'abord, le type 4 avec eux (même appel au registre), le type 3 à l'étape E27 | Le livrable doit dire tout ce qui est à mettre à jour |
| 2 | Quelle version compte comme « utilisée » ? | Celle du lockfile s'il y en a un ; sinon la borne basse de la contrainte, marquée « approximative » | Sans lockfile on ne connaît pas la version réelle : on le dit au lieu de deviner |
| 3 | Directes ou transitives ? | Directes pour « version plus récente ». Transitives aussi pour les failles : affichées à part, corrigées via le lockfile | Évite de noyer le signal sous des centaines de paquets |
| 4 | Quels écosystèmes ? | Les 8 de `reference/`. Python et npm d'abord, de bout en bout (analyse, mise à jour, interface, forges), puis les 6 autres | Outil utilisable tôt ; uv et npm sont installés sur la machine |
| 5 | Réseau obligatoire ? | Oui pour une vraie analyse. Cache disque ; en mode hors ligne, l'outil n'utilise que le cache et le reste sort « non concluant » | On ne connaît pas la dernière version sans demander au registre |
| 6 | Un client par registre ou une API agrégée ? | Un client par registre, derrière une interface commune. Pas de deps.dev | deps.dev ne couvre ni RubyGems ni Packagist : il faudrait des clients dédiés de toute façon |
| 7 | Sortie ? | L'interface web. Pour la ligne de commande : terminal (`rich`), JSON (le même schéma que l'API) et Markdown (sert aussi de corps de PR). `--fail-on` pour bloquer une CI | Le JSON sert à la fois au front, aux scripts et à la CI |
| 8 | Priorisation ? | Faille (par sévérité) > fin de vie > retiré > déprécié > majeur > mineur > patch | Le plus grave d'abord |
| 9 | Langage de l'outil ? | Python ≥ 3.11 (pour `tomllib`), géré avec uv | `reference/` est en Python |
| 10 | Interface ? | **Interface web en V1**, qui tourne sur l'ordinateur de la personne, pas un site en ligne : `forceupdate ui` ouvre le navigateur. Conçue avec le skill `ui-ux-pro-max`. La ligne de commande reste (`scan`, `update`) pour les scripts et la CI | **Confirmé.** Accès direct aux dossiers et aux fichiers à réécrire ; rien à héberger ; les tokens restent sur la machine. Un site en ligne serait un autre projet, bien plus gros (serveur, comptes, isolation) : l'API de E12 pourrait lui servir de base plus tard |
| 11 | Comment mettre à jour en local ? | Sélection → diff → validation. Réécriture ciblée du texte des manifestes (la mise en forme et les commentaires restent). Lockfile régénéré par l'outil natif (npm, uv…), sans jamais lancer les scripts du projet | Un diff minimal, relisible, sans surprise |
| 12 | Quelles mises à jour sont proposées par défaut ? | Correctifs, mineures et failles pré-cochés. Majeures proposées mais **jamais cochées d'office** : c'est la personne qui les coche (voir « Les trois niveaux »). En ligne de commande : `--level minor` par défaut | **Confirmé.** Une majeure peut demander d'adapter le code |
| 13 | Connexion aux forges ? | Chaque personne connecte son propre compte depuis l'interface (OAuth). L'outil est enregistré une fois auprès de chaque forge par son auteur, l'utilisateur de ce projet. Repli : token collé, ou `gh`. Tokens dans le trousseau du système | **Confirmé.** « Je lie mon compte, l'outil a accès » |
| 14 | Mettre à jour sur une forge ? | Une PR (ou MR) par dépôt, idempotente. Jamais de push sur la branche par défaut | **Confirmé.** La CI du dépôt teste la PR, un humain la fusionne |
| 15 | Analyser sur une forge ? | Par l'API, sans cloner (arborescence + manifestes). Clone superficiel seulement pour mettre à jour, ou si l'API ne donne pas l'arborescence | Rapide sur des dizaines de dépôts |
| 16 | Quelles forges en V1 ? | GitHub, GitLab (gitlab.com et auto-hébergé), Bitbucket Cloud | **Confirmé.** Demandé par l'utilisateur |
| 17 | Avec quoi faire le front ? | React + TypeScript + Vite + Tailwind + shadcn/ui. Choix confirmé à E13 avec le design system. Le front construit est livré dans le paquet Python : pas besoin de node pour utiliser l'outil | Pile que le skill connaît, proche de celle d'Argos (React, Vite, Tailwind) |
| 18 | Nom ? | `forceupdate` : nom sur PyPI, paquet Python, commande. Fichier de configuration `forceupdate.toml`, branche des PR `forceupdate/dependencies` | **Confirmé.** Choisi par l'utilisateur, en clin d'œil à Star Wars. Libre sur PyPI le 2026-10-27 ; `update-checker` était pris |
| 19 | Publication ? | Sur PyPI, gratuitement, code public : on installe avec `uv tool install forceupdate`. Une première version (0.1.0) est publiée dès que l'analyse marche (E08), pour réserver le nom | **Confirmé.** Gratuit ; le code public ne gêne pas l'utilisateur |
| 20 | Licence ? | MIT : fichier `LICENSE` à la racine, déclaré dans `pyproject.toml` (E01) | **Confirmé.** La plus simple : chacun peut utiliser, modifier et redistribuer le code, en gardant la mention de l'auteur |

## Questions encore ouvertes

Aucune pour l'instant. Une question qui surgit en route s'ajoute ici, puis passe
dans « Décisions prises » une fois tranchée.

**À faire par toi, plus tard** (la session concernée te guidera, quelques minutes
chaque fois) :

- créer un compte PyPI et y relier le dépôt GitHub, pour publier (E08 pour la
  0.1.0, puis E30) ;
- enregistrer l'outil auprès de GitHub (E16), de GitLab (E19) et de Bitbucket
  (E20).

## Pièges connus

### Versions et fichiers

- **Comparer des versions n'est pas comparer des chaînes.** Chaque écosystème a
  ses règles :
  - PEP 440 côté Python ;
  - semver côté npm ;
  - l'ordre Maven côté Java ;
  - les pseudo-versions côté Go ;
  - `Gem::Version` côté Ruby.

  `"1.10" < "1.9"` en texte.
- **Les pré-versions** (`2.0.0rc1`, `1.0.0-beta`) ne sont pas « la dernière
  version » pour la plupart des gens.
- **`go.sum`** contient aussi des versions qui ne sont plus utilisées.
- **Les lockfiles noient le signal** si on remonte toutes les transitives.
- **OSV `querybatch`** ne renvoie que les identifiants des failles (voir
  `reference/README.md`, point 3). Constaté à E08 : il arrondit leur date de
  modification à la microseconde, `vulns/{id}` la donne en nanosecondes ; une même
  faille a souvent deux avis (GitHub et PyPI) qui se citent dans leurs `aliases` ;
  un paquet malveillant peut avoir un avis `MAL-…` et des avis GitHub qui ne se
  citent pas.
- **Réécrire un manifeste sans le casser** : re-sérialiser un JSON, un TOML ou un
  XML change toute sa mise en forme et perd les commentaires. Il faut remplacer
  seulement le texte de la contrainte, à l'endroit exact où elle est écrite.
- **Garder le style de contrainte** : `^4.17.0` devient `^4.21.2`, pas `4.21.2`.
- **Un lockfile se régénère avec l'outil natif** (npm, uv, cargo…). S'il n'est pas
  installé, on ne peut que modifier le manifeste et dire quelle commande lancer.
- **Régénérer un lockfile peut exécuter du code du projet** : scripts npm,
  `Gemfile` (c'est du Ruby), `build.gradle`, `setup.py`. Toujours passer
  `--ignore-scripts` / `--no-scripts` quand l'outil le permet, et le dire quand il
  ne le permet pas.
- **Plafond de taille** : `safe_read_text` ignore les fichiers de plus de 2 Mo. Un
  `package-lock.json` les dépasse souvent : relever le plafond pour les lockfiles.
- **Go, majeur ≥ 2** : changer de majeur change le chemin du module (`/v2`) et
  tous les imports du code. Signalé, jamais appliqué automatiquement.
- **Windows** : `npm` s'appelle `npm.cmd`. Toujours passer par `shutil.which`.

### Interface web

- **Le serveur local est puissant** : il lit le disque, réécrit des fichiers et
  détient les tokens. Il faut donc :
  - écouter sur `127.0.0.1` seulement ;
  - exiger un jeton de session aléatoire (donné dans l'URL que la commande ouvre,
    puis gardé en cookie) ;
  - vérifier les en-têtes `Host` (contre le DNS rebinding) et `Origin` (contre les
    requêtes venues d'autres sites) ;
  - ne pas activer CORS.
- **Les tokens ne vont jamais au navigateur** : le front demande au serveur, et
  c'est le serveur qui parle aux forges.
- **Les analyses sont longues** (des dizaines de dépôts) : tâches de fond,
  progression en direct (Server-Sent Events), annulation possible.
- **Livrer le front** : il est construit (`npm run build`) avant de faire le paquet
  Python, et embarqué dedans. node n'est nécessaire que pour développer.

### Forges

- **Les tokens** ne doivent jamais apparaître dans les arguments d'une commande
  ni dans les logs (le `git_client.py` d'Argos sait déjà faire).
- **Le secret d'une OAuth App** embarqué dans un outil installé chez les gens
  n'est pas vraiment secret (`gh` fait pareil, c'est admis pour les applications
  installées). Préférer PKCE là où la forge l'accepte (GitLab), et le device flow
  en repli (GitHub).
- **Les organisations** GitHub peuvent restreindre l'accès des OAuth Apps : leurs
  dépôts n'apparaissent qu'après accord d'un propriétaire. Le dire dans
  l'interface au lieu de les cacher sans explication.
- **Cas à gérer** : dépôts archivés (lecture seule), vides, forks, ou sans droit
  d'écriture.
- **GitHub** :
  - 5 000 requêtes par heure avec un token ;
  - arborescence tronquée au-delà de 100 000 entrées ;
  - l'API « contents » ne renvoie pas le contenu au-delà de 1 Mo : passer par
    `Accept: application/vnd.github.raw` ;
  - l'en-tête `X-OAuth-Scopes` n'existe que pour les tokens « classic ».
- **GitLab** : les projets sont rangés dans des groupes et des sous-groupes ;
  l'arborescence est paginée ; on parle de « merge request ».
- **Bitbucket** :
  - pas d'arborescence complète en un seul appel ;
  - un seul « langage » par dépôt ;
  - les « app passwords » sont en fin de vie, remplacés par des tokens d'API (à
    revérifier).
- **PR idempotente** : relancer l'outil ne doit pas ouvrir une deuxième PR.
- **Registres** : limites de débit (crates.io : 1 requête par seconde et
  User-Agent obligatoire). Un même paquet revient dans plusieurs dépôts : cache
  partagé. Constaté à E06 :
  - PyPI : l'API Simple ne range pas les fichiers par version, il faut lire la
    version dans leur nom, qui l'écrit parfois autrement (`1.8rc1` pour `1.8c1`) ;
  - npm : `dist-tags.latest` n'est pas toujours la plus haute version ; certains
    documents sont énormes (`next` : 31 Mo) ; un paquet malveillant retiré est
    remplacé par une version `0.0.1-security`.

## Sources de données

Points d'entrée connus, **à revérifier au moment de coder** (formats et limites de
débit changent).

| Écosystème | Dernière version |
|---|---|
| PyPI | **Vérifié (E06)** : `GET https://pypi.org/simple/{nom}/` avec `Accept: application/vnd.pypi.simple.v1+json` (API Simple, PEP 691) → `versions` (PEP 700), `files[*].yanked` et `upload-time`, `project-status` (PEP 792 : archivé, déprécié, en quarantaine). La clé `releases` de `/pypi/{nom}/json` est dépréciée |
| npm | **Vérifié (E06)** : `GET https://registry.npmjs.org/{nom}` (scopé : `@scope%2Fnom`), document complet → `dist-tags`, `versions[*].deprecated`, `time` (les dates : l'abrégé ne les a pas) |
| crates.io | `GET https://crates.io/api/v1/crates/{nom}` (User-Agent exigé), ou l'index « sparse » `https://index.crates.io/…` |
| RubyGems | `GET https://rubygems.org/api/v1/versions/{nom}.json` |
| Go | `GET https://proxy.golang.org/{module}/@v/list` et `/@latest` (majuscules du chemin encodées en `!minuscule`) |
| Packagist | `GET https://repo.packagist.org/p2/{vendor}/{paquet}.json` (champ `abandoned`) |
| Maven Central | `GET https://repo1.maven.org/maven2/{groupe/en/chemin}/{artifact}/maven-metadata.xml` |
| NuGet | `GET https://api.nuget.org/v3-flatcontainer/{id-en-minuscules}/index.json` ; dépréciation via l'API « registration » |

| Besoin | Source |
|---|---|
| Failles connues, complètes | **Vérifié (E08)** : OSV, `POST https://api.osv.dev/v1/querybatch` (jusqu'à 1000 versions, les identifiants seulement, `next_page_token` par version), puis `GET https://api.osv.dev/v1/vulns/{id}` (l'avis complet : `aliases`, `severity` en vecteur CVSS, `affected[].ranges[].events`). `POST /v1/query` renvoie les avis complets, mais une version par requête |
| Fins de vie | endoflife.date : `GET https://endoflife.date/api/v1/products/{produit}` (l'ancienne forme `/api/{produit}.json` existe aussi) |

| Besoin | GitHub (`api.github.com`) | GitLab (`/api/v4`) | Bitbucket Cloud (`api.bitbucket.org/2.0`) |
|---|---|---|---|
| Connexion OAuth | `github.com/login/oauth/authorize` + `/access_token` ; device flow : `/login/device/code` | `/oauth/authorize` + `/oauth/token` (PKCE) | `bitbucket.org/site/oauth2/authorize` + `/access_token` |
| Qui est connecté | `GET /user` | `GET /user` | `GET /user` |
| Dépôts accessibles | `GET /user/repos?affiliation=owner,collaborator,organization_member` (pagination `Link`) | `GET /projects?membership=true` | `GET /repositories?role=member` (pagination `next`) |
| Langages | `GET /repos/{o}/{r}/languages` | `GET /projects/{id}/languages` | champ `language` du dépôt (un seul) |
| Arborescence | `GET /repos/{o}/{r}/git/trees/{branche}?recursive=1` | `GET /projects/{id}/repository/tree?recursive=true` (paginée) | `GET /repositories/{ws}/{r}/src/{commit}/?max_depth=…` |
| Contenu d'un fichier | `GET /repos/{o}/{r}/contents/{chemin}?ref=` | `GET /projects/{id}/repository/files/{chemin}/raw?ref=` | `GET /repositories/{ws}/{r}/src/{commit}/{chemin}` |
| PR / MR déjà ouverte | `GET /repos/{o}/{r}/pulls?head={owner}:{branche}&state=open` | `GET /projects/{id}/merge_requests?source_branch=…&state=opened` | `GET /repositories/{ws}/{r}/pullrequests?q=…` |
| Ouvrir / modifier | `POST /repos/{o}/{r}/pulls`, `PATCH …/pulls/{n}` | `POST /projects/{id}/merge_requests`, `PUT …/{iid}` | `POST /repositories/{ws}/{r}/pullrequests`, `PUT …/{id}` |
| Clone avec token | `https://x-access-token:<token>@github.com/…` | `https://oauth2:<token>@gitlab.com/…` | `https://x-token-auth:<token>@bitbucket.org/…` |

## Ce qu'on a déjà

### Dans `reference/`

Le détail est dans [reference/README.md](../reference/README.md). En bref :

- trouver et lire les fichiers de dépendances de 8 écosystèmes (19 formats) ;
- interroger OSV, avec le bug connu (pas de version corrigée) ;
- calculer un score CVSS 3.1 sans dépendance.

### Dans Argos, pas copié

À lire dans `~/Desktop/the good guy` (commit `52c714b7`) le moment venu. Ces
fichiers ne sont pas dans `reference/` : on les adapte directement dans `src/`.

| Fichier | Ce qui sert | À couper |
|---|---|---|
| `sechunter/core/repo/git_client.py` | `git clone` avec token via un credential helper éphémère (le token n'est jamais dans `argv`), pour GitHub, GitLab et Bitbucket ; masquage du token dans les messages ; diagnostic des erreurs de clone | L'anti-SSRF `target_validator` : inutile si on ne parle qu'à des forges connues |
| `sechunter/core/repo/github_app.py` | Client REST GitHub : SHA d'une branche, création branche + commit + PR (un seul fichier, via l'API) | L'authentification GitHub App (JWT, token d'installation) : on utilise un token utilisateur |
| `sechunter/core/repo/workspace.py` | Dossier de travail temporaire, nettoyé à la sortie | — |
| `sechunter/dashboard/api/routes/oauth_sso.py` | Flux OAuth GitHub en FastAPI : `state` anti-CSRF en cookie `HttpOnly`, échange du code, rien de sensible dans les logs | La création de comptes Argos et les JWT de session : on garde le token du fournisseur, dans le trousseau |
| `sechunter/dashboard/frontend/` | Front React 19 + Vite + Tailwind 4 + Vitest, servi par une API FastAPI : un exemple d'organisation | Tout le contenu propre à Argos ; il est en JavaScript, nous en TypeScript |

### Ce qui manque

- les clients des registres ;
- la comparaison de versions ;
- la fin de vie ;
- le lien direct/transitif ;
- les formats non couverts (Gradle, `.csproj`, `uv.lock`, `Gemfile`, `Pipfile`,
  Yarn 2+, pnpm récent…) ;
- tout ce qui écrit : planificateur, réécriture des manifestes, régénération des
  lockfiles ;
- l'interface web : serveur local, API, front ;
- toute la partie forges : connexion, liste des dépôts, analyse par l'API, PR et MR.
