# Session 25 — Étape E25 : Java (Maven, Gradle)

Contexte : E01 à E24 sont faites. Ruby marche de bout en bout comme Python, npm, Rust, Go et PHP :
`Gemfile` (et `gems.rb`) lu par motifs sans jamais être exécuté (un lexer de Ruby), `.gemspec`,
`Gemfile.lock` (toutes les sections, versions à plateforme), une gem `path:` résolue dans le lockfile
du `Gemfile` qui la cite, `Gem::Version` et `Gem::Requirement` réécrits (aucun écart sur 6 013
versions et 221 contraintes ; 25 choix de `bundle lock` reproduits), l'index compact de RubyGems,
OSV `RubyGems`, `bundle lock` par le vrai Bundler (installé à E24, dans `~/sdk`), chaque version
épinglée le temps d'un passage. 3133 tests Python verts (plus 17 réseau), 141 Vitest, 49 Playwright.
E24 n'est pas commitée : à proposer d'abord. Java est le cinquième écosystème de la phase F.

Lis CLAUDE.md, puis dans PLAN.md l'introduction de la phase F (et ses paragraphes « Depuis E21 » à
« Depuis E24 » : `written`, `unlisted`, `moved`, `not_found_statuses`, `_complete`,
`Dependency.excluded`, `is_excluded`, `_versions_path`, `_WRITTEN`, `run_pinned(…, appended=)`,
`WORKSPACE_ROOTS`), les notes de E24 et de E23 (ce qui a été vérifié en vrai, et comment : un oracle
lancé par l'outil lui-même, puis les choix de l'outil reproduits ; des mutations pour voir que la
comparaison mord) et l'étape E25 ; `reference/README.md` (Java : `parse_pom_xml` ; `build.gradle`,
`build.gradle.kts`, `gradle/libs.versions.toml` repérés mais pas lus) et ses tests dans
`reference/argos_sca_parsers_tests.py` ; `docs/BRIEF.md` (décisions n°2, 3, 4, 11 et 12 ; « Versions
et fichiers », dont « Comparer des versions » : l'ordre Maven, et « Régénérer un lockfile peut
exécuter du code du projet » : `build.gradle` ; « Sources de données » : Maven Central) ; puis le code
de E24 et de E23 qui sert de modèle : `parsers/ruby.py` et `parsers/php.py`, `versions/rubygems.py`,
`registries/rubygems.py`, `update/writers/ruby.py`, `tests/test_ruby_projects.py` et
`tests/test_versions_rubygems.py`. Pas d'interface à toucher en principe : si un écran change,
charger d'abord le skill `ui-ux-pro-max`.

À faire :
- `pom.xml` : reprendre `parse_pom_xml` et ses tests, puis le réécrire avec `xml.etree` (bibliothèque
  standard) au lieu de motifs, avec l'emplacement exact de chaque version (le texte de la balise, ou
  la propriété qu'elle cite) : ordre des balises libre ; `${propriété}` résolues depuis
  `<properties>` (et le `pom.xml` parent s'il est dans le dépôt : `<parent><relativePath>`) ;
  `dependencyManagement`, plugins (`<build><plugins>`) ; `<scope>` (`test`, `provided`…) ; version
  héritée d'un parent ou d'un BOM distant (`<scope>import</scope>`) : « gérée par le parent », non
  vérifiable ; modules (`<modules>`) ; un nom Maven est `groupe:artefact`.
- Gradle : le catalogue `gradle/libs.versions.toml` (TOML : `[versions]`, `[libraries]` avec
  `version.ref`, `[plugins]`) ; `build.gradle` et `build.gradle.kts`, formes littérales courantes
  (`implementation("g:a:v")`, `implementation 'g:a:v'`, `libs.x` vers le catalogue) ; une variable
  non résolue : une remarque, pas une erreur ; ne jamais exécuter Gradle pour les lire.
- Versions Maven : l'ordre de `ComparableVersion` (qualificatifs `alpha` < `beta` < `milestone` <
  `rc` < `snapshot` < `""` < `sp`, `1.0` = `1.0.0`, `-SNAPSHOT`), et les plages (`[1.0,2.0)`,
  `(,1.0]`, une version nue est une « recommandation » : Maven prend celle-là) ; `satisfies`,
  `lower_bound`, `exact`, et les styles de `update/constraints.py` (un tableau de cas). Vérifier contre
  le vrai `ComparableVersion` : Java 8 est sur la machine (`java -version` : 1.8.0_481), et
  `maven-artifact` (un jar de Maven Central) a un `main` qui compare des versions
  (`java -jar maven-artifact-3.9.x.jar 1.0 1.0-alpha`) : un oracle comme à E23 et E24.
