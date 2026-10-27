# forceupdate

L'outil s'appelle `forceupdate` (nom PyPI, paquet Python et commande). Le dossier
du projet garde son nom, `update-checker`.

Outil avec une interface web, qui tourne sur l'ordinateur de la personne. Il
prend du code (un dossier, un fichier, ou tous les dépôts GitHub, GitLab et
Bitbucket d'une personne), repère les langages et les dépendances, dit ce qui doit
être mis à jour, et sait faire ces mises à jour : en local il réécrit les
fichiers, sur une forge il ouvre une PR.

## État

**En construction.** L'avancement est dans [PLAN.md](PLAN.md) (tableau « Vue
d'ensemble »). L'idée et les décisions prises sont dans
[docs/BRIEF.md](docs/BRIEF.md).

## Travail par sessions (règle obligatoire)

Le projet se construit étape par étape, en suivant [PLAN.md](PLAN.md).

1. **Au début de la session** : lire [PROCHAINE_SESSION.md](PROCHAINE_SESSION.md),
   le prompt préparé par la session d'avant, puis l'étape visée dans PLAN.md. Ne
   pas passer à une autre étape sans l'accord de l'utilisateur.
2. **Pendant** : une session = une étape. Les décisions prises en route et les
   écarts au plan sont notés sous l'étape, dans une rubrique « Notes ».
3. **À la fin de chaque session, toujours, même si l'étape n'est pas finie** :
   - mettre à jour PLAN.md : cases cochées, statut dans « Vue d'ensemble », une
     ligne dans « Journal des sessions » ;
   - **rédiger le prompt de la session suivante** dans PROCHAINE_SESSION.md, en
     remplaçant le précédent, sur le « Modèle de prompt de session » de PLAN.md.
     Il vise l'étape suivante du plan, ou la même étape si elle n'est pas finie,
     en disant ce qui reste ;
   - recopier ce prompt dans le dernier message à l'utilisateur.
4. **Le plan couvre 100 % du livrable.** Du travail non prévu s'ajoute au plan
   (nouvelle étape, ou étape découpée), il n'est jamais laissé de côté. Quand
   toutes les étapes sont faites et toutes les cases de « Le livrable » cochées,
   le projet est livrable, et le dernier prompt le dit.
5. **Pas de commit sans l'accord de l'utilisateur** : en fin de session, le
   proposer.

## Structure

```
update-checker/             ← dossier du projet ; l'outil s'appelle forceupdate
├── CLAUDE.md               ← ce fichier
├── PLAN.md                 ← le plan complet, étape par étape, et le journal des sessions
├── PROCHAINE_SESSION.md    ← le prompt de la prochaine session (réécrit à chaque session)
├── README.md
├── LICENSE                 ← MIT, « Copyright (c) 2026 Pauzzle »
├── pyproject.toml          ← le paquet, ses dépendances, la config ruff et pytest
├── uv.lock                 ← les versions figées des dépendances (versionné)
├── .github/workflows/      ← ci.yml : ruff + pytest, Ubuntu et Windows, Python 3.11 et 3.14
├── docs/
│   ├── BRIEF.md            ← l'idée, les décisions prises, les pièges, les sources de données
│   └── JSON_FORMAT.md      ← le format du rapport JSON (scan --format json, et l'API)
├── reference/              ← code repris d'Argos, à piocher (voir reference/README.md)
├── src/forceupdate/        ← le code de l'outil (architecture cible : PLAN.md)
└── tests/                  ← les tests ; conftest.py gère le marqueur network
    ├── fixtures/           ← réponses HTTP enregistrées ; record.py les ré-enregistre
    └── projects/           ← mini-projets par outil, lockfiles produits par les vrais outils
```

Viendront plus tard : `frontend/` (l'interface, à partir de E14) et
`design-system/` (produit à E13 avec le skill `ui-ux-pro-max`).

## Commandes

```bash
uv sync                          # installe l'outil et ses dépendances dans .venv
uv run forceupdate --version     # lance l'outil (ui, scan, update)
uv run forceupdate scan <chemin> # analyse ; --format json|md, --output, --offline, --fail-on…
uv run pytest                    # tests hors ligne ; reference/ n'est jamais ramassé
uv run pytest --run-network      # avec en plus les tests marqués network (vrai réseau)
uv run ruff check                # lint
uv run ruff format               # formatage ; la CI vérifie avec --check
uv run python tests/fixtures/record.py   # ré-enregistre les réponses des registres

# une autre version de Python que celle de .venv (la CI teste 3.11 et 3.14)
uv run --isolated --python 3.11 --group dev pytest

# tests de reference/, avec le Python du système (qui a loguru et pytest-asyncio)
cd reference && python -m pytest argos_sca_parsers_tests.py
```

- Sous Windows, uv prévient parfois « Failed to hardlink files » : sans effet sur
  le résultat, `UV_LINK_MODE=copy` le fait taire.
- Sous Windows, une sortie redirigée (tube, fichier) est écrite en cp1252 par
  défaut, pas en UTF-8. `forceupdate scan` repasse la sienne en UTF-8 (E07) ; pour
  un autre script, `PYTHONIOENCODING=utf-8`. Un script passé à Python par l'entrée
  standard (heredoc) abîme les accents : l'écrire dans un fichier.
- Les tests ne touchent jamais le réseau sans le marqueur `network`, ni le cache de
  l'utilisateur : deux garde-fous automatiques de `tests/conftest.py` y veillent.
  La fixture `recorded` simule PyPI et npm avec les réponses de `tests/fixtures/`.

## Interface

- **Avant d'écrire ou de modifier quoi que ce soit dans l'interface, charger le
  skill `ui-ux-pro-max`**
  (source : https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), puis lire
  `design-system/MASTER.md` et, s'il existe, `design-system/pages/<écran>.md`.
- L'interface et la ligne de commande ne contiennent pas de logique métier : elles
  appellent le moteur.
- Les tokens des forges ne vont jamais au navigateur.

## Règles pour `reference/`

- C'est une **réserve de morceaux à copier puis adapter** dans `src/`. Le code de
  `src/` n'importe jamais `reference/`.
- L'outil ne dépend **jamais** d'Argos (`sechunter`) : il doit tourner seul.
- Avant d'écrire un parseur de fichier de dépendances, regarder s'il existe déjà
  dans `reference/argos_sca_parsers.py` et lire ses limites dans
  `reference/README.md`.
- `reference/` est une copie figée (commit `52c714b7` d'Argos) : on ne la modifie
  pas. Quand on reprend un morceau, on l'adapte dans `src/` et on reprend aussi
  ses tests depuis `reference/argos_sca_parsers_tests.py`.
- Les trois dépendances à Argos à couper sont marquées `ARGOS (n)` dans le code.
- Le dépôt Argos d'origine est dans `~/Desktop/the good guy`, si besoin de
  remonter à la source. Pour la partie GitHub (clone avec token, PR), il a du code
  qui n'est pas dans `reference/` : voir [docs/BRIEF.md](docs/BRIEF.md), « Ce
  qu'on a déjà ».

## Langue

Français.
