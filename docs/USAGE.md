# Utiliser forceupdate

Le mode d'emploi complet : l'installation, l'interface écran par écran, la ligne de commande et
toutes ses options, la configuration, ce que forceupdate lit et fait pour chaque écosystème, et
ses limites. Les forges (GitHub, GitLab, Bitbucket) ont leur page :
[FORGES.md](FORGES.md). Le format du rapport JSON : [JSON_FORMAT.md](JSON_FORMAT.md).

- [Installer](#installer)
- [L'interface](#linterface)
- [La ligne de commande](#la-ligne-de-commande)
- [Lire un rapport](#lire-un-rapport)
- [Configuration](#configuration)
- [Les écosystèmes](#les-écosystèmes)
- [Particularités de la mise à jour](#particularités-de-la-mise-à-jour)
- [Fins de vie et runtimes](#fins-de-vie-et-runtimes)
- [Un fichier de code](#un-fichier-de-code)
- [Registres et dépôts privés](#registres-et-dépôts-privés)
- [Réseau d'entreprise](#réseau-dentreprise)
- [Robustesse](#robustesse)

## Installer

```bash
uv tool install forceupdate        # ou : pipx install forceupdate
uv tool upgrade forceupdate        # la dernière version
uv tool uninstall forceupdate
```

Python 3.11 ou plus récent (uv l'installe s'il manque) ; Windows, Linux ou macOS. L'interface
est dans le paquet : node ne sert qu'à développer forceupdate, pas à s'en servir. La 1.0.0rc1
est une pré-version : `uv tool install forceupdate==1.0.0rc1` tant que la 1.0.0 n'est pas
publiée.

À installer selon l'usage :

- **git** : pour ouvrir des PR, et pour le garde-fou de la mise à jour locale (sans git, rien
  ne permet de revenir en arrière, et forceupdate le dit) ;
- **l'outil de chaque lockfile** à régénérer : npm (et pnpm, Yarn), uv, Poetry, PDM, pipenv,
  pip-compile, cargo, go, Composer, Bundler, le SDK .NET. Sans lui, les manifestes sont quand
  même réécrits, et forceupdate donne la commande à lancer.

### Où forceupdate range ses données

| Quoi | Windows | Linux | macOS |
|---|---|---|---|
| Le cache des registres, d'OSV et d'endoflife.date (`cache.sqlite3`) | `%LOCALAPPDATA%\forceupdate\Cache` | `~/.cache/forceupdate` | `~/Library/Caches/forceupdate` |
| Les réglages (`forceupdate.toml`, l'écran Réglages) | `%LOCALAPPDATA%\forceupdate` | `~/.config/forceupdate` | `~/Library/Application Support/forceupdate` |
| Les chemins récents et les comptes connectés, sans leur token (`recent.json`, `accounts.json`) | `%LOCALAPPDATA%\forceupdate` | `~/.local/state/forceupdate` | `~/Library/Application Support/forceupdate` |
| Les tokens des forges | le trousseau du système (Gestionnaire d'identification de Windows, Secret Service, Trousseau de macOS) | | |
| Le dossier de travail de `forceupdate ui` (fichiers des dépôts, clones des PR) | `forceupdate-ui-*` dans le dossier temporaire, effacé à l'arrêt | | |

Le cache garde les versions d'un paquet 1 heure, les avis d'OSV 7 jours, les fins de vie
24 heures ; hors ligne (`--offline`), il sert même périmé. « Vider le cache » (écran
Réglages) ou `--no-cache` pour s'en passer.

## L'interface

```bash
forceupdate ui                           # un port libre, et le navigateur s'ouvre
forceupdate ui --port 8765 --no-browser  # l'adresse seulement
```

Le serveur n'écoute que sur `127.0.0.1`. L'adresse affichée porte un jeton de session : en
l'ouvrant, le navigateur reçoit un cookie, puis l'adresse se recharge sans le jeton. Sans ce
jeton, le serveur ne répond pas : une autre page ouverte dans le navigateur, ou un autre
programme de l'ordinateur, ne peut pas s'en servir. Le jeton change à chaque démarrage : après
un redémarrage, l'interface le dit (« Session terminée ») ; rouvrir l'adresse affichée. Ctrl+C
arrête le serveur ; une mise à jour en cours est alors remise comme avant (voir
[Robustesse](#robustesse)).

Les analyses ne vivent que le temps de la session (le serveur en garde 20) ; les chemins
récents restent d'une session à l'autre. Le thème (clair, sombre, celui du système) se choisit
dans l'en-tête ; tout est utilisable au clavier.

### 1. Accueil

Trois cartes : **un dossier** (« Choisir un dossier »), **un fichier** (« Choisir un fichier »,
ou le déposer n'importe où sur la page), **mes dépôts** (« Connecter un compte », puis le nombre
de comptes et de dépôts). Plus bas, un champ pour coller un chemin absolu et « Analyser », les
**options d'analyse** (repliées : dépendances de dev, versions des indirectes, dossiers de tests
et d'exemples, hors ligne, sans cache ; les mêmes valeurs par défaut que `scan`), et les
**analyses récentes** : celles de la session (ouvrir, suivre, relancer) et les chemins
récents (un clic relance l'analyse).

### 2. Choisir un dossier ou un fichier

Le navigateur ne peut pas donner un chemin à une page : c'est le serveur qui liste les dossiers
(les noms seulement, sans suivre les liens ni les jonctions). Départ : le dossier personnel,
les lecteurs, les dossiers récents. Chaque dossier montre ses sous-dossiers, ses fichiers de
dépendances et ses fichiers de code ; les éléments cachés sont repliés ; un filtre par nom ; au
clavier : flèches, Entrée pour ouvrir, Retour arrière pour remonter. « Analyser ce dossier » ou
« Analyser ce fichier ».

Un fichier **déposé** ou choisi par « Choisir un fichier » est envoyé au serveur, pas désigné
par son chemin : il est analysé seul (sans son lockfile voisin), et sa version mise à jour se
**télécharge** au lieu de s'écrire.

### 3. Analyse en cours

Les étapes (lecture des fichiers, téléchargement pour un dépôt, projets trouvés, vérification
des paquets avec le paquet en cours, failles), la barre de progression, le temps écoulé.
« Annuler » arrête l'analyse.

### 4. Rapport

- **En tête** : la source, la date, les options ; « Relancer l'analyse » ; « Mettre à jour »
  avec le nombre de mises à jour cochées d'office. Pour un fichier de code, comment il a été lu
  (via quel manifeste, son bloc PEP 723, ou ses imports). La configuration du projet et les
  réglages qui ont joué sont dits sous la source.
- **Synthèse** : un compteur par type de constat (failles, plus récentes, fins de vie,
  retirées, dépréciées, versions non fixées, non vérifiables, non concluants), la répartition
  des gravités, ce qui a été vérifié et audité. Un compteur filtre le tableau.
- **Langages** et **projets** (dossier, écosystèmes, manifestes, lockfiles, runtimes).
- **Dépendances** : le tableau, filtrable (nom, directes ou indirectes, écosystème, type de
  constat, projet) et triable (gravité par défaut). Chaque ligne : la version utilisée, la
  contrainte et où elle est écrite, les constats, la mise à jour proposée. Une ligne ouvre le
  **détail** : les versions (utilisée, acceptée par la contrainte, dernière), chaque constat
  (identifiants, CVSS, version corrigée, lien vers l'avis), les mises à jour possibles,
  « Choisir la version ».
- **Fins de vie** : le runtime ou le framework, sa date, d'où la version est lue, le cycle
  conseillé.
- **Fichiers écartés** (les manifestes des dossiers de tests et d'exemples) et **Remarques** :
  ce qui n'a pas pu être lu ou vérifié, fichier par fichier. Une source lue en partie (liste
  coupée, sous-module non initialisé, arborescence tronquée d'une forge) fait l'alerte
  « Analyse partielle » : ce n'est pas « à jour ».

### 5. Mise à jour

1. **Choisir** : une carte par paquet, groupées par lockfile (ce qui sera régénéré ensemble).
   Pour chaque paquet, ses options (dernier correctif, dernière mineure, dernière majeure,
   correction des failles, remplacement), ce que chacune corrige et touche. Correctifs,
   mineures et corrections de failles sont cochés d'office (la version qui corrige le plus,
   puis la plus récente), sans passer une majeure tant que la sélection réglée ne le permet
   pas ([Configuration](#configuration)) ; une version
   qui apporterait une faille est en rouge et jamais cochée d'office ; une option « à la main »
   est grisée, avec sa raison. « Sélection proposée », « Tout décocher ». Le récapitulatif (à
   droite, ou en bas sur un petit écran) compte les mises à jour, les failles corrigées et
   laissées, les fichiers réécrits, les lockfiles régénérés. « Vérifier le plan ».
2. **Vérifier** : rien n'est encore écrit. Le diff de chaque fichier, les mises à jour qui ne
   seront pas faites et pourquoi, chaque lockfile (outil trouvé, ou la commande à lancer à la
   main ; ce que l'outil exécute quand même), les cases proposées en plus (le npm du projet,
   `go mod vendor` : voir [Particularités](#particularités-de-la-mise-à-jour)), et le
   garde-fou git : un fichier visé qui a des changements pas commités bloque « Appliquer »
   (« Appliquer quand même… » demande une confirmation) ; hors d'un dépôt git, un
   avertissement. Un fichier déposé : « Télécharger » à la place d'« Appliquer ».
3. **Appliquer** : les manifestes réécrits, puis chaque lockfile, l'un après l'autre. Pas
   d'annulation : un outil qui échoue fait remettre ses fichiers. Fermer la page n'arrête rien.
4. **Résultat** : par lockfile, régénéré (avec chaque version obtenue : exacte, plus haute que
   choisie, ou retenue par un autre paquet), outil absent (la commande à copier), en échec (la
   sortie de l'outil, les fichiers remis) ; ce qui a changé d'autre dans le lockfile.
   « Relancer l'analyse ».

### 6. Comptes, 7. Mes dépôts, 8. PR / MR

Connecter GitHub, GitLab ou Bitbucket, analyser tous ses dépôts sans les cloner, puis ouvrir
une PR (une MR sur GitLab) par dépôt : tout est dans [FORGES.md](FORGES.md).

### 9. Réglages

Ce qui vaut pour toutes les analyses, écrit dans le fichier des réglages
(`forceupdate.toml`, voir [Configuration](#configuration)) : la sélection par défaut (niveau,
failles seulement, par écosystème), les paquets et versions ignorés, les dépôts exclus,
l'analyse des dossiers de tests, les délais des outils et du clone, la chaîne d'outils Rust.
« Enregistrer » écrit le fichier ; « Valeurs par défaut » remplit le formulaire sans
enregistrer. Le **cache** (sa taille, ses dates, « Vider le cache… » confirmé) et le **thème**
sont à part. La configuration d'un projet prime sur les réglages : le rapport le dit.

## La ligne de commande

Trois commandes : `forceupdate ui` (ci-dessus), `forceupdate scan` et `forceupdate update`.
`forceupdate --version` affiche la version ; `--help` après une commande, ses options.

### `forceupdate scan [chemin]`

Analyse un dossier ou un fichier (par défaut, le dossier courant) et écrit le rapport.

| Option | Effet |
|---|---|
| `--format`, `-f` `terminal\|json\|md` | La forme du rapport (par défaut `terminal`). Le JSON est décrit dans [JSON_FORMAT.md](JSON_FORMAT.md) (`schema_version: 1`). |
| `--output`, `-o` *fichier* | Écrit le rapport dans ce fichier, en UTF-8, au lieu de la sortie standard. |
| `--dev` / `--no-dev` | Vérifie aussi les dépendances de développement (par défaut), ou non. |
| `--transitive` | Cherche aussi les versions plus récentes, retirées ou dépréciées des dépendances indirectes. Leurs failles sont toujours cherchées. |
| `--include-tests` | Analyse aussi les projets des dossiers de tests et d'exemples (par défaut : les réglages, ou `include-tests` du projet). |
| `--offline` | N'interroge pas les registres : seulement le cache ; le reste est « non concluant ». |
| `--no-cache` | Ne lit ni n'écrit le cache disque. |
| `--fail-on` `vuln\|major\|any` | Sort avec le code 1 si un constat atteint ce seuil : `vuln`, une faille ; `major`, une faille, une fin de vie, une version retirée, un paquet ou une version déprécié, une majeure plus récente ; `any`, tout ce qui est à mettre à jour. Une version non fixée, un constat non vérifiable ou non concluant ne comptent jamais. |

Dans un terminal, une barre de progression s'affiche sur la sortie d'erreur ; rien ne s'y écrit
quand la sortie est redirigée.

### `forceupdate update [chemin]`

Calcule les mises à jour à faire, montre le plan et le diff des manifestes, puis, après
confirmation (`[o/N]`), réécrit les manifestes et régénère les lockfiles.

| Option | Effet |
|---|---|
| `--level` `patch\|minor\|major` | L'écart le plus grand choisi : `patch` (correctifs), `minor` (et mineures, par défaut), `major` (et majeures, qui peuvent demander d'adapter le code). Sans lui : la sélection du projet, puis celle des réglages. Une correction de faille n'est choisie que si son écart ne dépasse pas ce niveau ; parmi les versions permises, celle qui corrige le plus de failles, puis la plus récente. |
| `--security-only` | Ne choisit que les corrections de failles. |
| `--include` *motif* | Ne choisit que les paquets dont le nom correspond (`*` permis ; répétable). |
| `--exclude` *motif* | Écarte les paquets dont le nom correspond (`*` permis ; répétable). |
| `--ecosystem` *nom* | Ne choisit que les paquets de cet écosystème : `pypi`, `npm`, `crates.io`, `go`, `packagist`, `rubygems`, `maven`, `nuget` (répétable). |
| `--dev` / `--no-dev` | Met à jour aussi les dépendances de développement (par défaut), ou non. |
| `--include-tests`, `--offline`, `--no-cache` | Comme pour `scan`. |
| `--dry-run` | Montre le plan et le diff, sans rien écrire. |
| `--yes`, `-y` | Écrit sans demander de confirmation. Hors d'un terminal, sans `--yes` ni `--dry-run`, rien n'est écrit (et la commande le dit). |
| `--force` | Écrit même si les fichiers visés ont des changements que git n'a pas en commit. |
| `--no-extras` | Ne fait pas ce que forceupdate propose en plus pour un lockfile : le régénérer avec le npm qu'attend le projet, refaire `vendor/` (`go mod vendor`). |

```bash
forceupdate update . --dry-run                       # voir, sans écrire
forceupdate update . --level major --include "django*"
forceupdate update . --security-only --ecosystem npm --yes
```

`update` refuse d'écrire dans un fichier qui a des changements pas encore commités (les
commiter ou les mettre de côté d'abord, ou `--force`) ; hors d'un dépôt git, il prévient que
rien ne permettra de revenir en arrière. Ctrl+C pendant l'écriture ou un outil remet comme
avant ce qui n'était pas fini.

### Codes de retour

| Code | Sens |
|---|---|
| 0 | Rien à signaler. |
| 1 | `scan --fail-on` : un constat atteint le seuil. |
| 2 | Une erreur : chemin introuvable, fichier de sortie impossible à écrire, refus du garde-fou git, mise à jour interrompue, ou un lockfile que son outil n'a pas pu régénérer. |

### Dans la CI

```yaml
- run: uv tool install forceupdate
- run: forceupdate scan . --fail-on vuln --format md -o rapport.md
```

Le rapport Markdown se colle dans un commentaire de PR ou un résumé de job ; le JSON se lit
par un script (`schema_version` change si le format change de façon incompatible).

### Sous Windows

Sous **PowerShell 5.1** (celui de Windows), `>` ne copie pas la sortie d'un programme telle
quelle : il la recode en UTF-16, en passant par le codage de la console, et les accents
peuvent s'y abîmer. Y préférer `--output` :

```powershell
forceupdate scan . --format json --output rapport.json   # UTF-8, tel quel
```

L'invite de commandes (`cmd`) copie la sortie telle quelle. `scan` écrit toujours en UTF-8 une
sortie redirigée vers un fichier ou un tube ; c'est PowerShell qui la recode ensuite.

## Lire un rapport

Les constats sont rangés du plus grave au moins grave : faille, fin de vie, version retirée,
dépréciée, majeure, mineure, correctif.

| Constat | Ce qu'il dit | Gravité |
|---|---|---|
| Faille | La version utilisée a une faille connue (OSV, et les avis de Packagist pour PHP), avec ses identifiants (CVE, GHSA…), son score CVSS et la version qui la corrige. Un paquet malveillant est toujours critique. | celle de l'avis |
| Fin de vie | Le runtime (Python, Node.js…) ou le framework (Django, Spring Boot…) n'a plus de correctifs de sécurité, ou n'en aura plus dans moins de 6 mois. | moyenne (passée), faible (bientôt) |
| Retirée | La version utilisée a été retirée du registre (*yanked*). | moyenne |
| Dépréciée | Le paquet, ou la version utilisée, est déprécié ; le remplaçant s'il est dit. | faible |
| Plus récente | Une version plus récente existe : majeure, mineure ou correctif. | faible (majeure), information |
| Version non fixée | Rien ne fixe la version (un import d'un fichier de code, une dépendance sans contrainte ni lockfile) : la dernière est dite, les failles ne sont pas vérifiables. | information |
| Non vérifiable | Impossible à vérifier : dépendance git ou locale, paquet introuvable, registre privé qu'on ne peut pas interroger. | information |
| Non concluant | Rien n'a pu être conclu : erreur réseau, hors ligne sans cache, version utilisée inconnue. **Ce n'est pas « à jour ».** | information |

Une erreur réseau ou un registre muet donne « non concluant », jamais un faux constat ni un
faux « à jour ».

Quelques mots du rapport :

- **utilisée** : la version installée, lue dans le lockfile ; sans lockfile, la borne basse de
  la contrainte, marquée « approximative », sauf quand le manifeste fixe la version (une
  version exacte, `go.mod`, une version Maven nue) ;
- **permise** (*wanted*) : la plus haute version que la contrainte accepte déjà, choisie comme le
  gestionnaire de paquets le ferait ; on y monte en régénérant le lockfile, sans toucher au
  manifeste ;
- **directe** ou **indirecte** : écrite dans un manifeste, ou tirée par une autre dépendance
  (lue dans le lockfile). Les failles des indirectes sont toujours cherchées ; leurs versions
  plus récentes seulement avec `--transitive` ;
- **écart** : en `0.y.z`, `y` compte comme une majeure (`0.2.3` → `0.3.0` est une majeure),
  comme le font `^` de npm et Cargo.

## Configuration

Deux fichiers, au même format, règlent forceupdate :

- **la configuration du projet**, rangée dans le dépôt : elle vaut pour tous ceux qui
  analysent ce projet ;
- **les réglages de la personne**, sur son ordinateur : ils valent pour toutes ses analyses.

Aucun des deux n'est nécessaire : sans eux, forceupdate prend ses valeurs par défaut. Quand les
deux disent quelque chose, la configuration du projet prime.

### La configuration du projet

C'est un fichier `forceupdate.toml`, ou la table `[tool.forceupdate]` d'un `pyproject.toml`
(comme pour ruff). Les clés sont les mêmes. Si les deux existent, seul `forceupdate.toml` est lu,
et le rapport le dit : « pyproject.toml : [tool.forceupdate] n'est pas lue : forceupdate.toml
prime. » Les deux ne se complètent pas.

Le fichier est lu à la racine de ce qu'on analyse, et seulement là :

| On analyse | La configuration lue |
|---|---|
| un dossier | celle de ce dossier |
| un manifeste ou un lockfile seul | celle de son dossier |
| un fichier de code dans un projet | celle de la racine du dépôt git qui contient le projet, sinon celle du dossier du projet (voir [Un fichier de code](#un-fichier-de-code)) |
| un dépôt d'une forge (« Mes dépôts ») | celle de la racine du dépôt, téléchargée en premier : ses dossiers exclus ne sont jamais téléchargés |

Le rapport la cite sous la source, en une ligne (ici, le terminal ; de même le Markdown et
l'interface) :

```
Configuration du projet : forceupdate.toml (2 règles ignore, 1 dossier exclu, sélection par défaut réglée).
```

Un exemple complet :

```toml
# forceupdate.toml, à la racine du dépôt

ignore = [
  "@types/*",                         # tous les paquets de la portée @types
  "werkzeug",                         # ni vérifié ni mis à jour ; ses failles restent dites
  "django@>=5",                       # rester en Django 4.x
  "pydantic@==2.11.0",                # sauter une version
  "org.springframework.boot:*@>=4",   # Maven : groupe:artefact, rester en Spring Boot 3
]
exclude = ["legacy", "packages/*/examples"]   # jamais lus
include-tests = true                          # analyser aussi tests/, examples/…

[selection]              # ce que le plan choisit d'office, pour tous les écosystèmes
level = "patch"          # correctifs seulement

[selection.npm]          # pour les paquets npm : correctifs et mineures
level = "minor"

[selection.maven]        # pour Maven : seulement les corrections de failles
security-only = true
```

Le même genre de configuration dans un `pyproject.toml` :

```toml
[tool.forceupdate]
ignore = ["werkzeug", "django@>=5"]
exclude = ["legacy"]

[tool.forceupdate.selection]
level = "patch"

[tool.forceupdate.selection.pypi]
level = "major"
```

### Les clés

| Clé | Valeur | Par défaut | Effet |
|---|---|---|---|
| `ignore` | liste de règles | `[]` | paquets, ou versions de paquets, que forceupdate ignore |
| `exclude` | liste de dossiers | `[]` | dossiers jamais lus |
| `include-tests` | `true` ou `false` | `false` | analyser aussi les projets des dossiers de tests et d'exemples |
| `[selection]` `level` | `"patch"`, `"minor"` ou `"major"` | `"minor"` | l'écart le plus grand que le plan choisit d'office |
| `[selection]` `security-only` | `true` ou `false` | `false` | ne choisir d'office que les corrections de failles |
| `[selection.<écosystème>]` | `level`, `security-only` | ceux de `[selection]` | les mêmes, pour un seul écosystème |

Une clé inconnue est écartée (« clé inconnue, ignorée. »), les autres restent lues.

### Ignorer un paquet ou des versions

Chaque règle de `ignore` vise un paquet entier, ou des versions d'un paquet. La syntaxe est celle
de forceupdate, la même pour les huit écosystèmes : celle de chaque écosystème ne convenait pas
(Go n'a pas de plages, Maven et NuGet en ont d'autres, comme `[5,)`).

| Règle | Ce qui est ignoré |
|---|---|
| `lodash` | le paquet lodash |
| `@types/*` | tous les paquets de la portée `@types` |
| `django@>=5` | les versions 5 et plus de Django : il reste en 4.x |
| `requests@<2.30` | les versions de requests sous la 2.30 |
| `urllib3@>=2,<2.3` | les versions de 2 (comprise) à 2.3 (exclue) |
| `pydantic@2.11.0` | cette version seule (comme `pydantic@==2.11.0`) |
| `org.springframework.boot:*@>=4` | Maven : les versions 4 et plus de tous les artefacts du groupe |
| `golang.org/x/text@>=0.20` | Go : les versions v0.20.0 et plus du module |

**Le nom** est celui que montre le rapport : `groupe:artefact` pour Maven, le chemin du module
pour Go, la portée comprise pour npm (le `@` de `@types/node@>=20` n'est pas un séparateur).
`*` et `?` y sont permis, la casse ne compte pas, et pour PyPI le nom est normalisé (PEP 503 :
`Foo_Bar` vaut `foo-bar`).

**Les versions** suivent un `@` : une ou plusieurs comparaisons séparées par des virgules, toutes
à respecter, avec `<`, `<=`, `>`, `>=`, `==` (ou `=`), ou une version seule (`==`). Elles sont
jugées selon les règles de version de l'écosystème du paquet (PEP 440, semver, Maven…), et une
borne se complète au besoin : `5` vaut `5.0.0` pour npm, `v5.0.0` pour Go. `^4`, `~4` ou `[5,)` ne
sont pas des comparaisons : la règle est écartée, et le rapport le dit.

> Attention au sens : une règle dit les versions **ignorées**. `lodash@<5` ignore les versions
> sous la 5 ; pour rester en 4.x, il faut `lodash@>=5`.

**Un paquet ignoré** n'est pas vérifié auprès de son registre : ni version plus récente, ni
version retirée, ni dépréciation, ni fin de vie de framework. Il n'a jamais de mise à jour. **Ses
failles restent cherchées et dites** : ignorer un paquet ne cache jamais une faille, et
`--fail-on vuln` les compte. La règle vaut pour les directes comme pour les indirectes. Une
remarque par fichier le dit :

```
requirements.txt Paquet ignoré : werkzeug (forceupdate.toml). Ni versions plus récentes ni mises à jour ; les failles restent cherchées.
```

**Une version ignorée** est traitée comme si elle n'était pas publiée : elle n'est jamais
proposée, ni comme version plus récente, ni comme option du plan, ni pour corriger une faille,
ni pour remplacer une version dépréciée, ni comme dernière version du cycle conseillé d'un
framework. La version utilisée n'est jamais retirée. Une remarque dit combien de versions la
règle écarte :

```
package.json     lodash@>=4.18 (forceupdate.toml) : 2 versions publiées de lodash jamais proposées.
```

Une borne qui ne se lit pas selon l'écosystème du paquet n'écarte rien, et le rapport le dit
(« … : version illisible pour … , rien n'est écarté. »).

`ignore` n'est pas l'option `--exclude` de `forceupdate update` : `--exclude "eslint*"` écarte des
paquets du plan, pour une commande ; `ignore` les retire aussi de l'analyse, pour toutes.

### Exclure des dossiers

`exclude` liste des dossiers relatifs à la racine (`legacy`, `packages/*/examples`). Un dossier
exclu n'est jamais lu : ni pour les langages, ni pour les projets, ni pour leurs fichiers de
runtime. Sur une forge, il n'est pas téléchargé.

- `*` et `?` sont permis, et `*` passe aussi les `/` : `packages/*/examples` exclut
  `packages/a/examples` comme `packages/a/b/examples`.
- Le motif part de la racine : `legacy` exclut `legacy/`, pas `apps/legacy/` (pour celui-là :
  `apps/legacy` ou `*/legacy`).
- La casse ne compte pas ; `\` vaut `/`, un `./` de tête et un `/` de fin sont retirés.
- Un chemin absolu (« un dossier relatif à la racine du projet est attendu. ») ou qui remonte par
  `..` (« un dossier exclu reste dans le projet (pas de ..). ») est écarté.

Sans rien configurer, certains dossiers ne sont jamais lus : `.git`, `node_modules`, `vendor`,
`.venv`, `venv`, `site-packages`, `dist`, `build`, `target`, `coverage`… (leurs manifestes sont
ceux des dépendances, pas ceux du projet), ni, dans un dépôt git, ce que `.gitignore` écarte.

### Les dossiers de tests et d'exemples

Par défaut, les projets rangés dans un dossier `tests`, `test`, `__tests__`, `spec`, `specs`,
`fixtures`, `fixture`, `examples`, `example`, `demo`, `demos`, `mocks`, `mock` ou `stubs` sont
écartés : ce sont souvent des mini-projets de démonstration. Le rapport les liste à la fin
(« Écartés, car rangés dans des dossiers de tests ou d'exemples : … »).

`include-tests = true` les analyse aussi. L'option `--include-tests` de `scan` et `update` fait de
même, comme l'option « Analyser aussi les dossiers de tests et d'exemples » de l'interface (cochée
d'office si les réglages le demandent). Il suffit que l'un des trois le demande : le projet, les
réglages ou la commande.

### La sélection par défaut

`[selection]` dit ce que le plan choisit d'office : ce que `forceupdate update` met à jour, et ce
qui est déjà coché à l'écran de mise à jour de l'interface.

- `level` : l'écart le plus grand choisi. `"patch"` : les correctifs ; `"minor"` (par défaut) :
  correctifs et mineures ; `"major"` : les majeures aussi, qui peuvent demander d'adapter le code.
- `security-only = true` : seulement les corrections de failles (pour chaque paquet, la plus
  petite version qui corrige le plus de failles).

Une table par écosystème remplace la règle générale pour ses paquets. Son nom :

| Écosystème | Clé | Autres noms acceptés |
|---|---|---|
| PyPI | `pypi` | `python` |
| npm | `npm` | |
| crates.io | `cargo` | `rust`, `"crates.io"` |
| Go | `go` | |
| Packagist | `composer` | `php`, `packagist` |
| RubyGems | `rubygems` | `ruby`, `bundler` |
| Maven, Gradle | `maven` | `java`, `gradle` |
| NuGet | `nuget` | `dotnet` |

La casse ne compte pas. Avec l'exemple du `pyproject.toml` plus haut (`level = "patch"`, et
`"major"` pour PyPI), le plan le rappelle :

```
Mises à jour choisies : 3 sur 3 paquets à mettre à jour (--level patch ; PyPI : --level major).
```

### Les réglages de la personne

Ce sont aussi un `forceupdate.toml`, rangé dans le dossier de configuration de la personne
(comme `uv.toml` pour uv) :

| Système | Fichier |
|---|---|
| Windows | `%LOCALAPPDATA%\forceupdate\forceupdate.toml` |
| Linux | `~/.config/forceupdate/forceupdate.toml` (ou `$XDG_CONFIG_HOME/forceupdate/forceupdate.toml`) |
| macOS | `~/Library/Application Support/forceupdate/forceupdate.toml` |

L'écran Réglages de l'interface l'écrit ; on peut aussi l'écrire à la main. `forceupdate scan` et
`update` le lisent à chaque commande, `forceupdate ui` à son démarrage : un réglage fait dans
l'interface vaut aussi en ligne de commande. L'écran **réécrit le fichier en entier** à chaque
enregistrement : ses commentaires sont perdus, et une modification faite à la main pendant que
`ui` tourne est écrasée par le prochain enregistrement.

Les clés sont celles d'un projet (`ignore`, `include-tests`, `[selection]`), sauf `exclude`
(refusée : « clé inconnue, ignorée. »), plus quatre :

| Clé | Valeur | Par défaut | Effet |
|---|---|---|---|
| `excluded-repositories` | liste de dépôts | `[]` | dépôts des forges exclus : `hôte/propriétaire/dépôt` (`github.com/moi/vieux-site`), `*` et `?` permis (`gitlab.com/equipe/*`, sous-groupes compris), sans tenir compte de la casse |
| `lock-timeout` | secondes, de 10 à 86 400 | `600` | le délai de chaque commande d'un outil de lockfile (npm, uv, cargo…) |
| `clone-timeout` | secondes, de 10 à 86 400 | `600` | le délai d'un clone, d'un fetch ou d'un push, pour une PR |
| `rust-default-toolchain` | `true` ou `false` | `false` | lancer cargo avec la chaîne d'outils par défaut de la personne, pas celle du projet |

- **Un dépôt exclu** est masqué dans « Mes dépôts », comme un dépôt archivé (« exclu dans les
  réglages »). On peut encore l'analyser en le choisissant, mais il n'a jamais de PR (« exclu dans
  les réglages : pas de PR »). Un préfixe `https://` et un `.git` final sont retirés.
- **Au-delà de `lock-timeout`**, la commande est arrêtée (le résultat dit qu'elle « n'a pas fini
  en 600 s »), et les fichiers du projet sont remis comme avant. `clone-timeout` ne sert qu'à
  l'interface : la ligne de commande ne clone rien.
- **`rust-default-toolchain`** : un `rust-toolchain.toml` du projet fait installer puis lancer
  par rustup la chaîne d'outils qu'il désigne (même un dossier du projet). Avec ce réglage, cargo
  est lancé avec celle de `rustup default` (par `RUSTUP_TOOLCHAIN`), sans rien installer. Plus
  ancienne que ce que demande le projet, la régénération du `Cargo.lock` peut échouer. Si rustup
  n'a pas de chaîne d'outils par défaut, le plan le dit.

Le fichier tel que l'écran l'écrit :

```toml
# Réglages de forceupdate, écrits par l'écran Réglages (forceupdate ui).
# Une configuration de projet (forceupdate.toml, [tool.forceupdate]) prime sur eux.

ignore = ["@types/*", "eslint@>=10"]
include-tests = false
excluded-repositories = ["github.com/moi/archives-*", "gitlab.com/equipe/bac-a-sable/*"]
lock-timeout = 900
clone-timeout = 1200
rust-default-toolchain = false

[selection]
level = "patch"

[selection.npm]
level = "minor"
```

L'écran Réglages montre aussi le cache (sa taille, et de quoi le vider) et le thème, qui ne sont
pas dans ce fichier : le thème est une préférence du navigateur.

### Qui prime

| Réglage | Ordre |
|---|---|
| la sélection (`level`, `security-only`) | `--level` et `--security-only` de `update`, puis le projet, puis les réglages, puis les valeurs par défaut (`minor`, pas seulement les failles). Dans le projet comme dans les réglages, une table d'écosystème passe devant `[selection]`. Un champ que l'un ne dit pas vient du suivant |
| `ignore` | les règles du projet et celles des réglages s'ajoutent ; le rapport dit d'où vient chacune (`(forceupdate.toml)`, `(réglages)`) |
| `include-tests` | il suffit que l'un le demande : `--include-tests`, le projet ou les réglages |
| `exclude` | le projet seul |
| dépôts exclus, délais, chaîne d'outils Rust | les réglages seuls |

### Une valeur fausse

Rien n'arrête l'analyse.

**Dans la configuration du projet**, la valeur fausse est écartée, le reste est lu, et le rapport
le dit sous la ligne « Configuration du projet » (terminal, Markdown, interface, et
`config.problems` du JSON) :

```
Configuration du projet : forceupdate.toml.
  forceupdate.toml : ignore[0] : « lodash@~4 » : « ~4 » n'est pas une comparaison (>=5, <2, ==1.2.3, ou une version).
  forceupdate.toml : ignore[1] : « lo dash » : un nom de paquet sans espace est attendu (lodash, django@>=5).
  forceupdate.toml : exclude[0] : « ../dehors » : un dossier exclu reste dans le projet (pas de ..).
  forceupdate.toml : include-tests : « oui » n'est pas true ou false.
  forceupdate.toml : couleur : clé inconnue, ignorée.
  forceupdate.toml : selection.level : « mineur » n'est pas patch, minor, major.
  forceupdate.toml : selection.java2 : « java2 » n'est pas un écosystème (pypi, npm, cargo, go, composer, rubygems, maven, nuget).
```

Dans un `pyproject.toml`, le chemin de la clé commence par `tool.forceupdate.`. Un TOML invalide
n'est pas lu du tout : « forceupdate.toml : TOML invalide (…) : non lu. »

**Dans les réglages de la personne**, la valeur par défaut prend sa place. La ligne de commande
le dit sur la sortie d'erreur, l'écran Réglages à l'écran :

```
forceupdate : réglages : forceupdate.toml : lock-timeout : 5 s : entre 10 et 86400 secondes.
forceupdate : réglages : forceupdate.toml : excluded-repositories[0] : « github.com/x » : hôte, propriétaire et dépôt sont attendus (github.com/owner/repo, gitlab.com/groupe/*).
forceupdate : réglages : forceupdate.toml : exclude : clé inconnue, ignorée.
```

Un fichier de réglages illisible ou en TOML invalide donne toutes les valeurs par défaut (« … :
TOML invalide (…) : valeurs par défaut. »). L'écran Réglages, lui, refuse d'enregistrer une
valeur fausse et dit laquelle, champ par champ.

### Limites

- La configuration n'est lue qu'à la racine de ce qu'on analyse : dans un monorepo analysé depuis
  sa racine, le `forceupdate.toml` de `web/` n'est pas lu. Mettre les règles à la racine (avec
  `exclude` pour viser un sous-dossier), ou analyser `web/` seul.
- Une règle `ignore` vise un nom, quel que soit l'écosystème : `jquery` ignore le paquet npm comme
  le paquet NuGet.
- Les commentaires du fichier de réglages ne survivent pas à un enregistrement depuis l'écran.
- Un projet ne peut pas désactiver `include-tests` que demandent les réglages ou la commande.

## Les écosystèmes

forceupdate lit huit écosystèmes. Pour chacun, il lit les manifestes et les lockfiles sans
rien exécuter, demande les versions publiées au registre de l'écosystème, et les failles à
[OSV](https://osv.dev) (plus, pour PHP, aux avis de Packagist). La mise à jour réécrit les
manifestes, puis fait régénérer les lockfiles par l'outil de chacun.

### En bref

| Écosystème | Manifestes | Lockfiles | Registre | Lockfile régénéré par |
|---|---|---|---|---|
| Python | `requirements*.txt`, `requirements*.in`, `requirements/*.txt`, `pyproject.toml`, `Pipfile`, `setup.cfg`, le bloc `# /// script` d'un script | `uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock`, un `.txt` de pip-tools, un `requirements.txt` exporté, `script.py.lock` | PyPI (l'API « Simple ») | uv, Poetry, PDM, pipenv, pip-compile, `uv pip compile`, `uv export`, `poetry export`, `pdm export` |
| JavaScript | `package.json`, `pnpm-workspace.yaml` | `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock` (Yarn 1 et 2+), `pnpm-lock.yaml` | registry.npmjs.org | npm, pnpm, Yarn |
| Rust | `Cargo.toml` | `Cargo.lock` | l'index « sparse » de crates.io | cargo |
| Go | `go.mod`, `go.work` | `go.sum` | proxy.golang.org | go (`go mod tidy`) |
| PHP | `composer.json` | `composer.lock` | Packagist | Composer |
| Ruby | `Gemfile`, `gems.rb`, `*.gemspec` | `Gemfile.lock`, `gems.locked` | l'index « compact » de RubyGems | Bundler (`bundle lock`) |
| Java | `pom.xml` ; `build.gradle`, `build.gradle.kts`, `settings.gradle(.kts)`, `gradle/libs.versions.toml`, `gradle.properties` | `gradle.lockfile` (lu, jamais régénéré) | Maven Central, Google Maven, le portail des plugins Gradle | aucun |
| .NET | `*.csproj`, `*.fsproj`, `*.vbproj`, `Directory.Packages.props`, `Directory.Build.props`, `Directory.Build.targets`, `packages.config`, `global.json` | `packages.lock.json` | nuget.org | dotnet (`dotnet restore`) |

Un paquet d'un registre privé (déclaré dans `.npmrc`, `nuget.config`, `settings.xml`…) est
demandé à ce registre : voir « Registres et dépôts privés ».

### Ce qui vaut pour tous

**La réécriture.** Rien n'est re-sérialisé : seul le texte de la contrainte change, à
l'endroit exact où l'analyse l'a lu. Commentaires, ordre, mise en forme, fins de ligne (CRLF)
et BOM restent. La contrainte garde son style : seuls les numéros changent (`^4.17.0` devient
`^4.21.2`, `>=2.25,<3` devient `>=3.1,<4`). Une borne haute qui exclut la version visée
monte au niveau qu'elle fixait (`<1.5` vers 1.7.2 : `<1.8`). Pour corriger une faille, la
nouvelle contrainte n'accepte plus aucune version concernée : quand le style ne le permet pas,
une borne basse s'ajoute (`~=1.9,>=1.9.2`). Une contrainte que forceupdate ne sait pas réécrire
(`*`, une étiquette comme `latest`) est « à réécrire à la main » : l'option n'est jamais cochée.

Chaque fichier réécrit est relu par son parseur avant d'être écrit : il doit redonner les
mêmes dépendances, avec la nouvelle contrainte à chaque endroit réécrit, et rien d'autre de
changé. Sinon il n'est pas réécrit, et la raison est dite.

**Une contrainte qui accepte déjà la version visée** n'est pas réécrite : seul le lockfile
change. Sans lockfile, la version utilisée est la borne basse de la contrainte : c'est elle qui
monte. Une dépendance indirecte monte par son lockfile, sauf exceptions dites plus bas (une
version forcée npm, Go, NuGet).

**La régénération.** Un lockfile est toujours régénéré par l'outil de son format, jamais
réécrit par forceupdate. L'outil est cherché sur le `PATH` (sous Windows, `npm` est
`npm.cmd`, `composer` le `composer.bat` de son installateur, `bundle` le `bundle.bat` de
RubyInstaller). Il est lancé sans shell, dans le dossier du lockfile (à la racine d'un
workspace : une fois pour tous ses membres), sans entrée standard, sans couleurs ni questions,
avec un délai (voir « Robustesse »), et sans les scripts du projet quand l'outil le permet.

Régénérer garde les versions déjà figées qui respectent les contraintes. Pour obtenir la
version choisie, et pas une autre, forceupdate vise le paquet, à la façon de chaque outil :

- uv et pip-compile : `-P nom==version` ;
- npm, pnpm, Poetry, PDM, Cargo, Bundler : la version exacte écrite à la place de la
  contrainte le temps d'un premier passage, puis la contrainte remise et l'outil relancé, qui
  garde la version. Si ce passage échoue (un pair qui exige autre chose…), le lockfile est
  régénéré sans, et le résultat le dit (« Versions exactes refusées : … ») ;
- Composer : `composer update nom:version` ;
- Go et NuGet : rien à viser, la version est écrite dans le manifeste ;
- Yarn et pipenv ne savent pas garder une version épinglée : ils prennent la plus haute que
  permet la contrainte.

Ensuite le projet est relu. Pour chaque mise à jour, le résultat dit la version obtenue :
« version exacte », une version plus haute (« au lieu de 4.1.0 : Yarn prend la plus haute
version que permet la contrainte. »), ou une version restée en dessous, avec ce qui la retient
(« retenue par debug 4.3.1. »). Les autres paquets que le lockfile a changés sont listés
(« aussi changé »).

Une version retenue est presque toujours celle d'une dépendance **indirecte** : l'outil ne la
monte pas au-delà de la plage que demande le paquet qui la tire. `nodemon` 3.1.14 demande
`minimatch ^10.2.1` : la correction d'une faille de minimatch, publiée en 11.0.1 (une
majeure), reste hors d'atteinte, et le lockfile ne change pas. Le plan le signale d'avance (« le
paquet qui la tire devra peut-être monter aussi ») ; pour aller plus loin, monter d'abord ce
paquet (une version plus récente de nodemon qui accepte minimatch 11), ou forcer la version dans
le manifeste (`overrides` de npm, `resolutions` de Yarn), à ses risques.

Commandes vérifiées avec npm 11.6, pnpm 12.15, Yarn 1.22 et 4.18, uv 0.10, Poetry 1.8 et
2.5, PDM 2.29, pipenv 2026.10, pip-tools 7.6, cargo 1.99, Go 1.27, Composer 2.11, Bundler 4.0
et le SDK .NET 10.0.403.

**Ce qui s'exécute quand même.** Certains outils exécutent du code du projet ou de ses
dépendances, faute d'option pour l'en empêcher. Le plan le dit sous le lockfile, avant de
confirmer :

| Outil | Ce qu'il exécute |
|---|---|
| npm, pnpm, Yarn 1 | rien du projet (`--ignore-scripts` ; pnpm : `--ignore-pnpmfile`) |
| Yarn 2+ | rien du projet (`--mode=update-lockfile`), sauf la version de Yarn et les extensions qu'il déclare (`yarnPath`, `plugins`, `yarn-path` : dit) |
| uv, Poetry, PDM, pipenv, pip-compile | le code de construction d'un paquet publié sans wheel, dont l'outil lit les dépendances (uv : aussi le projet, si ses dépendances sont dynamiques) |
| cargo | ni `build.rs`, ni le `rustc` ou les « wrappers » d'un `.cargo/config.toml` ; mais rustup installe et lance la chaîne d'outils d'un `rust-toolchain.toml` (dit) |
| go | rien n'est compilé ; les modules sont téléchargés |
| Composer | rien du projet (`--no-scripts`, `--no-plugins`, `--no-install`) |
| Bundler | le `Gemfile` (c'est du Ruby), ce qu'il charge par `eval_gemfile`, les `.gemspec` du projet et de ses gems `path:` et `git:` |
| dotnet | MSBuild évalue le projet : une cible accrochée à la restauration (projet, `Directory.Build.targets`) s'exécute, comme un SDK de projet venu de NuGet |

Sur un projet dont vous ne connaissez pas le code, lisez ces avertissements avant de confirmer :
Bundler et dotnet exécutent du code du projet lui-même.

### Python

**Fichiers lus** :

- `requirements*.txt` et `requirements*.in` (aussi sous `requirements/`), avec les
  `-r autre.txt` et `-c contraintes.txt` qu'ils citent ;
- `pyproject.toml` : `[project]` (PEP 621), `[dependency-groups]` (PEP 735), Poetry,
  `[build-system] requires`, les dépendances de dev de uv et de PDM ;
- `Pipfile`, `setup.cfg` ; `setup.py` n'est pas lu (il faudrait l'exécuter : « pas lu : il
  faudrait l'exécuter pour connaître ses dépendances. ») ;
- les lockfiles `uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock` ; un `.txt` compilé par
  pip-tools, posé à côté du `.in` du même nom ; un `requirements.txt` généré (voir
  « Les `requirements.txt` générés ») ;
- le bloc PEP 723 d'un script (`# /// script`) et son `script.py.lock` (voir « Un fichier de
  code »).

Le lockfile d'un `pyproject.toml` : celui de l'outil qu'il déclare (`[tool.poetry]`,
`[tool.pdm]`), sinon `uv.lock`, `poetry.lock` puis `pdm.lock`. Un autre lockfile présent n'est
pas lu, et une remarque le dit. Un membre d'un workspace uv prend le `uv.lock` de la racine.

**Registre** : PyPI, par l'API « Simple » en JSON (`https://pypi.org/simple/{nom}/`). Une
version est « retirée » si tous ses fichiers le sont (yanked) ; un projet archivé ou déprécié
sur PyPI est déprécié ; un projet en quarantaine a toutes ses versions retirées.

**Réécriture** : PEP 440 (`==`, `>=`, `~=`, `!=`…) et la syntaxe de Poetry (`^`, `~`, version
nue, `1.2.*`). `~=` garde sa précision (`~=1.4` vers 1.9.2 : `~=1.9`). Un fichier de
contraintes (`-c constraints.txt`) n'est pas un lockfile : sa ligne `==X` est réécrite comme
une contrainte, dans le diff.

**Lockfile** :

| Lockfile | Commande lancée |
|---|---|
| `uv.lock` | `uv lock -P nom==version…` |
| `script.py.lock` | `uv lock --script script.py -P nom==version…` |
| `poetry.lock` | `poetry lock --no-interaction` (`--no-update` avec Poetry 1), la version épinglée (`==V`) le temps d'un passage ; une indirecte : `poetry update --lock nom` |
| `pdm.lock` | `pdm lock --update-reuse`, épinglée de même ; une indirecte : `pdm update --no-sync --update-reuse nom` |
| `Pipfile.lock` | `pipenv lock`, qui re-résout tout |
| `.txt` de pip-tools | la commande de son en-tête (`pip-compile …` ou `uv pip compile …`), ses options reprises, plus `-P nom==version` |
| `requirements.txt` exporté | `uv export …`, `poetry export …` ou `pdm export …`, après le lockfile dont il vient |

Un `.txt` de pip-tools qui en cite un autre (`-c requirements.txt`) est recompilé après lui.
Des options de l'en-tête, seules celles d'une liste connue sont reprises (index, forme du
fichier, version de Python…). `--exclude-newer` ne l'est jamais : il écarterait les versions
choisies. Le plan dit ce qui n'est pas repris (« Pas repris de l'en-tête de
requirements.txt : … »).

**Ce qui s'exécute** : uv, Poetry, PDM, pipenv et pip-compile peuvent construire un paquet
publié sans wheel. `uv --no-build` n'est pas passé : il refuse tout paquet sans wheel pour une
plateforme, et change donc la résolution. PDM crée le `.venv` du projet s'il n'en a pas ;
pipenv crée son virtualenv (dans `~/.virtualenvs`). Un virtualenv activé (`VIRTUAL_ENV`)
n'est pas transmis à l'outil : pipenv et Poetry le prendraient pour celui du projet.

**Particularités** :

- les noms sont normalisés (PEP 503 : `Django_REST.framework` est `django-rest-framework`) ;
- une dépendance git, par URL, par chemin, ou membre du workspace est « non vérifiable » ; une
  dépendance rattachée à un autre index (`index =` de uv, `source =` de Poetry, `index =` de
  Pipfile) est demandée à cet index (voir « Registres et dépôts privés ») ;
- une version que le Python du projet (`requires-python`) ne fait pas tourner n'est pas
  proposée ; `exclude-newer` de `[tool.uv]` écarte les versions publiées après sa date ;
- une ligne à empreintes (`--hash`) se met à jour à la main (voir plus bas).

**Limites** :

- pipenv re-résout tout : une version plus haute que la choisie est possible ;
- un paquet en plusieurs versions dans `uv.lock` (selon la version de Python) : la plus haute
  compte ;
- une contrainte continuée sur la ligne suivante (`\`) ou une chaîne TOML à échappement n'a
  pas d'emplacement : à réécrire à la main ;
- une date d'`exclude-newer` est lue en UTC (uv prend le fuseau de la machine).

### JavaScript (npm, pnpm, Yarn)

**Fichiers lus** : `package.json` (`dependencies`, `devDependencies`, `peerDependencies`,
`optionalDependencies`) ; `package-lock.json` et `npm-shrinkwrap.json` (formats 1 à 3) ;
`yarn.lock` de Yarn 1 et de Yarn 2+ ; `pnpm-lock.yaml` (formats 5.4, 6.0 et 9.0, et celui à
deux documents de pnpm 11+) ; `pnpm-workspace.yaml` (catalogues, `overrides`).

Le lockfile pris est celui de `packageManager` (`"pnpm@9.15.9"`), sinon, dans l'ordre,
`npm-shrinkwrap.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`. Les autres
reçoivent une remarque (« pas lu : … est le lockfile pris pour package.json. »). Un membre d'un
workspace npm, Yarn ou pnpm prend le lockfile de la racine, s'il en est bien membre.

**Registre** : `https://registry.npmjs.org`. La dernière version est celle de
`dist-tags.latest` (celle que prend `npm install`) ; une version publiée sous une autre
étiquette (`next`) n'est pas proposée. Un paquet est déprécié si sa version `latest` l'est.

**Réécriture** : `^`, `~`, `1.x`, `>=1 <2`, `||`, version exacte. Quelques cas :

- un alias (`"mon-ms": "npm:ms@2.0.0"`) est vérifié sous le vrai nom, et seule la version
  change (`npm:ms@2.1.3`) ;
- une dépendance pair voit sa plage s'élargir au lieu d'être remplacée (`^18.0.0` vers
  19.1.0 : `^18.0.0 || ^19.1.0`) : la remplacer retirerait React 18 aux utilisateurs de la
  bibliothèque ;
- un catalogue pnpm (`catalog:`) se réécrit dans `pnpm-workspace.yaml` ;
- une indirecte figée par une version forcée (`overrides`, `resolutions`, `pnpm.overrides`,
  `overrides` de `pnpm-workspace.yaml`) qui n'accepte pas la version visée : c'est la version
  forcée qui est réécrite.

**Lockfile** :

| Lockfile | Commande lancée |
|---|---|
| `package-lock.json` | `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`, la version épinglée le temps d'un passage ; une indirecte : `npm update nom` (`--workspaces --include-workspace-root` dans un workspace) |
| `pnpm-lock.yaml` | `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile --no-frozen-lockfile`, épinglée de même ; une indirecte : `pnpm update nom --no-save` (`-r` dans un workspace) |
| `yarn.lock` (Yarn 1) | l'entrée du paquet retirée du `yarn.lock`, puis `yarn install --ignore-scripts --ignore-engines --non-interactive --no-progress`, avec `node_modules` dans un dossier temporaire (Yarn 1 n'a pas de mode « lockfile seul ») |
| `yarn.lock` (Yarn 2+) | `yarn up -R nom… --mode=update-lockfile` (rien n'est installé) |

`yarn upgrade` n'est pas lancé : il réordonne le `package.json`. Avec `CI=true`, Yarn et pnpm
refusent de changer leur lockfile : forceupdate le leur permet. Yarn 2+ écrit aussi
`.yarn/install-state.gz`.

**Particularités** : le `package-lock.json` peut être régénéré avec le npm qu'attend le projet,
pas celui de la machine (voir « Le npm du projet »). Une version que le Node du projet
(`engines.node`, `.nvmrc`, la CI…) ne fait pas tourner n'est pas proposée. Une dépendance git,
`file:`, `link:`, `workspace:` ou `patch:` n'est pas vérifiable.

**Limites** :

- Yarn 1 et Yarn 2+ montent à la plus haute version que permet la contrainte ;
- une version forcée par référence (`"$minimist"`) suit la directe de la racine, proposée à
  côté ; vers un chemin local, elle est à réécrire à la main ;
- un intervalle `1.2.3 - 2.3.4` dépassé, `*` ou une étiquette : à réécrire à la main ;
- deux alias du même paquet montent ensemble ;
- npm 11 ajoute parfois des paquets facultatifs de plateforme (`@emnapi/*`) : ils sont dans
  « aussi changé ».

### Rust (Cargo)

**Fichiers lus** : `Cargo.toml` (`[dependencies]`, `[dev-dependencies]`,
`[build-dependencies]`, et les mêmes sous `[target.'…']`), `Cargo.lock` (formats 1 à 4). Une
dépendance renommée (`package = "log"`) est vérifiée sous le vrai nom. Un membre d'un workspace
prend le `Cargo.lock` de la racine (d'après `members` et `exclude`), et `workspace = true` la
contrainte de `[workspace.dependencies]`.

**Registre** : l'index « sparse » de crates.io (`https://index.crates.io`), celui que lit
Cargo. Il dit les versions retirées (yanked) et le `rust-version` de chaque version.

**Réécriture** : `1.2` veut dire `^1.2` pour Cargo, et reste sans opérateur ; `=`, `~`, `^`.
`=1.2` (qui veut dire `1.2.*`) garde sa précision. Une contrainte `workspace = true` se
réécrit dans `[workspace.dependencies]` du `Cargo.toml` de la racine.

**Lockfile** : une directe est épinglée (`=V`) le temps d'un `cargo update --workspace`, puis la
contrainte est remise et `cargo update --workspace` relancé, qui garde la version. Une
indirecte : `cargo update -p nom@actuelle --precise V`. Pas `--precise` pour une directe :
Cargo l'ignore dès que la contrainte réécrite n'accepte plus la version figée. Un `Cargo.lock`
garde son format.

**Ce qui s'exécute** : ni `build.rs` (`cargo update` ne compile rien), ni le `rustc` ou les
« wrappers » d'un `.cargo/config.toml` du projet : forceupdate passe le `rustc` installé
(`RUSTC`), et vide `RUSTC_WRAPPER` et `RUSTC_WORKSPACE_WRAPPER`. Mais rustup lit le
`rust-toolchain.toml` du projet : il installe s'il le faut la chaîne d'outils qu'il désigne, et
la lance (le plan le dit). Le réglage « chaîne d'outils Rust » (`rust-default-toolchain` des
réglages) fait tourner cargo avec la chaîne par défaut de la personne à la place
(`RUSTUP_TOOLCHAIN`) ; plus ancienne que ce que demande le projet, la régénération peut échouer.
Le plan dit aussi qu'un `.cargo/config.toml` est lu par cargo (registres, sources, programmes
d'identification).

**Particularités** : une version dont le `rust-version` dépasse celui du projet n'est jamais
proposée ; la version « permise » suit le résolveur 3 (la plus haute qui convient, sinon la
plus haute). Une dépendance `git` ou `path` n'est pas vérifiable ; une source remplacée par
`[patch]` non plus.

**Limites** :

- `rust-toolchain.toml` et `.cargo/config.toml` sont dits, pas neutralisés ;
- deux renommages du même crate (`rand` 0.8 et 0.9) montent ensemble ;
- `[patch]` et `[replace]` ne sont vus que par le lockfile ;
- `[package] workspace` doit désigner un dossier de la source ;
- `[resolver] incompatible-rust-versions` n'est pas lu ; sans `rust-version` ni
  `rust-toolchain`, la version de Rust du projet n'est pas connue (forceupdate ne lance pas
  `rustc`).

### Go

**Fichiers lus** : `go.mod` (`require`, `replace`, `exclude`, `retract`, `go`, `toolchain`),
`go.work` (`use`, `replace`). **La version utilisée est celle de `go.mod`** : depuis Go 1.17,
`go mod tidy` y écrit chaque module qui fournit un paquet, indirectes comprises
(`// indirect`). `go.sum` n'est pas une source de versions : c'est le lockfile que `go mod tidy`
refait. Dans un workspace `go.work`, la version construite est la plus haute que demandent ses
membres : c'est elle qui est vérifiée, et une remarque le dit.

**Registre** : `https://proxy.golang.org` (`@v/list`, `@latest`, le `go.mod` de la dernière
version, pour ses `retract` et sa dépréciation `// Deprecated:`).

**Réécriture** : une version de `go.mod` n'est pas une plage : elle devient la version visée,
avec son `v` (`v1.3.0` vers 1.6.0 : `v1.6.0`). Une indirecte se réécrit dans `go.mod`, comme
une directe ; une version remplacée se réécrit dans son `replace`, celle d'un `replace` de
`go.work` dans `go.work`, sans rien régénérer (le prochain `go build` du workspace complète
`go.work.sum`).

**Lockfile** : `go mod tidy`, après la réécriture de `go.mod`. Il garde les versions écrites,
refait `go.sum`, et fait monter ce que la sélection minimale exige (une dépendance de la
nouvelle version qui en demande plus : le résultat le dit, « aussi changé dans go.mod »). Pas
`go get nom@V` : pour descendre, il retire les modules qui demandent plus. forceupdate passe
`GOTOOLCHAIN=local` (le go installé, sans en télécharger un autre), `GOFLAGS=-mod=mod` et
`GOWORK=off` ; `GOPROXY`, `GOPRIVATE`… restent ceux de la personne. Un changement de la
directive `go` ou `toolchain` est dit (« go mod tidy a changé la directive go : 1.21 →
1.24.0. »). Avec un dossier `vendor/` : voir « `go mod vendor` ».

**Ce qui s'exécute** : rien n'est compilé, `go generate` ne tourne pas. Les modules sont
téléchargés (sans exécuter leur code), et git est lancé pour un module hors du proxy, comme
avec tout `go`. Si `go.mod` a une ligne `toolchain`, le plan dit que le go installé est
lancé à sa place : plus ancien que la directive `go`, il échoue, et rien ne change.

**Particularités** :

- **une majeure est un autre module** (`…/v2`, `gopkg.in/x.v3`) : elle est cherchée sous son
  chemin, proposée, mais jamais appliquée, car les imports du code changent aussi
  (« Majeure publiée sous un autre module (…) : … go get …/v5@V, puis remplacer les
  imports. ») ;
- une version de `exclude` n'est jamais proposée ; une version retirée par `retract` l'est
  avec sa raison ;
- une pseudo-version (`v0.0.0-20230101…-abcdef`) se compare par sa date ;
- un `replace` vers un chemin local rend la dépendance non vérifiable.

**Limites** :

- avant `go 1.17`, `go.mod` ne liste pas toutes les indirectes : elles ne sont pas toutes
  vérifiées (une remarque le dit) ;
- les `go.mod` des dépendances ne sont pas lus : une indirecte peut être construite plus haut
  encore ;
- un module qui change d'hôte (`go-redis` → `redis/go-redis`) n'est vu que par sa
  dépréciation ;
- le retrait d'une pseudo-version n'est pas vérifié (le proxy ne les liste pas) ;
- `tool` (Go 1.24) ne change pas le scope.

### PHP (Composer)

**Fichiers lus** : `composer.json` (`require`, `require-dev`, `conflict`, `replace`,
`provide`, `repositories`, `minimum-stability`, `prefer-stable`, `config.platform.php`),
`composer.lock`. Les noms sont mis en minuscules, comme le fait Composer. `php`, `ext-*`,
`lib-*` et les autres paquets « plateforme » sont mis de côté (la version de PHP sert aux fins
de vie et aux versions écartées).

**Registre** : Packagist, ses métadonnées `p2` (`https://repo.packagist.org/p2/{nom}.json`).
Un paquet abandonné est déprécié, avec son remplaçant. Les failles viennent d'OSV et des avis
de Packagist (dont FriendsOfPHP), réunis par leurs identifiants.

**Réécriture** : une version nue est exacte (`1.2` vers 1.5.3 : `1.5.3`) ; `~1.2` va jusqu'à
2.0 et garde sa précision (`~1.5`) ; `^`, les jokers (`3.4.*`), `||` et `|` ; un drapeau de
stabilité (`^1.0@beta`) est gardé. Le `v` que Packagist donne à certaines versions
(`v5.4.20`) n'est pas écrit, sauf si la contrainte en avait un.

**Lockfile** : une seule commande, qui vise chaque version, directe ou indirecte :

```
composer update nom:version… --with-all-dependencies --no-install --no-scripts --no-plugins
  --no-interaction --no-progress --no-ansi --ignore-platform-req=ext-* --ignore-platform-req=lib-*
```

`--with-all-dependencies` laisse bouger ce que la nouvelle version exige (une autre directe
comprise) ; `COMPOSER_MINIMAL_CHANGES=1` ne bouge rien d'autre ; `COMPOSER_NO_AUDIT=1` saute
l'audit de fin. Pas `composer update --lock` : il garde une version que la contrainte réécrite
n'accepte plus. Composer ne touche jamais au `composer.json`. Les variables qui lui feraient
lire un autre fichier ou choisir d'autres versions (`COMPOSER`, `COMPOSER_PREFER_LOWEST`,
`COMPOSER_NO_DEV`…) ne lui sont pas transmises ; `COMPOSER_HOME` et `COMPOSER_AUTH` le sont.

**Ce qui s'exécute** : rien du projet. Sans `--no-scripts`, `pre-update-cmd` et
`post-update-cmd` tourneraient même sans installation ; sans `--no-plugins`, un plugin déjà dans
`vendor/` serait activé. Seules les métadonnées des paquets sont téléchargées.

**Particularités** :

- `conflict` donne des versions jamais proposées ;
- une branche (`dev-main`, `1.x-dev`), un paquet d'un dépôt `path`, `vcs`, `package` ou
  `artifact`, un paquet que le projet fournit (`replace`, `provide`) ne sont pas vérifiables ;
- sans `config.platform.php`, Composer choisit les versions pour le PHP de la machine (le plan
  le dit) ;
- Composer 2.9 et plus refuse les versions qui ont une faille : voir « Composer 2.9 et les
  failles ».

**Limites** :

- seules des versions stables sont proposées ; une branche ne l'est jamais. Avec une
  `minimum-stability` basse sans `prefer-stable`, une remarque dit que Composer peut choisir une
  pré-version ;
- `vendor/` n'est pas mis à jour : lancer `composer install` après la mise à jour (le plan le
  dit) ;
- avec Composer 2.9, la mise à jour d'une version qui garde une faille échoue, et tout est
  remis.

### Ruby (Bundler)

**Fichiers lus** : `Gemfile` et `gems.rb`, **lus par motifs, jamais exécutés** (c'est du Ruby) ;
les `.gemspec` (`add_dependency`, `add_development_dependency`) ; `Gemfile.lock` et
`gems.locked`. Ce qui est lu du `Gemfile` : `gem "nom", "~> 2.2", ">= 2.2.3"`, les groupes
(`development` et `test` seuls : `dev`), `gemspec`, `platforms`, `source`, `git:`, `path:`.
Une gem `path:` (un `.gemspec` sans `Gemfile`) est résolue dans le `Gemfile.lock` du `Gemfile`
qui la cite.

**Registre** : l'index « compact » de RubyGems (`https://index.rubygems.org/info/{gem}`),
celui que lit Bundler. Une version à plateforme (`nokogiri (1.19.0-x86_64-linux-gnu)`) est lue
sans sa plateforme.

**Réécriture** : `~>` garde toujours sa précision, car le nombre de nombres y fixe la borne
haute (`~> 2.2.3` vers 2.2.8.1 : `~> 2.2.8`, et `~> 2.2.8, >= 2.2.8.1` pour une faille) ; `=`
et une version nue sont exactes. Une contrainte en plusieurs chaînes sur une ligne se réécrit
avec ses guillemets (`">= 1.19.0", "< 1.20"`). Le `.gemspec` se réécrit comme le `Gemfile`.

**Lockfile** : `bundle lock` ne sait pas viser une version sans toucher au `Gemfile`. La
contrainte est donc remplacée par `= V` (dans le `Gemfile` ou le `.gemspec`), et une ligne
`gem "nom", "= V"` est ajoutée à la fin du `Gemfile` pour une indirecte, le temps d'un `bundle
lock` ; puis les fichiers sont remis et `bundle lock` relancé, qui garde les versions. Si
l'épinglage échoue : `bundle lock --update nom… --conservative`. Aucune ligne n'est ajoutée
après `__END__`, ni pour un nom qui n'est pas celui d'une gem. Sous une autre plateforme que
celles du lockfile (Windows pour un projet Linux), Bundler ajoute la sienne : elle est retirée
(`bundle lock --remove-platform`, qui ne change aucune version). `BUNDLE_GEMFILE` et
`BUNDLE_LOCKFILE` sont ceux du projet, quoi que dise l'environnement.

**Ce qui s'exécute** : **Bundler exécute le `Gemfile`**, ce qu'il charge (`eval_gemfile`) et
les `.gemspec` du projet, de ses gems `path:` et `git:`. Aucune option ne l'en empêche ; le plan
le dit. Les crochets des plugins ne tournent qu'à l'installation (`bundle lock` n'installe
rien).

**Particularités** :

- Bundler résout pour le Ruby qui tourne : une version que le Ruby du projet ne fait pas
  tourner n'est pas proposée ;
- le `cooldown` de Bundler 4 (versions publiées depuis peu écartées) est respecté, et dit ;
- un changement de `BUNDLED WITH` (la version du Bundler qui tourne) ou de `RUBY VERSION` est
  dit ;
- une gem `git:`, `path:`, d'un plugin, ou installée sur aucune plateforme du lockfile, n'est
  pas vérifiable, ni `bundler` lui-même (sa version est celle de `BUNDLED WITH`) ;
- une gem d'une autre source (`source "…" do`, `source:`) est demandée à ce serveur : voir
  « Registres et dépôts privés ».

**Limites** :

- une condition (`if`, `case`) n'est pas évaluée : la gem est lue comme toujours déclarée ; une
  contrainte dans une variable vient du `Gemfile.lock`, à réécrire à la main ; le fichier d'un
  `eval_gemfile` n'est pas lu (une remarque le dit) ;
- une contrainte en plusieurs chaînes sur plusieurs lignes ne se réécrit pas ;
- une indirecte qui ne s'épingle pas monte à la plus haute version permise ;
- une gem retirée est « inconnue du registre », sans raison (l'index ne la liste plus) ;
- `gemspec path:` vers un autre dossier est lu avec son propre projet ;
- `vendor/cache` n'est pas refait ;
- sous une directive `ruby` sans section `RUBY VERSION`, Bundler y écrit le Ruby de la
  machine (dit après coup).

### Java (Maven, Gradle)

**Ni Maven ni Gradle ne sont lancés.** Il n'y a pas de lockfile à régénérer : la mise à jour
s'arrête à la réécriture des fichiers (« Aucun lockfile à régénérer : les manifestes réécrits
suffisent. »). Relancez ensuite le build du projet.

**Fichiers lus, Maven** : `pom.xml`, dans l'ordre de ses balises, et chacun de ses
`<profiles>` : `<dependencies>`, `<dependencyManagement>` (et les BOM importés), `<build>`
(plugins, `<pluginManagement>`, `<extensions>`), `<parent>`. Un `${propriété}` se lit dans les
`<properties>` du `pom.xml` ou d'un parent du dépôt (`<relativePath>`, `../pom.xml` par
défaut). Un parent distant (`spring-boot-starter-parent`) et les BOM importés sont des
dépendances : leur version se met à jour.

**Fichiers lus, Gradle** : `build.gradle` et `build.gradle.kts` (lus en jetons : un script est un
programme), `settings.gradle(.kts)` (`plugins`, `pluginManagement`, et les autres catalogues de
`versionCatalogs`), le catalogue `gradle/libs.versions.toml`, `gradle.properties`, et les
verrous `gradle.lockfile` (versions installées et indirectes). Les formes courantes :
`implementation("g:a:v")`, `platform(…)`, la notation en carte, `id("x") version "v"`, les
versions riches (`strictly`, `require`, `prefer`). Une variable (`$v`, `${v}`) se cherche dans
le script (`val`, `def`, `ext`, `extra`), dans les `ext` des scripts parents, puis dans
`gradle.properties`.

**Registres** : Maven Central (`https://repo1.maven.org/maven2`, son `maven-metadata.xml`),
Google Maven (`https://dl.google.com/android/maven2`) pour `androidx.*`, `com.android.*`,
`com.google.android.*`, `com.google.firebase` et `com.google.gms`, et le portail des plugins
Gradle (`https://plugins.gradle.org/m2`) pour un plugin. Le `pom` d'un artefact dit s'il est
déplacé (`<relocation>` : une dépréciation, avec le remplaçant).

**Réécriture** : là où la version est écrite. Le texte de `<version>`, la valeur de la propriété
qu'elle cite (dans le `pom.xml` parent si elle y est), l'entrée `[versions]` du catalogue, la
variable d'un script, la ligne de `gradle.properties`. Une version partagée par plusieurs
dépendances n'est réécrite qu'une fois, et le plan le dit (« Version partagée avec … : elle
monte aussi. »). Une version nue devient la version visée telle que la publie le dépôt
(`30.1-jre` → `33.7.2-jre`) ; `V!!` (Gradle) garde ses `!!`, `[V]` aussi ; un intervalle prend
la version visée pour borne basse (`[1.9,2.0)` → `[2.3.1,3.0)`) ; `1.+` garde sa précision.

**Particularités** :

- **une version gérée par un parent ou un BOM distant** : forceupdate lit le `pom` de ce parent
  ou de ce BOM (et leurs parents, leurs imports), comme Maven construit le modèle, pour
  connaître la version qu'il impose et la vérifier. Sa mise à jour est celle du parent ou du
  BOM : elle est « à la main », jamais cochée (« version gérée par … : la changer avec lui, ou
  écrire la <version> voulue ») ;
- les variantes ne se mélangent pas : une version `-jre` de Guava ne devient jamais `-android` ;
- un module du même build (`${project.version}`), `<scope>system`, un plugin sans version
  (Maven en choisit une) ne sont pas vérifiables ;
- `gradle.lockfile` donne les versions installées, mais n'est jamais régénéré (Gradle exécute
  les scripts du projet). Une remarque le dit : « Après une mise à jour, les refaire (gradle
  dependencies --write-locks), sinon le build échoue. »

**Limites** :

- Gradle peut résoudre plus haut que la version écrite (la plus haute l'emporte) ;
- les verrous `buildscript-gradle.lockfile` et `gradle/dependency-locks/` ne sont pas lus ;
- un `kotlin("stdlib")` sans version est ignoré ; les constantes de `buildSrc`, un catalogue
  publié (`from("g:a:v")`) ne sont pas lus ; les entrées d'un autre catalogue que `libs` sont
  `runtime` ;
- une variable définie deux fois autrement, une expression (`${deps.x}`), une concaténation, une
  version Maven faite de plusieurs propriétés (`${a}.${b}`) : non vérifiables ou à réécrire à
  la main ;
- pour un BOM importé, `${project.version}` est celle du BOM ; les profils d'un `pom` distant
  ne sont jamais lus ; 120 `pom` distants au plus par analyse ;
- l'ordre des versions de Gradle diffère un peu de celui de Maven (`1.1.0` > `1.1` pour
  Gradle) : celui de Maven sert pour les deux.

### .NET (NuGet)

**MSBuild n'est jamais lancé** pour lire un projet. **Fichiers lus** :

- les projets `*.csproj`, `*.fsproj`, `*.vbproj` : `<PackageReference>` (version en attribut ou
  en élément), `VersionOverride`, les propriétés, les SDK de projet (`Sdk="Nom/Version"`) ;
- avant le projet, comme MSBuild, le `Directory.Build.props` le plus proche puis le
  `Directory.Packages.props` le plus proche ; après lui, le `Directory.Build.targets` le plus
  proche (dont `PackageReference Update=`) ;
- la gestion centrale (`ManagePackageVersionsCentrally`) : `<PackageVersion>`,
  `<GlobalPackageReference>` ;
- `packages.config` (l'ancien format : sa version est l'installée ; `allowedVersions` donne
  des versions jamais proposées) ;
- `packages.lock.json` (`RestorePackagesWithLockFile`) ; `msbuild-sdks` de `global.json`.

**Registre** : nuget.org, son API « registration »
(`https://api.nuget.org/v3/registration5-gz-semver2/{id}/index.json`), versions non listées
comprises : une version que son auteur a retirée de la liste est « retirée », comme sur PyPI ;
la dépréciation d'une version donne son remplaçant. Les noms ne tiennent pas compte de la
casse.

**NuGet prend la plus basse version qui convient.** Une version nue est un minimum (`>= V`), et
c'est elle que NuGet installe. Une mise à jour réécrit donc toujours la borne basse ; régénérer
ne fait rien monter, sauf une version flottante.

**Réécriture** : là où la version est écrite : l'attribut `Version`, la valeur d'une propriété
`$(X)`, `VersionOverride`, la `PackageVersion` centrale (réécrite une fois pour tous les
projets), `packages.config`. Une version nue devient la version visée, à la même précision si
elle s'y écrit (`1.0` → `2.0`) ; `[V]` ; un intervalle prend la version visée pour borne basse,
incluse (`(,2.0]` → `[1.5.3,2.0]`) ; une version flottante garde sa précision (`1.*` → `2.*`).

**Lockfile** :

```
dotnet restore <projet> --force-evaluate -noAutoResponse -p:RestoreLockedMode=false
```

Le projet est nommé (un dossier peut aussi avoir une solution). `--force-evaluate` fait monter
une version flottante, et ne change rien d'autre. `-noAutoResponse` écarte le
`Directory.Build.rsp` du projet (ses options, ses loggers) ; `-p:RestoreLockedMode=false` lève
le mode verrouillé, qui refuserait de changer le lockfile. Le lockfile d'un autre projet qui lit
une version réécrite (`Directory.Packages.props`) est régénéré aussi (« Directory.Packages.props
a changé »). Sans `packages.lock.json`, rien n'est régénéré. Un `dotnet` sans SDK (les runtimes
seuls, `dotnet --list-sdks` vide) compte comme un outil absent.

**Ce qui s'exécute** : `dotnet restore` évalue le projet avec MSBuild : une cible du projet ou
de ses `Directory.Build.targets` accrochée à la restauration s'exécute, comme un SDK de projet
venu de NuGet. Il écrit aussi le dossier `obj/` du projet. Ni bannière, ni télémétrie, ni
certificat de développement, ni processus MSBuild laissé ensuite.

**Particularités** :

- une indirecte en faille ne monte pas en régénérant : elle est ajoutée au projet (voir
  « Une indirecte NuGet ajoutée au projet ») ;
- un `global.json` qui demande un SDK absent fait échouer `dotnet` (le plan le dit) ;
- un projet de tests (`IsTestProject`, `Microsoft.NET.Test.Sdk`) est en `dev`,
  `PrivateAssets="all"` en `build`.

**Limites** :

- les conditions MSBuild (`Condition="…"`, `<Choose>`) ne sont pas évaluées : une référence
  conditionnelle est lue comme toujours présente (une remarque le dit) ; une propriété définie
  sous condition n'est pas vérifiable ;
- les imports autres que les `Directory.*.props` et `Directory.Build.targets` ne sont pas lus,
  ni un `Update="@(…)"`, ni `PackageDownload`, ni un lockfile au nom propre
  (`NuGetLockFilePath`) ;
- une `PackageVersion` déjà là pour une indirecte : à écrire à la main.

## Particularités de la mise à jour

### Le npm du projet

Un `package-lock.json` régénéré par le npm de la machine peut être refusé par la CI du projet.
Vu en vrai : npm 11 (Node 24) retire du lockfile des paquets facultatifs que npm 10 exige, et
`npm ci` d'une CI en Node 22 (npm 10) refuse alors le lockfile (« Missing: … from lock file »).
npm 10 et npm 11 se disputent aussi les `"peer": true`.

**D'où il se lit**, dans cet ordre (le premier qui dit quelque chose décide) :

1. `packageManager` du `package.json` (`npm@10.9.0`) ; un autre gestionnaire (`pnpm@…`,
   `yarn@…`) : rien à dire, l'outil suit lui-même cette version ;
2. `devEngines.packageManager`, puis `engines.npm` : une plage, que le npm installé respecte ou
   non ;
3. le Node.js choisi par le projet : `.nvmrc`, `.node-version`, `volta`, `.tool-versions`, un
   `FROM node:22`, la `node-version` de `actions/setup-node` dans `.github/workflows/`, l'`image`
   de `.gitlab-ci.yml` ou de `bitbucket-pipelines.yml`. Le plus ancien compte : un lockfile
   qu'accepte le npm le plus ancien est accepté des autres. Il donne le npm livré avec ce Node
   (Node 22 : npm 10 ; Node 24 : npm 11 ; relevé sur nodejs.org) ; une version partielle
   (`22`) vaut la dernière de sa ligne, comme pour `actions/setup-node` ;
4. `engines.node` : seulement si le Node installé ne la respecte pas.

`npm --version` n'est demandé que si le projet dit quelque chose.

**Si la majeure diffère** de celle du npm installé, le plan propose une case, **cochée
d'office** :

```
package-lock.json npx -y npm@10 install --package-lock-only --ignore-scripts
                  [x] Régénérer avec npm 10, celui du projet : npm 11.6.2 ici ; le projet
                  attend npm 10 : Node.js 22, lu dans .github/workflows/ci.yml
                  (actions/setup-node : node-version 22). …
```

Le lockfile est alors régénéré par `npx -y npm@10`, sans toucher au npm de l'ordinateur (npx
télécharge le dernier npm 10 dans son cache la première fois), puis **relu** par ce npm :
`npx -y npm@10 ci --dry-run --ignore-scripts --no-audit --no-fund`, qui n'installe rien. Le
résultat dit « Relu par … : accepté. », ou ce que `npm ci` reproche, avec la commande qui le
reproduit. Un refus n'est pas un échec : le lockfile reste régénéré (par le npm qu'attend le
projet, c'est le meilleur qu'on ait).

- `--no-extras` décoche la case : le npm de la machine régénère le lockfile. Dans
  l'interface, la case se décoche à l'étape « Vérifier » de l'écran de mise à jour ;
- **pour une PR, la case est toujours faite** : c'est la CI du dépôt qui recevra le lockfile ;
- un projet qui attend npm 7 ou moins : rien n'est lancé (npm 7 réécrirait le lockfile au
  format 2, npm 6 au format 1), le plan le dit ; sans `npx`, le plan le dit aussi.

**Limites** : un élagage propre à une version de npm (11.6.2, refusé par 11.16 aussi) n'est
pas vu, la majeure étant la même ; une CI qui a plusieurs projets (`working-directory`) donne
son Node à tous ; `node-version-file` n'est pas suivi (le `.nvmrc` est déjà lu) ; Node 27 et
plus ne sont pas encore connus (rien n'est dit).

### Les `requirements.txt` générés

Un `requirements.txt` sans `.in` à côté peut être généré par un outil. forceupdate le
reconnaît, et le traite comme un lockfile du projet (ses paquets ne sont plus des directes) :

| Ce qui le reconnaît | Ce que c'est | Comment il est refait |
|---|---|---|
| l'en-tête `# uv pip compile …` ou `# pip-compile …` qui compile `pyproject.toml`, `setup.cfg` ou `setup.py` | le lockfile de ce manifeste | recompilé par sa commande, avec `-P nom==version` |
| l'en-tête de `uv export` (« autogenerated by uv via the following command ») | l'export de `uv.lock` | `uv export` avec les options de l'en-tête, après `uv.lock` |
| l'en-tête de PDM (`# This file is @generated by PDM.`) | l'export de `pdm.lock` | `pdm export -o requirements.txt` (`--no-hashes`, `--prod` d'après le contenu), après `pdm.lock` |
| pas d'en-tête, mais toutes ses lignes figées (`==`) aux versions du lockfile du projet | l'export de `poetry.lock` (`poetry export` n'écrit pas d'en-tête) | `poetry export -f requirements.txt -o requirements.txt` (`--without-hashes`, `--with dev` d'après le contenu), après `poetry.lock` |

Une remarque le dit (« généré depuis uv.lock (uv export) : il en a les versions, et se
régénère après lui. »). Un export se refait dans le même groupe que son lockfile : si l'un
échoue, les deux sont remis. Son en-tête ne change pas. Un export dont le lockfile n'est pas
dans le projet reste lu comme un `requirements` écrit à la main (une remarque le dit).

**`poetry export` demande le plugin `poetry-plugin-export`** à Poetry 2. Sans lui, la commande
échoue, et le lockfile est remis comme avant avec ses manifestes (le plan le dit).

**Limites** : un export Poetry fait avec d'autres groupes que `dev`, ou un export PDM fait avec
d'autres options, se refait autrement (PDM n'écrit pas sa commande, Poetry pas d'en-tête).

### Une ligne à empreintes (`--hash`)

Une ligne de `requirements` qui porte des `--hash` n'est jamais réécrite : ce sont les
empreintes de la version actuelle, et pip refuserait d'installer la nouvelle. La mise à jour est
proposée « à la main », jamais cochée : « ligne 3 à empreintes (--hash) : ce sont celles de la
version actuelle, à réécrire à la main avec celles de la nouvelle (pip refuserait
d'installer). » Un fichier `-c constraints.txt` à empreintes n'est refusé qu'à la réécriture
(dans « Pas appliquées »).

### Une indirecte NuGet ajoutée au projet

NuGet garde une indirecte à la plus basse version que demandent ceux qui la tirent : régénérer
ne la fait pas monter. Pour corriger une faille, forceupdate l'ajoute au projet MSBuild du
dossier de son lockfile :

- sans gestion centrale : `<PackageReference Include="nom" Version="V" />` dans le projet ;
- avec la gestion centrale : `<PackageVersion Include="nom" Version="V" />` dans le
  `Directory.Packages.props`, et **l'épinglage transitif**
  (`<CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled>`, sous
  `ManagePackageVersionsCentrally`) s'il n'y est pas : une version centrale vaut alors aussi pour
  les indirectes. Si le projet l'a mis à `false`, une `PackageReference` sans version est ajoutée
  au projet à la place.

L'élément va après le dernier de sa sorte, à son indentation et avec les fins de ligne du
fichier, sinon dans un nouvel `<ItemGroup>`. Le fichier est relu comme les autres. L'option se
coche comme une autre correction, avec l'avertissement : « NuGet ne fait pas monter une
indirecte seul (il prend la plus basse version qui convient) : elle est ajoutée au projet, par
une référence ou une version centrale. » Avec la gestion centrale, les lockfiles de tous les
projets qui lisent ce `Directory.Packages.props` sont régénérés : l'épinglage peut changer les
leurs. Une `PackageVersion` déjà là pour ce paquet : à écrire à la main.

### `go mod vendor`

Un module qui a un dossier `vendor/` (`vendor/modules.txt`) : après `go mod tidy`, `go build`
refuse un `vendor/modules.txt` périmé (« inconsistent vendoring »). Le plan propose une case,
cochée d'office : « Refaire vendor/ (go mod vendor) ». forceupdate copie `vendor/` dans un
dossier temporaire, lance `go mod tidy` puis `go mod vendor` (rien n'est compilé), et remet
`vendor/` tel qu'il était si une commande échoue. `vendor/` compte dans le garde-fou git et dans
le commit d'une PR. Décochée (`--no-extras`), le résultat dit de lancer `go mod vendor` après la
mise à jour.

### Composer 2.9 et les failles

Composer 2.9 et plus refuse, pendant un `composer update`, toute version qui a encore un avis de
sécurité (`config.policy.advisories.block`, vrai par défaut). Une mise à jour partielle qui garde
une version vulnérable (une correction qui ne règle pas toutes les failles) échouerait.

- **Composer 2.10 et plus** : forceupdate lève ce blocage le temps de la régénération, pour les
  failles seulement (`COMPOSER_POLICY_ADVISORIES_BLOCK=0`) ; les logiciels malveillants restent
  bloqués. C'est la sélection vérifiée par forceupdate qui s'applique, et le plan montre les
  failles qui restent. Si le projet règle lui-même le blocage (`config.policy`,
  `config.audit.block-insecure`) ou si la variable est déjà dans l'environnement de la personne,
  forceupdate n'y touche pas ;
- **Composer 2.9** n'a ni variable ni option : le blocage ne se lève que dans `composer.json`
  (`config.audit.block-insecure` à `false`), où forceupdate ne touche pas. D'après
  `composer --version`, le plan prévient : une version visée qui garde une faille fait échouer
  la régénération, et tout est remis ;
- avant 2.9, rien ne bloque.

### Le garde-fou git

`forceupdate update` refuse d'écrire si l'un des fichiers qu'il touchera (manifestes réécrits,
lockfiles régénérés, `vendor/` refait) a des changements que git n'a pas en commit : modifié,
ajouté à l'index sans commit, ou pas suivi. La réécriture mêlerait sinon ses changements à ceux
de la personne, et `git checkout` ne permettrait plus de revenir en arrière :

```
forceupdate update : package.json : des changements que git n'a pas en commit. Les commiter (ou
les mettre de côté) d'abord, ou relancer avec --force.
```

Code de retour 2. `--force` écrit quand même. Hors d'un dépôt git, une ligne le dit (« Pas de
dépôt git ici : rien ne permettra de revenir en arrière. »), et l'écriture se fait. Dans
l'interface, le même garde-fou s'affiche à l'étape « Vérifier », avec « Appliquer quand même… »
et un dialogue de confirmation.

Entre le diff et l'écriture, chaque fichier est relu : s'il a changé, rien n'est écrit
(« … a changé depuis le calcul du diff : rien n'est écrit, relancer la mise à jour. »).

### Un outil absent

Si l'outil d'un lockfile n'est pas installé, les manifestes sont quand même réécrits, et la
commande à lancer est donnée, avec son dossier :

```
web/package-lock.json : à régénérer, npm n'est pas installé : « npm install --package-lock-only
--ignore-scripts » dans web.
```

Ce n'est pas une erreur (code 0). Le plan le dit déjà avant de confirmer.

### Sur un échec

Les lockfiles qui dépendent des mêmes fichiers forment un groupe (un `.txt` de pip-tools et
celui qui le cite, un lockfile et son export, les lockfiles NuGet d'un même
`Directory.Packages.props`). Avant de lancer un groupe, ses fichiers sont gardés. Si un outil
échoue (conflit de versions, délai dépassé, programme qui ne se lance pas) :

- **tout le groupe est remis comme avant** : les manifestes réécrits tels qu'avant leur
  réécriture, les lockfiles et le reste tels qu'avant la régénération, `vendor/` compris ;
- les autres groupes ne bougent pas ;
- le résultat garde les 12 dernières lignes de l'outil, et dit ce qui a été remis :

```
package-lock.json : échec de npm ; remis comme avant : package-lock.json, package.json.
   « npm install --package-lock-only --ignore-scripts --no-audit --no-fund » a échoué (code 1) :
   npm error ERESOLVE could not resolve
   …
```

Un autre lockfile du groupe : « pas régénéré, package-lock.json a échoué ». Code de retour 2.

### Les majeures

Avec la sélection par défaut (`--level minor`), une majeure est proposée, jamais cochée :
« Majeure : peut demander d'adapter le code. » Une faille que seule une majeure corrige est
proposée de même, avec les deux mentions. En 0.x, ce qui sort de `^` est une majeure
(`0.2.3` → `0.3.0`). Une indirecte majeure ajoute : « Dépendance indirecte : le paquet qui la
tire devra peut-être monter aussi. »

`--level major` (ou `level = "major"` dans la sélection de `forceupdate.toml` ou des réglages)
les fait cocher. Une majeure Go publiée sous un autre module reste toujours « à la main ».

### Une version qui apporte une faille

Toutes les versions proposées sont soumises à OSV, en une requête. Une version qui a une faille
que la version utilisée n'a pas est dite (« Faille connue dans cette version : CVE-… »), et
**n'est jamais cochée d'office**, quelles que soient les options. Si OSV ne répond pas, les
options restent, et une remarque le dit (« Failles non vérifiées pour 4 versions proposées. … »).

## Fins de vie et runtimes

forceupdate lit la version de chaque runtime d'un projet (Python, Node.js, Go, Ruby, PHP, Java,
.NET, Rust), **sans rien exécuter**, et la juge d'après [endoflife.date](https://endoflife.date).
Il s'en sert deux fois :

- pour dire qu'un runtime, ou un framework, est en fin de vie ou le sera bientôt (le constat
  « fin de vie ») ;
- pour ne pas proposer une version de paquet que ce runtime ne fait pas tourner.

Un runtime n'est jamais mis à jour par forceupdate : il est seulement signalé. Un framework, lui,
monte comme toute autre dépendance.

### Où chaque runtime est lu

forceupdate distingue deux sortes de versions :

- **une version choisie**, celle qui tourne : `.python-version`, `.nvmrc`, un `FROM` de
  `Dockerfile`, la version d'une CI ;
- **une borne basse**, ce qu'un manifeste accepte : `requires-python = ">=3.8"` dit « au moins
  3.8 ». Le rapport l'écrit « Python 3.8 et plus ».

Dans les manifestes (une contrainte donne sa borne basse ; une contrainte qui fixe une version
exacte, comme `ruby "3.2.2"`, et les champs marqués « choisie » donnent une version choisie) :

| Runtime | Lu dans |
|---|---|
| Python | `requires-python` de `[project]` (et du bloc PEP 723 d'un script), `python` de `[tool.poetry.dependencies]`, `python_requires` de `setup.cfg` ; `[requires]` du `Pipfile` (`python_version`, `python_full_version` : choisie) |
| Node.js | `engines.node` du `package.json` ; `volta.node` (choisie) |
| Go | la directive `go` de `go.mod` ou `go.work` ; `toolchain` (choisie) |
| Ruby | `ruby "…"` du `Gemfile` ou de `gems.rb` ; `required_ruby_version` d'un `.gemspec` ; `RUBY VERSION` du `Gemfile.lock` (choisie) |
| PHP | `require.php` du `composer.json` ; `config.platform.php` (choisie) |
| Java | `maven.compiler.release`, `maven.compiler.target`, `maven.compiler.source`, `java.version` d'un `pom.xml` (ou de ses parents du dépôt) ; `targetCompatibility`, `sourceCompatibility` de Gradle ; `JavaLanguageVersion.of(17)` et `jvmToolchain(17)` (choisies) |
| .NET | `TargetFramework`, `TargetFrameworks` (`net8.0` : .NET 8 ; `netcoreapp3.1` ; `net48` : .NET Framework 4.8), `TargetFrameworkVersion` (`v4.7.2`), `Directory.Build.props` compris : des versions choisies. `netstandard2.0` n'est pas un runtime. Défini sous condition : chacune des valeurs écrites |
| Rust | `rust-version` de `[package]` du `Cargo.toml` (`rust-version.workspace = true` : celle de `[workspace.package]`) |

Dans les fichiers de version (des versions choisies) :

| Fichier | Ce qui est lu |
|---|---|
| `.python-version` (pyenv, uv) | la première ligne : `3.8.10`, `3.12`, `3.13t`, `cpython-3.12` ; pas `pypy3.9`, `system` |
| `runtime.txt` (Heroku) | `python-3.8.10` |
| `.nvmrc`, `.node-version` | `16`, `v16.20.2`, `lts/gallium` ; pas `lts/*`, `node`, `stable` |
| `.ruby-version` | `3.2.2`, `ruby-3.2.2` ; pas `jruby-9.4` |
| `.tool-versions` (asdf, mise) | `nodejs` (ou `node`), `python`, `ruby`, `golang` (ou `go`), `php`, `dotnet` (ou `dotnet-core`), `rust`, `java temurin-17.0.2+8` ; la première version de la ligne |
| `mise.toml`, `.mise.toml` | `[tools]` : `python = "3.11"`, une liste (la première), `{ version = "…" }`, `java = "temurin-17"` ; pas `latest`, `lts`, `prefix:3` |
| `global.json` | `sdk.version` : le SDK .NET |
| `rust-toolchain.toml`, `rust-toolchain` | `channel = "1.80.0"` ; pas `stable`, `nightly` |

Dans les `Dockerfile` (`Dockerfile`, `Dockerfile.*`, `*.Dockerfile`, `Containerfile`, sans tenir
compte de la casse), le `FROM` de chaque étape :

- les images officielles `python`, `node`, `ruby`, `php`, `golang`, `eclipse-temurin`,
  `amazoncorretto`, `openjdk` (dépréciée : lue comme Eclipse Temurin),
  `mcr.microsoft.com/dotnet/sdk`, `…/aspnet`, `…/runtime`, `…/runtime-deps` (et `…/core/…`),
  `mcr.microsoft.com/dotnet/framework/…` ;
- les mêmes écrites en entier (`docker.io/library/python`) ou prises d'une copie
  (`public.ecr.aws/docker/library/…`, `mirror.gcr.io/…`) ;
- des images non officielles qui suivent les mêmes versions : `bitnami/…` (`python`, `node`,
  `ruby`, `php-fpm`, `golang`, `java`, `dotnet`, `dotnet-sdk`, `aspnet-core`), `cimg/…` et
  `circleci/…` de CircleCI, `mcr.microsoft.com/devcontainers/…` (`1-3.11-bookworm` : Python
  3.11, le `1-` est la version de l'image).

Les `ARG` d'avant le premier `FROM` sont remplacés (`ARG NODE_VERSION=16` puis
`FROM node:${NODE_VERSION}-alpine` : Node.js 16). Les noms des LTS de Node.js sont compris
(`node:gallium`, `node:hydrogen-alpine`). Une étiquette sans version (`latest`, `lts`, `alpine`)
ne dit rien.

Dans la CI :

- **les workflows de GitHub Actions** (`.github/workflows/*.yml` et `*.yaml`) : la version
  qu'installe `actions/setup-node` (`node-version`), `actions/setup-python` (`python-version`),
  `actions/setup-go` (`go-version`), `actions/setup-java` (`java-version`, et sa `distribution`),
  `actions/setup-dotnet` (`dotnet-version`), `ruby/setup-ruby` (`ruby-version`) et
  `shivammathur/setup-php` (`php-version`) ; et l'image d'un `container`, lue comme un `FROM`.
  Une `matrix` donne chacune de ses valeurs (`include` compris) ; `${{ env.X }}` est remplacé
  (`env` du workflow, du job, de l'étape). `3.11`, `1.21.x`, `22`, `22.x`, `v20.10.0`, `lts/jod`
  se lisent ; `lts/*`, `latest`, `stable`, `3.x`, une plage ou une autre expression ne disent rien,
  ni un nombre seul pour Python, Go, Ruby, PHP ou .NET (`3` : toute une majeure) ;
- **`.gitlab-ci.yml` et `bitbucket-pipelines.yml`** : chaque `image` (une chaîne, ou son `name`),
  où qu'elle soit (le fichier, `default`, un job, une étape), lue comme un `FROM` ; les `variables`
  de premier niveau de GitLab sont remplacées.

Un exemple : un projet Python dont la CI teste 3.9 et 3.12, avec une image GitLab en 3.7 et un
`mise.toml` en 3.10 :

```
Projet .  (PyPI)
  manifestes : pyproject.toml
  lockfiles  : aucun
  runtimes   : Python 3.9 (.github/workflows/tests.yml), Python 3.12 (.github/workflows/tests.yml), Python 3.7 (.gitlab-ci.yml), Python 3.10 (mise.toml)
```

**À quel projet va un fichier.** Comme pyenv ou nvm, un projet prend le plus proche de chaque
fichier de version, dans son dossier ou au-dessus (dans ce qu'on analyse). Un `Dockerfile` va au
projet le plus proche, dans son dossier ou au-dessus ; sans projet au-dessus, à ceux d'en dessous
(le `Dockerfile` de la racine d'un dépôt dont le code est dans `app/`). Un fichier de CI vaut pour
tous les projets de son dossier (celui qui a le `.github/`) et d'en dessous. Un fichier pris dans
un autre dossier que celui du projet ne vaut que pour un projet de son écosystème : le `.nvmrc` de
la racine d'un monorepo ne donne pas Node.js au `backend/` Python.

**Où les voir.** La ligne « runtimes » du projet, dans le terminal et le Markdown, donne les
versions jugées pour la fin de vie (les versions choisies, sinon les bornes basses). La carte du
projet, dans l'interface, et le JSON (`runtimes` du projet) donnent toutes les versions lues, avec
leurs fichiers.

### La source : endoflife.date

Les cycles de vie viennent de l'API d'endoflife.date,
`https://endoflife.date/api/v1/products/{produit}`, pour les produits `python`, `nodejs`, `go`,
`ruby`, `php`, `eclipse-temurin`, `amazon-corretto`, `azul-zulu`, `dotnet` (.NET et .NET Core),
`dotnetfx` (.NET Framework), et ceux des frameworks. Une réponse est gardée 24 heures dans le
cache. Hors ligne (`--offline`), le cache sert même plus ancien.

Une erreur ne donne jamais de faux constat : endoflife.date injoignable, hors ligne sans cache, un
produit ou une version qu'il ne connaît pas donnent un « non concluant », un par produit et par
version :

```
non concluant Fin de vie de Python 3.8 non vérifiée. endoflife.date : mode hors ligne, et python n'est pas dans le cache.
```

Une fin de vie se juge **à la date du jour**, d'après la date qu'endoflife.date donne à chaque
cycle (la fin des correctifs de sécurité).

### Le cycle d'une version

La version lue se range dans le plus long cycle d'endoflife.date dont les nombres la commencent :
3.8.10 est dans le cycle 3.8 de Python, 16.20.2 dans le cycle 16 de Node.js. Une borne basse se
complète de zéros (`>=7` : 7.0). Une version plus récente que tous les cycles connus (une Python en
développement), ou moins précise qu'eux (l'image `python:3`, qui suit la dernière), ne donne pas
de constat.

Pour un même runtime, les versions choisies comptent plutôt que les bornes basses : avec un
`.python-version` en 3.8, le `requires-python = ">=3.8"` n'est pas jugé à part. Chaque cycle
distinct donne son constat (une CI qui teste 3.9 et 3.12 : 3.9 est jugée, 3.12 aussi).

### Le constat

Un constat « fin de vie » dans deux cas :

- la fin de vie est **passée** (gravité moyenne) ;
- elle arrive **dans moins de 6 mois** (gravité faible).

Il dit le cycle, la date, d'où vient la version, et le cycle conseillé :

```
fin de vie Python 3.8 : fin de vie depuis le 07/10/2024. Lu dans .python-version : 3.8. Cycle conseillé : 3.15, dernière version 3.15.2.
fin de vie Node.js 16 : fin de vie depuis le 11/09/2023. Lu dans .nvmrc : 16. Cycle conseillé : 26 (LTS), dernière version 26.13.0.
fin de vie Node.js 22 : fin de vie le 30/04/2027, dans moins de 6 mois. Lu dans .tool-versions : nodejs 22. Cycle conseillé : 26 (LTS), dernière version 26.13.0.
```

Une borne basse est dite comme telle : « Lu dans pyproject.toml : requires-python = ">=3.8" (au
moins 3.8) ». Un cycle fini sans date connue : « en fin de vie (endoflife.date n'en donne pas la
date) ».

Une fin de vie compte parmi ce qui est « à mettre à jour », et pour `--fail-on major` et
`--fail-on any`. Dans l'interface, le rapport a une section « Fins de vie » : chaque cycle, sa
date, d'où vient la version, le cycle conseillé et s'il est à support long.

### Le cycle conseillé

Parmi les cycles publiés, encore maintenus et plus récents que celui utilisé : ceux qui ne
finissent pas dans les 6 mois (s'il n'y en a pas, tous ceux-là), et parmi eux le plus récent à
support long (LTS) s'il y en a, sinon le plus récent. Exemples : Django 3.2 → 5.2 (LTS), pas 6.1 ;
Django 6.0 → 6.1 ; Node.js 16 → 26 (LTS) ; Python 3.8 → 3.15. Le constat donne aussi la dernière
version de ce cycle.

Sans cycle maintenu à conseiller, une fin de vie passée le dit (« Aucun cycle maintenu à
conseiller. ») ; une fin prochaine sans cycle plus récent (le dernier cycle d'Electron : chacun
ne vit que 8 mois) n'est pas un constat : il n'y a rien de mieux à faire.

### Les frameworks

Une dépendance de la table des frameworks a aussi sa fin de vie, d'après sa version utilisée.
La table compte 56 produits d'endoflife.date :

| Écosystème | Frameworks |
|---|---|
| PyPI | Django, Wagtail, NumPy, Apache Airflow |
| npm | Angular (`@angular/core`), AngularJS (`angular`), Vue, Nuxt, Next.js, React, React Native, Svelte, Electron, Express, NestJS, Ember (`ember-source`), jQuery, jQuery UI, Bootstrap, Tailwind CSS, Ionic, Vuetify, Quasar, Strapi, AdonisJS, ESLint, Protractor, Font Awesome |
| Packagist | Laravel, Symfony (`symfony/symfony` et ses composants qui suivent ses versions : `symfony/console`, `symfony/http-kernel`…), Drupal, TYPO3, CakePHP, Magento, Shopware, Sylius, API Platform, Livewire, Behat, Guzzle, Bootstrap |
| RubyGems | Rails (`rails`, `railties`) |
| Maven | Spring Boot (`org.springframework.boot:*`), Spring Framework, Spring Security, Spring Cloud, Hibernate ORM, Log4j, Micronaut, Quarkus, Apache Struts, Jetty, Tomcat, Apache Camel, Keycloak, Apache Groovy |
| NuGet | ASP.NET Core (`Microsoft.AspNetCore.*`, `Microsoft.NETCore.App` : le cycle de .NET), jQuery, Bootstrap |

- Un constat par produit et par cycle dans un projet, sur la première de ses dépendances : les
  starters de Spring Boot, les composants de Symfony ne le répètent pas.
- Seules les dépendances vérifiées sont jugées : les directes (les indirectes avec
  `--transitive`), pas un paquet ignoré.
- Le framework monte comme les autres dépendances. Le plan propose en plus la dernière version du
  cycle conseillé (« cycle conseillé (fin de vie) »), à côté de la dernière tout court : pour
  Django 3.2 sous un Python récent, 5.2.18 à côté de 6.1.2. Elle n'est proposée que si elle est
  publiée sous ce nom, et si le runtime du projet la fait tourner. Sinon, le constat le dit :

```
fin de vie django : Django 3.2 : fin de vie depuis le 01/04/2024. Cycle conseillé : 5.2 (LTS), dernière version 5.2.18, qui demande Python >=3.10 ; le projet : 3.8 et plus (pyproject.toml). Changer de Python d'abord.
```

### Les versions que le runtime du projet ne fait pas tourner

Certains registres disent, pour chaque version d'un paquet, le runtime qu'elle demande :

| Écosystème | Ce que dit le registre | Qui écarte déjà ces versions |
|---|---|---|
| npm | `engines.node` | `npm outdated` (d'après le Node installé ; `npm install` avertit seulement) |
| PyPI | `requires-python` (l'API « simple ») | uv, Poetry, PDM (d'après tout le `requires-python` du projet) |
| Packagist | `require.php` | Composer (d'après `config.platform.php`, sinon le PHP de la machine) |
| RubyGems | `required_ruby_version` (l'index compact) | Bundler (d'après le Ruby qui tourne) |
| crates.io | `rust_version` | Cargo, résolveur 3 (d'après le `rust-version` du projet) |

Go, Maven et NuGet ne le disent pas : rien n'y est écarté.

Proposer une telle version ferait échouer la régénération du lockfile (ou casserait ce que le
projet promet de faire tourner). Elle n'est donc **jamais proposée** : ni comme version plus
récente, ni comme option du plan, ni pour corriger une faille, ni pour remplacer une version
dépréciée, ni comme dernière version du cycle conseillé. Le constat vise la plus haute qui
convient, et dit la plus récente écartée :

```
Version 4.2.30 disponible (majeure) ; utilisée : 3.2.25. La 6.1.2 n'est pas proposée : elle demande Python >=3.12 ; le projet : 3.8 et plus (pyproject.toml).
Version 4.0.0 disponible (majeure) ; utilisée : au moins 3.1.0 d'après la contrainte (pas de version installée). La 7.3.3 n'est pas proposée : elle demande Node.js >=20 ; le projet : 16 et plus (package.json).
```

Si aucune version plus récente ne convient, le constat cite la dernière sans la proposer (« Elle
n'est pas proposée : … »), et la colonne « Permise » reste vide. Si seule une version écartée
corrige toutes les failles, le plan le dit : « La correction de toutes ses failles (…) n'est pas
proposée : elle demande … ».

Le tableau d'un projet ne donne que les versions : dans le terminal et le Markdown (et donc la
description d'une PR), un constat qui écarte une version est aussi écrit sous le tableau, dans
« Détails » ; dans l'interface, dans le détail du paquet ; dans le JSON, son champ `blocked`.

**Le runtime du projet** est le plus ancien de ceux lus pour l'écosystème, versions choisies et
bornes basses comprises, CI comprise. C'est le plus prudent : uv résout pour toutes les versions
qu'accepte `requires-python`, même si `.python-version` en choisit une plus récente ; un `^8.1`
promet PHP 8.1 ; une CI en Node 18 refuserait une version qui demande Node 20. Une version choisie
partielle (`.nvmrc` : `16`) vaut la dernière de sa ligne (16.x), une borne basse (`>=16`) vaut
16.0.0. Sans runtime lu, rien n'est écarté.

**Rust.** Le `rust-version` du projet (ou le `channel` de son `rust-toolchain.toml`) écarte les
versions d'un crate qui demandent un Rust plus récent, quel que soit le résolveur : c'est la
promesse du projet. La version « permise » (ce que la contrainte accepte déjà) suit le résolveur 3
de Cargo (édition 2024, `resolver = "3"`) : la plus haute qui convient, sinon la plus haute. Sous
le résolveur 2 (édition 2021 et avant), `cargo update` prendrait la plus haute de toute façon.
Rust n'a pas de constat de fin de vie : chaque version n'est suivie que six semaines, jusqu'à la
suivante, et `rust-version` est la plus ancienne que le projet promet, pas celle qui tourne. Il
n'est donc pas sur la ligne « runtimes » du terminal et du Markdown (mais il est dans la carte du
projet et dans le JSON).

### Java, d'après Eclipse Temurin

Java a plusieurs distributions, aux cycles différents. forceupdate juge Java d'après **Eclipse
Temurin**, la distribution de référence d'OpenJDK, sauf quand une autre est nommée :

| Lu | Jugé d'après |
|---|---|
| un `pom.xml`, un script Gradle ; les images `eclipse-temurin`, `openjdk`, `bitnami/java`, `cimg/openjdk`, `circleci/openjdk`, `mcr.microsoft.com/devcontainers/java` ; `temurin-17`, `adoptopenjdk-17`, `openjdk-17` dans `.tool-versions` ou `mise.toml` (et `java = "17"` dans `mise.toml`) ; `actions/setup-java` avec `distribution: temurin`, `adopt…`, ou une distribution autre que les deux ci-dessous | Eclipse Temurin |
| l'image `amazoncorretto` ; `corretto-17` (`.tool-versions`, `mise.toml`) ; `distribution: corretto` | Amazon Corretto |
| `zulu-17` (`.tool-versions`, `mise.toml`) ; `distribution: zulu` | Azul Zulu |

Une autre distribution nommée dans `.tool-versions` ou `mise.toml` (`oracle-17`…) n'est pas lue.

Le JDK installé sur la machine n'est jamais lu : un `pom.xml` en Java 11 est jugé comme Temurin
11, quel que soit le JDK qui le construit.

### Limites

- La table des frameworks et les noms des LTS de Node.js (`lts/gallium`…) sont tenus à la main
  (un test réseau les compare à endoflife.date et à nodejs.org) : un framework absent de la table
  n'a pas de fin de vie.
- Les images non officielles autres que celles listées plus haut ne sont pas lues ; une image
  `openjdk` est lue comme Eclipse Temurin.
- Le Java réel de la machine n'est pas lu.
- `node-version-file` (et les autres `*-version-file` des actions `setup-*`) n'est pas suivi :
  le `.nvmrc` est déjà lu directement. Une CI qui sert à plusieurs projets (`working-directory`)
  donne ses versions à tous les projets de son dossier. Les `variables` d'un job GitLab ne sont
  pas remplacées (celles du fichier, oui).
- Un `TargetFramework` calculé (`$(…)`) n'est pas lu ; sous condition, toutes ses valeurs écrites
  le sont, sans évaluer la condition.
- Rust : sans `rust-version` ni `rust-toolchain`, la version de `rustc` n'est pas connue
  (forceupdate ne lance pas `rustc`) ; `[resolver] incompatible-rust-versions` n'est pas lu.
- Un fichier de version au-dessus du dossier analysé n'est pas vu : analyser un sous-dossier
  d'un dépôt ne lit pas le `.nvmrc` de sa racine (sauf pour un fichier de code, dont la source est
  le dépôt git entier).
- Sur une forge, chaque workflow de GitHub Actions est une requête de plus à la forge.

## Un fichier de code

On peut choisir un fichier de code (`app.py`, `index.ts`, `main.go`…), en ligne de commande
(`forceupdate scan app.py`, `forceupdate update app.py`) comme dans l'interface : choisi dans la
liste des dossiers (écran 2), il est désigné par son chemin, comme en ligne de commande ; déposé,
ou choisi par « Choisir un fichier », il est envoyé au serveur et n'a jamais de projet autour.
Trois cas, que le rapport dit en tête :

| Cas | Ce qui est analysé | Ce que dit le rapport |
|---|---|---|
| le fichier est dans un projet | le projet | « Fichier de code app/__init__.py : analysé via pyproject.toml, le projet qui le contient. » |
| un script Python à bloc PEP 723 | son bloc, son propre manifeste | « Script pep723.py : son bloc PEP 723 (« # /// script ») tient lieu de manifeste, comme pour uv run. » |
| aucun des deux | ses imports, sans version | « Fichier de code imports.py, sans projet autour : ses imports, sans version. Les failles ne sont pas vérifiables sans version. » |

### Dans un projet : la remontée

forceupdate remonte les dossiers, depuis celui du fichier, jusqu'au premier qui a **un manifeste
de son écosystème** : un `.py` passe un `package.json`, un `.ts` passe un `pyproject.toml`. Un
fichier d'un langage sans écosystème connu prend le premier manifeste venu. Un lockfile seul n'est
pas un projet ; un `requirements/*.txt` en est un.

La remontée s'arrête :

- à la racine du dépôt git (dont le manifeste compte encore) ;
- à la racine du disque ;
- **avant le dossier personnel** : un `package.json` laissé par erreur dans `~` n'en fait pas un
  projet (sinon tout `~` serait parcouru).

Sans manifeste trouvé, c'est le fichier seul qui est lu (son bloc PEP 723, ou ses imports).

Le projet trouvé est analysé comme si on l'avait choisi, seul, même s'il est rangé dans un
dossier de tests. La source est **le dépôt git qui le contient** : ses lockfiles de workspace, ses
`Directory.Packages.props`, ses `pom.xml` parents, son `.python-version` sont souvent au-dessus de
lui. Hors git, ou pour un projet rangé dans un dossier jamais parcouru (`node_modules/x`), c'est
le dossier du projet. La configuration (`forceupdate.toml`) est lue à la racine de cette source,
et les langages sont ceux du dossier du projet. `forceupdate update` met à jour le projet (ses
manifestes, ses lockfiles), jamais le fichier de code.

### Un script à bloc PEP 723

Un fichier `.py` ou `.pyw` qui a un bloc `# /// script` (la [métadonnée de script en
ligne](https://packaging.python.org/en/latest/specifications/inline-script-metadata/)) est **son
propre manifeste**, comme pour `uv run`, même dans un projet : le projet autour est ignoré, comme
uv l'ignore.

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "flask>=2.3",
#   "requests",
# ]
# ///
import flask
import requests
```

- `dependencies` donne les dépendances et leurs contraintes. Sans lockfile, la version utilisée
  est la borne basse (« ≈ 2.3 ») : une faille de cette version est une « faille possible ». Une
  dépendance sans contrainte (`requests`) est une « version non fixée » (plus bas).
- `requires-python` est le runtime du script : sa fin de vie est jugée, et les versions qu'il ne
  fait pas tourner ne sont pas proposées.
- `[tool.uv] exclude-newer` est suivi (plus bas).
- **Le lockfile du script**, `script.py.lock` à côté de lui (écrit par
  `uv lock --script script.py`), donne les versions installées et les dépendances indirectes. Une
  mise à jour le régénère par `uv lock --script script.py -P paquet==version`.
- `forceupdate update script.py` réécrit les contraintes du bloc, dans leur style, et rien
  d'autre du fichier. Un script envoyé à l'interface (déposé) ne s'écrit pas : sa version mise à
  jour se télécharge.

Un bloc mal formé est une remarque, sans repli sur les imports (uv refuse aussi le script) :

- « un bloc « # /// script » s'ouvre sans se fermer par « # /// » : chaque ligne du bloc, même
  vide, doit commencer par « # ». uv refuse ce script. »
- « plusieurs blocs « # /// script » : uv refuse ce script. »

### Sans projet : les imports

Les imports sont lus **sans jamais exécuter ni importer le fichier** : par le module `ast` de
Python pour Python, par des lexers pour JavaScript, TypeScript et Go.

| Fichiers | Ce qui est lu | Ce qui est écarté |
|---|---|---|
| Python (`.py`, `.pyw` ; pas `.pyi`) | `import a.b`, `from a.b import c`, et `importlib.import_module("x")` ou `__import__("x")` d'un nom écrit en clair | les imports relatifs ; la bibliothèque standard ; un module posé à côté du fichier (`util.py`, `util/__init__.py`, ou un dossier `util/` sans `__init__.py`) |
| carnet Jupyter (`.ipynb`) | les cellules de code, comme du Python | les lignes `%magie` et `!commande`, les cellules `%%magie`, une cellule qui ne se lit pas |
| JavaScript, TypeScript (`.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.mts`, `.cts`, `.tsx`) | `import … from "x"`, `import "x"`, `import("x")`, `export … from "x"`, `require("x")`, `import x = require("x")` : le paquet (`lodash/fp` → `lodash`, `@scope/a/b` → `@scope/a`) | `node:…` et les modules intégrés de Node (`fs`, `path`, `fs/promises`… ; un `test` nu est le paquet npm) ; un chemin (`./util`, `/abs`) ; un import interne (`#lib`) ; un alias (`@/…`, `~/…`, et ceux du `tsconfig.json` ou du `jsconfig.json` le plus proche : `compilerOptions.paths`, un module sous `baseUrl` comme `src/utils`) ; une adresse (`https:`, `bun:`…) |
| Vue, Svelte (`.vue`, `.svelte`) | leurs `<script>`, comme du JavaScript ou du TypeScript | le reste du composant |
| Go (`.go`) | les déclarations `import` qui suivent `package` | la bibliothèque standard (un premier élément sans point : `fmt`, `net/http`), `C` (cgo) |

Pour Python, la bibliothèque standard est celle du Python qui fait tourner forceupdate
(`sys.stdlib_module_names`), plus les modules retirés depuis 3.11 (`distutils`, `imp`,
`asyncore`, ceux de la PEP 594…) : un script qui les importe vise un Python plus ancien, ce ne
sont pas des paquets.

**Facultatif, ou pour les types.** Un import gardé par un `try` qui rattrape `ImportError`
(`ModuleNotFoundError`, `Exception`, ou tout) est facultatif (`optional`). Un import sous
`if TYPE_CHECKING:`, ou un `import type`, ne sert qu'aux annotations : de développement (`dev`).
Un paquet ne l'est que si tous ses imports le sont.

**Deno.** `npm:express@4.18.2` est le paquet npm `express`, avec sa contrainte (`4.18.2`) : il se
vérifie comme une dépendance, mais sa contrainte est à réécrire à la main dans l'import.
`jsr:@std/assert` vient du registre JSR, que forceupdate ne lit pas : « Non vérifiable : vient du
registre JSR (jsr:), que forceupdate ne lit pas. »

**Go.** Un import est rattaché à son module : le plus long préfixe que le proxy connaît, comme le
fait `go mod tidy` (`golang.org/x/text/language` → `golang.org/x/text`). Chez `github.com`,
`gitlab.com`, `bitbucket.org` et `golang.org`, un module a au moins trois éléments. Deux imports
du même module n'en font qu'un.

**Un autre langage** (Rust, PHP, Ruby, Java, C#…) n'a pas ses imports lus seul : « forceupdate ne
lit pas les imports d'un tel fichier seul : choisir son projet (le dossier de son manifeste). »

### La table import → paquet

En Python, un import ne porte pas toujours le nom de son paquet. Une table de 96 entrées les
relie, par exemple :

| Import | Paquet PyPI |
|---|---|
| `yaml` | `PyYAML` |
| `cv2` | `opencv-python` |
| `PIL` | `Pillow` |
| `sklearn` | `scikit-learn` |
| `bs4` | `beautifulsoup4` |
| `dateutil` | `python-dateutil` |
| `dotenv` | `python-dotenv` |
| `jwt` | `PyJWT` |
| `git` | `GitPython` |
| `serial` | `pyserial` |
| `win32api`, `win32com`… | `pywin32` |
| `google.protobuf` | `protobuf` |

Une entrée à points (`google.protobuf`) vaut pour ce module et ce qui est dessous ; la plus longue
l'emporte. Hors de la table, le paquet est l'import lui-même.

Sous un **espace de noms partagé** (`google`, `azure`, `zope`, `backports`, `jaraco`, `plone`,
`ruamel`, `sphinxcontrib`, `z3c`), le paquet est le plus long des noms possibles que PyPI connaît :
`google.cloud.storage` vient de `google-cloud-storage`, et `from google.cloud import storage,
bigquery` donne deux paquets.

Quand le nom diffère, le rapport montre l'import à côté du paquet :
`python-dateutil (import dateutil)`. Un import que ne fournit aucun paquet est non vérifiable :

```
Non vérifiable : aucun paquet de proxy.golang.org ne fournit « example.com/nothing/here » (example.com/nothing/here, example.com/nothing, example.com : introuvables).
Aucun paquet « notapackage » sur le registre pour l'import « notapackage » : un module du projet, ou un paquet qui ne porte pas le nom de son import ?
```

Un registre qui ne répond pas donne un « non concluant ».

### « Version non fixée »

Un import n'a pas de version. Son constat est « version non fixée », avec la dernière version
publiée :

```
Paquet                              Contrainte   Utilisée   Permise   Dernière   État
flask                               -            -                    3.1.3      version non fixée
jinja2 (optional)                   -            -                    3.1.6      version non fixée
python-dateutil (import dateutil)   -            -                    4.0.0      version non fixée
requests                            -            -                    2.34.2     version non fixée
```

Le message du constat (dans le JSON, et le détail de la dépendance dans l'interface) : « Version
non fixée (importé : dateutil) : la dernière est 4.0.0. »

- Rien n'a échoué, et relancer n'y changerait rien : ce n'est ni « non concluant » ni « à mettre à
  jour ». Le constat est de gravité info, et ne compte jamais pour `--fail-on`. Le résumé les
  compte à part : « rien à mettre à jour ; 4 versions non fixées. »
- Le reste de ce que dit le registre vaut toujours : un paquet déprécié est dit déprécié
  (`left-pad`).
- Il vaut aussi pour toute dépendance écrite sans contrainte ni lockfile : `requests` seul dans un
  `requirements.txt`, ou dans le bloc d'un script.
- Rien n'est réécrit dans le code : un import n'a ni contrainte ni emplacement. Seul un bloc
  PEP 723 se met à jour.

### « Failles non vérifiables »

OSV juge une version : sans version, les failles ne peuvent pas être cherchées, et le résumé ne
compte pas ces dépendances parmi celles dont les failles sont cherchées (« failles cherchées sur
0 »). Une remarque par fichier le dit :

```
imports.py Failles non vérifiables pour les 4 dépendances sans version fixée : OSV juge une version. Fixer les versions (un manifeste, un lockfile, un bloc PEP 723) pour qu'elles le soient.
```

Pour un script Python, le plus simple est de lui donner un bloc PEP 723 :
`uv add --script app.py requests` l'écrit, puis `uv lock --script app.py` fixe les versions.

### `exclude-newer` de uv

uv n'installe pas les versions publiées après `exclude-newer`. forceupdate le suit, pour un
script comme pour un projet : celui du `[tool.uv]` du bloc du script, sinon du `[tool.uv]` du
`pyproject.toml`, sinon du `uv.toml` du projet. Les versions de PyPI publiées après cette date ne
sont jamais proposées, même pour corriger une faille, et une remarque le dit :

```
outil.py exclude-newer = « 2024-01-01T00:00:00Z » (uv) : les versions de PyPI publiées après le 01/01/2024 à 00:00 (UTC) ne sont pas proposées, comme uv ne les installe pas.
```

Se lisent : un horodatage (`2024-01-01T00:00:00Z`), une date (`2024-01-01`), une durée (`24 hours`,
`1 week`, `30 days`) ou une durée ISO 8601 (`P7D`, `PT24H`), comptée depuis l'analyse. Autre chose
n'écarte rien (« exclude-newer = « … » (uv) : illisible, rien n'est écarté. »). Un paquet
qu'utilise aussi un projet sans ce réglage, dans la même analyse, garde toutes ses versions.

### Limites

- Les imports ne sont jamais réécrits ; la contrainte d'un import `npm:` de Deno est à changer à
  la main. Le registre JSR (`jsr:`) n'est pas lu.
- L'`extends` d'un `tsconfig.json` n'est pas suivi.
- `importlib.import_module` d'un nom calculé n'est pas lu.
- Un import absent de la table, mais qui existe sur PyPI sous son nom, est pris pour ce paquet
  (un homonyme). La table est tenue à la main : un test réseau vérifie que chacun de ses paquets
  existe sur PyPI, pas qu'il fournit l'import.
- La bibliothèque standard et la syntaxe de Python sont celles du Python qui fait tourner
  forceupdate : un fichier écrit pour un Python plus récent peut ne pas se lire (« ne se lit pas
  comme du Python, ligne … »).
- La date d'un `exclude-newer` sans fuseau est lue en UTC, quand uv prend le fuseau de la machine :
  quelques heures d'écart.
- Un fichier déposé dans l'interface, ou choisi par « Choisir un fichier », n'a jamais de projet
  autour (il est rangé dans un dossier temporaire) : ce sont ses imports, ou son bloc PEP 723,
  qui sont lus, sans le `script.py.lock` voisin. Pour avoir le projet, ou le lockfile du script,
  le choisir dans la liste des dossiers.

## Registres et dépôts privés

forceupdate demande chaque paquet au registre que le projet utilise vraiment : le registre public de
son écosystème, ou ceux que déclarent les fichiers du projet et ceux de la personne (`~/.npmrc`,
`~/.m2/settings.xml`, `NuGet.Config`…), lus comme l'outil de l'écosystème les lit. Un paquet d'un
registre privé est demandé à ce registre, avec l'identifiant que la personne a déjà configuré pour
son outil. Sinon, le rapport dit qu'il n'a pas été vérifié.

Un paquet privé n'est jamais demandé au registre public à sa place : un homonyme public peut y
exister, et ce n'est pas le même paquet (l'attaque par « confusion de dépendances »).

Il n'y a rien à configurer dans forceupdate : il lit ce qui est déjà là. Les fichiers de la personne
sont relus à chaque analyse : pas besoin de relancer `forceupdate ui` après avoir changé
`~/.npmrc`.

### Trois cas

| Cas | Exemples | À qui le paquet est demandé | OSV |
|---|---|---|---|
| Un registre **remplace** le public (un miroir : Nexus, Artifactory, Verdaccio…) | `registry=` de npm, `--index-url` de pip, un index `default` de uv, un `<mirror>` Maven, `GOPROXY` sans proxy.golang.org, `replace-with` de Cargo, un miroir de Bundler, la source globale d'un `Gemfile` | à ce registre seul | oui : un miroir sert des paquets publics |
| Des registres **en plus** du public | `--extra-index-url`, `[[tool.uv.index]]`, un dépôt `composer`, des `<repositories>` Maven, `repositories { }` de Gradle, les sources de NuGet | à eux d'abord, dans l'ordre ; le premier qui a le paquet l'emporte ; le public ensuite, si aucun ne l'a | oui |
| Un paquet **privé par son nom** | une portée npm (`@acme:registry=`), un module de `GOPRIVATE`, un paquet rattaché à un index (uv, Poetry, Pipenv, PDM), `only` de Composer, `packageSourceMapping` de NuGet, `includeGroup` et `exclusiveContent` de Gradle, une gem d'un bloc `source … do`, un crate d'un registre nommé | à son registre seul | jamais |

**Un refus arrête la chaîne.** Si un registre déclaré refuse l'accès (401, 403), ne répond pas ou
répond par une erreur, le registre public n'est pas demandé à sa place : le registre déclaré
pourrait avoir le paquet. Le constat le dit (voir « Ce que dit le rapport »).

**OSV.** Seuls les paquets privés par leur nom n'y vont pas. OSV ne connaît que les paquets publics,
et n'a pas à apprendre leur nom : leurs failles ne sont pas cherchées, et une remarque par fichier
le dit. Il en va de même pour les avis de failles de Packagist (PHP), et pour les versions qu'une
mise à jour propose.

### Les identifiants

forceupdate lit les identifiants là où l'outil de l'écosystème les lit (le détail suit, par
écosystème). Puis :

- un identifiant ne part que vers l'hôte exact pour lequel il est déclaré (et son port, et son
  chemin, quand ils sont écrits) ;
- seulement en https, ou en http vers la machine elle-même (`localhost`, `127.0.0.1` et toute
  adresse `127.x.x.x`, `::1` : rien ne quitte l'ordinateur, pour un Verdaccio ou un index local).
  Un registre déclaré en http sur une autre machine est demandé sans identifiant ;
- une redirection vers une autre origine (un autre hôte, un autre port, ou de https vers http) part
  sans identifiant ;
- le registre public reçoit l'identifiant déclaré pour son hôte (un paquet privé hébergé sur
  npmjs.com : `//registry.npmjs.org/:_authToken`). OSV, endoflife.date et les avis de Packagist n'en
  reçoivent jamais ;
- un identifiant n'est jamais écrit dans le cache, un rapport, un journal, les réponses de l'API ni
  le navigateur. Les messages citent l'hôte, jamais l'adresse. Les identifiants écrits dans une
  adresse (`https://nom:secret@hôte/…`) en sont retirés avant tout usage.

Une exception : un jeton écrit dans le *chemin* d'une adresse (`https://repo.example/<jeton>/simple/`)
fait partie de l'adresse. Il n'apparaît dans aucun message, mais l'adresse sert de clé au cache, sur
l'ordinateur. Préférer un identifiant à part (`.netrc`, `_authToken`…).

**Les variables d'environnement.** Dans un fichier de la personne, `${NOM}` (npm, Yarn, pip, uv ;
`${env.NOM}` pour Maven) et `%NOM%` (NuGet) sont remplacées par la variable, comme le fait l'outil.
Une variable absente rend la valeur inutilisable. Dans un fichier du projet, elles ne sont **jamais**
développées : un dépôt pourrait sinon faire partir un secret de l'environnement vers l'adresse de
son choix. La valeur n'est pas utilisée, et une remarque le dit : un identifiant, le registre est
demandé sans lui ; une adresse, le registre n'est pas lu. Mettre l'identifiant dans le fichier de la
personne.

**Un identifiant écrit en clair dans un fichier du projet** (un `.npmrc`, un `auth.json`, un
`nuget.config` versionnés) sert, pour l'adresse que ce fichier donne.

**Les identifiants rattachés à un nom.** Maven (un `<server>` et son `<id>`), NuGet (les
`packageSourceCredentials` d'une source) et Cargo (le jeton d'un registre nommé) rattachent un
identifiant à un nom, pas à une adresse. Celui de la personne ne part que vers l'adresse que donne
à ce nom un fichier de la personne : `settings.xml`, son `NuGet.Config`, son `config.toml` de Cargo
ou `CARGO_REGISTRIES_<NOM>_INDEX`. Jamais vers celle qu'un fichier du projet donne au même nom : un
dépôt pourrait sinon recevoir les identifiants de la personne en déclarant ce nom avec l'adresse de
son choix. Quand seul le projet donne l'adresse, une remarque le dit : la déclarer aussi chez soi.

Les identifiants de uv rattachés au nom d'un index (`UV_INDEX_<NOM>_USERNAME`,
`UV_INDEX_<NOM>_PASSWORD`) et ceux de Poetry (`poetry config http-basic.<nom>`) ne sont jamais
envoyés. Pour Python, mettre l'identifiant dans `~/.netrc`.

### En bref

| Écosystème | Fichiers du projet | De la personne | Identifiants |
|---|---|---|---|
| npm, pnpm, Yarn 1 | `.npmrc` (dossier du projet et parents) | `~/.npmrc`, `NPM_CONFIG_USERCONFIG`, `npm_config_registry` | `//hôte/:_authToken`, `:_auth`, `:username` et `:_password` |
| Yarn 2 et plus | `.yarnrc.yml` (dossier du projet et parents) | `~/.yarnrc.yml` | `npmAuthToken`, `npmAuthIdent` |
| Python | `pyproject.toml`, `uv.toml`, `Pipfile`, `requirements*.txt`, le bloc d'un script | `UV_INDEX`…, son `uv.toml`, `PIP_INDEX_URL`…, `pip.ini` ou `pip.conf` | dans l'adresse de l'index, `~/.netrc` |
| Go | aucun | `GOPRIVATE`, `GONOPROXY`, `GOPROXY`, `GOAUTH` (environnement, `go env -w`) | `~/.netrc`, dans l'adresse du proxy |
| PHP | `composer.json`, `auth.json` | `COMPOSER_AUTH`, `auth.json` de `COMPOSER_HOME` | `http-basic`, `bearer`, par hôte |
| Ruby | `Gemfile`, `Gemfile.lock`, `.bundle/config` | `BUNDLE_*`, `~/.bundle/config` | dans l'adresse de la source, par adresse ou par hôte |
| Rust | `Cargo.toml`, `Cargo.lock`, `.cargo/config.toml` (dossier du projet et parents) | `$CARGO_HOME/config.toml`, `credentials.toml`, `CARGO_REGISTRIES_<NOM>_*` | un jeton rattaché au nom du registre |
| Maven | `pom.xml` et ses parents | `~/.m2/settings.xml` | `<server>`, rattaché à son id |
| Gradle | les scripts, `settings.gradle(.kts)` | aucun | pas lus |
| .NET | `nuget.config` (dossier du projet et parents) | son `NuGet.Config` | `packageSourceCredentials`, rattachés au nom de la source |

### npm, Yarn, pnpm

**npm, pnpm et Yarn 1** lisent `.npmrc` :

- les `.npmrc` du dossier du projet, puis de ses dossiers parents dans la source (la racine d'un
  workspace), puis celui de la personne : `~/.npmrc`, ou le fichier que donne
  `NPM_CONFIG_USERCONFIG`. `npm_config_registry` (ou `NPM_CONFIG_REGISTRY`) passe devant tout. Pour
  une même clé, le fichier le plus proche l'emporte ;
- `registry` : le registre de tous les paquets (un miroir). `@portée:registry` : celui des paquets
  de la portée, privés par leur nom. Une portée qui pointe sur `registry.npmjs.org` reste publique ;
- les identifiants, par adresse sans schéma : `//hôte[:port]/chemin/:_authToken` (un jeton, envoyé
  en `Bearer`), `:_auth` (`nom:mot de passe` en base 64), `:username` et `:_password` (en base 64) ;
  ou ceux écrits dans l'adresse du registre.

```ini
; .npmrc du projet
@acme:registry=https://npm.acme.example/

; ~/.npmrc de la personne
//npm.acme.example/:_authToken=${ACME_NPM_TOKEN}
```

**Yarn 2 et plus** lit `.yarnrc.yml`, à la place de `.npmrc` :

- dès qu'un `.yarnrc.yml` est dans le dossier du projet ou un parent, `.npmrc` n'est plus lu. Puis
  `~/.yarnrc.yml` ;
- `npmRegistryServer` (un miroir), `npmScopes.<portée>.npmRegistryServer` (des paquets privés par
  leur nom), avec leur `npmAuthToken` ou leur `npmAuthIdent` (`nom:mot de passe`) ; `npmRegistries`
  donne des identifiants par adresse.

Limites :

- `.yarnrc` (celui de Yarn 1), le `npmrc` global (celui de l'installation de npm), les variables
  `YARN_*` et les autres `npm_config_*` ne sont pas lus ;
- sans `.yarnrc.yml` dans le projet, c'est `.npmrc` qui est lu, même pour Yarn 2 ;
- `cafile`, `ca` et `strict-ssl` ne sont pas lus (voir « Réseau d'entreprise ») ;
- l'adresse `resolved` d'un lockfile n'est pas suivie : un paquet installé depuis un autre registre,
  sans que la configuration le dise, est demandé au registre public. Déclarer son registre dans
  `.npmrc`.

### Python : uv, Poetry, PDM, Pipenv, pip

L'outil du projet décide de ce qui est lu : un script à bloc PEP 723 (uv), puis Poetry
(`[tool.poetry]`), PDM (`[tool.pdm]`), Pipenv (un `Pipfile`), uv (`[tool.uv]`, `uv.lock` ou
`uv.toml`), sinon pip (les `requirements`).

- **uv**, et un script : les `[[tool.uv.index]]` (`name`, `url`, `default`, `explicit`) du
  `pyproject.toml`, du `uv.toml` du dossier du projet ou du bloc du script, et les anciennes clés
  `index-url` et `extra-index-url`. Puis `UV_INDEX` (`nom=adresse`, séparés par des espaces),
  `UV_EXTRA_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_INDEX_URL`, et le `uv.toml` de la personne
  (`%APPDATA%\uv\uv.toml` sous Windows, `$XDG_CONFIG_HOME/uv/uv.toml` ou `~/.config/uv/uv.toml`
  ailleurs). Les index de l'environnement sont demandés d'abord, puis ceux du projet, puis ceux de
  la personne. Comme uv, le premier qui a le paquet l'emporte, PyPI (ou l'index `default = true`) en
  dernier. Un
  index `explicit` ne sert que les paquets qui lui sont rattachés (`[tool.uv.sources]`,
  `{ index = "corp" }`) : ceux-là sont privés par leur nom.
- **Poetry** : les `[[tool.poetry.source]]` et leur `priority`. Une source `primary` (la valeur par
  défaut) est demandée d'abord et retire PyPI, sauf si une source s'appelle `PyPI` ; une source
  `supplemental` ensuite. Une source `explicit` ne sert que les paquets qui la nomment
  (`source = "corp"`), privés par leur nom. Les anciennes `default` et `secondary` sont lues.
- **PDM** : les `[[tool.pdm.source]]`. Une source nommée `pypi` remplace PyPI ; les autres sont en
  plus. `include_packages` réserve des paquets à une source : ils sont privés par leur nom. Une
  source `type = "find_links"` n'est pas un index : pas lue.
- **Pipenv** : les `[[source]]` du `Pipfile`. La première est l'index par défaut, les autres sont en
  plus. `index = "corp"` d'un paquet le rend privé par son nom.
- **pip** : `--index-url` (`-i`), `--extra-index-url` et `--no-index` des `requirements*.txt` et des
  `.in` (et des fichiers qu'ils incluent par `-r` et `-c`). Puis `PIP_INDEX_URL` et
  `PIP_EXTRA_INDEX_URL`. Puis le fichier de configuration de pip de la personne, sections
  `[global]` et `[install]` : celui de `PIP_CONFIG_FILE`, sinon `%APPDATA%\pip\pip.ini` sous Windows,
  `~/.config/pip/pip.conf` ou `~/.pip/pip.conf` ailleurs (sous macOS,
  `~/Library/Application Support/pip/pip.conf` d'abord).

Les identifiants : ceux écrits dans l'adresse d'un index (`https://nom:secret@hôte/simple/`), et
`~/.netrc` (ou le fichier de `NETRC` ; sous Windows, `~/_netrc` aussi) pour l'hôte de chaque index
déclaré, quel que soit le port. `UV_INDEX_<NOM>_USERNAME`, `UV_INDEX_<NOM>_PASSWORD` et les
identifiants de Poetry ne sont jamais envoyés (voir plus haut).

```text
# ~/.netrc
machine pkgs.corp.example
  login jo
  password <jeton>
```

Un index est lu par son API « simple », comme uv et pip : en JSON (PEP 691), sinon sa page HTML
(PEP 503). Un index nommé `pypi`, ou à l'adresse de pypi.org, est PyPI.

Un paquet rattaché à un index que la configuration ne déclare pas : « Non vérifiable : vient de
l'index « corp », pas de PyPI. » `--no-index` : « Non vérifié : requirements.txt dit --no-index, pip
prend les paquets dans des fichiers locaux. »

Une variable dans un fichier du projet : dans l'hôte d'une adresse d'index, l'adresse ne se lit pas,
et aucun paquet du projet n'est vérifié (« Non vérifié : l'adresse d'un index de Pipfile ne se lit
pas ; il pourrait servir ce paquet. ») ; dans ses identifiants (`https://${USER}:${TOKEN}@…`),
l'index est demandé sans eux, et une remarque dit de les mettre dans `~/.netrc`.

Limites : le trousseau (`keyring`), les identifiants de Poetry et `UV_INDEX_<NOM>_*` ;
`--find-links` ; `UV_CONFIG_FILE` et les fichiers de configuration du système (`/etc/pip.conf`,
`/etc/uv/uv.toml`) ; les variables de Poetry, PDM et Pipenv ; la source notée dans un lockfile
(`uv.lock`, `poetry.lock`, `Pipfile.lock`) : seule la configuration compte.

### Go

Rien n'est lu dans le projet : comme `go`, forceupdate suit le `go env` de la personne.

- `GOPRIVATE`, `GONOPROXY`, `GOPROXY` et `GOAUTH` sont pris dans l'environnement, sinon dans le
  fichier qu'écrit `go env -w` : celui de `GOENV`, par défaut `%APPDATA%\go\env` sous Windows,
  `~/Library/Application Support/go/env` sous macOS, `~/.config/go/env` ailleurs (`GOENV=off` :
  aucun). L'environnement l'emporte sur le fichier.
- `GONOPROXY` vaut `GOPRIVATE` s'il n'est pas donné (`none` : aucun module). Ce sont des motifs
  séparés par des virgules (`*.corp.example,github.com/acme/*`), comparés au début du chemin du
  module, comme le fait `go`.
- Un module de `GONOPROXY` : `go` le prend directement chez son hôte, par git. forceupdate ne le
  demande à personne : ni au proxy public, qui irait lui-même le chercher chez son hôte (et
  apprendrait son chemin), ni à OSV. « Privé : non vérifié : module de GOPRIVATE, que go prend
  directement chez son hôte ; ni le proxy public ni OSV ne sont interrogés. »
- `GOPROXY` : les proxys avant le premier `direct` ou `off`. proxy.golang.org est le public ; un
  autre est un proxy d'entreprise, demandé d'abord, puis le public s'il suit dans la liste.
- Un module de `GOPRIVATE` que `GONOPROXY` laisse aux proxys (`GONOPROXY=none`) n'est demandé
  qu'aux proxys d'entreprise, jamais à proxy.golang.org. Sans eux : « Privé : non vérifié : module
  de GOPRIVATE, et pas d'autre proxy que proxy.golang.org dans GOPROXY, qui ne sera pas
  interrogé. »
- `direct` ou `off` en tête de `GOPROXY` : `go` prend chaque module chez son hôte, aucun n'est
  vérifié. « Non vérifié : GOPROXY=direct, go prend chaque module chez son hôte ; forceupdate ne
  demande pas le proxy public à sa place. »

Les identifiants d'un proxy d'entreprise : `~/.netrc` (le fichier de `NETRC` ; sous Windows,
`~/_netrc` aussi) quand `GOAUTH` vaut `netrc`, sa valeur par défaut ; ou ceux écrits dans l'adresse
du proxy. Une `machine` de `.netrc` vaut pour tous les ports de son hôte ; `default` n'est pas lu.

Limites : les autres méthodes de `GOAUTH` (`git`, une commande) ; ce qui suit proxy.golang.org dans
`GOPROXY` (un proxy de repli) n'est jamais demandé ; `GOINSECURE` n'est pas lu.

### PHP : Composer

- Les `repositories` du `composer.json` du projet (une liste, ou un objet par nom). Un dépôt
  `{"type": "composer", "url": …}` (Satis, Private Packagist, le registre Composer de GitLab, un
  miroir) est demandé avant Packagist, dans l'ordre ; le premier qui a le paquet l'emporte, comme
  Composer 2. `exclude` lui retire des paquets ; `only` lui en réserve, et ceux-là sont privés par
  leur nom. `"packagist.org": false` retire Packagist. Un dépôt `composer` à l'adresse de Packagist
  est Packagist.
- Un dépôt est lu comme Composer le lit : son `packages.json` (une fois par analyse), puis le
  fichier de chaque paquet, par `metadata-url`. `available-packages` et
  `available-package-patterns` disent quels paquets il a : un autre ne lui est pas demandé. Sans
  `metadata-url` (un Satis ancien) : les paquets écrits dans `packages` et dans ses `includes` (20
  fichiers au plus).
- Les identifiants, comme Composer : ceux écrits dans l'adresse du dépôt, puis `COMPOSER_AUTH` (du
  JSON), puis l'`auth.json` à côté du `composer.json`, puis celui de `COMPOSER_HOME`
  (`%APPDATA%\Composer\auth.json` sous Windows, `~/.config/composer/auth.json` ou
  `~/.composer/auth.json` ailleurs). Le premier qui en donne un pour un hôte l'emporte. Seuls
  `http-basic` (`username`, `password`) et `bearer` sont lus, chacun pour un hôte (`hôte` ou
  `hôte:port`).
- Packagist retiré, et aucun dépôt pour un paquet : « Non vérifié : aucun dépôt de « repositories »
  ne sert ce paquet, et Packagist est retiré. »

```json
{
  "repositories": [
    {"type": "composer", "url": "https://satis.acme.example", "only": ["acme/*"]}
  ]
}
```

Limites :

- la configuration globale de Composer (le `config.json` de `COMPOSER_HOME`, ses `repositories`)
  n'est pas lue ;
- `canonical: false` n'est pas lu : le premier dépôt qui a le paquet l'emporte toujours ;
- un dépôt qui n'a que `providers-url` (l'ancien protocole) n'est pas lu : ses paquets y sont
  introuvables (et cherchés sur Packagist, s'il reste) ;
- les autres identifiants d'`auth.json` (`github-oauth`, `gitlab-token`, `gitlab-oauth`,
  `bitbucket-oauth`) ne sont pas lus ;
- les dépôts `vcs`, `path`, `package` et `artifact` restent non vérifiables.

### Ruby : Bundler

- Le `Gemfile` (ou `gems.rb`), lu par motifs, jamais exécuté : la source globale
  (`source "https://…"` hors d'un bloc), les blocs `source "…" do … end`, l'option `source:` d'une
  gem. Et le `Gemfile.lock` (ou `gems.locked`) : chaque section `GEM` et son `remote:`.
- Une source globale autre que rubygems.org le remplace (OSV compris). Bundler 4 n'en accepte
  qu'une : s'il y en a plusieurs, la première est prise, et une remarque le dit.
- Une gem d'un bloc, d'une option `source:` ou d'une autre section `GEM` du lockfile que celle de la
  source globale (une indirecte tirée par une gem privée) est privée par son nom : demandée à son
  serveur seul, même s'il ne l'a pas, comme Bundler.
- La configuration de Bundler, comme lui : celle du projet (`.bundle/config`, ou
  `$BUNDLE_APP_CONFIG/config`), puis les variables `BUNDLE_*`, puis celle de la personne
  (`BUNDLE_CONFIG`, `BUNDLE_USER_CONFIG`, `$BUNDLE_USER_HOME/config`, sinon `~/.bundle/config`).
- Un miroir remplace sa source : `mirror.https://rubygems.org` (la clé
  `BUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/`), ou `mirror.all` pour toutes les sources.
- Les identifiants, `nom:mot de passe` envoyés en Basic : ceux écrits dans l'adresse de la source ;
  sinon la clé de son adresse exacte (`BUNDLE_HTTPS://GEMS__CORP__EXAMPLE/`) ; sinon celle de son
  hôte (`BUNDLE_GEMS__CORP__EXAMPLE`, qui vaut pour tous ses ports et ses chemins). Dans une clé,
  `.` s'écrit `__` et `-` s'écrit `___`.

```bash
bundle config set --global mirror.https://rubygems.org https://gems.corp.example
bundle config set --global gems.corp.example nom:secret
```

- Vers une source en http (hors de la machine elle-même), l'identifiant ne part pas : « L'identifiant
  de Bundler pour gems.corp.example n'est pas envoyé : la source est en http, forceupdate n'envoie
  un identifiant qu'en https (ou vers la machine elle-même). »
- Un serveur est lu par son index compact (`/versions`, `/info/<gem>`), comme Bundler. Une source
  qui n'est pas une adresse http(s) (un dossier) : « Non vérifié : la source de acme-core dans
  Gemfile n'est pas un serveur http(s). »

Limites : un serveur qui n'a que l'ancienne API (`/api/v1/dependencies`) est « non concluant »
(« gems.corp.example ne sert pas l'index compact de Bundler (/versions, /info/…), le seul que lit
forceupdate. ») ; un `BUNDLE_APP_CONFIG` relatif est pris dans le dossier du projet ; le délai de
repli d'un miroir (`fallback_timeout`) est ignoré : le miroir est toujours pris.

### Rust : Cargo

- Une dépendance `registry = "<nom>"` d'un `Cargo.toml` vient du registre de ce nom, déclaré par
  `[registries.<nom>] index = "sparse+https://…/"` : dans un `.cargo/config.toml` (ou
  `.cargo/config`) du dossier du projet ou d'un parent, puis dans celui de la personne
  (`$CARGO_HOME/config.toml`, par défaut `~/.cargo/config.toml`). `CARGO_REGISTRIES_<NOM>_INDEX`
  passe devant. Le plus proche l'emporte.
- Le `Cargo.lock` dit la source de chaque crate : une autre que crates.io
  (`source = "sparse+https://…"`) rend le crate privé, indirectes comprises.
- Un crate d'un registre nommé, ou d'une autre source du lockfile, est privé par son nom : demandé à
  cet index seul.
- `[source.crates-io] replace-with = "<nom>"` remplace crates.io : par un registre de
  `[registries]` (avec son jeton), ou par une source `[source.<nom>] registry = "sparse+…"` (sans
  jeton, comme Cargo). Des fichiers locaux à sa place (`directory`, `local-registry` : ceux de
  `cargo vendor`) sont des copies de crates.io : crates.io est demandé.
- Le jeton d'un registre : `CARGO_REGISTRIES_<NOM>_TOKEN`, puis `$CARGO_HOME/credentials.toml`
  (`[registries.<nom>] token`, ce qu'écrit `cargo login`), puis le `token` des `config.toml`. Il est
  envoyé comme le fait Cargo : `Authorization: <jeton>`, sans « Bearer ».
- Le jeton est rattaché au nom du registre (voir plus haut) : celui de la personne ne part que vers
  l'adresse que lui donnent son `config.toml` ou `CARGO_REGISTRIES_<NOM>_INDEX` ; un jeton écrit dans
  un fichier du projet, vers l'adresse que ce fichier donne. Sinon : « Le jeton du registre « acme »
  ne part que vers l'adresse que donne à ce nom un fichier de la personne (son
  $CARGO_HOME/config.toml, ou CARGO_REGISTRIES_ACME_INDEX) : jamais vers celle d'un fichier du
  projet. L'y déclarer pour qu'il soit envoyé. »
- Seuls les index « sparse » sont lus. Un index git : « Privé : non vérifié : l'index du registre
  « acme » (.cargo/config.toml) n'est pas un index « sparse » (un dépôt git), que forceupdate ne lit
  pas. » Un registre que rien ne déclare : « Privé : non vérifié : le registre « acme » n'est
  déclaré dans aucun .cargo/config.toml ni par CARGO_REGISTRIES_ACME_INDEX. »

Limites : les jetons des autres fournisseurs d'identifiants (`cargo:wincred`,
`cargo:macos-keychain`, `cargo:libsecret`, un programme) ne sont pas lus ; un index git
(`registry+…`) non plus, y compris à la place de crates.io : ses crates ne sont pas vérifiés.

### Java : Maven

- Le `~/.m2/settings.xml` de la personne : ses `<mirrors>`, ses `<servers>`, et les dépôts de ses
  profils actifs (`activeByDefault`, `<activeProfiles>`). `${env.NOM}` y est remplacé.
- Le `pom.xml` et ses parents présents dans la source : leurs `<repositories>` et
  `<pluginRepositories>`, `${propriété}` remplacée par les `<properties>`.
- Les dépôts des profils, puis ceux des `pom.xml`, sont demandés d'abord, dans l'ordre ; le premier
  qui a l'artefact l'emporte ; Maven Central en dernier. Les `pom` des parents et des BOM distants
  sont demandés de même.
- Un `<mirror>` remplace chaque dépôt que désigne son `mirrorOf` : son id exact d'abord, puis `*`,
  `external:*`, `external:http:*`, une liste, `!id`. Un miroir de `*` remplace tout, Central compris.
- Un artefact Maven n'est jamais privé par son nom : tous vont à OSV.
- Les identifiants : un `<server>` (`username`, `password`) est rattaché à son `<id>`. Il ne part que
  vers une adresse que `settings.xml` donne à cet id : un miroir, un dépôt d'un profil. Si seul un
  `pom.xml` la donne : « les identifiants du serveur « corp » ne partent pas vers l'adresse qu'un
  pom.xml donne à cet id : la déclarer dans settings.xml (un miroir). » Ceux écrits dans l'adresse
  d'un dépôt servent aussi.
- Un mot de passe chiffré (`{…}`) : « le mot de passe du serveur « corp » est chiffré : forceupdate
  ne le lit pas (le dépôt est demandé sans lui). »
- Une adresse de dépôt qui reste une propriété (`${env.NEXUS_URL}`, une propriété inconnue) : le
  dépôt n'est pas lu, une remarque le dit, et les artefacts du projet ne sont pas vérifiés :
  « Non vérifié : l'adresse d'un dépôt de pom.xml ne se lit pas ; il pourrait servir cet
  artefact. »

```xml
<!-- ~/.m2/settings.xml -->
<settings>
  <servers>
    <server><id>corp</id><username>jo</username><password>${env.NEXUS_PASSWORD}</password></server>
  </servers>
  <mirrors>
    <mirror><id>corp</id><url>https://nexus.corp.example/repository/maven/</url><mirrorOf>*</mirrorOf></mirror>
  </mirrors>
</settings>
```

Limites : un mot de passe chiffré (`settings-security.xml`) ; le `settings.xml` de l'installation de
Maven ; `<httpHeaders>` d'un serveur (un jeton dans un en-tête) ; `${env.…}` dans un `pom.xml` ;
les dépôts des `<profiles>` d'un `pom.xml`.

### Java : Gradle

- Les blocs `repositories { }` des scripts du projet (`build.gradle`, `build.gradle.kts`), de ceux de
  ses dossiers parents, et de `settings.gradle(.kts)` (`dependencyResolutionManagement`,
  `pluginManagement`) ; lus en jetons, jamais exécutés.
- `mavenCentral()`, `google()`, `gradlePluginPortal()` et `jcenter()` sont publics. `maven("…")`,
  `maven { url = uri("…") }`, `maven { url "…" }` et `setUrl("…")` déclarent un dépôt, demandé avant
  les publics.
- `content { includeGroup("…") }` (ou `includeModule`, `includeGroupAndSubgroups`) et
  `exclusiveContent { … }` réservent des groupes à un dépôt : leurs artefacts sont privés par leur
  nom.
- Sans bloc `repositories` : les dépôts publics. Un bloc sans dépôt lisible (seulement
  `mavenLocal()`) : « Non vérifié : aucun dépôt lu dans repositories { } (mavenLocal ?). »
- Les identifiants ne sont pas lus : un script les prend dans des propriétés ou l'environnement en
  s'exécutant, et forceupdate ne l'exécute jamais. Une remarque le dit (« les identifiants d'un
  dépôt Gradle viennent de propriétés ou de l'environnement, que le script lit en s'exécutant :
  forceupdate ne les lit pas (le dépôt est demandé sans eux). ») ; un dépôt qui en exige un refuse
  alors l'accès.

Limites : les identifiants ; un dépôt dont l'adresse est calculée (`"$nexusUrl/releases"`,
`uri(findProperty(…))`) n'est pas lu, sans remarque ; les scripts d'init (`~/.gradle/init.d/`),
`ivy { }` et `includeGroupByRegex` ne sont pas lus ; `includeGroupAndSubgroups` ne vaut que pour le
groupe nommé, pas pour ses sous-groupes.

### .NET : NuGet

- Les `nuget.config` (ou `NuGet.config`, `NuGet.Config`) du dossier du projet et de ses parents dans
  la source, du plus proche au plus lointain, puis celui de la personne
  (`%APPDATA%\NuGet\NuGet.Config` sous Windows, `~/.nuget/NuGet/NuGet.Config` ailleurs ; sans lui,
  nuget.org). Comme `dotnet` : les sources du plus proche viennent d'abord ; `<clear />` écarte
  celles des fichiers plus lointains, celui de la personne compris ; `disabledPackageSources`
  désactive une source.
- Sans `packageSourceMapping`, les sources autres que nuget.org sont demandées d'abord, et la
  première qui a le paquet l'emporte ; nuget.org ensuite. Avec, chaque paquet ne va qu'aux sources
  du motif le plus précis qui lui correspond (`Contoso.*`, `*`). Un paquet que ses motifs envoient
  ailleurs qu'à nuget.org est privé par son nom. Un paquet qu'aucun motif ne sert : « Non vérifié :
  aucune source de packageSourceMapping ne sert ce paquet (NuGet le refuserait). »
- Une source est lue par son index de services (NuGet v3, `…/index.json`). Un flux v2 ne l'est pas :
  « Non vérifié : la source « legacy » est un flux NuGet v2, que forceupdate ne lit pas ; elle
  pourrait servir ce paquet. » Celui de nuget.org (`www.nuget.org/api/v2`) est nuget.org. Une source
  qui est un dossier n'est pas lue.
- Les identifiants : `packageSourceCredentials`, un élément par nom de source (`_x0020_` pour une
  espace), avec `Username` et `ClearTextPassword` ; `%NOM%` n'y est développé que dans le fichier de
  la personne. Ils sont rattachés au nom de la source (voir plus haut), et valent pour tout l'hôte
  de la source. Ceux écrits dans l'adresse de la source servent aussi.
- Un mot de passe chiffré : « le mot de passe de la source « corp » est chiffré (Password) :
  forceupdate ne lit que ClearTextPassword. » Le projet donne une autre adresse au nom : « les
  identifiants de la source « corp » ne partent pas vers l'adresse qu'un fichier du projet lui donne :
  la déclarer aussi dans le NuGet.Config de la personne. »

Limites : un `Password` chiffré (ce qu'écrit `dotnet nuget add source` sous Windows, sans
`--store-password-in-clear-text`) ; les fournisseurs d'identifiants (celui d'Azure Artifacts) ;
`NuGetPackageSourceCredentials_<nom>` ; les fichiers de configuration de la machine ; un flux v2 ;
une source qui est un dossier.

### Ce que dit le rapport

Ces constats sont des « non vérifiable » (`unverifiable` dans le JSON), sauf le dernier :

| Message | Ce qui s'est passé |
|---|---|
| « Registre privé : non vérifié : npm.acme.example refuse l'accès à @acme/ui (HTTP 401) : identifiants absents ou refusés. » | Le registre déclaré a répondu 401 ou 403 : l'identifiant manque, ou il est refusé. Le registre public n'est pas demandé à sa place. Rien n'est gardé dans le cache : corriger l'identifiant, puis relancer. Pour un dépôt Composer ou un flux NuGet, le refus porte sur « son packages.json » ou « son index de services ». |
| « Privé : non vérifié : … » | Un paquet privé par son nom, et personne à qui le demander : un module de `GONOPROXY`, ou de `GOPRIVATE` sans proxy d'entreprise ; un registre Cargo non déclaré, ou en git. |
| « Non vérifié : … » | Aucun registre à qui demander ce paquet sans risque : `GOPROXY=direct`, `--no-index`, un flux NuGet v2, un `packageSourceMapping` qui ne le sert pas, Packagist retiré sans dépôt qui le serve, crates.io remplacé par un index git, une adresse de registre qui ne se lit pas, la source d'une gem qui n'est pas un serveur http(s), seulement `mavenLocal()`. Le registre public n'est pas demandé à sa place. |
| « @acme/ui est introuvable sur npm.acme.example. » | Les registres déclarés ne connaissent pas le paquet (et le public n'est pas à demander : paquet privé par son nom, ou miroir). Gardé une heure dans le cache, comme pour un registre public (`--no-cache` pour redemander). |
| « Non vérifiable : vient de l'index « corp », pas de PyPI. » | Python : le paquet est rattaché à un index que la configuration ne déclare pas. |
| « non concluant » (`inconclusive`), avec la raison | Le registre déclaré ne répond pas, ou répond par une erreur (5xx) ; un serveur de gems sans index compact. Le registre public n'est pas demandé à sa place. |

Et, dans les remarques du projet :

- « Failles non cherchées pour le paquet privé : OSV ne connaît que les paquets publics (un homonyme
  n'est pas le même paquet), et n'a pas à apprendre leur nom. » (une par fichier) ;
- une variable d'un fichier du projet, jamais développée : « « //npm.acme.example/:_authToken »
  utilise une variable d'environnement : forceupdate ne développe jamais celles d'un fichier du
  projet (un dépôt pourrait faire partir un secret vers l'adresse de son choix). Mettre l'identifiant
  dans le fichier de la personne (~/.npmrc). » ;
- une variable absente d'un fichier de la personne : « « //npm.acme.example/:_authToken » utilise
  une variable d'environnement absente : pas utilisé. » ;
- un identifiant rattaché à un nom que le projet est seul à déclarer, un mot de passe chiffré, les
  identifiants d'un dépôt Gradle, un identifiant de Bundler vers une source en http (les messages
  sont cités plus haut, par écosystème).

### Un dépôt analysé sur une forge

Un dépôt de GitHub, GitLab ou Bitbucket est analysé par l'API, sans clone. Les fichiers de
configuration des registres y sont téléchargés comme les manifestes, s'ils sont dans le dépôt :
`.npmrc`, `.yarnrc.yml`, `uv.toml`, `nuget.config`, `auth.json`, `.bundle/config`,
`.cargo/config.toml`, `settings.gradle(.kts)`, les `pom.xml` parents…, ceux du dossier du projet et
de ses parents. Rien d'autre.

Les fichiers de la personne, sur l'ordinateur où tourne forceupdate, sont lus comme pour un
dossier : les mêmes identifiants, les mêmes règles. Les fichiers du dépôt sont des fichiers du
projet : leurs variables ne sont jamais développées, et un nom qu'ils déclarent avec une autre
adresse ne reçoit pas les identifiants de la personne.

### Et la mise à jour

Ce qui précède vaut pour l'analyse, d'où viennent les versions proposées. Pour régénérer un
lockfile, `forceupdate update` (et l'envoi d'une PR) lance l'outil du projet (npm, uv, Composer,
Bundler, cargo, dotnet…). C'est lui qui lit alors sa configuration et ses identifiants, comme
d'habitude, avec l'environnement de la personne.

## Réseau d'entreprise

Toutes les requêtes de forceupdate (les registres, OSV, endoflife.date, les avis de Packagist, les
API des forges) passent par le même client HTTP. Il suit les variables habituelles :

| Variable | Rôle |
|---|---|
| `HTTPS_PROXY` | le proxy des requêtes en https, c'est-à-dire presque toutes |
| `HTTP_PROXY` | le proxy des requêtes en http (un registre servi en http sur la machine elle-même) |
| `ALL_PROXY` | le proxy des deux, quand la variable propre au schéma manque |
| `NO_PROXY` | les hôtes joints sans proxy |
| `SSL_CERT_FILE` | des autorités de certification en plus : un fichier PEM |
| `SSL_CERT_DIR` | des autorités de certification en plus : un dossier |

Sans réseau du tout, `--offline` analyse avec le cache seul.

### Proxy

```bash
export HTTPS_PROXY=http://proxy.corp.example:3128
export NO_PROXY=localhost,127.0.0.1,.corp.example
```

- Les noms s'écrivent en majuscules ou en minuscules (`https_proxy`).
- `NO_PROXY` : des hôtes séparés par des virgules (`.corp.example` pour ses sous-domaines) ; `*` :
  aucun proxy. Y mettre un registre d'entreprise joignable en direct, et la machine elle-même si
  `HTTP_PROXY` ou `ALL_PROXY` est défini et qu'un registre y est servi en http.
- Un proxy qui demande un identifiant : dans son adresse (`http://nom:secret@proxy.corp.example:3128`),
  envoyé en Basic. NTLM et Kerberos ne sont pas pris en charge.
- Un proxy SOCKS (`socks5://`) n'est pas pris en charge : le client HTTP refuse de démarrer
  (« Using SOCKS proxy, but the 'socksio' package is not installed. »).
- Un proxy injoignable se dit comme une coupure du réseau (« pypi.org injoignable (ConnectError). ») ;
  un proxy qui refuse le tunnel (un identifiant manquant, 407) : « requête vers pypi.org impossible
  (ProxyError). » Les constats concernés sont « non concluant ».

**Les réglages de proxy du système.** Sans aucune variable `*_PROXY` dans l'environnement (pas même
`NO_PROXY`), le client HTTP prend le proxy des réglages du système : sous Windows, celui réglé à la
main (Paramètres > Réseau et Internet > Proxy > « Utiliser un serveur proxy »), mais sans sa liste
d'exceptions ; sous macOS, ceux des réglages réseau. Le script de configuration automatique (PAC) et
la détection automatique ne sont jamais lus. Derrière un proxy d'entreprise, le plus sûr est de
définir `HTTPS_PROXY` et `NO_PROXY`.

### Certificats

forceupdate fait confiance au magasin de certificats du système, comme pip (par `truststore`) : le
magasin de Windows, le trousseau de macOS, celui d'OpenSSL sous Linux. Un proxy d'entreprise qui
déchiffre le trafic présente des certificats signés par l'autorité de l'entreprise ; celle-ci est
en général déjà dans le magasin, déployée par l'entreprise : rien à faire.

Sinon, `SSL_CERT_FILE` (un fichier PEM, une ou plusieurs autorités) et `SSL_CERT_DIR` (un dossier
d'autorités préparé par `openssl rehash`) les **ajoutent** au magasin du système, sous Windows et
sous macOS :

```bash
export SSL_CERT_FILE=~/certificats/autorite-entreprise.pem
```

Sous Linux, OpenSSL lit lui-même `SSL_CERT_FILE` et `SSL_CERT_DIR` **à la place** de son fichier et
de son dossier d'autorités par défaut : selon la distribution, les autorités publiques peuvent ne
plus être reconnues (pypi.org refusé, par exemple, si le proxy ne déchiffre pas tout). Le plus sûr :
ajouter l'autorité de l'entreprise au magasin du système (sous Debian et Ubuntu,
`/usr/local/share/ca-certificates/` puis `update-ca-certificates`), sans `SSL_CERT_FILE` ; ou faire
de `SSL_CERT_FILE` un fichier qui contient aussi les autorités du système.

Un `SSL_CERT_FILE` ou un `SSL_CERT_DIR` illisible (absent, mal formé) est dit sur la sortie d'erreur
(« certificats de SSL_CERT_FILE ou SSL_CERT_DIR illisibles : [Errno 2] No such file or
directory »), puis laissé de côté : le magasin du système reste.

forceupdate ne lit pas les réglages de certificats des autres outils : `cafile`, `ca` et
`strict-ssl` de `.npmrc`, `cert` de pip, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`. La
vérification des certificats ne se désactive pas.

### Un certificat refusé

> certificat de pypi.org refusé ([SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer
> certificate) : derrière un proxy d'entreprise, donner son autorité par SSL_CERT_FILE.

- Entre parenthèses, la raison que donne le système (sous Windows, dans sa langue).
- Un certificat refusé n'est pas réessayé : rien n'y changerait. L'hôte n'est plus interrogé
  pendant une minute, comme un hôte injoignable, et les constats qui en dépendent sont « non
  concluant ».
- Que faire : obtenir l'autorité du proxy d'entreprise au format PEM (auprès du service
  informatique, ou exportée depuis le navigateur, au format « X.509 encodé en base 64 »), puis la
  donner par `SSL_CERT_FILE`.

### git et les outils de lockfile

- Le clone d'un dépôt (quand l'API d'une forge ne suffit pas) et l'envoi d'une PR passent par git,
  qui garde la configuration de la personne : son proxy (`http.proxy`, ou `HTTPS_PROXY`) et ses
  certificats (`http.sslCAInfo`, `http.sslBackend`).
- Les outils que lance `forceupdate update` (npm, uv, Composer, cargo…) reçoivent l'environnement,
  proxy compris, et suivent leur propre configuration (le `proxy` et le `cafile` de `.npmrc`…).

## Robustesse

### Les fichiers

- **UTF-16, UTF-32 et BOM** : un fichier est lu d'après son BOM. `>` de PowerShell 5.1 écrit de
  l'UTF-16 (`pip freeze > requirements.txt`) : il se lit. Le BOM UTF-8 est retiré pour les
  parseurs, et gardé à la réécriture. **Un fichier en UTF-16 ou UTF-32 n'est pas réécrit** :
  « requirements.txt : en UTF-16, pas réécrit (le réenregistrer en UTF-8 pour que forceupdate
  le mette à jour). » ;
- **un autre encodage** (cp1252, ISO-8859-1) : le fichier se lit, ses octets illisibles
  remplacés (d'ordinaire des accents dans un commentaire), mais ne se réécrit pas (« pas en
  UTF-8, pas réécrit. ») ;
- un fichier aux fins de ligne `\r` seules, un lien symbolique, un fichier hors du dossier
  analysé ne sont pas réécrits ;
- chaque fichier est remplacé d'un coup (un fichier temporaire à côté, puis un renommage), ses
  droits gardés : jamais à moitié écrit ;
- au plus 2 Mo par manifeste, 50 Mo par lockfile ; au-delà, le fichier n'est pas lu.

### Les gros dossiers

- au plus **200 000 fichiers** listés par source. Au-delà, la liste s'arrête, dans l'ordre de
  git ou du parcours, et le rapport le dit : « plus de 200 000 fichiers : la liste s'arrête là,
  les projets des fichiers suivants ne sont pas analysés (choisir un dossier plus petit). » ;
- au plus **2 000 fichiers de dépendances** : « plus de 2 000 fichiers de dépendances : seuls
  les 2 000 premiers sont lus, dans l'ordre des chemins. » ;
- dans un dépôt git, la liste vient de git (`git ls-files`) : ce que `.gitignore` écarte ne
  compte pas. Les dossiers de dépendances installées, de caches et de build (`node_modules`,
  `.venv`, `vendor`, `target`, `dist`…) sont toujours sautés.

Un rapport qui a ces remarques n'est pas complet ; l'interface le dit (« Analyse partielle »).

### Liens, jonctions, sous-modules

- ni les liens symboliques ni les jonctions Windows (`mklink /J`) ne sont suivis ;
- un sous-module git non initialisé (un clone sans `--recurse-submodules`) n'est pas analysé :
  « sous-module git non initialisé : pas analysé (git submodule update --init). » Un
  sous-module rempli est lu ;
- un dépôt git rangé dans le dossier analysé garde son propre `.gitignore`.

### Interrompre une mise à jour

**Ctrl+C pendant `forceupdate update`** : ce qui n'était pas fini est remis comme avant.

- pendant l'écriture des manifestes : ceux déjà écrits sont remis ;
- pendant un outil : l'outil est tué (tout son arbre), le groupe en cours est remis, et les
  manifestes des groupes qui n'ont pas encore tourné aussi (un manifeste réécrit sans son
  lockfile serait à moitié fait) ;
- les groupes déjà finis restent : leur manifeste et leur lockfile vont ensemble.

```
forceupdate update : interrompu : ce qui n'était pas fini est remis comme avant.
```

Code de retour 2.

**L'arrêt de `forceupdate ui`** (Ctrl+C dans son terminal) pendant une mise à jour lancée de
l'interface fait de même : l'outil en cours est tué aussitôt, sans attendre sa fin, et ce qui
n'était pas fini est remis comme avant. Une mise à jour ne s'annule pas depuis l'interface.
Fermer le navigateur ne change rien : elle continue, et son résultat reste. Sous Windows,
Ctrl+Break arrête `ui` comme Ctrl+C.

### Le délai des outils

Chaque commande d'un outil de lockfile a un délai : 600 s par défaut, de 10 s à 24 h avec
`lock-timeout` des réglages (l'écran Réglages). Au-delà, l'outil est tué, et c'est un échec
(`« npm install … » n'a pas fini en 600 s.`) : le groupe est remis.

**Tout l'arbre de l'outil est tué**, pas seulement le programme lancé. Sous Windows, c'est
souvent un lanceur (`npm.cmd` lance `cmd.exe`, qui lance node) : forceupdate passe par
`taskkill /F /T` (celui du système). Ailleurs, l'outil a sa propre session, dont tout le groupe
est tué. Une fois l'arbre tué, la fin de sa sortie est attendue 10 s au plus.

Sous Windows, un `.cmd` ou un `.bat` passe par `cmd.exe` : un argument qui contient
`"%!&|<>^()` est refusé (« … : argument refusé (…). ») plutôt que d'être interprété.

### Le réseau

- **une erreur ne donne jamais de faux constat** : un registre, OSV ou endoflife.date qui ne
  répond pas donne un « non concluant », avec la raison (« pypi.org injoignable (…). »,
  « … ne répond pas (délai dépassé). »). Pour des indirectes, une remarque par lockfile le dit,
  au lieu d'un constat par paquet ;
- délais : 10 s pour se connecter, 30 s sans rien recevoir, 2 min par essai ; des reprises sur
  429, 5xx et coupures, en suivant `Retry-After` (au-delà d'une minute demandée, abandon). Un
  hôte resté injoignable n'est plus interrogé pendant une minute. Au plus 8 requêtes à la fois
  par hôte ; une réponse de plus de 128 Mo est refusée ;
- un certificat refusé n'est pas réessayé : « certificat de pypi.org refusé (…) : derrière un
  proxy d'entreprise, donner son autorité par SSL_CERT_FILE. » (voir « Réseau d'entreprise ») ;
- `--offline` : seulement le cache, le reste « non concluant ». Les outils de lockfile, eux, ont
  besoin du réseau : hors ligne, ils échoueront, et les fichiers seront remis.

### Limites

- au-delà de 200 000 fichiers, la source est coupée ;
- un fichier en UTF-16, ou qui n'est pas en UTF-8, se lit mais ne se réécrit pas ;
- un descendant d'un outil qui sort de son arbre (un démon) n'est pas tué ;
- le proxy des réglages de Windows (WinINet, PAC) n'est pas lu : seulement `HTTPS_PROXY` ;
- sous Linux, `SSL_CERT_FILE` remplace le magasin de certificats du système (OpenSSL), au lieu
  de s'y ajouter.
