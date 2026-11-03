"""La mise à jour d'un dépôt d'une forge, par une PR (une MR sur GitLab) : ce qu'enchaîne
l'interface (``web/proposals.py``) pour chaque dépôt (brief, décision n°14).

1. **Le récapitulatif** : la sélection préparée comme en local (``update.local.prepare``), sur
   les fichiers de dépendances téléchargés à l'analyse : diffs, lockfiles, commandes, sans rien
   cloner ni pousser ;
2. **``deliver``**, une fois le récapitulatif validé :

   - un clone superficiel de la branche par défaut (``Forge.clone``), dans un dossier de
     travail effacé à la fin (``forges.git.Workspace``) ;
   - la même sélection préparée de nouveau sur le clone (un fichier qui a changé depuis
     l'analyse : ses options sont sautées, avec la raison), écrite, puis les lockfiles
     régénérés (``update.local.apply``) ;
   - un commit des fichiers changés, au nom du compte : les manifestes réécrits et les
     lockfiles régénérés, jamais ceux qu'un outil en échec a remis comme avant ;
   - la branche ``BRANCH`` poussée à la place de l'ancienne, jamais la branche par défaut. Si
     elle a des commits qui ne viennent pas de forceupdate (une correction poussée à la main),
     rien n'est poussé : on ne les écrase pas. Si elle a déjà ce contenu, rien n'est poussé ;
   - la PR ouverte, ou celle déjà ouverte mise à jour (titre, description) : relancer n'en
     ouvre jamais une deuxième. Sa description dit ce qui a été fait (mises à jour, lockfiles,
     commandes à lancer, erreurs), puis donne le rapport Markdown de l'analyse.

   Rien à faire (aucune option applicable, aucun fichier changé) : rien n'est poussé.

Les outils de lockfile peuvent tourner plusieurs minutes : ``run`` les fait tourner hors de la
boucle (l'interface : dans le thread des mises à jour, une à la fois).
"""

import asyncio
import enum
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from forceupdate import __version__, processes
from forceupdate.forges import git, info
from forceupdate.forges.base import (
    Access,
    AccessDenied,
    Branch,
    BranchCommit,
    ChangeRequest,
    Forge,
    ForgeError,
    ForgeKind,
    Identity,
    Repository,
    TokenRefused,
)
from forceupdate.models import Event, Report, Update, UpdateOption
from forceupdate.net import NetworkError
from forceupdate.report import markdown
from forceupdate.report.markdown import code, escape
from forceupdate.sources.base import SourceError
from forceupdate.sources.local import LocalSource
from forceupdate.update import local, lockfiles, planner
from forceupdate.update.local import Prepared
from forceupdate.update.lockfiles import ExtraKind, LockStatus, Reach, Regenerated
from forceupdate.update.writers import WriteError

logger = logging.getLogger(__name__)

BRANCH = "forceupdate/dependencies"
"""La branche des PR de forceupdate (brief, décision n°18)."""
TITLE = "Mise à jour des dépendances (forceupdate)"
MARKER = "Generated-by: forceupdate"
"""La dernière ligne du message des commits de forceupdate : un commit de la branche qui ne
l'a pas vient de quelqu'un d'autre."""
MAX_BODY = 60_000
"""Caractères au plus dans la description d'une PR (GitHub en refuse au-delà de 65 536 ; GitLab
en accepte bien plus, mais une description si longue ne se lit plus)."""

FINE_GRAINED = (
    " Token fine-grained : il lui faut « Contents » et « Pull requests » en écriture sur ce dépôt."
)
INTERRUPTED = (
    "Interrompu : forceupdate s'est arrêté. Relancer l'envoi ; une branche déjà poussée sera "
    "reprise."
)
"""L'échec d'un dépôt dont l'envoi a été arrêté (``cancel``)."""

T = TypeVar("T")


class Runner(Protocol):
    """Fait tourner une fonction bloquante (git, les outils de lockfile) hors de la boucle."""

    def __call__(self, function: Callable[[], T], /) -> Awaitable[T]: ...


