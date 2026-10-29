# Format JSON des rapports

Version du schéma : **1**.

C'est ce qu'écrit `forceupdate scan --format json`, et ce que rend l'API de
l'interface web (`GET /api/scans/{id}`, champ `report`). Le code qui le produit est
`src/forceupdate/report/json.py`. Les autres objets de l'API sont décrits à la fin :
[L'API de l'interface web](#lapi-de-linterface-web).

## Conventions

- **Encodage** : UTF-8, accents non échappés, sur la sortie standard comme dans un
  fichier (`--output`).
- **Chemins** : au format POSIX (`backend/pyproject.toml`), relatifs à la racine de
  la source analysée. Même forme sous Windows, sous Linux et pour un dépôt distant.
- **Dates** : ISO 8601 avec fuseau, en UTC (`2026-10-27T19:52:06.684328+00:00`).
- **Énumérations** : des chaînes (`"outdated"`, `"major"`). Les valeurs possibles
  sont listées plus bas.
- **Absent** : `null` pour une valeur inconnue, `[]` pour une liste vide. Tous les
  champs sont toujours présents.
- **Versions** : telles que le registre ou le fichier les écrit. Pour les comparer,
  utiliser les règles de l'écosystème (PEP 440, semver), jamais l'ordre des chaînes.

### Évolution du schéma

`schema_version` passe à 2 si un champ est retiré, renommé, ou change de sens. Un
champ ou une valeur d'énumération ajoutés ne le changent pas : un lecteur doit
ignorer ce qu'il ne connaît pas. Les failles (E08) sont arrivées ainsi (champs
`cvss_score` des constats et `audited` du résumé), puis les mises à jour
proposées (E09 : `updates` et `overrides` des projets, `lockfile` des
dépendances), puis les failles des versions proposées (E10 : `introduced` des
options), puis les répartitions par gravité du résumé (E14 : `severities`,
`vulnerabilities`) ; les fins de vie (E27) arriveront de même, avec des constats `eol`.

## Le rapport

