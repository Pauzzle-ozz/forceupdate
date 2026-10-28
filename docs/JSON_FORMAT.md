# Format JSON des rapports

Version du schéma : **1**.

C'est ce qu'écrit `forceupdate scan --format json`, et ce que renverra l'API de
l'interface web (`GET /api/scans/{id}`, étape E12). Le code qui le produit est
`src/forceupdate/report/json.py`.

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
dépendances) ; les fins de vie (E27) arriveront de même, avec des constats `eol`.

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
| `overrides` | liste de [versions forcées](#version-forcée) | celles de son `package.json` |
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

`overrides` (npm), `resolutions` (Yarn), `pnpm.overrides` : une version imposée à un
paquet, quoi que demandent les paquets qui le tirent. Seules celles du `package.json`
à la racine d'un workspace comptent.

| Champ | Type | Sens |
|---|---|---|
| `ecosystem` | [écosystème](#écosystèmes) | `npm` |
| `name` | chaîne | le paquet forcé |
| `constraint` | chaîne | la version forcée telle qu'écrite (`^3.4.13`, `$dompurify`) ; `""` pour un chemin local ou une URL |
| `key` | chaîne | la clé telle qu'écrite : `dompurify`, `**/lodash` (Yarn), `foo@<2` ou `a>b` (pnpm) ; pour npm, les clés imbriquées séparées par `>` |
| `section` | chaîne | `overrides`, `resolutions` ou `pnpm.overrides` |
| `file` | chemin | le `package.json` |
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
majeures, ne reviennent pas en arrière et ne sont pas à faire à la main, celle qui
corrige le plus de failles, puis la plus récente. Une majeure n'est jamais cochée
d'office, même quand elle seule corrige une faille. En 0.x, ce qui sort de `^` est
une majeure.

### Option de mise à jour

| Champ | Type | Sens |
|---|---|---|
| `version` | chaîne | la version visée |
| `gap` | [écart](#écarts) ou `null` | depuis `current_version` ; `null` pour un retour à une version plus ancienne (remplacer une version retirée quand rien au-dessus ne convient) |
| `reasons` | liste de [raisons](#raisons) | pourquoi elle est proposée |
| `fixes` | liste de chaînes | les failles qu'elle corrige : le premier identifiant de chacune (une CVE s'il y en a) |
| `unfixed` | liste de chaînes | les failles du paquet qu'elle laisse |
| `edits` | liste de [réécritures](#réécriture) | les contraintes à réécrire. `[]` : la version est déjà dans la contrainte, le lockfile seul suffit |
| `lockfile` | chemin ou `null` | le lockfile à régénérer ; `null` sans lockfile |
| `manual` | chaîne ou `null` | pourquoi forceupdate ne sait pas l'appliquer seul (contrainte sans emplacement, style non géré) ; une telle option n'est jamais pré-cochée |
| `warnings` | liste de chaînes | à lire avant de cocher : `Majeure : peut demander d'adapter le code.`, `Revient à une version plus ancienne.`, `Version dépréciée : …` |

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
| `message` | chaîne | en français : `pas lu : il faudrait l'exécuter…`, `JSON invalide…`, `Failles non vérifiées pour 5 dépendances indirectes. OSV : …` |

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
    "to_update": 4
  }
}
```

`wanted_version` est `null` partout : `==2.32.0` n'accepte que la version
retirée, il faut changer la contrainte. Chaque constat donne sa propre cible
(2.33.0 et 2.32.4 pour les failles, 2.32.2 pour le retrait, 2.34.2 pour la
dernière) : choisir la version qui les satisfait toutes est le travail du
planificateur (E09).
