# reference/ — code repris d'Argos

Copie figée du commit `52c714b7` d'Argos (dépôt `~/Desktop/the good guy`), faite
le 2026-10-27. Le code est copié **à l'identique** : seuls les bandeaux
« Origine » et les commentaires `ARGOS (n)` ont été ajoutés.

Vérifié à la copie : les **31 tests des parseurs passent** sur ce fichier tel quel.
Les **5 tests OSV passent** aussi une fois la session HTTP Argos remplacée
(point 2 ci-dessous). Ils sont en `skip` en attendant.

```bash
cd reference && python -m pytest argos_sca_parsers_tests.py
```

## Fichiers

| Fichier | Contenu |
|---|---|
| `argos_sca_parsers.py` | Trouver et lire les fichiers de dépendances, interroger OSV (1 400 lignes) |
| `argos_sca_parsers_tests.py` | Les tests correspondants : de vrais exemples de chaque format (500 lignes) |

## Ce qu'il y a dedans

Les lignes renvoient à `sechunter/modules/sast/_common.py` au commit `52c714b7`, sauf mention contraire.

| Morceau | À quoi ça sert | Origine |
|---|---|---|
| `DEFAULT_MAX_FILES`, `DEFAULT_MAX_FILE_SIZE`, `_IGNORE_DIRS_COMMON` | Plafonds de collecte, dossiers sautés (`node_modules`, `.venv`, `dist`…) | L43-83 |
| `is_test_path` | Reconnaît un chemin de tests / fixtures / exemples | L90-159 |
| `safe_read_text` | Lecture UTF-8 tolérante, plafonnée à 2 Mo | L477-487 |
| `DEPENDENCY_MANIFESTS`, `_ECOSYSTEM_BY_FILENAME`, `ecosystem_for_manifest` | Quels noms de fichiers sont des manifestes, et de quel écosystème | L6221-6290, L6378 |
| `SCAComponent` | La structure commune : écosystème, nom, version, `pinned`, scope, fichier, ligne | L6292 |
| `OSVVulnerability` | Une faille OSV normalisée (CVE, CVSS, versions corrigées) | L6315 |
| `discover_dependency_manifests` | Parcourt un dossier et liste les manifestes | L6337 |
| `parse_*` (19 parseurs) + `parse_manifest` | Lit chaque format → `list[SCAComponent]` ; `parse_manifest` choisit le parseur par nom de fichier | L6389-7130 |
| `query_osv_batch`, `_parse_osv_vuln` | Interroge OSV.dev en lot, normalise la réponse | L7135-7312 |
| `_cvss_base_score_from_vector`, `_cvss_to_severity` | Score CVSS 3.1 calculé sans dépendance | L7315-7377 |
| `MANIFEST_LOCKFILES` | Quel lockfile va avec quel manifeste | `supply_chain.py` L1199-1209 |

## Formats couverts

| Écosystème | Lus | Repérés mais **pas lus** (aucun parseur) |
|---|---|---|
| Python (PyPI) | `requirements*.txt`, `pyproject.toml`, `poetry.lock`, `Pipfile.lock` | `Pipfile`, `setup.py`, `setup.cfg` |
| JS (npm) | `package.json`, `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml` | — |
| Ruby (RubyGems) | `Gemfile.lock` | `Gemfile` |
| Go | `go.mod`, `go.sum` | — |
| Rust (crates.io) | `Cargo.toml`, `Cargo.lock` | — |
| PHP (Packagist) | `composer.json`, `composer.lock` | — |
| Java (Maven) | `pom.xml` | — |
| .NET (NuGet) | `packages.config` | — |

Pas du tout repérés : `uv.lock`, `pdm.lock`, `build.gradle(.kts)`, `*.csproj`,
`packages.lock.json`, `Directory.Packages.props`. Pas d'écosystème Dart, Swift,
Elixir, Haskell, C/C++ (conan, vcpkg)…

## Les 3 dépendances à Argos à couper

