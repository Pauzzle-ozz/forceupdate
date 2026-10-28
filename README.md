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

`forceupdate update <dossier>` montre, pour l'instant sans rien écrire, les mises à
jour qu'il ferait : vers quelle version, quelle contrainte réécrire (dans son style :
`^4.17.0` devient `^4.21.2`), quel lockfile régénérer. Correctifs, mineures et
corrections de failles sont choisis ; les majeures sont proposées à part.

```bash
forceupdate update .                     # correctifs et mineures (--level minor)
forceupdate update . --level major       # majeures comprises
forceupdate update . --security-only     # seulement les corrections de failles
forceupdate update . --exclude "eslint*" --ecosystem npm
```

- [docs/BRIEF.md](docs/BRIEF.md) : l'idée, les décisions prises, les pièges
- [docs/JSON_FORMAT.md](docs/JSON_FORMAT.md) : le format du rapport JSON
- [PLAN.md](PLAN.md) : le plan étape par étape, et l'avancement
- [reference/README.md](reference/README.md) : le code déjà disponible, repris d'Argos