- Registre : `maven-metadata.xml` de Maven Central (`https://repo1.maven.org/maven2/{groupe en
  chemin}/{artefact}/maven-metadata.xml` : `<versions>`, `<latest>`, `<release>`, `<lastUpdated>`),
  et Google Maven (`https://dl.google.com/android/maven2/…`) pour `androidx.*` et `com.android.*` ;
  un artefact inconnu ; les dates (les métadonnées n'en ont pas par version : à voir) ; le cache ;
  réponses enregistrées (`record.py`, `PACKAGES`).
- Failles : OSV `Maven`, le nom `groupe:artefact` ; vérifier la version corrigée d'un avis (Log4Shell :
  `org.apache.logging.log4j:log4j-core` 2.14.1 → 2.15.0, puis 2.16.0 et 2.17.1).
- Réécriture là où la version est définie : la balise `<version>`, ou la propriété qu'elle cite (une
  propriété partagée par plusieurs dépendances : toutes montent ensemble, le dire) ; dans
  `libs.versions.toml` (`[versions]` ou la version en ligne) ; dans les littéraux Gradle. **Pas de
  lockfile** : les verrous Gradle (`gradle.lockfile`) sont hors V1 ; la mise à jour s'arrête à la
  réécriture (pas de `LockKind`), comme un `pyproject.toml` sans lockfile ; le dire dans le plan.
- Un mini-projet `tests/projects/maven` (et `gradle` ?) : un `pom.xml` aux formes ci-dessus et un
  `libs.versions.toml` ; ils n'ont pas de lockfile, rien à produire par un outil ; vérifier l'analyse
  et la mise à jour dans l'interface et en ligne de commande.

Attention :
- **Demander à l'utilisateur** : d'abord le commit de E24 ; puis s'il faut télécharger
  `maven-artifact` (un jar, vérifié par sa somme SHA-1 ou SHA-256 publiée sur Maven Central) dans
  `~/sdk` pour l'oracle des versions, et si Maven ou Gradle sont à installer (pas besoin pour lire ni
  pour réécrire : pas de lockfile en V1 ; utile seulement pour vérifier qu'un `pom.xml` réécrit se
  lit encore : `mvn help:effective-pom` lance des plugins). Sans eux, l'ordre se vérifie contre la
  spécification de `ComparableVersion` et ses tests publiés.
- **Ne jamais exécuter Gradle** pour lire un `build.gradle` (c'est du Groovy ou du Kotlin, comme le
  `Gemfile` est du Ruby) : lire par motifs, comme à E24 (`parsers/ruby_spans.py`).
- Les tests qui prenaient Maven pour « pas encore géré » (`test_checks_vulns.py`, `test_cli.py`,
  `test_lockfiles.py`, `test_parsers_python.py`, `test_registries.py`, `test_versions.py`) : les passer
  à NuGet (`packages.config`).
- Ruby (`~/sdk/ruby-4.0.9/bin`), `go` (`~/sdk/go1.27.3/bin`), cargo (`~/.cargo/bin`), PHP et Composer
  (`~/sdk/php-8.5.12`, `~/sdk/composer-2.11.0`) sont hors du `PATH` des outils : la ligne de
  CLAUDE.md pour les tests `network`.
- Les tests : jamais le réseau sans `network`, jamais un vrai outil (`FakeTools`), jamais le cache de
  l'utilisateur ; `reference/` n'est jamais importé par `src/` ; on ne modifie pas `reference/`
  (copier, adapter, reprendre les tests). Pour OSV, n'ajouter à `queries.json` que les versions du
  nouveau mini-projet (fait à E23 et E24 par un script : la requête de `record.py osv` pour ce projet
  seul), pour ne rien changer aux autres.
- Les dépôts de test des forges (`Pauzzle-ozz/forceupdate-demo` sur GitHub et gitlab.com,
  `pauzzle/forceupdate-demo` sur Bitbucket) sont gardés pour la recette E31 : ne pas y toucher.
- Scripts : les écrire dans le scratchpad avec l'outil d'écriture (un heredoc a encore cassé un `\\n`
  à E24) ; jamais `node -e "…"` avec des accents graves ; un argument qui commence par `/` sous Git
  Bash : `MSYS_NO_PATHCONV=1`. Pour piloter la vraie interface : un script Playwright en `.cjs` dans
  le scratchpad, qui `require` le Playwright de `frontend/node_modules` (fait à E21-E24 : `ui
  --no-browser` en arrière-plan, l'adresse lue dans sa sortie, le serveur arrêté ensuite par son
  port) ; attendre le titre exact du rapport (`exact: true`).

Fini quand : sur un mini-projet Maven (et un catalogue Gradle), l'analyse et la mise à jour donnent
un résultat juste, dans l'interface et en ligne de commande (pas de lockfile : la mise à jour réécrit
les fichiers, et le plan le dit). Vérifier avec : `uv run pytest`, `uv run ruff check`,
`uv run ruff format --check` ; dans `frontend/` : `npm test`, `npm run typecheck`, `npm run lint`,
`npm run test:e2e` ; à la main, `uv run forceupdate scan` et `update` sur une copie du mini-projet
dans le scratchpad, et `uv run forceupdate ui`.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
