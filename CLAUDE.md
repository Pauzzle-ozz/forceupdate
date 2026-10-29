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
├── .github/workflows/      ← ci.yml : ruff + pytest (Ubuntu et Windows, Python 3.11 et 3.14), et le
│                             front (types, lint, Vitest, Playwright) ; publish.yml : PyPI, front compris
├── design-system/          ← produit à E13 avec le skill ui-ux-pro-max
│   ├── MASTER.md           ← les règles de l'interface : tokens, typo, composants, accessibilité
│   ├── ECRANS.md           ← les 9 écrans : contenu, appels à l'API, états, adresses
│   ├── pages/              ← les écarts au MASTER, par écran
│   └── mockups/            ← maquettes HTML statiques (ouvrir index.html), tokens de référence
├── docs/
│   ├── BRIEF.md            ← l'idée, les décisions prises, les pièges, les sources de données
│   └── JSON_FORMAT.md      ← le format du rapport JSON (scan --format json), et l'API de ui
├── reference/              ← code repris d'Argos, à piocher (voir reference/README.md)
├── frontend/               ← l'interface : React + TypeScript + Vite + Tailwind 4 + shadcn/ui (E14)
│   ├── src/api/            ← schema.d.ts (généré depuis openapi.json), client.ts, types.ts
│   ├── src/styles/         ← tokens.css (ceux de MASTER), app.css (Tailwind, polices)
│   ├── src/components/ui/  ← les composants shadcn/ui, habillés par les tokens ; sheet.tsx, dialog.tsx : <dialog> natif
│   ├── src/screens/        ← les écrans (Home, Choose, ScanProgress, report/…, update/ : l'écran 5,
│   │                         accounts/ : l'écran 6, repositories/ : l'écran 7, proposals/ : l'écran 8) ;
│   │                         tests *.test.tsx à côté
│   ├── src/test/           ← mise en place de Vitest, fetch et EventSource simulés, rapport d'exemple
│   └── e2e/                ← tests Playwright (vrai serveur, front construit, CSP, axe-core) ;
│                             helpers.ts : copie d'un mini-projet dans un dossier temporaire ;
│                             forges.spec.ts : écrans 6, 7 et 8, GitHub et GitLab, en série (comptes du
│                             serveur partagés)
├── src/forceupdate/        ← le code de l'outil (architecture cible : PLAN.md)
│   ├── forges/             ← interface Forge et OAuthFlow (base.py), GitHub (github.py : REST, dépôts,
│   │                         arborescence, fichiers, OAuth, device flow, gh, clone, branche, push, PR),
│   │                         GitLab (gitlab.py : gitlab.com ou une instance, projets, arborescence
│   │                         paginée, fichiers, OAuth PKCE et refresh token, clone, branche, MR), git (git.py :
│   │                         token par un credential helper éphémère, clone superficiel, commit, push
│   │                         avec bail, dossier de travail), comptes connectés (accounts.py : tokens
│   │                         dans le trousseau, keyring, un compte par forge et par hôte, renouvellement)
│   ├── sources/            ← d'où vient le code : local.py (dossier, fichier), forge.py (un dépôt lu par
│   │                         l'API : seuls les fichiers que lisent les parseurs sont téléchargés ; un
│   │                         clone superficiel si l'arborescence est tronquée)
│   ├── update/             ← planner, writers/, lockfiles, local.py (mise à jour d'un dossier), forge.py
│   │                         (une PR par dépôt : clone, mise à jour, commit, push, PR)
│   └── web/                ← le serveur de ui (FastAPI) ; repositories.py : les dépôts des comptes et leurs
│                             analyses groupées ; proposals.py : le récapitulatif des PR et leur envoi ;
│                             openapi.json, exporté, donne les types du front ;
│                             static/ : le front construit (npm run build), ignoré par git, livré dans le paquet
└── tests/                  ← les tests ; conftest.py gère le marqueur network
    ├── e2e_server.py       ← le serveur de ui hors ligne pour Playwright (npm, uv, gh, GitHub, GitLab
    │                         et une instance, leurs dépôts, trousseau simulés ; des dépôts « bare » où
    │                         git pousse), et les
    │                         rapports d'exemple du front
    ├── fake_forge.py       ← GitHub simulé pour les dépôts (liste, arborescence, fichiers, organisations,
    │                         branches, comparaison, PR) ; make_remote : un dépôt « bare » local par dépôt
    ├── fake_gitlab.py      ← GitLab simulé (gitlab.com ou une instance : projets, arborescence paginée,
    │                         fichiers, branches, comparaison, MR, OAuth avec refresh token)
    ├── fixtures/           ← réponses HTTP enregistrées ; record.py les ré-enregistre
    └── projects/           ← mini-projets par outil, lockfiles produits par les vrais outils
```

## Commandes

```bash
uv sync                          # installe l'outil et ses dépendances dans .venv
uv run forceupdate --version     # lance l'outil (ui, scan, update)
uv run forceupdate scan <chemin> # analyse ; --format json|md, --output, --offline, --fail-on…
uv run forceupdate update <chemin>  # le plan, le diff, puis la réécriture des manifestes et
                                    # la régénération des lockfiles (npm, uv… s'ils sont là) ;
                                    # --dry-run, --yes, --force, --level, --security-only…
uv run forceupdate ui --no-browser  # le serveur local (127.0.0.1), l'adresse avec le jeton ; Ctrl+C
uv run python -m forceupdate.web.openapi  # réexporte web/openapi.json (un test vérifie qu'il est à jour)
uv run pytest                    # tests hors ligne ; reference/ n'est jamais ramassé
uv run pytest --run-network      # avec en plus les tests marqués network (vrai réseau)
uv run ruff check                # lint
uv run ruff format               # formatage ; la CI vérifie avec --check
uv run python tests/fixtures/record.py   # ré-enregistre les réponses des registres et d'OSV
uv run python tests/fixtures/record.py pypi:jinja2   # un seul paquet (déclaré dans PACKAGES)

# le front (node 24 ; dans frontend/, après « npm ci »)
npm run build                    # construit le front dans src/forceupdate/web/static/ (servi par ui)
npm test                         # tests de composants (Vitest + Testing Library), sans réseau
npm run typecheck                # types (tsc) ; npm run lint : oxlint, sans avertissement
npm run test:e2e                 # construit, puis Playwright : vrai serveur hors ligne (tests/e2e_server.py)
npm run gen:api                  # régénère src/api/schema.d.ts depuis openapi.json (un test le vérifie)
FORCEUPDATE_URL=<adresse de « forceupdate ui »> npm run dev   # Vite, /api passé au serveur, jeton compris

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
  standard (heredoc) abîme les accents, et l'outil Bash réduit `\\` à `\` dans un heredoc :
  l'écrire dans un fichier (outil d'écriture), puis le lancer.
- Les tests ne touchent jamais le réseau sans le marqueur `network` (donc jamais le vrai
  GitHub), ni le cache de l'utilisateur, ni un vrai outil de lockfile (npm, uv…), ni le
  trousseau du système ni `gh`, ne lancent git que vers des dépôts locaux, et n'ouvrent jamais
  le navigateur : six garde-fous automatiques de `tests/conftest.py` y veillent. Les tests des
  PR clonent et poussent pour de vrai, vers des dépôts « bare » du dossier du test
  (`fake_forge.make_remote`, `github.GIT_URL` vers `remotes_url(…)`). Dans un test, jamais
  `monkeypatch.undo()` : il défait aussi ces garde-fous (`monkeypatch.context()`). GitLab se simule avec
  `fake_gitlab.FakeGitLab` (`gitlab.GIT_URL` vers `remotes_url(…)` pour git). La fixture `recorded` simule PyPI, npm
  et OSV avec les réponses de `tests/fixtures/` ; `fake_tools("npm", "uv")` simule les
  outils (`FakeTools`) ; `keychain` est le trousseau en mémoire du test ; `api` est le
  serveur de `ui` (client de test de FastAPI, jeton compris), `finished` attend la fin
  d'une tâche. GitHub se simule avec respx (`tests/test_web_accounts.py`, `FakeGitHub` pour les
  comptes ; `tests/fake_forge.py`, `FakeGitHubRepos`, pour les dépôts, faits des mini-projets).
