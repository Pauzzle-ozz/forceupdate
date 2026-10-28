# Session 10 — Étape E10 : Réécriture des manifestes, commande `update`

Contexte : E01 à E09 sont faites. L'analyse locale Python + npm est complète, et le
planificateur (E09) sait, pour chaque paquet, vers quelles versions monter, ce qu'il faut
réécrire (contraintes dans leur style, versions forcées) et ce qui est pré-coché :
`forceupdate update` montre ce plan, sans rien écrire. La version 0.1.0 est publiée sur PyPI
(voir les notes de E09). 1430 tests verts, plus 4 réseau.

Lis CLAUDE.md, puis l'étape E10 de PLAN.md. Lis les « Notes » de E09 (`Update`,
`UpdateOption`, `Edit`, `Selection`, `planner.chosen`, ce qu'on touche, catalogues pnpm), de
E03 et E04 (emplacements des contraintes : `Location`, `toml_spans`, `json_spans`, alias
`npm:`, contrainte absente ou sans emplacement) et de E05 (catalogues pnpm,
`resolved_constraint`). Dans docs/BRIEF.md : la décision n°11 et les pièges « Réécrire un
manifeste sans le casser » et « Garder le style de contrainte ».

À faire :
- `update/writers/` : remplacer seulement le texte de la contrainte, à l'emplacement donné par chaque `Edit` (fichier, emplacement, `old`, `new`). Si le fichier n'a pas `old` à cet endroit, ne pas y toucher et le signaler. Plusieurs réécritures dans un même fichier : de la fin vers le début. Une option `manual` n'est pas appliquée : le dire.
- Formats : `requirements*.txt`, `pyproject.toml` (PEP 621, Poetry, `dependency-groups`), `Pipfile`, `setup.cfg`, `package.json` (l'emplacement d'un alias `npm:autre@^1.0` ne couvre que `^1.0`), et les versions forcées (`EditKind.OVERRIDE`).
- Catalogues pnpm (`EditKind.CATALOG`, sans emplacement) : réécrire la plage dans `pnpm-workspace.yaml` (positions YAML : `yaml.compose` donne ligne et colonne de chaque nœud), sinon dire qu'elle n'est pas réécrite. Lire aussi les `overrides` de `pnpm-workspace.yaml` (pnpm 10+), avec leur position.
- Auto-vérification : relire le fichier réécrit avec son parseur ; il doit redonner la nouvelle contrainte (la déclaration se retrouve dans `Update.dependencies` par fichier et emplacement).
- Diff unifié de chaque fichier, calculé avant d'écrire (l'interface l'affichera en E15).
- Commande `update <chemin>` (elle montre déjà le plan) : afficher le diff, demander confirmation (`--yes` pour ne pas demander, `--dry-run` pour s'arrêter au diff). Garde-fou : refuser si les fichiers visés ont des changements git non commités, sauf `--force`.
- Vérifier les versions proposées auprès d'OSV (reporté de E09) : une option qui a elle-même une faille connue n'est pas pré-cochée, et un avertissement le dit ; une seule requête `querybatch`.

Attention :
- La réécriture ne touche que les manifestes : les lockfiles sont E11. Après E10, `update` dit quel lockfile reste à régénérer (`UpdateOption.lockfile`) sans le faire.
- Une contrainte absente a un emplacement vide (`column == end_column`) : c'est là qu'on insère. `location=None` : ne pas réécrire (le planificateur en a déjà fait une option `manual`).
- Les fins de ligne : un fichier en CRLF doit le rester (les parseurs comptent les lignes sur `\n`, et `Location.extract` aussi ; un `\r` reste en fin de ligne). Un BOM en tête de `package.json` compte pour les colonnes de la ligne 1.
- Pas de logique métier dans `cli.py` : l'écriture et le diff sont dans `update/`.
- Sous Windows : `PYTHONIOENCODING=utf-8` pour lire les accents ; un script passé par heredoc, ou un heredoc plein d'apostrophes et de backticks, peut casser (et un `\n` dans une chaîne Python d'un script écrit par heredoc devient un vrai saut de ligne) : écrire le script dans un fichier avec l'outil d'écriture. `UV_LINK_MODE=copy` fait taire « Failed to hardlink files ».
- Les tests ne touchent ni le réseau ni le cache de l'utilisateur ; la fixture `recorded` simule PyPI (flask, requests, aioredis, jinja2, werkzeug), npm et OSV. Écrire sur des copies des mini-projets (`tmp_path`), jamais dans `tests/projects/`.

Fini quand : sur les mini-projets, le diff ne touche que les contraintes ; commentaires,
ordre et mise en forme restent intacts. Vérifier avec : `uv run pytest`,
`uv run pytest --run-network`, `uv run ruff check`, `uv run ruff format --check`, sous 3.11
et 3.14 (`uv run --isolated --python 3.11 --group dev pytest`), et `forceupdate update
--dry-run` sur une copie de `tests/projects/vulnerable`, de chaque mini-projet et d'Argos
(`$HOME/Desktop/the good guy`, sur une copie), relu à la main.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