| Champ | Type | Sens |
|---|---|---|
| `schema_version` | entier | `1` |
| `tool` | objet | `{"name": "forceupdate", "version": "0.1.0"}` |
| `source` | chaîne | ce qui a été analysé : un chemin absolu, ou `owner/repo` sur une forge |
| `languages` | liste de [langages](#langage) | du plus lourd au plus léger |
| `projects` | liste de [projets](#projet) | dans l'ordre des chemins |
| `ignored_manifests` | liste de chemins | manifestes et lockfiles écartés, parce que rangés dans un dossier de tests, de fixtures ou d'exemples |
| `options` | [options](#options) ou `null` | ce qui a été vérifié ; `null` si les dépendances n'ont pas été vérifiées auprès des registres |
| `scanned_at` | date ou `null` | début de l'analyse |
| `oldest_data` | date ou `null` | date des plus anciennes données des registres et d'OSV utilisées. Hors ligne (`options.offline`), elles viennent du cache et peuvent dater de plusieurs jours : à afficher |
| `summary` | [résumé](#résumé) | les chiffres |

## Langage

| Champ | Type | Sens |
|---|---|---|
| `name` | chaîne | nom de GitHub Linguist (`Python`, `TypeScript`, `C++`) |
| `bytes` | entier | octets de code, sans fichiers vendorisés, générés ni documentation |
| `ecosystem` | [écosystème](#écosystèmes) ou `null` | `null` si forceupdate n'en gère aucun pour ce langage |

## Projet

Un dossier qui contient au moins un manifeste ou un lockfile.

| Champ | Type | Sens |
|---|---|---|
| `path` | chaîne | dossier du projet ; `.` pour la racine de la source |
| `ecosystems` | liste d'[écosystèmes](#écosystèmes) | ceux de ses fichiers |
| `manifests` | liste de chemins | ses manifestes |
| `lockfiles` | liste de chemins | ses lockfiles, ou celui de la racine d'un workspace |
| `dependencies` | liste de [dépendances](#dépendance) | les directes d'abord, dans l'ordre des manifestes, puis les indirectes |
| `overrides` | liste de [versions forcées](#version-forcée) | celles de son `pnpm-workspace.yaml`, puis de son `package.json` |
| `findings` | liste de [constats](#constat) | **du plus grave au moins grave** (voir [l'ordre](#ordre-des-constats)) |
| `updates` | liste de [mises à jour](#mise-à-jour) | une par paquet à mettre à jour, dans l'ordre des constats ; `[]` si les dépendances n'ont pas été vérifiées |
| `notices` | liste de [remarques](#remarque) | ce que l'analyse n'a pas pu lire, ou pas pu vérifier |

## Dépendance

Une déclaration. Un paquet déclaré deux fois (en `runtime` et en `dev`, ou dans
deux extras) donne deux dépendances, chacune avec son emplacement.

| Champ | Type | Sens |
|---|---|---|
| `ecosystem` | [écosystème](#écosystèmes) | |
| `name` | chaîne | nom tel que le registre le connaît (normalisé selon PEP 503 pour PyPI) |
| `constraint` | chaîne | la contrainte telle qu'écrite (`^4.18.0`, `>=2.0,<3`) ; `""` s'il n'y en a pas |
| `resolved_constraint` | chaîne ou `null` | la plage que désigne `constraint` quand elle renvoie ailleurs : pour `catalog:` (pnpm), celle de `pnpm-workspace.yaml` |
| `installed` | chaîne ou `null` | version installée, lue dans le lockfile |
| `lockfile` | chemin ou `null` | le fichier où `installed` a été lu : le lockfile à régénérer pour la mettre à jour (ou un fichier `-c` de pip) ; `null` sans version installée. Pour une indirecte, c'est `file` |
| `direct` | booléen | `false` pour une dépendance qui ne vient que du lockfile |
| `scope` | [scope](#scopes) | |
| `file` | chemin | le fichier qui la déclare (le lockfile pour une indirecte) |
| `location` | [emplacement](#emplacement) ou `null` | où est écrite `constraint` dans `file` ; `null` si on ne sait pas la réécrire |
| `unverifiable_reason` | chaîne ou `null` | pourquoi on ne peut pas la vérifier : `dépendance git`, `chemin local`, `téléchargée depuis une URL`, `membre du workspace`… |

### Emplacement

| Champ | Type | Sens |
|---|---|---|
| `line` | entier | ligne, à partir de 1 |
| `column` | entier | première colonne, à partir de 0, en caractères (pas en octets) |
| `end_column` | entier | colonne de fin, exclue. `column == end_column` : la contrainte est absente, c'est là qu'on l'insérerait |

## Constat

| Champ | Type | Sens |
|---|---|---|
| `kind` | [type](#types-de-constats) | |
| `severity` | [gravité](#gravités) | |
| `message` | chaîne | le constat en une ou deux phrases, en français, à montrer tel quel |
| `dependency` | [dépendance](#dépendance) ou `null` | la dépendance concernée, en entier ; `null` pour la fin de vie d'un runtime (E27) |
| `current_version` | chaîne ou `null` | la version utilisée : l'installée, sinon celle qu'impose une contrainte exacte (`==1.2.3`), sinon la borne basse de la contrainte |
| `current_is_approximate` | booléen | `true` quand `current_version` est une borne basse, faute de version installée : la version réelle peut être plus haute. Pour une faille : faille **possible** (voir [les failles](#les-failles)) |
| `target_version` | chaîne ou `null` | la version visée (voir le tableau ci-dessous) |
| `wanted_version` | chaîne ou `null` | `outdated` : la plus haute version que la contrainte accepte déjà, choisie comme le gestionnaire de paquets le ferait. On y monte en régénérant le lockfile, sans toucher au manifeste. `null` pour une dépendance indirecte ou une contrainte illisible |
| `gap` | [écart](#écarts) ou `null` | de `current_version` à `target_version` ; `null` si la cible n'est pas plus haute |
| `identifiers` | liste de chaînes | `vulnerable` : les identifiants de la faille, les CVE d'abord, puis les GHSA, puis les autres (`PYSEC-…`, `MAL-…`) ; `[]` pour les autres types |
| `cvss_score` | nombre ou `null` | `vulnerable` : le score CVSS 3 de la faille, de 0 à 10, s'il est connu ; `null` sinon, et pour les autres types |
| `detail` | chaîne ou `null` | ce que dit la source, tel quel, souvent en anglais : la raison d'un retrait, le message de dépréciation, le titre de l'avis de sécurité |
| `url` | chaîne ou `null` | pour en savoir plus : la page du paquet ; pour une faille, celle de l'avis sur osv.dev |

Ce que remplit chaque type :

| `kind` | `target_version` | Autres champs |
|---|---|---|
| `outdated` | la dernière version stable (pour npm : `dist-tags.latest`) | `current_version`, `gap`, `wanted_version` |
| `vulnerable` | la plus petite version qui corrige la faille, au-dessus de la version utilisée ; `null` si aucune n'est connue (paquet malveillant, faille jamais corrigée, avis illisible) | `identifiers`, `cvss_score`, `detail` (le titre de l'avis), `url` (l'avis), `gap` |
| `yanked` | la plus proche version non retirée ; `null` s'il n'y en a pas | `detail` : la raison du retrait |
| `deprecated` (paquet) | `null` : le remplacer est un choix humain | `detail` : le message du registre |
| `deprecated` (version, npm) | la plus proche version non dépréciée | `detail` : le message du registre |
| `unverifiable` | `null` | `message` : la raison (paquet introuvable, dépendance git…) |
| `inconclusive` | la dernière, si on la connaît | `message` : pourquoi (réseau, hors ligne sans cache, version utilisée inconnue, version inconnue du registre, failles non vérifiées) |

### Les failles

Les failles viennent d'[OSV](https://osv.dev), qui réunit les avis de GitHub
(GHSA), de PyPI (PYSEC), des paquets malveillants (MAL) et des autres
écosystèmes.

- **Toutes les dépendances**, indirectes comprises, quelle que soit
  `options.transitive` ; celles de développement sauf avec `options.dev` à
  `false`. Une indirecte en faille a un constat comme une directe
  (`dependency.direct` à `false`), avec sa version installée.
- **Un constat par faille** : les avis qui se citent (un GHSA et le PYSEC de la
  même CVE) sont réunis, avec tous leurs identifiants. Les avis d'un paquet
  malveillant sont réunis en un seul constat.
- **`severity`** : celle du plus grave des avis réunis (CVSS 3, sinon la gravité
  donnée par GitHub). Un paquet malveillant est toujours `critical`. Sans rien
  pour en juger, `medium` : le `message` dit « gravité inconnue », et
  `cvss_score` est `null`.
- **Faille possible** : sans lockfile, la version utilisée est la borne basse de
  la contrainte (`current_is_approximate`). La faille concerne cette version,
  mais la version installée peut être plus récente, et corrigée. C'est quand même
  un constat `vulnerable` (la contrainte accepte une version concernée), qui
  compte pour `--fail-on vuln`.
- **Jamais « pas de faille » par erreur** : si OSV n'a pas pu répondre, une
  dépendance vérifiée a un constat `inconclusive` (« Failles non vérifiées. … ») ;
  les autres indirectes, une [remarque](#remarque) sur le lockfile. Un avis
  qu'on n'a pas pu lire reste une faille, de gravité et de version corrigée
  inconnues.

### Ordre des constats

Dans chaque projet, du plus grave au moins grave (décision n°8 du brief) :
faille (par gravité) > fin de vie > retirée > dépréciée > majeure > mineure >
correctif > non vérifiable > non concluant. À rang égal, par nom de paquet.

## Version forcée

`overrides` (npm), `resolutions` (Yarn), `pnpm.overrides`, et `overrides` de
`pnpm-workspace.yaml` (pnpm 10+) : une version imposée à un paquet, quoi que demandent
les paquets qui le tirent. Seules celles de la racine d'un workspace comptent. Celles de
`pnpm-workspace.yaml` viennent en premier : pnpm 10 les fait passer devant, et pnpm 11+
ne lit plus celles du `package.json`.

| Champ | Type | Sens |
|---|---|---|
| `ecosystem` | [écosystème](#écosystèmes) | `npm` |
| `name` | chaîne | le paquet forcé |
| `constraint` | chaîne | la version forcée telle qu'écrite (`^3.4.13`, `$dompurify`) ; `""` pour un chemin local ou une URL |
| `key` | chaîne | la clé telle qu'écrite : `dompurify`, `**/lodash` (Yarn), `foo@<2` ou `a>b` (pnpm) ; pour npm, les clés imbriquées séparées par `>` |
| `section` | chaîne | `overrides`, `resolutions` ou `pnpm.overrides` (`overrides` aussi dans `pnpm-workspace.yaml`) |
| `file` | chemin | le `package.json`, ou le `pnpm-workspace.yaml` |
| `location` | [emplacement](#emplacement) ou `null` | où est écrite `constraint` |

## Mise à jour

Les mises à jour possibles d'un paquet d'un projet. C'est un groupe de cases à
cocher : **au plus une option est choisie**. Une directe monte avec toutes ses
déclarations ; une indirecte est une version installée précise.

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | identifiant unique dans le rapport (`api\|PyPI\|requests`, plus la version installée pour une indirecte) : c'est lui que désigne une sélection |
| `ecosystem` | [écosystème](#écosystèmes) | |
| `name` | chaîne | le paquet |
| `direct` | booléen | `false` pour une indirecte : elle monte par son lockfile |
| `dependencies` | liste de [dépendances](#dépendance) | ses déclarations, ou l'indirecte |
| `current_version` | chaîne | la version utilisée (la plus basse de ses déclarations) |
| `current_is_approximate` | booléen | `true` sans lockfile : monter, c'est relever la borne basse |
| `options` | liste d'[options](#option-de-mise-à-jour) | de la plus ancienne à la plus récente version |
| `selected` | chaîne ou `null` | la version **pré-cochée**, ou `null` |
| `note` | chaîne ou `null` | ce que les options ne disent pas : `Code malveillant (…) : retirer ce paquet, aucune version sûre connue.`, `Aucune version corrigée connue pour …`, `Versions publiées inconnues du registre…` |

**Pré-cochée** (décision n°12 du brief) : parmi les options qui ne sont pas
majeures, ne reviennent pas en arrière, ne sont pas à faire à la main et n'ont pas
de faille que la version utilisée n'a pas (`introduced`), celle qui corrige le plus
de failles, puis la plus récente. Une majeure n'est jamais cochée d'office, même
quand elle seule corrige une faille. En 0.x, ce qui sort de `^` est une majeure.

### Option de mise à jour

| Champ | Type | Sens |
|---|---|---|
| `version` | chaîne | la version visée |
| `gap` | [écart](#écarts) ou `null` | depuis `current_version` ; `null` pour un retour à une version plus ancienne (remplacer une version retirée quand rien au-dessus ne convient) |
| `reasons` | liste de [raisons](#raisons) | pourquoi elle est proposée |
| `fixes` | liste de chaînes | les failles qu'elle corrige : le premier identifiant de chacune (une CVE s'il y en a) |
| `unfixed` | liste de chaînes | les failles du paquet qu'elle laisse |
| `introduced` | liste de chaînes | les failles connues de cette version que la version utilisée n'a pas (OSV, une requête pour toutes les versions proposées) : le premier identifiant de chacune. Une telle option n'est jamais pré-cochée. `[]` aussi si OSV n'a pas pu répondre : une [remarque](#remarque) du projet le dit |
| `edits` | liste de [réécritures](#réécriture) | les contraintes à réécrire. `[]` : la version est déjà dans la contrainte, le lockfile seul suffit |
| `lockfile` | chemin ou `null` | le lockfile à régénérer ; `null` sans lockfile |
| `manual` | chaîne ou `null` | pourquoi forceupdate ne sait pas l'appliquer seul (contrainte sans emplacement, style non géré) ; une telle option n'est jamais pré-cochée |
| `warnings` | liste de chaînes | à lire avant de cocher : `Majeure : peut demander d'adapter le code.`, `Revient à une version plus ancienne.`, `Version dépréciée : …`, `Faille connue dans cette version : …` |

### Réécriture

Une contrainte à réécrire, dans son style : `^4.17.0` devient `^4.21.2`, pas
`4.21.2` ; `>=2.25,<3` devient `>=3.1,<4`. Pour une faille, la nouvelle
contrainte n'accepte plus de version concernée (`~=1.4` → `~=1.9,>=1.9.2`).

| Champ | Type | Sens |
|---|---|---|
| `kind` | chaîne | `dependency` (une contrainte du manifeste), `catalog` (la plage d'un catalogue pnpm, dans `pnpm-workspace.yaml`), `override` (une version forcée) |
| `file` | chemin | le fichier à modifier ; pour un catalogue, le `package.json` qui y renvoie |
| `location` | [emplacement](#emplacement) ou `null` | où est écrite `old` ; `null` pour un catalogue |
| `old` | chaîne | le texte actuel de la contrainte |
| `new` | chaîne | le nouveau texte |
| `override` | [version forcée](#version-forcée) ou `null` | `override` : celle qui est réécrite |

## Remarque

| Champ | Type | Sens |
|---|---|---|
| `file` | chemin | le fichier concerné |
| `message` | chaîne | en français : `pas lu : il faudrait l'exécuter…`, `JSON invalide…`, `Failles non vérifiées pour 5 dépendances indirectes. OSV : …`, `Failles non vérifiées pour 4 versions proposées. OSV : …` |

## Options

| Champ | Type | Sens |
|---|---|---|
| `include_tests` | booléen | projets des dossiers de tests et d'exemples gardés |
| `dev` | booléen | dépendances de développement vérifiées (`scan --no-dev` : `false`) |
| `transitive` | booléen | dépendances indirectes vérifiées (`scan --transitive`) |
| `offline` | booléen | hors ligne : cache seul (`scan --offline`) |
| `cache` | booléen | cache disque utilisé (`scan --no-cache` : `false`) |

Une dépendance non vérifiée (de développement avec `dev: false`, indirecte sans
`transitive`) n'a pas de constat : son absence ne veut pas dire qu'elle est à jour.

## Résumé

Un paquet déclaré deux fois dans un projet y compte pour un.

| Champ | Type | Sens |
|---|---|---|
| `projects` | entier | nombre de projets |
| `direct` | entier | dépendances directes (déclarations) |
| `transitive` | entier | dépendances indirectes |
| `checked` | entier | dépendances vérifiées auprès des registres |
| `audited` | entier | dépendances dont les failles ont été cherchées (OSV) : toutes celles dont on connaît la version, indirectes comprises |
| `findings` | objet | constats par type, tous les types présents (`{"yanked": 1, "outdated": 3, …}`) |
| `outdated` | objet | constats `outdated` par écart (`{"major": 1, "minor": 2, "patch": 0}`) |
| `to_update` | entier | ce qui est à mettre à jour : tous les constats sauf `unverifiable` et `inconclusive` |
| `severities` | objet | les constats de `to_update` par gravité, toutes les gravités présentes (`{"critical": 0, "high": 13, …}`) |
| `vulnerabilities` | objet | les failles par gravité, de même |

## Valeurs des énumérations

### Écosystèmes

Les noms d'OSV : `PyPI`, `npm`, `crates.io`, `Go`, `Packagist`, `RubyGems`,
`Maven`, `NuGet`.

### Scopes

`runtime`, `dev`, `optional`, `peer`, `build`.

### Types de constats

| Valeur | Sens |
|---|---|
| `outdated` | une version plus récente existe |
| `vulnerable` | la version utilisée a une faille connue, d'après OSV |
| `eol` | le runtime ou le framework est en fin de vie (E27) |
| `yanked` | la version utilisée a été retirée du registre |
| `deprecated` | le paquet, ou la version utilisée (npm), est déprécié |
| `unverifiable` | impossible à vérifier : paquet introuvable, dépendance git ou locale |
| `inconclusive` | on ne conclut rien : erreur réseau, hors ligne sans cache, version utilisée inconnue |

### Gravités

`critical`, `high`, `medium`, `low`, `info`. Une faille a celle de son avis
(voir [les failles](#les-failles)). Pour
les autres : `yanked` est `medium` ; `deprecated` est `low` ; `outdated` est `low`
pour une majeure, `info` pour une mineure ou un correctif ; `unverifiable` et
`inconclusive` sont `info`.

### Écarts

`major`, `minor`, `patch`. En `0.y.z`, `y` joue le rôle de la majeure : `0.2.3` →
`0.3.0` est `major`.

### Raisons

| Valeur | Sens |
|---|---|
| `latest_patch` | le dernier correctif de la version utilisée |
| `latest_minor` | la dernière mineure : la plus haute version sans changer de majeure |
| `latest_major` | la dernière version, quand elle est majeure |
| `security_fix` | la plus petite version publiée, ni retirée ni dépréciée, qui corrige toutes les failles qui peuvent l'être |
| `replacement` | remplace une version retirée ou dépréciée |

## Exemple

Un `requirements.txt` qui contient `requests==2.32.0` (dépendance répétée dans
chaque constat, abrégée ici) :

```json
{
  "schema_version": 1,
  "tool": {"name": "forceupdate", "version": "0.1.0"},
  "source": "C:/Projets/demo",
  "languages": [],
  "projects": [
    {
      "path": "api",
      "ecosystems": ["PyPI"],
      "manifests": ["api/requirements.txt"],
      "lockfiles": [],
      "dependencies": [
        {
          "ecosystem": "PyPI",
          "name": "requests",
          "constraint": "==2.32.0",
          "resolved_constraint": null,
          "installed": null,
          "lockfile": null,
          "direct": true,
          "scope": "runtime",
          "file": "api/requirements.txt",
          "location": {"line": 1, "column": 8, "end_column": 16},
          "unverifiable_reason": null
        }
      ],
      "overrides": [],
      "findings": [
        {
          "kind": "vulnerable",
          "severity": "medium",
          "message": "CVE-2026-25645, GHSA-gc5v-m9x4-r6x2 (gravité moyenne, CVSS 5,5) : Requests has Insecure Temp File Reuse in its extract_zipped_paths() utility function. Corrigée en 2.33.0.",
          "dependency": {"ecosystem": "PyPI", "name": "requests", "…": "…"},
          "current_version": "2.32.0",
          "current_is_approximate": false,
          "target_version": "2.33.0",
          "wanted_version": null,
          "gap": "minor",
          "identifiers": ["CVE-2026-25645", "GHSA-gc5v-m9x4-r6x2", "PYSEC-2026-2275"],
          "cvss_score": 5.5,
          "detail": "Requests has Insecure Temp File Reuse in its extract_zipped_paths() utility function",
          "url": "https://osv.dev/vulnerability/GHSA-gc5v-m9x4-r6x2"
        },
        {
          "kind": "vulnerable",
          "severity": "medium",
          "message": "CVE-2024-47081, GHSA-9hjg-9r4m-mvj7 (gravité moyenne, CVSS 5,3) : Requests vulnerable to .netrc credentials leak via malicious URLs. Corrigée en 2.32.4.",
          "dependency": {"ecosystem": "PyPI", "name": "requests", "…": "…"},
          "current_version": "2.32.0",
          "current_is_approximate": false,
          "target_version": "2.32.4",
          "wanted_version": null,
          "gap": "patch",
          "identifiers": ["CVE-2024-47081", "GHSA-9hjg-9r4m-mvj7", "PYSEC-2026-1872"],
          "cvss_score": 5.3,
          "detail": "Requests vulnerable to .netrc credentials leak via malicious URLs",
          "url": "https://osv.dev/vulnerability/GHSA-9hjg-9r4m-mvj7"
        },
        {
          "kind": "yanked",
          "severity": "medium",
          "message": "Version 2.32.0 retirée de PyPI : Yanked due to conflicts with CVE-2024-35195 mitigation. La plus proche non retirée : 2.32.2.",
          "dependency": {"ecosystem": "PyPI", "name": "requests", "…": "…"},
          "current_version": "2.32.0",
          "current_is_approximate": false,
          "target_version": "2.32.2",
          "wanted_version": null,
          "gap": "patch",
          "identifiers": [],
          "cvss_score": null,
          "detail": "Yanked due to conflicts with CVE-2024-35195 mitigation",
          "url": "https://pypi.org/project/requests/"
        },
        {
          "kind": "outdated",
          "severity": "info",
          "message": "Version 2.34.2 disponible (mineure) ; utilisée : 2.32.0.",
          "dependency": {"ecosystem": "PyPI", "name": "requests", "…": "…"},
          "current_version": "2.32.0",
          "current_is_approximate": false,
          "target_version": "2.34.2",
          "wanted_version": null,
          "gap": "minor",
          "identifiers": [],
          "cvss_score": null,
          "detail": null,
          "url": "https://pypi.org/project/requests/"
        }
      ],
      "updates": [
        {
          "id": "api|PyPI|requests",
          "ecosystem": "PyPI",
          "name": "requests",
          "direct": true,
          "dependencies": [{"ecosystem": "PyPI", "name": "requests", "…": "…"}],
          "current_version": "2.32.0",
          "current_is_approximate": false,
          "options": [
            {
              "version": "2.32.2",
              "gap": "patch",
              "reasons": ["replacement"],
              "fixes": [],
              "unfixed": ["CVE-2026-25645", "CVE-2024-47081"],
              "introduced": [],
              "edits": [
                {
                  "kind": "dependency",
                  "file": "api/requirements.txt",
                  "location": {"line": 1, "column": 8, "end_column": 16},
                  "old": "==2.32.0",
                  "new": "==2.32.2",
                  "override": null
                }
              ],
              "lockfile": null,
              "manual": null,
              "warnings": []
            },
            {"version": "2.32.5", "gap": "patch", "reasons": ["latest_patch"], "fixes": ["CVE-2024-47081"], "unfixed": ["CVE-2026-25645"], "…": "…"},
            {"version": "2.33.0", "gap": "minor", "reasons": ["security_fix"], "fixes": ["CVE-2026-25645", "CVE-2024-47081"], "unfixed": [], "…": "…"},
            {"version": "2.34.2", "gap": "minor", "reasons": ["latest_minor"], "fixes": ["CVE-2026-25645", "CVE-2024-47081"], "unfixed": [], "…": "…"}
          ],
          "selected": "2.34.2",
          "note": null
        }
      ],
      "notices": []
    }
  ],
  "ignored_manifests": [],
  "options": {"include_tests": false, "dev": true, "transitive": false, "offline": false, "cache": true},
  "scanned_at": "2026-10-27T19:52:06.684328+00:00",
  "oldest_data": "2026-10-27T19:35:15.956959+00:00",
  "summary": {
    "projects": 1,
    "direct": 1,
    "transitive": 0,
    "checked": 1,
    "audited": 1,
    "findings": {"vulnerable": 2, "eol": 0, "yanked": 1, "deprecated": 0, "outdated": 1, "unverifiable": 0, "inconclusive": 0},
    "outdated": {"major": 0, "minor": 1, "patch": 0},
    "severities": {"critical": 0, "high": 0, "medium": 3, "low": 0, "info": 1},
    "vulnerabilities": {"critical": 0, "high": 0, "medium": 2, "low": 0, "info": 0},
    "to_update": 4
  }
}
```

`wanted_version` est `null` partout : `==2.32.0` n'accepte que la version
retirée, il faut changer la contrainte. Chaque constat donne sa propre cible
(2.33.0 et 2.32.4 pour les failles, 2.32.2 pour le retrait, 2.34.2 pour la
dernière) : choisir la version qui les satisfait toutes est le travail du
planificateur (E09).

# L'API de l'interface web

Le serveur local de `forceupdate ui` (E12). Le code est dans `src/forceupdate/web/` ;
le schéma OpenAPI, d'où viennent les types du front, est exporté dans
`src/forceupdate/web/openapi.json` (`uv run python -m forceupdate.web.openapi` le
refait ; un test vérifie qu'il est à jour, un autre que les réponses le suivent). Les
conventions sont celles du rapport : UTF-8, dates ISO 8601 en UTC, énumérations en
chaînes, tous les champs toujours présents (`null` ou `[]` s'il n'y a rien). Les
chemins envoyés sont absolus ; ceux que rend l'API aussi, au format POSIX
(`C:/Users/…` sous Windows).

## Accès

- Le serveur n'écoute que sur `127.0.0.1`, sur un port libre (ou `--port`).
- Chaque requête porte le **jeton de session**, tiré au démarrage : le cookie que pose
  l'adresse affichée par `forceupdate ui` (`http://127.0.0.1:<port>/?token=<jeton>`,
  qui renvoie ensuite vers `/` sans le jeton), ou l'en-tête
  `Authorization: Bearer <jeton>`. Sans lui : `401`. Le jeton n'est jamais accepté
  dans l'adresse d'une route de `/api`.
- `Host` doit être `127.0.0.1:<port>` ou `localhost:<port>` (sinon `400`) ; `Origin`,
  s'il y en a un, l'adresse du serveur, et `Sec-Fetch-Site`, s'il y en a un,
  `same-origin` ou `none` (sinon `403`). Pas de CORS.
- Seule exception : l'[adresse de retour d'OAuth](#adresse-de-retour-doauth), où la forge
  renvoie le navigateur.

Avec curl :

```bash
curl -H "Authorization: Bearer $JETON" "http://127.0.0.1:$PORT/api/scans"
```

## Les routes

| Méthode et chemin | Corps | Réponse |
|---|---|---|
| `GET /api/fs?path=` | | `200` [liste de dossier](#liste-de-dossier) ; sans `path`, les points de départ |
| `POST /api/scans` | [demande d'analyse](#demande-danalyse) | `202` [analyse](#analyse), lancée en tâche de fond |
| `GET /api/scans` | | `200` les [analyses](#analyse) de la session, de la plus récente à la plus ancienne |
| `GET /api/scans/{id}` | | `200` [analyse](#analyse), avec `report` une fois finie |
| `GET /api/scans/{id}/events` | | `200` [progression](#progression-sse) en Server-Sent Events |
| `DELETE /api/scans/{id}` | | `200` [analyse](#analyse) annulée ; `409` si elle est déjà finie |
| `POST /api/updates/plan` | `{"scan": id, "selection": {…}}` | `201` [plan](#plan-de-mise-à-jour) |
| `POST /api/updates/apply` | `{"plan": id, "force": false}` | `202` [plan](#plan-de-mise-à-jour), appliqué en tâche de fond |
| `GET /api/updates/{id}` | | `200` [plan](#plan-de-mise-à-jour), avec `results` une fois appliqué |
| `GET /api/updates/{id}/events` | | `200` [progression](#progression-sse) de l'application ; `409` si le plan n'est pas appliqué |
| `GET /api/updates/{id}/files/{chemin}` | | `200` le fichier tel que le plan le réécrit, à télécharger |
| `POST /api/files?name=<nom>` | le contenu du fichier | `202` [analyse](#analyse) d'un [fichier envoyé](#fichier-envoyé) |
| `GET /api/accounts` | | `200` [liste des comptes](#liste-des-comptes) : les forges, et qui y est connecté |
| `POST /api/accounts/{forge}/oauth` | | `201` [connexion](#connexion) OAuth : aller à `authorize_url` |
| `POST /api/accounts/{forge}/device` | | `201` [connexion](#connexion) par device flow : le code à taper |
| `GET /api/accounts/connections/{id}` | | `200` [connexion](#connexion) : où elle en est |
| `DELETE /api/accounts/connections/{id}` | | `200` [connexion](#connexion) annulée |
| `POST /api/accounts/{forge}/token` | `{"token": "…"}` | `201` [compte](#compte), une fois le token accepté par la forge |
| `POST /api/accounts/{forge}/gh` | | `201` [compte](#compte) de GitHub CLI (`gh auth token`) |
| `POST /api/accounts/{forge}/verify` | | `200` [compte](#compte), droits relus auprès de la forge |
| `DELETE /api/accounts/{forge}` | | `200` [déconnexion](#déconnexion) |
| `GET /api/repositories?reload=` | | `200` [liste des dépôts](#liste-des-dépôts) des comptes connectés, avec la synthèse ; `reload=true` la redemande aux forges |
| `POST /api/repositories/batches` | [demande d'analyse groupée](#demande-danalyse-groupée) | `202` [analyse groupée](#analyse-groupée), lancée en tâche de fond |
| `GET /api/repositories/batches/{id}` | | `200` [analyse groupée](#analyse-groupée) |
| `DELETE /api/repositories/batches/{id}` | | `200` [analyse groupée](#analyse-groupée) : ses analyses pas finies sont annulées |
| `POST /api/repositories/scans` | `{"repository": "owner/nom ou adresse", …}` | `202` [analyse](#analyse) d'un dépôt, même d'un autre compte s'il est public |

`{forge}` : `github`, `gitlab` ou `bitbucket` (sinon `422`) ; GitLab et Bitbucket
répondent `409` tant que leur connexion n'est pas prête (E19, E20). Un plan
(`POST /api/updates/plan`) sur l'analyse d'un dépôt est refusé (`409`) : un dépôt se mettra à
jour par une PR (E18).

Une erreur rend `{"detail": "…"}`, une phrase en français : `400` (requête invalide :
chemin relatif, sélection qui ne correspond pas au rapport, nom de fichier refusé ; token
refusé par la forge), `401`, `403`, `404` (analyse, plan, chemin, connexion inconnus ;
aucun compte connecté), `409` (impossible dans l'état actuel : analyse pas finie, plan
déjà appliqué, changements que git n'a pas en commit, rien à appliquer ; trousseau
indisponible, limite d'API de la forge atteinte), `413` (fichier envoyé trop gros), `502`
(la forge ne répond pas). Un corps mal formé rend le `422` de FastAPI, dont `detail` est
une liste. **Un refus de la forge n'est jamais un `401`** : celui-là veut toujours dire
« jeton de session manquant ».

Les analyses et les plans restent en mémoire le temps de la session (les 20 analyses
les plus récentes, avec leurs plans) ; seuls les chemins récents sont gardés sur le
disque.

## Demande d'analyse

| Champ | Type | Sens |
|---|---|---|
| `path` | chaîne | chemin absolu d'un dossier ou d'un fichier ; requis |
| `dev`, `transitive`, `include_tests`, `offline`, `cache` | booléens | les [options](#options), mêmes valeurs par défaut que `scan` |

## Analyse

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | identifiant de l'analyse |
| `source` | chaîne | le chemin analysé ; pour un fichier envoyé, son nom ; pour un dépôt, `owner/nom` |
| `kind` | chaîne | `folder`, `file`, `upload` (un fichier envoyé) ou `repository` (un [dépôt d'une forge](#dépôts-des-forges)) |
| `repository` | objet ou `null` | un dépôt : `{"forge", "host", "full_name", "url", "commit", "truncated"}` ; `commit` est celui lu (la branche par défaut au début de l'analyse ; `null` avant que l'arborescence soit lue) ; `truncated` : la forge n'a pas rendu toute l'arborescence (GitHub, plus de 100 000 entrées), l'analyse est partielle |
| `batch` | chaîne ou `null` | l'[analyse groupée](#analyse-groupée) dont elle fait partie |
| `status` | chaîne | `running`, puis `done`, `failed` ou `cancelled` |
| `options` | [options](#options) | |
| `started_at`, `finished_at` | dates | `finished_at` : `null` tant qu'elle tourne |
| `error` | chaîne ou `null` | `failed` : ce qui s'est passé |
| `progress` | [événement](#événement) ou `null` | le dernier reçu |
| `summary` | [résumé](#résumé) ou `null` | une fois `done` : le `summary` du rapport (ses chiffres, sans charger le rapport) ; `null` avant, ou si l'analyse n'a pas abouti |
| `report` | [rapport](#le-rapport) ou `null` | seulement dans `GET /api/scans/{id}`, une fois `done` : le JSON de `scan --format json` |

## Plan de mise à jour

Un plan est la sélection préparée sur le rapport d'une analyse finie, sans rien
écrire. Il reste sur le serveur : on l'applique par son identifiant, et c'est ce plan
qui est écrit (si un fichier a changé depuis son diff, rien n'est écrit). Les mises à
jour et leurs options ne sont pas recopiées : elles sont désignées par l'`id` de la
[mise à jour](#mise-à-jour) et la `version` de l'option, dans le rapport de l'analyse.

`selection`, envoyée et rendue : `{"<id de la mise à jour>": "<version>"}`. La
sélection par défaut est celle des `selected` du rapport. Un paquet absent n'est pas
mis à jour.

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | identifiant du plan |
| `scan` | chaîne | l'analyse dont il vient |
| `status` | chaîne | `planned`, puis `running` (écriture et lockfiles), `done` (écrit ; chaque lockfile dit dans `results` ce qu'il est advenu de lui) ou `failed` (rien n'est écrit) |
| `created_at`, `finished_at` | dates | |
| `selection` | objet | la sélection envoyée |
| `applied` | liste de `{"update", "version"}` | les options qui seront appliquées |
| `skipped` | liste de `{"update", "version", "reason"}` | celles qui ne le seront pas, et pourquoi (à faire à la main, fichier changé depuis l'analyse, `--hash`…) |
| `files` | liste de `{"path", "diff"}` | les fichiers réécrits, par chemin, avec leur diff unifié (comme `git diff`) |
| `lockfiles` | liste de [lockfiles à régénérer](#lockfile-à-régénérer) | dans l'ordre ; aucun pour un fichier envoyé |
| `uncommitted` | liste de chemins ou `null` | parmi les fichiers à écrire, ceux qui ont des changements que git n'a pas en commit ; `null` hors d'un dépôt git (rien ne permettra de revenir en arrière). Revérifié en appliquant : refusé (`409`) sauf `"force": true` |
| `applicable` | booléen | on peut l'appliquer : pas encore fait, quelque chose à écrire ou à lancer, pas un fichier envoyé |
| `error` | chaîne ou `null` | `failed` : pourquoi rien n'a été écrit |
| `results` | liste de [lockfiles régénérés](#lockfile-régénéré) | une fois `done` |
| `progress` | [événement](#événement) ou `null` | le dernier reçu |

Les mises à jour s'appliquent une à la fois, dans l'ordre où elles sont demandées. Une
mise à jour en cours ne s'annule pas : si un outil échoue, ses fichiers sont remis
comme avant.

### Lockfile à régénérer

| Champ | Type | Sens |
|---|---|---|
| `lockfile` | chemin | |
| `kind` | chaîne | `npm`, `pnpm`, `yarn1`, `yarn`, `uv`, `poetry`, `pdm`, `pipenv`, `pip-compile`, `uv-pip-compile` |
| `tool` | chaîne | le nom de l'outil, pour le dire (`uv pip compile`) |
| `program` | chaîne | le programme à installer (`uv`) |
| `available` | booléen | l'outil est installé ; sinon le lockfile n'est pas régénéré, et `command` est à lancer à la main |
| `command` | chaîne | la commande à lancer à la main, dans `directory` |
| `directory` | chemin | le dossier du lockfile |
| `updates` | liste de `{"update", "version"}` | les mises à jour qu'il porte |
| `workspace` | booléen | le lockfile d'un workspace |
| `reason` | chaîne ou `null` | pourquoi il est régénéré sans mise à jour à lui (pip-tools : `requirements.txt a changé`) |
| `warnings` | liste de chaînes | ce que l'outil exécute quand même, une option d'en-tête pas reprise… |

### Lockfile régénéré

| Champ | Type | Sens |
|---|---|---|
| `lockfile` | chemin | |
| `status` | chaîne | `regenerated`, `tool_missing` (manifestes réécrits, commande à lancer), `failed` (fichiers remis comme avant), `undone` (remis comme avant : un lockfile qui dépend des mêmes fichiers a échoué) |
| `error` | chaîne ou `null` | `failed` : ce que l'outil a dit ; `undone` : quel lockfile a échoué |
| `restored` | liste de chemins | les fichiers remis comme avant |
| `installed` | liste | `regenerated` : pour chaque mise à jour, `{"update", "version", "versions", "reach", "held_by"}`, les versions installées relues ; `reach` vaut `exact`, `above` (l'outil a pris la plus haute permise), `below` (retenue par `held_by`, `["debug 4.3.1"]`) ou `unknown` |
| `changed` | liste de chaînes | les autres paquets que le lockfile a changés (`h11 0.16.0 → 0.14.0`) |
| `warnings` | liste de chaînes | ce qui s'est passé en route |

## Progression (SSE)

`GET …/events` envoie des Server-Sent Events. Les événements déjà passés sont envoyés
d'abord : depuis le début, ou depuis celui qui suit `Last-Event-ID` quand le
navigateur se rebranche.

```
id: 0
event: progress
data: {"kind":"reading","done":0,"total":0,"ecosystem":null,"name":null}

id: 7
event: end
data: {"status":"done","error":null}
```

- `progress` : un [événement](#événement) ;
- `end` : la tâche est finie (`status` et `error` comme dans l'analyse ou le plan) ; le
  flux se ferme. Le navigateur doit alors fermer son `EventSource`, qui sinon se
  rebrancherait ;
- `: ping`, un commentaire, après 15 s sans rien.

### Événement

| Champ | Type | Sens |
|---|---|---|
| `kind` | chaîne | l'étape (ci-dessous) |
| `done`, `total` | entiers | où on en est |
| `ecosystem` | chaîne ou `null` | `package_checked` : l'écosystème du paquet |
| `name` | chaîne ou `null` | `package_checked` : le paquet ; `regenerating` : le lockfile |

Une analyse : `downloading` (un dépôt seulement : ses fichiers de dépendances téléchargés,
`done` sur `total` ; le total grandit quand un fichier en désigne d'autres), `reading`,
`projects_found` (`total` projets), `checking` (`total`
vérifications : une par paquet, plus une pour les failles), `package_checked` et
`vulnerabilities_checked` (`done` sur `total`), `finished`. L'application d'un plan :
`written` (`total` fichiers réécrits), `regenerating` (un par outil lancé : `done`
déjà faits sur `total`), `finished`. Un outil peut tourner plusieurs minutes (10 au
plus par commande).

## Liste de dossier

Seulement des noms : les dossiers, et les fichiers de dépendances que forceupdate sait
lire. Jamais le contenu d'un fichier. Les liens symboliques et les jonctions Windows
ne sont pas listés (un dossier OneDrive l'est).

| Champ | Type | Sens |
|---|---|---|
| `path` | chemin ou `null` | le dossier listé ; `null` pour les points de départ (le dossier personnel, puis les lecteurs : `C:/`… sous Windows, `/` ailleurs) |
| `parent` | chemin ou `null` | |
| `entries` | liste de `{"name", "path", "kind", "hidden"}` | les dossiers puis les fichiers, par nom ; `kind` : `drive`, `folder` ou `file` ; `hidden` : nom en `.`, ou caché pour Windows |
| `truncated` | booléen | plus de 5000 entrées : la liste est coupée |
| `home` | chemin | le dossier personnel |
| `recent` | liste de `{"path", "kind"}` | les 10 derniers chemins analysés qui existent encore, du plus récent au plus ancien ; `kind` : `folder` (dossier, lecteur compris) ou `file` |

## Fichier envoyé

`POST /api/files?name=package.json`, avec le contenu du fichier comme corps
(`application/octet-stream`) : un manifeste ou un lockfile (`400` sinon), de 2 Mo au
plus (50 Mo pour un lockfile ; `413` au-delà). Il est analysé comme un fichier de
l'ordinateur (`kind: "upload"`) : même progression, même rapport (`source` est son
nom), même plan. Mais rien ne s'écrit sur le disque de la personne et aucun outil
n'est lancé : le plan n'a pas de lockfiles, ne s'applique pas (`409`), et sa version
réécrite se télécharge par `GET /api/updates/{id}/files/{nom}`.

## Comptes des forges

Chaque personne connecte son propre compte (E16 : GitHub ; GitLab à E19, Bitbucket à
E20). **Le token reste sur le serveur** : rangé dans le trousseau du système (`keyring`),
jamais renvoyé au navigateur, jamais dans un journal ni dans `accounts.json` (qui garde le
reste, dans le dossier d'état de l'utilisateur). Le navigateur n'envoie un token que quand
la personne le colle.

Quatre façons de se connecter (`method`) :

- `oauth` : `POST …/oauth` rend `authorize_url`, la page d'autorisation de la forge, où
  le navigateur doit aller ; la forge le renvoie sur l'[adresse de retour](#adresse-de-retour-doauth),
  qui échange le code contre le token puis renvoie vers `/comptes?connexion=<id>` ;
- `device` (device flow) : `POST …/device` rend un code (`user_code`) à taper sur
  `verification_uri` ; le serveur attend l'autorisation tout seul, le navigateur suit la
  connexion par `GET /api/accounts/connections/{id}` ;
- `token` : un token collé (`POST …/token`) ;
- `gh` : le token de GitHub CLI (`POST …/gh`), lu par `gh auth token`.

Portées demandées à GitHub : `repo` et `read:org`.

### Liste des comptes

| Champ | Type | Sens |
|---|---|---|
| `keyring` | chaîne ou `null` | pourquoi le trousseau du système ne peut pas garder de token (aucun n'est utilisable) ; `null` s'il marche |
| `forges` | liste | une entrée par forge, dans l'ordre GitHub, GitLab, Bitbucket (ci-dessous) |

Chaque forge :

| Champ | Type | Sens |
|---|---|---|
| `forge` | chaîne | `github`, `gitlab`, `bitbucket` |
| `name`, `host` | chaînes | `GitHub`, `github.com` |
| `available` | booléen | la connexion est prête ; sinon elle arrive à une étape à venir |
| `methods` | liste de chaînes | les façons de se connecter possibles maintenant : `gh` seulement s'il est installé, `oauth` seulement si l'application a son secret |
| `scopes` | liste de chaînes | les portées demandées par `oauth` et `device` |
| `token_url` | chaîne ou `null` | où créer un token à coller, portées pré-cochées |
| `account` | [compte](#compte) ou `null` | le compte connecté |
| `connection` | [connexion](#connexion) ou `null` | une connexion en attente (un device flow se retrouve après un rechargement) |

Rien n'est demandé aux forges pour lister : `POST …/verify` relit les droits.

### Compte

| Champ | Type | Sens |
|---|---|---|
| `forge`, `host` | chaînes | |
| `login` | chaîne | l'identifiant (`octo`) |
| `name` | chaîne ou `null` | le nom affiché |
| `url` | chaîne | son profil sur la forge |
| `access` | chaîne | ce que permet le token : `write` (lire, pousser, ouvrir des PR, dépôts publics et privés), `public` (la même chose, dépôts publics seulement), `read` (lire les dépôts publics), `unknown` (droits non vérifiés : la forge ne les dit pas, token « fine-grained » de GitHub) |
| `scopes` | liste ou `null` | les portées du token (`X-OAuth-Scopes` de GitHub) ; `null` si la forge ne les dit pas |
| `warnings` | liste de chaînes | ce qui manquera avec ces droits (`read:org` absente…) |
| `method` | chaîne | `oauth`, `device`, `token`, `gh` |
| `connected_at` | date | |
| `checked_at` | date | la dernière fois que la forge a accepté le token |
| `problem` | chaîne ou `null` | ce qui n'allait pas au dernier contrôle : la forge refuse le token (révoqué sur la forge) ; le compte reste, pour qu'on se reconnecte |

### Connexion

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | |
| `forge`, `method` | chaînes | `method` : `oauth` ou `device` |
| `status` | chaîne | `pending`, puis `done`, `failed`, `expired` (pas d'autorisation à temps : 10 min pour OAuth, la durée du code pour le device flow) ou `cancelled` (annulée, ou remplacée par une autre connexion à la même forge) |
| `created_at`, `expires_at` | dates | |
| `authorize_url` | chaîne ou `null` | OAuth, tant qu'elle attend : la page d'autorisation |
| `user_code`, `verification_uri` | chaînes ou `null` | device flow : le code, et où le taper |
| `interval` | entier ou `null` | device flow : secondes entre deux demandes du serveur à la forge |
| `error` | chaîne ou `null` | `failed`, `expired` : ce qui s'est passé |
| `account` | [compte](#compte) ou `null` | `done` : le compte connecté |

Les connexions vivent en mémoire, le temps de la session (les 20 dernières).

### Déconnexion

`DELETE /api/accounts/{forge}` efface le token du trousseau et le compte. Un token obtenu
par `oauth` ou `device` est aussi révoqué auprès de la forge ; un token collé, ou celui
de `gh`, n'appartient pas à forceupdate et reste valable.

| Champ | Type | Sens |
|---|---|---|
| `forge`, `login` | chaînes | |
| `revoked` | booléen ou `null` | `true` : révoqué ; `false` : la forge n'a pas pu le révoquer (injoignable) ; `null` : token collé ou de `gh`, pas à révoquer |
| `message` | chaîne | ce qui a été fait, à montrer |

### Adresse de retour d'OAuth

`GET /oauth/github/callback?code=…&state=…` : la forge y renvoie le navigateur après
l'autorisation. Elle n'est pas dans `/api` ni dans le schéma OpenAPI : le front ne
l'appelle jamais.

C'est une navigation venue d'un autre site (github.com) : le cookie de session
(`SameSite=Strict`) n'y est pas envoyé, et `Sec-Fetch-Site` vaut `cross-site`. Le garde
la laisse donc passer sans jeton de session, mais seulement en `GET`, en navigation
(`Sec-Fetch-Mode: navigate` et `Sec-Fetch-Dest: document` s'ils sont là), sans `Origin`
étrangère (sinon `403`), et toujours avec le bon `Host`. Ce qui la protège est le
`state`, tiré par le serveur pour une connexion lancée avec le jeton de session, gardé en
mémoire, valable 10 minutes et **une seule fois** ; PKCE (`S256`) s'ajoute au secret de
l'application. Sans `state` connu, la page ne fait rien (`400`).

Elle rend une petite page HTML qui renvoie aussitôt vers `/comptes?connexion=<id>`
(`<meta http-equiv="refresh">`, avec un lien) : une redirection HTTP laisserait la page
suivante « d'un autre site » (la chaîne de redirections part de github.com), sans cookie.
Lancée par cette page, la navigation vient du serveur lui-même.

GitHub ne revient que vers `127.0.0.1` (l'adresse enregistrée, sur n'importe quel port) :
`POST …/oauth` est refusé (`409`) si l'interface est ouverte par `localhost`.

## Dépôts des forges

Les dépôts des comptes connectés (E17), analysés **sans les cloner** : l'arborescence du
dernier commit de la branche par défaut vient de l'API de la forge, puis seuls les fichiers que
les parseurs lisent sont téléchargés (manifestes, lockfiles, et ce qu'ils désignent : les `-r`
et `-c` d'un `requirements.txt`, le `pyproject.toml` racine d'un workspace uv, un
`pnpm-workspace.yaml` parent). Le rapport est ensuite celui d'un dossier : même JSON, `source`
vaut `owner/nom`. Le token ne quitte pas le serveur.

La liste est demandée aux forges au premier `GET /api/repositories`, puis gardée le temps de la
session (`reload=true` la redemande ; un compte reconnecté la recharge). Les dépôts archivés,
les forks et les dépôts vides sont listés mais **masqués et sautés par défaut** (`hidden`) ; un
dépôt vide n'est jamais analysé.

### Liste des dépôts

| Champ | Type | Sens |
|---|---|---|
| `accounts` | liste de [comptes et leurs dépôts](#compte-et-ses-dépôts) | un par compte connecté |
| `repositories` | liste de [dépôts](#dépôt) | par forge, puis par nom |
| `synthesis` | [synthèse](#synthèse-multi-dépôts) | les chiffres de tous les dépôts, calculés par le serveur |
| `batch` | [analyse groupée](#analyse-groupée) ou `null` | la dernière |

### Compte et ses dépôts

| Champ | Type | Sens |
|---|---|---|
| `forge`, `host`, `login`, `access` | | comme dans le [compte](#compte) |
| `problem` | chaîne ou `null` | la forge refuse le token (au chargement de la liste, ou pendant une analyse) |
| `listed_at` | date ou `null` | le dernier chargement réussi de la liste |
| `error` | chaîne ou `null` | pourquoi le dernier chargement a échoué ; la liste d'avant reste |
| `repositories` | entier | |
| `restrictions` | liste de `{"organization", "kind", "url"}` | les organisations du compte dont les dépôts ne sont pas tous lisibles : `kind` vaut `app_access` (elle restreint l'accès des applications OAuth : ses dépôts privés n'apparaissent qu'après l'accord d'un propriétaire ; `url` : où le demander) ou `sso` (elle exige d'autoriser le token pour son SSO ; `url` : où le faire). GitHub : `GET /user/orgs` (portée `read:org`), puis un `403` sur la liste de ses dépôts. Sans `read:org`, rien n'est su |
| `rate_limit` | `{"limit", "remaining", "reset_at"}` ou `null` | les requêtes d'API restantes, d'après la dernière réponse de la forge |

### Dépôt

| Champ | Type | Sens |
|---|---|---|
| `forge`, `host` | chaînes | |
| `full_name`, `owner`, `name` | chaînes | `octo/app`, `octo`, `app` |
| `url` | chaîne | sa page sur la forge |
| `default_branch` | chaîne ou `null` | `null` pour un dépôt vide |
| `private`, `archived`, `fork`, `empty` | booléens | |
| `can_push` | booléen | le compte peut pousser une branche et ouvrir une PR ; sinon : lecture seule |
| `pushed_at` | date ou `null` | le dernier push |
| `hidden` | booléen | archivé, fork ou vide : masqué par défaut, et pas analysé avec les autres |
| `languages` | liste de chaînes | ceux de la dernière analyse ; avant, ou si elle n'a trouvé aucun fichier de code, le langage principal d'après la forge |
| `state` | chaîne | `not_scanned` (ou analyse annulée), `running` (en cours, ou en attente de son tour), `to_update`, `up_to_date`, `inconclusive` (pas tout vérifié : registre, OSV ou forge muets, arborescence tronquée, ou analyse échouée), `no_dependencies`, `skipped` (vide ; archivé ou fork pas encore analysé) |
| `reason` | chaîne ou `null` | pourquoi : `vide`, `archivé`, `fork` ; ce qui n'a pas répondu ; l'erreur ; `analyse annulée` |
| `counts` | objet ou `null` | la dernière analyse finie : `vulnerabilities`, `critical`, `worst` (la gravité de la faille la plus grave, `null` sans faille), `to_update`, `inconclusive`, `updates` (les mises à jour pré-cochées) |
| `scan` | [analyse](#analyse) ou `null` | la dernière analyse du dépôt, groupée ou non (sa progression s'il tourne ; son rapport par `GET /api/scans/{id}`) |

`to_update` : au moins un constat à mettre à jour. `up_to_date` ne se dit que si rien n'est
resté sans réponse et que toute l'arborescence a été lue (`report.synthesis.verdict`).

### Synthèse multi-dépôts

Calculée par le serveur sur la dernière analyse de chaque dépôt listé : le navigateur ne
recompte rien.

| Champ | Type | Sens |
|---|---|---|
| `repositories`, `hidden`, `archived`, `forks`, `empty` | entiers | dépôts listés ; masqués par défaut (archivés, forks, vides) |
| `analyzed` | entier | ceux dont la dernière analyse a abouti |
| `running`, `not_scanned`, `skipped`, `to_update`, `up_to_date`, `inconclusive`, `no_dependencies` | entiers | les dépôts par `state` |
| `vulnerabilities`, `critical` | entiers | les failles de tous les dépôts (un même paquet dans deux dépôts compte deux fois), dont critiques |
| `vulnerable_repositories` | entier | les dépôts qui ont au moins une faille |
| `findings` | objet | les constats par type, additionnés, tous les types présents |
| `severities` | objet | les constats à mettre à jour par gravité, additionnés |

Les PR ouvertes par forceupdate s'y ajouteront à E18.

### Demande d'analyse groupée

| Champ | Type | Sens |
|---|---|---|
| `forge` | chaîne | la forge du compte connecté |
| `repositories` | liste de chaînes | les dépôts (`owner/nom`), parmi ceux de la liste (sinon `400`) ; les vides sont sautés |
| `dev`, `transitive`, `include_tests`, `cache` | booléens | les [options](#options) ; jamais hors ligne |

`404` sans compte connecté à cette forge, `409` pour une forge pas encore prête.

`POST /api/repositories/scans` prend `repository` (`owner/nom`, `https://github.com/owner/nom`,
`…/nom.git`, `git@github.com:owner/nom.git`, une page du dépôt) et les mêmes options : avec le
token du compte connecté à sa forge s'il y en a un, sans token sinon (GitHub : 60 requêtes par
heure, dépôts publics seulement). `400` nom illisible ou forge inconnue, `404` dépôt introuvable
(ou privé et invisible), `409` dépôt vide, forge pas prête ou limite d'API atteinte, `502` forge
injoignable.

### Analyse groupée

Une analyse par dépôt, dans la boucle des analyses, `concurrency` dépôts à la fois (4), avec le
même client HTTP et le même cache des registres ; les requêtes à un même hôte sont en plus
limitées à 8 à la fois. Chaque analyse se suit comme une autre (`GET /api/scans/{id}`, SSE).

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | |
| `forge`, `host` | chaînes | |
| `status` | chaîne | `running`, puis `done` (toutes finies, abouties ou non) ou `cancelled` |
| `started_at`, `finished_at` | dates | |
| `concurrency` | entier | |
| `scans` | liste de chaînes | les identifiants de ses analyses |
| `total`, `finished`, `failed` | entiers | |
| `skipped` | liste de chaînes | les dépôts demandés mais vides |
| `requests` | entier | les requêtes d'API envoyées à la forge par ce lot |
| `rate_limit` | objet ou `null` | les requêtes restantes, d'après la dernière réponse |

Annuler (`DELETE`) arrête les analyses pas finies ; celles qui le sont gardent leur rapport.
Les analyses gardées en mémoire sont les 20 plus récentes, **plus la dernière de chaque
dépôt**.