Cherche `ARGOS (` dans `argos_sca_parsers.py`.

1. **`Severity`** : l'enum de sévérité d'Argos (CRITICAL / HIGH / MEDIUM / LOW / INFO).
   Il n'est pas importé, donc `_cvss_to_severity` et `_parse_osv_vuln` lèvent
   `NameError` tant qu'il n'est pas redéfini. Les parseurs, eux, n'en ont pas besoin.
2. **Session HTTP** : `query_osv_batch` importe la session tracée d'Argos. Hors
   Argos, la remplacer par `aiohttp.ClientSession(timeout=client_timeout)`.
3. **Bug OSV connu, jamais corrigé dans Argos** : `/v1/querybatch` ne renvoie que
   `{id, modified}` pour chaque faille.
   - Conséquence : `_parse_osv_vuln` reçoit des entrées vides. Toutes les failles
     sortent à 5.5 (MEDIUM), sans CVE et **sans version corrigée**, alors que c'est
     justement la version corrigée qui dit « mets à jour vers X ».
   - Correctif : demander le détail de chaque id via `GET /v1/vulns/{id}`, ou
     interroger chaque paquet via `POST /v1/query`, qui renvoie les failles complètes.

## Limites repérées en relisant le code

Aucune n'est couverte par un test. À vérifier avant de reprendre le parseur concerné.

- **`yarn.lock`** : seul le format v1 est lu. Le format Yarn 2+ (`version: 1.2.3`, sans
  guillemets) ne produit aucun composant.
- **`pnpm-lock.yaml`** : la regex attend `/nom/version:` (lockfile v5). Les formats
  v6 (`/nom@version:`) et v9 (`nom@version:`) ne sont pas reconnus.
- **`poetry.lock`** : le scope s'appuie sur `category`, que les versions récentes de
  Poetry n'écrivent plus. Tout sort alors en `runtime`.
- **`composer.lock`** : tout est `pinned=True`, y compris les branches du type
  `dev-master`.
- **`package.json`** : `_strip_npm_version` exige trois nombres. `^1.2` donne une
  version vide, et les dépendances git, `file:` ou `workspace:` aussi.
- **`Cargo.toml`** : une dépendance `workspace = true` donne une version vide.
- **`requirements.txt`** : les `-r autre.txt` ne sont pas suivis.
- **`go.mod`** : `// indirect` n'est pas distingué et les `replace` sont ignorés.
  **`go.sum`** contient aussi des versions qui ne sont plus utilisées, donc ce n'est
  pas la liste de ce qui est réellement compilé.
- **`pom.xml`** :
  - les `${propriété}` ne sont pas résolues (la dépendance est marquée non épinglée) ;
  - l'ordre `groupId` puis `artifactId` est imposé ;
  - pas de lecture du parent ni du BOM.
- **Lien manifeste ↔ lockfile** : `SCAComponent` ne sait pas si une dépendance est
  directe ou transitive. Un lockfile npm sort des centaines de composants à plat.

## Ce qui n'a pas été repris, et où le trouver

| Quoi | Pourquoi pas repris | Où dans Argos |
|---|---|---|
| `build_sca_finding*` | Fabrique le `Finding` d'Argos : format de sortie propre à Argos | `_common.py` L7729 |
| Atteignabilité SCA | Dit si la fonction vulnérable est vraiment appelée. Utile plus tard, mais lourd (graphe d'appels multi-langage) | `sechunter/modules/sast/v2/sca_reachability/` |
| Failles des images Docker | Wrapper Trivy : à regarder si l'outil doit couvrir les `FROM` des Dockerfiles | `sechunter/modules/sast/v2/container_cve/` |
| Typosquatting, dependency confusion, scripts d'install | Sécurité, hors sujet « mises à jour » | `sechunter/modules/sast/supply_chain.py` |
| Licences, SBOM | Hors sujet | `license_audit.py`, `sbom.py`, `_common.py` L7390+ |
