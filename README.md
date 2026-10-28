# forceupdate

On donne du code à l'outil : un dossier, un fichier, ou tous ses dépôts GitHub,
GitLab et Bitbucket. Dans une interface web qui tourne sur son ordinateur, il
montre les langages et les dépendances, et dit ce qui doit être mis à jour :
versions en retard, failles, fins de vie, paquets dépréciés. On coche les mises à
jour voulues, puis il les fait : en local il réécrit les fichiers, sur une forge il
ouvre une pull request par dépôt.

En construction. L'outil sera publié gratuitement sur PyPI
(`uv tool install forceupdate`), sous licence MIT.

Déjà là, en ligne de commande, pour Python et npm : `forceupdate scan <dossier>`
dit quelles dépendances ont une faille connue (d'après [OSV](https://osv.dev),
indirectes comprises, avec la version qui la corrige), une version plus récente,
une version retirée, ou sont dépréciées.

```bash
forceupdate scan .                              # rapport dans le terminal
forceupdate scan . --format json -o rapport.json   # ou md ; toujours en UTF-8
forceupdate scan . --fail-on vuln               # code 1 si une faille est connue
forceupdate scan . --fail-on major              # code 1 si une majeure (ou pire) attend
forceupdate scan . --offline                    # seulement le cache, sans réseau
```

Autres options : `--no-dev`, `--transitive`, `--no-cache` (`forceupdate scan --help`).

`forceupdate update <dossier>` fait les mises à jour : il montre vers quelle version
monter et le diff des manifestes, puis, après confirmation, réécrit les contraintes
(dans leur style : `^4.17.0` devient `^4.21.2`), sans toucher au reste du fichier.
Correctifs, mineures et corrections de failles sont choisis ; les majeures sont
proposées à part, comme une version qui aurait elle-même une faille connue. Il refuse
d'écrire dans un fichier que git n'a pas en commit (sauf `--force`). Ensuite, les
lockfiles sont régénérés par leur outil (npm, pnpm, Yarn, uv, Poetry, PDM, pipenv,
pip-compile), sans les scripts du projet, à la version choisie quand l'outil le
permet ; si l'outil n'est pas installé, `update` dit la commande à lancer, et si la
résolution échoue, les fichiers sont remis comme avant.

```bash
forceupdate update . --dry-run           # le diff, sans rien écrire
forceupdate update .                     # correctifs et mineures (--level minor), après confirmation
forceupdate update . --yes               # sans demander
forceupdate update . --level major       # majeures comprises
forceupdate update . --security-only     # seulement les corrections de failles
forceupdate update . --exclude "eslint*" --ecosystem npm
```

`forceupdate ui` démarre le serveur local de l'interface, sur `127.0.0.1`
seulement, et ouvre le navigateur. L'interface elle-même n'est pas encore là : pour
l'instant, le serveur offre son API (analyser, préparer et appliquer les mises à jour,
suivre la progression), réservée à qui a le jeton de session que porte l'adresse
affichée. Ctrl+C l'arrête.

```bash
forceupdate ui                           # un port libre, et le navigateur
forceupdate ui --port 8765 --no-browser  # l'adresse seulement, jeton compris
```

- [docs/BRIEF.md](docs/BRIEF.md) : l'idée, les décisions prises, les pièges
- [docs/JSON_FORMAT.md](docs/JSON_FORMAT.md) : le format du rapport JSON, et l'API de l'interface
- [PLAN.md](PLAN.md) : le plan étape par étape, et l'avancement
- [reference/README.md](reference/README.md) : le code déjà disponible, repris d'Argos
