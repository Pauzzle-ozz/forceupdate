# Session 8 — Étape E08 : Failles (OSV)

Contexte : E01 à E07 sont faites. `forceupdate scan <chemin>` est la première version utile :
pour Python et npm, il dit ce qui a une version plus récente, une version retirée ou
dépréciée, dans le terminal, en JSON (`docs/JSON_FORMAT.md`) ou en Markdown, avec
`--fail-on`, `--offline`, `--transitive`. Il manque les failles : c'est cette étape, qui
termine l'analyse locale (jalon « après E08 »). Le dépôt n'a encore aucun commit : le
proposer d'abord à l'utilisateur. 1142 tests verts, plus 3 réseau.

Lis CLAUDE.md, puis l'étape E08 de PLAN.md. Lis les « Notes » de E07 (`engine.check`,
`checks/`, la priorité, `report.rows`, les garde-fous des tests) et de E06
(`HttpClient.request(…, retry=True)`, `CacheKind`). Dans docs/BRIEF.md : le type 2, les
décisions n°3, 8 et 19. Dans `reference/` : `reference/README.md` (point 3, OSV), puis
`reference/argos_sca_parsers.py` L211-219, L314-329, L1135-1381, et
`TestQueryOSVNetworkErrors` dans `reference/argos_sca_parsers_tests.py`.

À faire :
- Reprendre `query_osv_batch`, `_parse_osv_vuln`, le calcul CVSS et leurs tests (les 5 tests OSV, en `skip` dans `reference/`). Couper `ARGOS (1)` (→ `models.Severity`), `ARGOS (2)` (→ `HttpClient` de E06, `request("POST", …, retry=True)` pour `querybatch`), `ARGOS (3)` (→ chaque faille complète par `GET /v1/vulns/{id}`, avec un `CacheKind` de plus, à durée de vie longue, sans doublon).
- Version corrigée : la plus petite version corrigée au-dessus de l'actuelle, lue dans les événements `introduced` / `fixed`, comparée avec `versions/`.
- `checks/vulns.py`, branché sur `engine.check` : toutes les dépendances, indirectes comprises, quelle que soit `--transitive` (qui ne vaut que pour les types 1 et 4) ; `--no-dev` s'applique. En npm, une indirecte par (nom, version) : les vérifier toutes. Les indirectes en faille s'affichent à part : `report.rows(direct=False)` ne montre aujourd'hui que celles que retient `checks.selected`, l'élargir.
- `uv.lock` à plusieurs versions d'un même paquet (fourches par marqueurs) : E03 ne garde que la plus haute. Décider s'il faut vérifier les autres, sinon l'écrire dans les limites.
- Constat `VULNERABLE` : gravité (CVSS), identifiants (CVE, GHSA), version corrigée minimale (`target_version`), lien. Mettre à jour `docs/JSON_FORMAT.md`.
- Avec l'accord de l'utilisateur : créer le dépôt GitHub public `Pauzzle-ozz/forceupdate` (`gh repo create`), y pousser `main`, vérifier que la CI est verte. Puis lui proposer de publier la 0.1.0 sur PyPI pour réserver le nom (son compte PyPI, le dépôt déclaré « Trusted Publisher », `uv build`, `uv publish`, `uv tool install forceupdate` dans un dossier vierge) ; s'il préfère attendre, le noter et revérifier que le nom est libre.

Attention :
- Déjà prêts depuis E07 : `FindingKind.VULNERABLE`, `Finding.identifiers`, la priorité (« faille, par gravité » en tête), `--fail-on vuln`, le compte `vulnerable` du résumé, le libellé « faille » des rapports. Un paquet malveillant retiré de npm (crossenv : OSV le connaît sous `MAL-…`) doit sortir en faille critique, plus seulement en « paquet déprécié ».
- OSV `querybatch` ne renvoie que les identifiants des failles (reference/README.md, point 3) : la version corrigée est dans `GET /v1/vulns/{id}`. C'est le bug connu d'Argos (pas de version corrigée).
- Version actuelle « approximative » (borne basse, sans lockfile) : une faille trouvée sur la borne basse n'est pas sûre pour la version réellement installée. Décider comment le dire, et l'écrire dans les notes. Sans version actuelle, ne rien demander à OSV.
- Hors ligne : les failles viennent du cache, sinon « non concluant ». Une erreur réseau ne doit jamais donner « pas de faille ».
- Le projet du critère de fin (`lodash 4.17.15`, `flask 0.12`) ira dans `tests/projects/` : un dossier de tests n'est pas analysé par défaut (E02), il faut pointer `scan` sur le mini-projet lui-même.
- Tests : `respx`, avec des réponses OSV enregistrées dans `tests/fixtures/osv/` (étendre `tests/fixtures/record.py`). Hors des tests `network`, toute connexion est refusée (garde-fou de `conftest.py`) ; `Cache.default()` y ouvre un cache propre au test. Les tests asynchrones passent par `asyncio.run`.
- `reference/` est figée : copier, adapter dans `src/`, reprendre les tests.
- Sous Windows : `PYTHONIOENCODING=utf-8` pour lire les accents à la main ; un script Python passé par heredoc abîme les accents, l'écrire dans un fichier. uv signale parfois « Failed to hardlink files » : sans effet, `UV_LINK_MODE=copy` le fait taire.

Fini quand : un projet de test avec `lodash 4.17.15` et `flask 0.12` sort les CVE attendues,
avec la bonne version corrigée. Vérifier avec : `uv run pytest`, `uv run pytest --run-network`,
`uv run ruff check`, `uv run ruff format --check`, sous 3.11 et 3.14
(`uv run --isolated --python 3.11 --group dev pytest`), et
`uv run forceupdate scan "$HOME/Desktop/the good guy"` (Argos).

En fin de session : suivre la règle « Travail par sessions » de CLAUDE.md.