class Step(enum.StrEnum):
    """Où en est l'envoi d'un dépôt."""

    CLONING = "cloning"
    UPDATING = "updating"
    """Réécriture des manifestes, régénération des lockfiles, commit."""
    PUSHING = "pushing"
    REQUESTING = "requesting"
    """Ouverture ou mise à jour de la PR."""


class Outcome(enum.StrEnum):
    """Ce qu'il est advenu d'un dépôt."""

    OPENED = "opened"
    """Une PR ouverte."""
    UPDATED = "updated"
    """La PR déjà ouverte, mise à jour (branche poussée si son contenu a changé, description)."""
    NOTHING = "nothing"
    """Rien à faire : rien n'est poussé."""
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class Delivered:
    """Ce qu'il est advenu d'un dépôt envoyé (``deliver``)."""

    outcome: Outcome
    request: ChangeRequest | None = None
    """La PR ouverte ou mise à jour."""
    pushed: bool = False
    """La branche a été poussée (faux : rien à faire, ou elle avait déjà ce contenu)."""
    base: str | None = None
    """Le commit de la branche par défaut sur lequel la mise à jour est faite."""
    commit: str | None = None
    """Le commit de forceupdate."""
    prepared: Prepared | None = None
    """La sélection préparée sur le clone."""
    results: tuple[Regenerated, ...] = ()
    committed: tuple[str, ...] = ()
    """Les fichiers du commit."""
    error: str | None = None
    refused: bool = False
    """La forge a refusé le token : le compte doit le dire."""


async def _in_thread(function: Callable[[], T]) -> T:
    return await asyncio.to_thread(function)


async def deliver(
    forge: Forge,
    repo: Repository,
    report: Report,
    selection: planner.Selection,
    *,
    author: Identity,
    workdir: Path,
    run: Runner = _in_thread,
    on_step: Callable[[Step], None] | None = None,
    on_event: Callable[[Event], None] | None = None,
    tools: lockfiles.Tools = lockfiles.DEFAULT_TOOLS,
    cancel: threading.Event | None = None,
) -> Delivered:
    """Met à jour ``repo`` par une PR : ``selection`` sur l'analyse ``report``, dans un clone
    rangé dans ``workdir`` (que l'appelant efface), ses outils de lockfile lancés selon ``tools``.
    Ne lève pas : un échec est rendu (``Outcome.FAILED``, avec l'erreur en français).

    ``on_step`` reçoit chaque étape, ``on_event`` les ``Event`` de la mise à jour (un
    ``regenerating`` par outil lancé). ``cancel`` levé (l'arrêt du serveur), l'outil de lockfile
    en cours est tué, comme les commandes git de la forge (``Forge.cancel``, le même), et l'envoi
    s'arrête là (``INTERRUPTED``). Une branche déjà poussée sans sa PR est reprise par l'envoi
    suivant : la branche est de forceupdate, la PR s'ouvre."""
    step = on_step or _ignore
    # Des droits inconnus : un token fine-grained de GitHub. Ailleurs (un token d'API Atlassian,
    # un token GitLab), le conseil ne s'applique pas.
    unknown = author.access is Access.UNKNOWN and forge.kind is ForgeKind.GITHUB
    hint = FINE_GRAINED if unknown else ""
    base: str | None = None
    prepared: Prepared | None = None
    results: tuple[Regenerated, ...] = ()

    def failed(message: str, *, refused: bool = False) -> Delivered:
        return Delivered(
            outcome=Outcome.FAILED,
            base=base,
            prepared=prepared,
            results=results,
            error=_sentence(message),
            refused=refused,
        )

    if repo.archived:
        return failed("Dépôt archivé : il est en lecture seule.")
    if not repo.can_push:
        return failed("Le compte n'a pas le droit de pousser dans ce dépôt.")
    if repo.default_branch is None or repo.default_branch == BRANCH:
        return failed(f"Pas de branche par défaut, ou c'est {BRANCH} : rien n'est poussé.")
    try:
        step(Step.CLONING)
        checkout = workdir / "depot"
        await forge.clone(repo, checkout)
        base = await run(lambda: git.head(checkout))
        step(Step.UPDATING)
        source = await run(lambda: LocalSource(checkout))
        prepared = await run(lambda: local.prepare(source, report, selection, tools=tools))
        if prepared.empty:
            return Delivered(outcome=Outcome.NOTHING, base=base, prepared=prepared)
        ready = prepared
        results = await run(
            lambda: local.apply(source, report, ready, on_event=on_event, cancel=cancel)
        )
        paths = committable(prepared, results)
        message = commit_message(prepared, results)
        who = git.Author(
            name=author.name or author.login,
            email=author.email or f"{author.login}@users.noreply.{author.host}",
        )
        commit = await run(lambda: git.commit(checkout, paths, message, author=who))
        if commit is None:
            return Delivered(outcome=Outcome.NOTHING, base=base, prepared=prepared, results=results)
        step(Step.PUSHING)
        existing = await forge.find_open_request(repo, BRANCH)
        remote = await forge.branch(repo, BRANCH)
        foreign = _foreign(remote)
        if foreign:
            return failed(_foreign_message(foreign, remote))
        tree = await run(lambda: git.tree(checkout))
        pushed = remote is None or await forge.branch_tree(repo, checkout, remote) != tree
        if pushed:
            expected = remote.head if remote is not None else None
            await forge.push_branch(repo, checkout, BRANCH, expected=expected)
        step(Step.REQUESTING)
        body = request_body(report, prepared, results, repo=repo, base=base)
        request = await forge.open_or_update_request(repo, branch=BRANCH, title=TITLE, body=body)
    except processes.Interrupted:
        return failed(INTERRUPTED)
    except TokenRefused as err:
        return failed(str(err), refused=True)
    except AccessDenied as err:
        return failed(f"{str(err).rstrip('.')}.{hint}")
    except git.GitError as err:
        message = str(err)
        if err.failure is git.GitFailure.STALE:
            message = (
                f"La branche {BRANCH} a changé sur la forge pendant l'envoi : rien n'est "
                "poussé. Relancer."
            )
        return failed(message)
    except (ForgeError, NetworkError, SourceError, WriteError, ValueError) as err:
        return failed(str(err))
    return Delivered(
        outcome=Outcome.UPDATED if existing is not None else Outcome.OPENED,
        request=request,
        pushed=pushed,
        base=base,
        commit=commit,
        prepared=prepared,
        results=results,
        committed=tuple(paths),
    )


