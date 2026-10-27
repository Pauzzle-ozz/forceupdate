# Session 9 — Étape E09 : Planificateur et sélection des mises à jour

Contexte : E01 à E08 sont faites, l'analyse locale Python + npm est complète en ligne de
commande (jalon « après E08 ») : `forceupdate scan` dit les failles (OSV, indirectes
comprises, avec la version qui corrige), les versions plus récentes, retirées ou dépréciées.
Le dépôt est sur GitHub (`Pauzzle-ozz/forceupdate`, public) avec deux commits. La phase C
commence : passer des constats aux mises à jour. 1240 tests verts, plus 4 réseau.

Lis CLAUDE.md, puis l'étape E09 de PLAN.md. Lis les « Notes » de E08 (version corrigée,
une faille par constat, « faille possible », limites), de E07 (`checks/`, `Current`,
« permise » à la manière de `npm-pick-manifest`, `nearest`) et de E05 (`gap` en 0.x,
`candidates`, `max_satisfying`). Dans docs/BRIEF.md : « Les trois niveaux de mise à jour »,
les décisions n°11 et 12, et les pièges « Garder le style de contrainte » et « Réécrire un
manifeste sans le casser ».

À faire :
- `update/planner.py` : pour chaque dépendance, les mises à jour possibles (dernier correctif, dernière mineure, dernière majeure, version corrigée d'une faille).
- Sélection par défaut (décision n°12) : correctifs, mineures et corrections de failles cochés ; majeures proposées, pas cochées, avec l'avertissement « peut demander d'adapter le code » (en 0.x, `gap` classe déjà en majeure ce qui sort de `^`) ; une faille corrigée seulement par une majeure : proposée, pas cochée, avec les deux mentions.
- La sélection est une donnée (l'interface la modifiera case par case). En ligne de commande : `--level patch|minor|major` (par défaut `minor`), `--security-only`, `--include`, `--exclude` (motifs de noms), `--ecosystem`.
- Garder le style de contrainte (`^`, `~`, `>=`, `==`, `~=`, version exacte) : calculer le nouveau texte de la contrainte.
- Deux natures d'opérations : la cible sort de la contrainte → manifeste (et lockfile) ; elle est déjà dedans → lockfile seul. Transitives en faille : lockfile seul (`uv lock --upgrade-package x`, `npm update x`).
- Dernier correctif et dernière mineure demandent toutes les versions publiées : redemander les `PackageInfo` aux registres de la session (le cache les a), ou les garder dans l'analyse.
- Failles : plusieurs par paquet, chacune avec sa version corrigée ; choisir la plus petite version publiée qui les corrige toutes (au moins la plus haute des versions corrigées), ni retirée ni dépréciée (lodash 4.17.15 → 4.18.0 corrige tout mais est dépréciée « Bad release » → 4.18.1). Sans version corrigée (paquet malveillant) : rien à proposer, le dire. « Faille possible » (borne basse sans lockfile) : relever la borne basse.
- Versions forcées : lire `overrides` (npm), `resolutions` (Yarn), `pnpm.overrides`, avec leur emplacement dans `package.json` (Argos force `dompurify` par `overrides`).
- PyPI : la 0.1.0 n'est pas publiée (l'utilisateur a préféré attendre à la session 8). Revérifier que le nom `forceupdate` est libre, et lui reproposer la publication ; s'il attend encore, la reporter à E30.

Attention :
- La « permise » npm suit `npm-pick-manifest` (E07) : préférer les versions non dépréciées. Une version actuelle « approximative » se met à jour en relevant la borne basse.
- Les constats ne portent que `target_version` et `wanted_version`. Une faille n'a pas de « permise » : sa cible est la plus petite version corrigée (`Finding.target_version`), son écart `gap` dit si elle est majeure.
- Le planificateur n'écrit rien : la réécriture est E10, les lockfiles E11. Pas de logique métier dans `cli.py`.
- Sous Windows : `PYTHONIOENCODING=utf-8` pour lire les accents ; un script Python passé par heredoc, ou un heredoc plein d'apostrophes et de backticks, peut casser : écrire le script dans un fichier. `UV_LINK_MODE=copy` fait taire « Failed to hardlink files ».
- Les tests ne touchent ni le réseau ni le cache de l'utilisateur (garde-fous de `conftest.py`) ; la fixture `recorded` simule PyPI, npm et OSV.

Fini quand : des tableaux de cas couvrent chaque style de contrainte et la sélection par
défaut. Vérifier avec : `uv run pytest`, `uv run pytest --run-network`, `uv run ruff check`,
`uv run ruff format --check`, sous 3.11 et 3.14 (`uv run --isolated --python 3.11 --group dev
pytest`), et le plan calculé pour `tests/projects/vulnerable` et pour Argos
(`$HOME/Desktop/the good guy`), relu à la main.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
