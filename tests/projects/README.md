# Mini-projets de test

Un dossier par outil. Les lockfiles ont été produits par les vrais outils, puis
figés : ne pas les régénérer sans mettre à jour les tests qui en dépendent.

| Dossier | Outil | Lockfile produit avec |
|---|---|---|
| `pip/` | pip : `-r`, `-c`, dépendance git, `-e` local | (pas de lockfile) |
| `pip-tools/` | pip-tools : `.in` compilés en `.txt` | `pip-compile` |
| `poetry/` | Poetry 1.8 : `poetry.lock` sans `category` ni `groups` | `poetry lock` (1.8.5) |
| `uv/` | workspace uv : un membre, un exclu, un projet hors workspace | `uv lock` |
| `pipenv/` | Pipfile | `pipenv lock` |
| `setuptools/` | `setup.cfg`, et un `setup.py` qui n'est pas lu | (pas de lockfile) |
| `npm/` | npm : chaque forme de plage, alias `npm:`, `file:`, pair, facultative, version imbriquée | `npm install` (npm 11.6, lockfile v3) |
| `yarn1/` | Yarn 1 : le même `package.json` que `npm/` | `yarn install` (1.22.22) |
| `yarn4/` | workspace Yarn 4 : la racine et un membre, `typescript` et `fsevents` patchés d'office | `yarn install --mode=update-lockfile` (4.18.1) |
| `pnpm9/` | workspace pnpm 9 : deux membres reliés par `workspace:*`, un exclu par `!packages/excluded` | `pnpm install --lockfile-only` (9.15.9) |
| `npm-workspace/` | workspace npm : deux membres, un conflit de versions entre eux, un dossier hors workspace | `npm install` (npm 11.6) |
| `pnpm-catalog/` | workspace pnpm à catalogues : `catalog:`, `catalog:default`, `catalog:legacy` (sous `catalogs:`), un alias `npm:` dans le catalogue | `pnpm install --lockfile-only --ignore-scripts` (12.15.0) |

Les lockfiles npm ont été produits avec `--ignore-scripts`, dans un dossier à part,
puis copiés ici sans `node_modules/`. `vendor/local-lib/` (cible du `file:` de `npm/`
et `yarn1/`) est rangé dans `vendor/` exprès : ce dossier est écarté, il ne fait pas
un projet de plus. Sous Windows, Yarn écrit `yarn.lock` en CRLF.

Ce dossier est rangé sous `tests/` : `forceupdate scan` sur forceupdate lui-même
l'écarte (voir E02 dans `PLAN.md`). Pour l'analyser, choisir un mini-projet
directement : `forceupdate scan tests/projects/uv`.