def committable(prepared: Prepared, results: tuple[Regenerated, ...]) -> list[str]:
    """Les fichiers à commiter : les manifestes réécrits et les lockfiles régénérés (avec les
    dossiers que leurs outils refont : ``vendor/``), sauf ce qu'un outil en échec a remis comme
    avant."""
    restored = {path for result in results for path in result.restored}
    regenerated = [
        path
        for result in results
        if result.status is LockStatus.REGENERATED
        for path in (result.job.lockfile, *result.job.refreshes)
    ]
    found = [change.path for change in prepared.changes.files] + regenerated
    return [path for path in dict.fromkeys(found) if path not in restored]


def ours(commit: BranchCommit) -> bool:
    """Un commit de la branche que forceupdate peut remplacer : le sien, ou une fusion de la
    branche par défaut (« Update branch » de GitHub)."""
    return commit.merge or re.search(rf"^{re.escape(MARKER)}\b", commit.message, re.M) is not None


def _foreign(remote: Branch | None) -> list[BranchCommit]:
    """Les commits de la branche distante qui ne viennent pas de forceupdate."""
    if remote is None:
        return []
    found = [commit for commit in remote.commits if not ours(commit)]
    unseen = remote.ahead - len(remote.commits)
    if unseen > 0 and not found:
        found = [BranchCommit(sha="", message="", merge=False)] * unseen
    return found


def _foreign_message(foreign: list[BranchCommit], remote: Branch | None) -> str:
    first = foreign[0]
    title = first.message.splitlines()[0] if first.message else ""
    which = f" ({first.sha[:7]} « {title} »)" if first.sha else ""
    count = len(foreign)
    noun = "un commit qui ne vient" if count == 1 else f"{count} commits qui ne viennent"
    return (
        f"La branche {BRANCH} a {noun} pas de forceupdate{which} : rien n'est poussé, pour ne "
        "pas l'écraser. L'intégrer à la branche par défaut, ou supprimer la branche, puis "
        "relancer"
    )


