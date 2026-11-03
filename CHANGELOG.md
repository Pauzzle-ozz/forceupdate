# Changements

Les versions de forceupdate publiées sur [PyPI](https://pypi.org/project/forceupdate/). Les
numéros suivent [SemVer](https://semver.org/lang/fr/) : à partir de la 1.0.0, une majeure peut
casser la ligne de commande, le format JSON du rapport (`schema_version`) ou la configuration.

## Non publié

### Ajouté

- « Parcourir… » (écran de choix) : la fenêtre de choix d'un dossier ou d'un fichier de
  l'ordinateur (l'Explorateur sous Windows), ouverte par le serveur local.
- Télécharger le rapport depuis l'interface : en Markdown, en JSON, et les dépendances à mettre
  à jour en CSV pour un tableur ; `forceupdate scan --format csv`.

### Corrigé

- Un `package-lock.json` que `npm ci` refuse n'est plus envoyé tel quel : tout lockfile npm est
  relu par `npm ci --dry-run`, et refait par une vraie installation (sans les scripts) quand npm
  a écrit un lockfile incomplet (npm 11.6.2 et les dépendances embarquées de
  `@tailwindcss/oxide-wasm32-wasi`).

## 1.0.0rc1 — 2026-11-03

La première version complète, à essayer avant la 1.0.0 (`uv tool install forceupdate==1.0.0rc1`).

### Interface web

- `forceupdate ui` : un serveur local sur `127.0.0.1`, réservé à qui a le jeton de l'adresse
  affichée, et l'interface dans le navigateur, en français, en clair et en sombre. Neuf écrans :
  accueil, choix d'un dossier ou d'un fichier (ou un fichier déposé sur la page), analyse en
  cours, rapport, mise à jour (choisir, vérifier le diff, appliquer, résultat), comptes, mes
  dépôts, PR / MR, réglages.
- L'interface est livrée dans le paquet : node n'est pas nécessaire pour s'en servir.

### Analyse

- Huit écosystèmes : Python (pip, uv, Poetry, PDM, Pipenv, pip-tools), JavaScript (npm, Yarn 1
  et 2+, pnpm), Rust (Cargo), Go, PHP (Composer), Ruby (Bundler), Java (Maven, Gradle) et .NET
  (NuGet). Manifestes et lockfiles lus sans rien exécuter, workspaces compris.
- Quatre types de constats, du plus grave au moins grave : faille connue (OSV, et les avis de
  Packagist pour PHP), fin de vie d'un runtime ou d'un framework (endoflife.date), version
  retirée ou dépréciée, version plus récente (correctif, mineure, majeure).
- Une erreur réseau donne « non concluant », jamais un faux constat ; `--offline` n'utilise que
  le cache.
- Une version que le runtime du projet ne fait pas tourner (`engines.node`, `requires-python`,
  `require.php`, `rust-version`…) n'est jamais proposée, et le rapport dit laquelle et pourquoi.
- Un fichier de code seul (`app.py`, `index.ts`, `main.go`, un carnet…) : le projet trouvé en
  remontant les dossiers, son bloc PEP 723, ou ses imports.
- Les registres privés et les miroirs déclarés dans la configuration des outils (`.npmrc`,
  `uv.toml`, `go env`, `auth.json`, `settings.xml`, `nuget.config`, Bundler, Cargo), avec les
  identifiants de la personne, jamais envoyés ailleurs qu'à leur hôte.
- La configuration d'un projet (`forceupdate.toml` ou `[tool.forceupdate]`) et les réglages de
  la personne : paquets et versions ignorés, dossiers exclus, sélection par défaut.

### Mise à jour

- Les contraintes réécrites dans leur style (`^4.17.0` devient `^4.21.2`), sans toucher au reste
  du fichier ; correctifs et mineures cochés d'office, majeures seulement si on le règle.
- Les lockfiles régénérés par leur outil (npm, pnpm, Yarn, uv, Poetry, PDM, pipenv, pip-compile,
  cargo, go, Composer, Bundler, dotnet), sans les scripts du projet, à la version choisie quand
  l'outil le permet ; un outil absent : la commande à lancer ; un échec : les fichiers remis
  comme avant.
- Le garde-fou git : rien n'est écrit dans un fichier qui a des changements pas commités, sauf
  `--force`.

### Forges

- Connexion à GitHub, GitLab (gitlab.com ou une instance) et Bitbucket Cloud, par OAuth ou un
  token ; le token reste dans le trousseau du système.
- Tous les dépôts des comptes analysés sans les cloner (seuls les fichiers de dépendances sont
  téléchargés), avec une synthèse.
- Une PR (une MR sur GitLab) par dépôt, sur la branche `forceupdate/dependencies` ; relancé,
  forceupdate met à jour la même PR, et ne pousse jamais sur la branche par défaut.

### Ligne de commande

- `forceupdate scan` : rapport dans le terminal, en JSON (`schema_version: 1`) ou en Markdown,
  `--fail-on` pour la CI.
- `forceupdate update` : le plan, le diff, puis la réécriture et les lockfiles ; `--dry-run`,
  `--yes`, `--level`, `--security-only`, `--include`, `--exclude`, `--ecosystem`.

## 0.1.0 — 2026-10-28

Première publication, pour réserver le nom : `forceupdate scan` pour Python et npm (versions plus
récentes, retirées, dépréciées, failles d'OSV), et le plan des mises à jour de
`forceupdate update`, sans écriture.
