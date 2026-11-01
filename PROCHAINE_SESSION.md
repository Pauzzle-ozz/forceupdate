# Session 26 — Étape E26 : .NET (NuGet)

Contexte : E01 à E25 sont faites. Java marche de bout en bout, sans lockfile (aucun en V1 pour
Maven ni Gradle) : `pom.xml` lu par expat (`parsers/xml_spans.py`, positions du texte) avec ses
propriétés, ses parents du dépôt, `dependencyManagement`, BOM et plugins ; le catalogue
`libs.versions.toml` et les scripts Gradle lus en jetons, jamais exécutés ; `ComparableVersion` et
`VersionRange` réécrits (aucun écart sur 9 102 versions et 4 980 600 comparaisons avec
`maven-artifact` 3.9.16) ; Maven Central, Google Maven et le portail des plugins Gradle ; une version
située là où elle est écrite, partagée par plusieurs dépendances (dit dans le plan) ; les variantes
(`-jre` / `-android`) jamais mélangées. 3801 tests Python verts (plus 18 réseau), 141 Vitest, 49
Playwright. E25 n'est pas commitée : à proposer d'abord. .NET est le dernier écosystème de la phase F.

Lis CLAUDE.md, puis dans PLAN.md l'introduction de la phase F (et ses paragraphes « Depuis E21 » à
« Depuis E25 » : `written`, `unlisted`, `moved`, `compatible`, `not_found_statuses`, `_complete`,
`Dependency.excluded`, `is_excluded`, `_versions_path`, `_WRITTEN`, `run_pinned(…, appended=)`,
`WORKSPACE_ROOTS`, les versions partagées et `_shared_warnings`), les notes de E25 et de E24 (ce qui a
été vérifié en vrai, et comment : un oracle lancé par l'outil lui-même, puis les choix de l'outil
reproduits ; des mutations pour voir que la comparaison mord) et l'étape E26 ;
`reference/README.md` (.NET : `parse_packages_config` ; `*.csproj`, `packages.lock.json`,
`Directory.Packages.props` pas repérés) et ses tests dans `reference/argos_sca_parsers_tests.py` ;
`docs/BRIEF.md` (décisions n°2, 3, 4, 11 et 12 ; « Versions et fichiers » ; « Régénérer un lockfile
peut exécuter du code du projet » ; « Sources de données » : NuGet) ; puis le code de E25 qui sert de
modèle : `parsers/xml_spans.py`, `parsers/maven.py`, `parsers/java.py`, `versions/maven.py` (les
plages : `Restriction`), `registries/maven.py`, `update/writers/java.py`,
`tests/test_java_projects.py`, `tests/test_versions_maven.py` ; et pour un lockfile, `update/
lockfiles.py` (un `LockKind`, son pilote, `_RUNS_CODE`). Pas d'interface à toucher en principe : si
un écran change, charger d'abord le skill `ui-ux-pro-max`.

À faire :
- `packages.config` : reprendre `parse_packages_config` et ses tests, le relire avec
  `parsers/xml_spans.py` (une version exacte en attribut `version="…"`, `targetFramework`,
  `developmentDependency` → `dev`, `allowedVersions` : une plage) ; `xml_spans` ne situe que le texte
  d'un élément : y ajouter la position de la valeur d'un attribut.
- `*.csproj`, `*.fsproj`, `*.vbproj` : `<PackageReference Include="x" Version="1.2.3" />`, la version
  en attribut ou en élément (`<Version>`), `VersionOverride`, `PrivateAssets="all"` (outil de build :
  `build` ?), `$(Propriété)` résolues depuis `<PropertyGroup>` du projet et de
  `Directory.Build.props` (celui du dossier ou d'un parent), conditions (`Condition=` : une
  remarque) ; `<Sdk>` et `<TargetFramework>` gardés pour E27.
- `Directory.Packages.props` (gestion centrale, `ManagePackageVersionsCentrally`) : ses
  `<PackageVersion Include="x" Version="…" />` donnent les versions des `.csproj` en dessous (E02 en
  fait un projet à part : le rattacher, comme un parent Maven) ; une version écrite une fois pour
  plusieurs projets : la même mécanique que les propriétés Maven (l'emplacement de la version,
  `Dependency.file` = le `.props`, `_shared_warnings`) ; `GlobalPackageReference`.
- `packages.lock.json` (`RestorePackagesWithLockFile`) : versions installées (`resolved`), directes
  et transitives par framework cible, `type` (`Direct`, `Transitive`, `CentralTransitive`, `Project`).
- Versions NuGet (`NuGetVersion`) : jusqu'à 4 nombres, `1.0` = `1.0.0.0`, pré-versions SemVer 2.0 (sans
  tenir compte de la casse), métadonnées `+…` ignorées ; les plages (`VersionRange`) : **une version
  nue est un minimum** (`>= 1.2.3`, et NuGet prend la plus basse qui convient), `[1.2.3]` exacte,
  `(1.0,2.0)`, `[1.0,)`, flottantes `1.*`, `1.0.*-*` ; `satisfies`, `lower_bound`, `exact`, les styles de
  `update/constraints.py` (un tableau de cas). **Oracle** : `NuGet.Versioning.dll` (le paquet
  `NuGet.Versioning` de nuget.org, un `.nupkg` est un zip, `lib/netstandard2.0/`), chargé par
  PowerShell 5.1 (`[Reflection.Assembly]::LoadFrom`) : `NuGetVersion.Parse`, `CompareTo`,
  `VersionRange.Parse`, `Satisfies`, `FindBestMatch` ; pas besoin du SDK .NET pour ça.