# -- le message du commit et la description de la PR ------------------------------------


def commit_message(prepared: Prepared, results: tuple[Regenerated, ...]) -> str:
    """Le message du commit : les mises à jour faites, puis la marque de forceupdate."""
    lines = ["Mise à jour des dépendances", ""]
    for update, option, _ in _done(prepared, results):
        current = update.current_version or "?"
        lines.append(f"- {update.name} {current} → {option.version}")
    lines += ["", f"{MARKER} {__version__}", ""]
    return "\n".join(lines)


def request_body(
    report: Report,
    prepared: Prepared,
    results: tuple[Regenerated, ...],
    *,
    repo: Repository,
    base: str | None,
) -> str:
    """La description de la PR, en Markdown : ce qui a été fait, puis le rapport de
    l'analyse, raccourci s'il dépasse ``MAX_BODY``."""
    where = f" sur le commit `{base[:7]}`" if base else ""
    lines = [
        f"Mise à jour des dépendances proposée par forceupdate {__version__}, faite{where} de "
        f"`{code(repo.default_branch or '')}`.",
        "",
        "## Mises à jour",
        "",
        "| Paquet | Projet | Version | Failles corrigées | État |",
        "|---|---|---|---|---|",
    ]
    by_lockfile = {result.job.lockfile: result for result in results}
    for project, update, option in prepared.changes.applied:
        result = by_lockfile.get(option.lockfile or "")
        fixes = ", ".join(option.fixes[:3]) + (" …" if len(option.fixes) > 3 else "")
        lines.append(
            f"| `{code(update.name)}` | `{code(project.path)}` "
            f"| {escape(update.current_version or '?')} → {escape(option.version)} "
            f"| {escape(fixes) or '-'} | {_state(update.id, result)} |"
        )
    lockfile_lines = [line for result in results for line in _lockfile_lines(result)]
    if lockfile_lines:
        lines += ["", "## Lockfiles", "", *lockfile_lines]
    if prepared.changes.skipped:
        lines += ["", "## Non appliquées", ""]
        lines += [
            f"- `{code(item.update.name)}` {escape(item.option.version)} : {escape(item.reason)}"
            for item in prepared.changes.skipped
        ]
    footer = [
        "",
        "---",
        "",
        f"Relancer forceupdate met à jour cette {info(repo.forge).request} : la branche "
        f"`{BRANCH}` est remplacée. Un commit ajouté à la main sur cette branche l'en empêche : "
        "forceupdate ne l'écrase pas.",
    ]
    head = "\n".join(lines) + "\n"
    tail = "\n".join(footer) + "\n"
    analysis = _analysis(report)
    room = MAX_BODY - len(head) - len(tail)
    if len(analysis) > room:
        cut = analysis[: max(room - 200, 0)].rpartition("\n")[0]
        analysis = (
            f"{cut}\n\n_Rapport raccourci : trop long pour la description d'une "
            f"{info(repo.forge).request}. Le rapport complet est dans forceupdate._\n"
        )
    return f"{head}\n{analysis}{tail}"


def _analysis(report: Report) -> str:
    """Le rapport Markdown de l'analyse, ses titres descendus d'un niveau."""
    lines = markdown.render(report).splitlines()[1:]  # sans « # Rapport forceupdate »
    demoted = [f"#{line}" if line.startswith("#") else line for line in lines]
    return "\n".join(["## Rapport de l'analyse", *demoted]).rstrip() + "\n"


def _done(
    prepared: Prepared, results: tuple[Regenerated, ...]
) -> list[tuple[Update, UpdateOption, Regenerated | None]]:
    """Les options appliquées qui restent faites : ni remises comme avant (un lockfile en échec,
    une majeure que l'outil refuse), ni retenues en dessous par le lockfile (session 36 : le
    commit disait « minimatch 10.2.6 → 11.0.1 », le lockfile gardait 10.2.6)."""
    by_lockfile = {result.job.lockfile: result for result in results}
    found = []
    for _, update, option in prepared.changes.applied:
        result = by_lockfile.get(option.lockfile or "")
        if result is not None and (
            result.status in (LockStatus.FAILED, LockStatus.UNDONE)
            or any(d.update.id == update.id for d in result.dropped)
            or any(i.update.id == update.id and i.reach is Reach.BELOW for i in result.installed)
        ):
            continue
        found.append((update, option, result))
    return found


