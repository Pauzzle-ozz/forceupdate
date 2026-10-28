# Session 11 — Étape E11 : Régénération des lockfiles

Contexte : E01 à E10 sont faites. `forceupdate update` montre le plan, le diff des manifestes,
puis les réécrit après confirmation (`update/writers/` : seules les contraintes changent, CRLF et
BOM gardés, fichier relu par son parseur ; garde-fou git ; `--yes`, `--dry-run`, `--force`). Les
versions proposées sont vérifiées auprès d'OSV. Mais les lockfiles ne suivent pas : `update` dit
seulement lesquels régénérer. 1541 tests verts, plus 4 réseau.

Lis CLAUDE.md, puis l'étape E11 de PLAN.md. Lis les « Notes » de E10 (`prepare`, `write`,
`Changes.lockfiles`, `Changes.applied`, `FileChange.before`, `--hash`, `update/git.py`), de E09
(`UpdateOption.lockfile`, mise à jour par le lockfile seul, indirectes, versions forcées,
`Dependency.lockfile`, fichier `-c` de pip) et de E03-E04 (formats de lockfiles, workspaces, pip-tools).
Dans docs/BRIEF.md : la décision n°11 et les pièges « Un lockfile se régénère avec l'outil
natif », « Régénérer un lockfile peut exécuter du code du projet », « Windows : npm s'appelle
npm.cmd ».

À faire :
- `update/lockfiles.py`, une commande par outil, vérifiée sur la version installée de chacun : `package-lock.json` (`npm install --package-lock-only --ignore-scripts`), `yarn.lock` Yarn 1 et 2+, `pnpm-lock.yaml` (`pnpm install --lockfile-only --ignore-scripts`), `uv.lock` (`uv lock`), `poetry.lock`, `Pipfile.lock`, pip-tools (`pip-compile`). Trouvée par `shutil.which`, lancée sans shell, avec un délai maximal, sans scripts du projet.
- Mise à jour par le lockfile seul (`edits` vide) : viser le paquet (`uv lock --upgrade-package x==V`, `poetry update x`, l'équivalent npm sans toucher au `package.json`…, à vérifier par outil). Indirecte : pareil ; si elle n'atteint pas la cible, dire quel paquet la retient (graphe de `parsers/lockfiles.py`).
- Outil absent : le manifeste est quand même modifié, et le rapport dit « lockfile à régénérer : `<commande>` ».
- La résolution échoue (conflit) : remettre les fichiers du projet comme avant (manifestes compris : `FileChange.before`) et rapporter l'erreur.
- Après régénération, relire le lockfile : la version installée doit être la cible.
- Fichier de contraintes pip (`-c constraints.txt`, `Dependency.lockfile`) : y réécrire la ligne `==X` par `update.writers` (un `Target` de plus ; une ligne à `--hash` n'y est pas réécrite, le dire). Mini-projet `pip` : `numpy` n'a pas de contrainte dans `requirements.txt`, sa version vient de `numpy==1.26.4` dans `constraints.txt` (aujourd'hui, `update` n'y touche pas et dit « Lockfiles à régénérer ensuite : constraints.txt »).
- Brancher sur `forceupdate update` : régénérer juste après `writers.write`, et remplacer « Lockfiles à régénérer ensuite … (forceupdate ne le fait pas encore) » par le résultat de chaque lockfile.

Attention :
- Pas de logique métier dans `cli.py` : la régénération est dans `update/`, l'affichage dans `report/terminal.py` (`render_outcome`).
- Sur la machine : npm 11.6.2, pnpm 12.15.0, uv 0.10.11 sont sur le PATH ; yarn, poetry, pipenv, pip-compile n'y sont pas (les sessions d'avant les ont lancés par `npx`, `corepack` ou `uvx`). Le cas « outil absent » se voit donc pour de vrai ; demander à l'utilisateur s'il veut en installer avant de chercher ailleurs.
- pnpm 11+ ne lit plus le champ `pnpm` du `package.json` (E10) ; pnpm 11+ écrit un premier document YAML dans `pnpm-lock.yaml` si `packageManager` est donné (E05).
- Un workspace (uv, npm, Yarn, pnpm) a un lockfile à sa racine pour plusieurs projets : le régénérer une fois, depuis la racine.
- Les commandes réseau des outils (npm, uv) touchent le vrai registre : en test, ne lancer les vrais outils que dans des tests marqués `network`, sur des copies (`tmp_path`), jamais dans `tests/projects/` ; le reste se teste en simulant `subprocess.run`.
- Sous Windows : `npm` est `npm.cmd` (passer par `shutil.which`) ; `PYTHONIOENCODING=utf-8` pour lire les accents ; écrire les scripts dans un fichier (pas de heredoc). `UV_LINK_MODE=copy` fait taire « Failed to hardlink files ».

Fini quand : sur un projet npm et un projet uv, `update` donne un manifeste et un lockfile
cohérents ; sans l'outil, le message est clair. Vérifier avec : `uv run pytest`,
`uv run pytest --run-network`, `uv run ruff check`, `uv run ruff format --check`, sous 3.11 et 3.14
(`uv run --isolated --python 3.11 --group dev pytest`), et `forceupdate update --yes` sur une copie
de `tests/projects/vulnerable` (npm + pip-tools), `npm`, `uv`, `pnpm-catalog` et d'un clone d'Argos
(`$HOME/Desktop/the good guy`), lockfiles relus à la main.

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