- Registre : le « flat container » (`https://api.nuget.org/v3-flatcontainer/{id en minuscules}/
  index.json` : les versions), l'API « registration » (`https://api.nuget.org/v3/registration5-gz-
  semver2/{id}/index.json`, gzip : `listed`, `published`, `deprecation` avec ses raisons et le
  paquet de remplacement, `vulnerabilities`) ; une version non listée ≈ retirée ; un paquet inconnu ;
  le cache ; réponses enregistrées (`record.py`, `PACKAGES`). Vérifier les formats en vrai.
- Failles : OSV `NuGet`, les noms sans tenir compte de la casse (`advisories/osv.py`, `_same_name`).
- Réécriture des `.csproj`, `.props` et `packages.config` (l'attribut `Version`, la propriété citée) ;
  lockfile : `dotnet restore --force-evaluate` si `packages.lock.json` existe (vérifier en vrai :
  garde-t-il une version épinglée ? les autres ? ce qu'il exécute : MSBuild évalue le projet, ses
  `Directory.Build.props/targets` et peut lancer des cibles du projet → `_RUNS_CODE`, le dire).
- Un mini-projet `tests/projects/nuget` (une solution : deux `.csproj`, un `Directory.Packages.props`,
  un `packages.lock.json` produit par le vrai `dotnet restore`, une faille connue : par exemple
  `Newtonsoft.Json` 12.0.1 ou `System.Text.Encodings.Web` 4.5.0) et un `packages.config` ; vérifier
  l'analyse et la mise à jour dans l'interface et en ligne de commande.

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E25 ; puis s'il faut télécharger
  `NuGet.Versioning` (le `.nupkg` de nuget.org, vérifié par son empreinte SHA-512 publiée par
  l'API) dans `~/sdk` pour l'oracle ; et s'il faut installer le **SDK .NET** : la machine n'a que des
  runtimes (`dotnet --list-runtimes` : 6.0, 8.0, 9.0 ; `dotnet --version` échoue, aucun SDK). Sans
  SDK, ni `packages.lock.json` vrai pour le mini-projet, ni régénération testée en vrai (seulement
  simulée, et le plan le dira). Le SDK s'installerait comme Go (l'archive officielle de
  dotnet.microsoft.com, vérifiée, dans `~/sdk`, hors du `PATH`, avec `DOTNET_ROOT` et
  `DOTNET_CLI_HOME` pour un essai à la main).
- **Plus d'écosystème « pas encore géré »** : les tests qui prenaient NuGet
  (`test_checks_vulns.py`, `test_cli.py`, `test_parsers_python.py`, `test_registries.py`,
  `test_versions.py`) n'ont plus d'écosystème à prendre : les garder en retirant un écosystème des
  tables le temps du test (monkeypatch), ou retirer ce chemin devenu mort (voir E26 dans PLAN.md).
- NuGet résout vers **la plus basse** version qui convient (pas la plus haute comme les autres) : la
  version « permise » (`wanted`) et la commande à la main en tiennent compte.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache de
  l'utilisateur ; `reference/` n'est jamais importé par `src/` ; on ne modifie pas `reference/`
  (copier, adapter, reprendre les tests). Pour OSV, n'ajouter à `queries.json` que les versions du
  nouveau mini-projet (fait à E23, E24 et E25 par un script : la requête de `record.py osv` pour ce
  projet seul), pour ne rien changer aux autres.
- Ruby (`~/sdk/ruby-4.0.9/bin`), `go` (`~/sdk/go1.27.3/bin`), cargo (`~/.cargo/bin`), PHP et Composer
  (`~/sdk/php-8.5.12`, `~/sdk/composer-2.11.0`) sont hors du `PATH` des outils : la ligne de
  CLAUDE.md pour les tests `network`.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture (une barre oblique inverse dans un
  `python -c` ou un heredoc a encore cassé un script à E25) ; jamais `node -e "…"` avec des accents
  graves ; un argument qui commence par `/` sous Git Bash : `MSYS_NO_PATHCONV=1`. Pour piloter la
  vraie interface : un script Playwright en `.cjs` dans le scratchpad, qui `require` le Playwright de
  `frontend/node_modules` (fait à E21-E25 : `ui --no-browser` en arrière-plan, l'adresse lue dans sa
  sortie, le serveur arrêté ensuite par son port) ; attendre le titre exact du rapport (`exact:
  true`).

Fini quand : sur un mini-projet .NET (`.csproj`, `Directory.Packages.props`, `packages.lock.json`,
et un `packages.config`), l'analyse et la mise à jour donnent un résultat juste, dans l'interface et
en ligne de commande (la régénération de `packages.lock.json` par le vrai `dotnet` si le SDK est
installé, simulée et notée sinon). Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` ; à la main, `uv run forceupdate scan` et `update` sur une copie du mini-projet
dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