def _state(update_id: str, result: Regenerated | None) -> str:
    """Ce qu'il est advenu d'une mise à jour, en quelques mots."""
    if result is None:
        return "faite"
    if result.status is LockStatus.TOOL_MISSING:
        return f"lockfile à régénérer ({result.job.program_name} absent)"
    if result.status in (LockStatus.FAILED, LockStatus.UNDONE):
        return "pas faite : lockfile en échec"
    dropped = next((d for d in result.dropped if d.update.id == update_id), None)
    if dropped is not None:
        return f"pas faite : {result.job.tool} la refuse ({escape(dropped.reason.rstrip('.'))})"
    installed = next((i for i in result.installed if i.update.id == update_id), None)
    if installed is None or installed.reach is Reach.EXACT:
        return "faite"
    if installed.reach is Reach.ABOVE:
        return f"faite, en {escape(', '.join(installed.versions))}"
    if installed.reach is Reach.BELOW:
        held = f" par {escape(', '.join(installed.held_by))}" if installed.held_by else ""
        return f"retenue en {escape(', '.join(installed.versions))}{held}"
    return "faite, version non relue"


def _lockfile_lines(result: Regenerated) -> list[str]:
    job = result.job
    name = f"`{code(job.lockfile)}`"
    if result.status is LockStatus.REGENERATED:
        tool = f"{job.tool}, celui du projet" if job.doing is ExtraKind.PROJECT_NPM else job.tool
        lines = [f"- {name} : régénéré par {tool}."]
        if job.doing is ExtraKind.GO_VENDOR:
            lines.append(f"  `{code(job.refreshes[0])}/` refait (`go mod vendor`).")
        verified = result.verified
        if verified is not None and verified.error is None:
            lines.append(f"  Relu par `{code(verified.command)}` : accepté.")
        elif verified is not None:
            lines.append(
                f"  **Refusé par `{code(verified.command)}`** : {escape(verified.error or '')}"
            )
        if result.dropped:
            names = ", ".join(f"{d.update.name} {d.option.version}" for d in result.dropped)
            lines.append(
                f"  {escape(job.tool)} échouait avec toutes les mises à jour : régénéré sans "
                f"{escape(names)}, qu'il refuse (le tableau dit pourquoi)."
            )
        lines += [f"  {escape(warning)}" for warning in result.warnings]
        if result.changed:
            lines.append(f"  Aussi changé : {escape(', '.join(result.changed))}.")
        return lines
    if result.status is LockStatus.TOOL_MISSING:
        return [
            f"- {name} : **pas régénéré**, {job.program_name} n'est pas installé là où cette PR "
            f"a été préparée. À lancer dans `{code(job.directory)}`, puis commiter :",
            "",
            *_fenced(job.command, indent="  "),
        ]
    if result.status is LockStatus.FAILED:
        return [
            f"- {name} : **{job.tool} a échoué** ; ses fichiers sont remis comme avant et ne "
            "sont pas dans cette PR.",
            "",
            *_fenced(result.error or "pas de détail", indent="  "),
        ]
    return [f"- {name} : remis comme avant, pas dans cette PR ({escape(result.error or 'échec')})."]


def _fenced(text: str, *, indent: str) -> list[str]:
    """``text`` en bloc de code, sans qu'il puisse le fermer."""
    fence = "```"
    while fence in text:
        fence += "`"
    body = [f"{indent}{line}" for line in text.strip().splitlines()]
    return [f"{indent}{fence}", *body, f"{indent}{fence}"]


def _sentence(message: str) -> str:
    message = message.strip().rstrip(".")
    return f"{message[:1].upper()}{message[1:]}."


def _ignore(_: object) -> None:
    pass