- Le retour d'OAuth (`/oauth/github/callback`) est la seule adresse que le garde du serveur
  laisse passer sans jeton : ne pas en ajouter d'autre sans la même protection (`state`).
  L'essayer pour de vrai : `forceupdate ui`, par l'adresse `127.0.0.1` (pas `localhost`) ;
  le compte connecté va dans le vrai trousseau (Gestionnaire d'identification de Windows).
- Un test qui lance une vraie commande `ui` (sans `serve` simulé) bloque la suite :
  le serveur attend Ctrl+C.
- Le front construit (`src/forceupdate/web/static/`) n'est pas versionné : sans lui, `ui`
  sert une ligne de texte. `npm run build` d'abord ; la publication (`publish.yml`) le fait
  avant `uv build`, et hatchling l'embarque (`artifacts`). Les tests Python ne lancent
  jamais node ; ceux du front ont leurs commandes (ci-dessus).
- Front : TypeScript 5.9, pas 7 (openapi-typescript a besoin de l'API JavaScript de
  TypeScript, que la 7 n'a pas). Playwright télécharge son Chromium une fois
  (`npx playwright install chromium`). Le serveur Vite de dev n'a pas la CSP : vérifier le
  front construit, servi par `ui` (les tests e2e échouent sur toute erreur de console).
- CSP du serveur (`default-src 'self'`) : rien d'un CDN, pas d'URL `data:`, pas de
  `<style>` ni de script en ligne (les styles posés par React passent). Radix Dialog et
  Sonner injectent un `<style>` : refusés ; le panneau et les dialogues sont des
  `<dialog>` natifs (`components/ui/sheet.tsx`, `dialog.tsx`), « Copié » s'annonce par une
  région `aria-live` (`components/Command.tsx`).
- Les tests e2e qui écrivent travaillent sur une copie (`e2e/helpers.ts`, `copyProject`) ;
  le serveur de test est partagé entre les tests : ses chemins récents s'accumulent.
- Pour essayer les PR en vrai : le dépôt de test `Pauzzle-ozz/forceupdate-demo` (privé, créé à
  E18, copie de `tests/projects/vulnerable`) sur GitHub, et le projet du même nom sur gitlab.com
  (privé, créé à E19) pour les MR ; gardés pour la recette (E31) ; jamais un autre dépôt sans
  l'accord de l'utilisateur.
- Pour essayer `forceupdate update` en vrai : sur une copie dans le scratchpad, jamais
  dans `tests/projects/` (les outils réécrivent les lockfiles). yarn, poetry, pdm,
  pipenv et pip-compile ne sont pas installés (choix de l'utilisateur) : `npx yarn@1`,
  `corepack yarn@4.18.1`, `uvx poetry`, `uvx pdm`, `uvx pipenv`,
  `uvx --from pip-tools pip-compile`. pipenv crée un virtualenv dans `~/.virtualenvs`
  (le retirer avec `uvx pipenv --rm`), et prend le `.venv` activé si `VIRTUAL_ENV` est
  défini.

## Interface

- **Avant d'écrire ou de modifier quoi que ce soit dans l'interface, charger le
  skill `ui-ux-pro-max`**
  (source : https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), puis lire
  `design-system/MASTER.md`, l'écran dans `design-system/ECRANS.md` et, s'il existe,
  `design-system/pages/<écran>.md`. Les maquettes (`design-system/mockups/`) donnent le
  rendu attendu et les tokens exacts (`mockups/assets/mockups.css`).
- Le skill sous Windows : ses dossiers `scripts/` et `data/` sont des liens git non
  résolus ; lancer `python ~/.claude/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py`
  (avec `PYTHONIOENCODING=utf-8`).
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
