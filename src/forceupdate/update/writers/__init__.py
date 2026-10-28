"""La réécriture des manifestes : appliquer les mises à jour choisies sans casser les fichiers.

Brief, décision n°11 et « Réécrire un manifeste sans le casser » : rien n'est re-sérialisé. Seul
le texte de chaque contrainte change, à l'endroit exact où l'analyse l'a lu (``Location``) ;
commentaires, ordre, mise en forme, fins de ligne (CRLF) et BOM restent tels quels.

En deux temps :

1. ``prepare`` calcule, sans rien écrire, le nouveau texte de chaque fichier et son diff unifié
   (``unified_diff``, que l'interface montrera). Pour chaque option choisie
   (``planner.chosen``) :

   - une option à faire à la main (``UpdateOption.manual``) n'est pas appliquée ;
   - chaque réécriture (``Edit``) est située (``Target``) : le manifeste et l'emplacement de la
     contrainte, ou la plage d'un catalogue pnpm dans ``pnpm-workspace.yaml`` (``npm``). Le
     fichier doit avoir ``old`` à cet endroit : sinon il a changé depuis l'analyse ;
   - une version figée par un fichier de contraintes de pip (``-c constraints.txt``) : ce n'est
     pas un lockfile, aucun outil ne le régénère. Sa ligne ``==X`` est réécrite comme une
     contrainte de plus (``python.constraints_target``) ;
   - une option s'applique en entier ou pas du tout. Deux options qui réécrivent la même
     contrainte (le catalogue de deux projets, la version forcée de deux versions installées)
     doivent dire la même chose, sinon la seconde n'est pas appliquée ;
   - dans un fichier, les réécritures s'appliquent de la fin vers le début : chacune garde
     l'emplacement lu dans le texte d'origine. Une contrainte absente a un emplacement vide :
     la nouvelle y est insérée ;
   - **auto-vérification** : le fichier réécrit est relu par son parseur (``python``,
     ``npm``). Il doit redonner les mêmes déclarations, dans le même ordre, avec la nouvelle
     contrainte à chaque endroit réécrit, et aucune autre contrainte changée. Sinon il n'est pas
     réécrit, ni les options qui le touchaient.

   Ce qui n'est pas appliqué est rendu avec la raison (``Skipped``).
2. ``write`` écrit les fichiers, si aucun n'a changé depuis ``prepare`` : chacun par un fichier
   temporaire qui le remplace d'un coup ; si l'un échoue, ceux déjà écrits sont remis comme
   avant.

Un fichier qui n'est pas de l'UTF-8 valide, ou qui a des fins de ligne « \\r » seules, n'est pas
réécrit : les emplacements des parseurs ne s'y retrouveraient pas. Les lockfiles ne sont pas
touchés ici : ``Changes.lockfiles`` dit lesquels régénérer, ``update.lockfiles`` le fait.
``rewrite`` sert aussi à ``update.lockfiles`` pour écrire, le temps d'une régénération, une
version exacte à la place d'une contrainte.
"""

import contextlib
import difflib
import itertools
import os
import posixpath
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Ecosystem, EditKind, Location, Project, Update, UpdateOption
from forceupdate.parsers.base import ParseError
from forceupdate.update.writers import npm, python
from forceupdate.update.writers.base import Check, Reader, Refused, Target

__all__ = [
    "Changes",
    "Choice",
    "FileChange",
    "Refused",
    "Skipped",
    "Target",
    "WriteError",
    "constraints_file",
    "prepare",
    "replace_file",
    "rewrite",
    "unified_diff",
    "write",
]

Choice = tuple[Project, Update, UpdateOption]
"""Une option choisie, avec sa mise à jour et son projet : ce que rend ``planner.chosen``."""

_READERS: dict[str, Reader] = {**python.READERS, **npm.READERS}
_CHECKS: dict[str, Check] = python.CHECKS


class WriteError(Exception):
    """Les fichiers n'ont pas pu être écrits. Le message, en français, dit lesquels et ce qui
    a été remis comme avant."""


@dataclass(frozen=True, kw_only=True)
class FileChange:
    """Un fichier à réécrire."""

    path: str
    """Relatif à la racine de la source, au format POSIX."""
    before: str
    """Son contenu tel que lu, fins de ligne comprises."""
    after: str
    """Son contenu réécrit."""
    diff: str
    """Le diff unifié de ``before`` à ``after`` (``unified_diff``)."""


@dataclass(frozen=True, kw_only=True)
class Skipped:
    """Une option choisie qui n'est pas appliquée, et pourquoi."""

    update: Update
    option: UpdateOption
    reason: str
    """En une phrase, en français."""


@dataclass(frozen=True, kw_only=True)
class Changes:
    """Ce que la réécriture fera : les fichiers et leurs diffs, ce qui est appliqué, ce qui ne
    l'est pas."""

    files: tuple[FileChange, ...] = ()
    """Par chemin."""
    applied: tuple[Choice, ...] = ()
    """Les options appliquées, dans l'ordre du choix : leurs contraintes sont dans ``files``
    (aucune pour une mise à jour par le lockfile seul)."""
    skipped: tuple[Skipped, ...] = ()

    @property
    def lockfiles(self) -> tuple[str, ...]:
        """Les lockfiles à régénérer ensuite pour les options appliquées, sans doublon. Un
        fichier de contraintes de pip n'en est pas un : il est dans ``files``."""
        found = (
            option.lockfile
            for project, update, option in self.applied
            if option.lockfile and constraints_file(project, update, option) is None
        )
        return tuple(dict.fromkeys(found))

    @property
    def diff(self) -> str:
        """Les diffs de tous les fichiers, à la suite."""
        return "".join(change.diff for change in self.files)


def prepare(root: Path, chosen: Iterable[Choice]) -> Changes:
    """Les réécritures des options ``chosen``, dans la source de dossier ``root``, sans rien
    écrire (voir la docstring du module)."""
    files = _Files(root)
    skipped: list[Skipped] = []
    pending: list[tuple[Choice, list[Target]]] = []
    for choice in chosen:
        project, update, option = choice
        if option.manual is not None:
            reason = f"à faire à la main : {option.manual}"
            skipped.append(Skipped(update=update, option=option, reason=reason))
            continue
        try:
            located = _locate(files, project, update, option)
            targets = [_target(files, target) for target in located]
        except Refused as refused:
            skipped.append(Skipped(update=update, option=option, reason=str(refused)))
            continue
        pending.append((choice, targets))
    pending = _without_conflicts(pending, skipped)
    while True:
        rewritten, failed = _rewrite_all(files, pending)
        if not failed:
            break
        kept = []
        for choice, targets in pending:
            reason = next((failed[t.path] for t in targets if t.path in failed), None)
            if reason is None:
                kept.append((choice, targets))
            else:
                skipped.append(Skipped(update=choice[1], option=choice[2], reason=reason))
        pending = kept
    return Changes(
        files=tuple(rewritten[path] for path in sorted(rewritten)),
        applied=tuple(choice for choice, _ in pending),
        skipped=tuple(skipped),
    )


def rewrite(root: Path, targets: Iterable[Target]) -> tuple[FileChange, ...]:
    """Les fichiers réécrits par ``targets``, dans la source de dossier ``root``, sans rien
    écrire : chaque réécriture vérifiée puis relue, comme dans ``prepare``, mais toutes ou
    aucune. Deux réécritures au même endroit n'en font qu'une. Lève ``Refused``."""
    files = _Files(root)
    by_path: dict[str, dict[Location, Target]] = {}
    for target in targets:
        checked = _target(files, target)
        by_path.setdefault(checked.path, {}).setdefault(checked.location, checked)
    changed = []
    for path in sorted(by_path):
        before = files.text(path)
        after = _rewrite(path, before, list(by_path[path].values()))
        if after != before:
            diff = unified_diff(path, before, after)
            changed.append(FileChange(path=path, before=before, after=after, diff=diff))
    return tuple(changed)


def constraints_file(project: Project, update: Update, option: UpdateOption) -> str | None:
    """Le fichier de contraintes de pip (``-c constraints.txt``) qui fige la version de
    ``update``, si c'est de lui que vient ``option.lockfile`` ; ``None`` pour un vrai lockfile.

    C'est un fichier que le projet ne range pas parmi ses lockfiles, et dont le nom n'est pas
    celui d'un lockfile : un ``.txt`` compilé par pip-tools, lui, en est un."""
    path = option.lockfile
    if path is None or update.ecosystem is not Ecosystem.PYPI or path in project.lockfiles:
        return None
    match = match_dependency_file(path)
    return None if match is not None and match.lockfile else path


def write(root: Path, changes: Changes) -> None:
    """Écrit les fichiers de ``changes`` dans la source de dossier ``root``.

    Lève ``WriteError`` sans rien écrire si l'un d'eux a changé depuis ``prepare`` ; si une
    écriture échoue, les fichiers déjà écrits sont remis comme avant.
    """
    for change in changes.files:
        try:
            current = _read(root, change.path)
        except Refused as refused:
            raise WriteError(f"{refused} Rien n'est écrit.") from refused
        if current != change.before:
            raise WriteError(
                f"{change.path} a changé depuis le calcul du diff : rien n'est écrit, "
                "relancer la mise à jour."
            )
    done: list[FileChange] = []
    for change in changes.files:
        try:
            replace_file(root / change.path, change.after.encode("utf-8"))
        except OSError as err:
            for previous in reversed(done):
                with contextlib.suppress(OSError):
                    replace_file(root / previous.path, previous.before.encode("utf-8"))
            restored = " ; les fichiers déjà écrits sont remis comme avant" if done else ""
            raise WriteError(
                f"{change.path} : écriture impossible ({err.strerror or err}){restored}."
            ) from err
        done.append(change)


def unified_diff(path: str, before: str, after: str, *, context: int = 3) -> str:
    """Le diff unifié de ``path``, comme ``git diff`` : ``--- a/…``, ``+++ b/…``, puis des blocs
    ``@@``. Les lignes sont coupées sur ``\\n`` ; un ``\\r`` de fin de ligne n'est pas montré.
    Vide si rien ne change."""
    lines = difflib.unified_diff(
        _diff_lines(before), _diff_lines(after), f"a/{path}", f"b/{path}", n=context, lineterm=""
    )
    text = "\n".join(lines)
    return f"{text}\n" if text else ""


def _diff_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()  # la fin de la dernière ligne, pas une ligne de plus
    return [line.removesuffix("\r") for line in lines]


# ---------------------------------------------------------------------------
# Situer
# ---------------------------------------------------------------------------


def _locate(
    files: "_Files", project: Project, update: Update, option: UpdateOption
) -> list[Target]:
    """Les réécritures de ``option``, situées, avec la ligne de son fichier de contraintes de pip
    s'il en a un. Lève ``Refused``."""
    targets = []
    for edit in option.edits:
        if edit.kind is EditKind.CATALOG:
            targets.append(npm.catalog_target(edit, update.dependencies, files.parsed_text))
        elif edit.location is None:
            raise Refused(
                f"{edit.file} : emplacement de « {edit.old} » inconnu, à réécrire à la main en "
                f"« {edit.new} »."
            )
        else:
            targets.append(
                Target(path=edit.file, location=edit.location, old=edit.old, new=edit.new)
            )
    constraints = constraints_file(project, update, option)
    if constraints is not None:
        targets.append(
            python.constraints_target(constraints, update, option.version, files.parsed_text)
        )
    return targets


def _target(files: "_Files", target: Target) -> Target:
    """``target``, si son fichier a bien ``old`` à cet endroit, et que son format n'y voit pas
    d'obstacle (``CHECKS``). Lève ``Refused``."""
    text = files.text(target.path)
    lines = text.split("\n")
    location = target.location
    line = lines[location.line - 1].removesuffix("\r") if location.line <= len(lines) else ""
    if location.end_column > len(line) or line[location.column : location.end_column] != target.old:
        raise Refused(
            f"{target.path} a changé depuis l'analyse : « {target.old} » n'est plus à la ligne "
            f"{location.line}."
        )
    check = _CHECKS.get(_pattern(target.path, target.pattern) or "")
    if check is not None:
        check(target.path, text, target)
    return target


def _without_conflicts(
    pending: list[tuple[Choice, list[Target]]], skipped: list[Skipped]
) -> list[tuple[Choice, list[Target]]]:
    """Écarte une option qui réécrirait autrement une contrainte qu'une option d'avant réécrit
    déjà ; la même réécriture n'est faite qu'une fois."""
    claimed: dict[tuple[str, Location], tuple[str, Choice]] = {}
    kept = []
    for choice, targets in pending:
        clash = next(
            (
                (target, claimed[key])
                for target in targets
                if (key := (target.path, target.location)) in claimed
                and claimed[key][0] != target.new
            ),
            None,
        )
        if clash is not None:
            target, (new, (project, other, _)) = clash
            reason = (
                f"{target.path} : « {target.old} » est déjà réécrite en « {new} » pour "
                f"{other.name} {other.current_version} (projet {project.path})."
            )
            skipped.append(Skipped(update=choice[1], option=choice[2], reason=reason))
            continue
        for target in targets:
            claimed.setdefault((target.path, target.location), (target.new, choice))
        kept.append((choice, targets))
    return kept


# ---------------------------------------------------------------------------
# Réécrire, puis relire
# ---------------------------------------------------------------------------


def _rewrite_all(
    files: "_Files", pending: list[tuple[Choice, list[Target]]]
) -> tuple[dict[str, FileChange], dict[str, str]]:
    """Réécrit chaque fichier touché par ``pending`` : ses changements, et la raison de chaque
    fichier qui n'a pas pu l'être."""
    by_path: dict[str, dict[Location, Target]] = {}
    for _, targets in pending:
        for target in targets:
            by_path.setdefault(target.path, {})[target.location] = target
    rewritten = {}
    failed = {}
    for path, targets in by_path.items():
        before = files.text(path)
        try:
            after = _rewrite(path, before, list(targets.values()))
        except Refused as refused:
            failed[path] = str(refused)
            continue
        if after != before:
            diff = unified_diff(path, before, after)
            rewritten[path] = FileChange(path=path, before=before, after=after, diff=diff)
    return rewritten, failed


def _rewrite(path: str, text: str, targets: list[Target]) -> str:
    """``text`` avec ``targets`` (toutes de ``path``) appliquées de la fin vers le début, puis
    relu (``_verify``)."""
    ordered = sorted(targets, key=lambda t: (t.location.line, t.location.column))
    for first, second in itertools.pairwise(ordered):
        if (
            first.location.line == second.location.line
            and second.location.column < first.location.end_column
        ):
            raise Refused(f"{path} : deux réécritures se chevauchent ligne {second.location.line}.")
    line_starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
    after = text
    for target in reversed(ordered):
        start = line_starts[target.location.line - 1] + target.location.column
        end = start + target.location.end_column - target.location.column
        after = after[:start] + target.new + after[end:]
    _verify(path, text, after, ordered)
    return after


def _verify(path: str, before: str, after: str, targets: list[Target]) -> None:
    """Relit ``after`` avec le parseur de ``path`` : mêmes déclarations que ``before``, la
    nouvelle contrainte à chaque endroit réécrit, rien d'autre de changé. Lève ``Refused``."""
    reader = _reader(path, next((t.pattern for t in targets if t.pattern), None))
    if reader is None:
        raise Refused(f"{path} : forceupdate ne sait pas relire ce fichier.")
    try:
        old = reader(path, _parsed(before))
    except ParseError as err:
        raise Refused(f"{path} : {err}") from err
    try:
        new = reader(path, _parsed(after))
    except ParseError as err:
        raise Refused(f"{path} : une fois réécrit, il ne se lit plus ({err})") from err
    if [d.identity for d in old] != [d.identity for d in new]:
        raise Refused(f"{path} : une fois réécrit, il ne redonne pas les mêmes dépendances.")
    expected = {target.location: target for target in targets}
    moved = _moved(targets)
    seen = set()
    for was, now in zip(old, new, strict=True):
        target = expected.get(was.location) if was.location is not None else None
        if target is None:
            if now.constraint != was.constraint:
                raise Refused(
                    f"{path} : une fois réécrit, « {was.constraint} » change aussi ; "
                    "rien n'est réécrit."
                )
            continue
        line = target.location.line
        if was.constraint != target.old:
            raise Refused(f"{path} : ligne {line}, la contrainte lue n'est pas « {target.old} ».")
        if now.constraint != target.new or now.location != moved[target.location]:
            raise Refused(
                f"{path} : une fois réécrit, il ne redonne pas « {target.new} » ligne {line}."
            )
        seen.add(target.location)
    for target in targets:
        if target.location not in seen:
            raise Refused(
                f"{path} : aucune contrainte n'est lue ligne {target.location.line}, colonne "
                f"{target.location.column + 1}."
            )


def _moved(targets: list[Target]) -> dict[Location, Location]:
    """Où chaque contrainte réécrite se trouve après les réécritures (``targets`` triées) : plus
    loin sur sa ligne si une réécriture avant elle a changé de longueur."""
    moved = {}
    shifts: dict[int, int] = {}
    for target in targets:
        location = target.location
        shift = shifts.get(location.line, 0)
        column = location.column + shift
        moved[location] = Location(
            line=location.line, column=column, end_column=column + len(target.new)
        )
        width = location.end_column - location.column
        shifts[location.line] = shift + len(target.new) - width
    return moved


def _reader(path: str, pattern: str | None = None) -> Reader | None:
    """Le parseur qui relit ``path`` (au format ``pattern`` s'il est donné) ; ``None`` pour un
    fichier qu'on ne sait pas relire."""
    if posixpath.basename(path) == npm.PNPM_WORKSPACE:
        return npm.read_pnpm_workspace
    return _READERS.get(_pattern(path, pattern) or "")


def _pattern(path: str, pattern: str | None) -> str | None:
    """Le motif de ``detect.manifests`` dont ``path`` suit le format : ``pattern`` s'il est
    donné, sinon celui que reconnaît son nom."""
    if pattern is not None:
        return pattern
    match = match_dependency_file(path)
    return None if match is None else match.pattern


def _parsed(text: str) -> str:
    """``text`` comme le voient les parseurs : ``LocalSource`` lit les fichiers en
    convertissant les fins de ligne. Les emplacements ne changent pas : un ``\\r`` n'est
    jamais qu'en fin de ligne."""
    return text.replace("\r\n", "\n")


# ---------------------------------------------------------------------------
# Fichiers
# ---------------------------------------------------------------------------


class _Files:
    """Les fichiers de la source, lus une fois, tels quels."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._texts: dict[str, str | Refused] = {}

    def text(self, path: str) -> str:
        """Le contenu de ``path``, relatif à la racine. Lève ``Refused`` s'il ne peut pas être
        réécrit."""
        if path not in self._texts:
            try:
                self._texts[path] = _read(self.root, path)
            except Refused as refused:
                self._texts[path] = refused
        found = self._texts[path]
        if isinstance(found, Refused):
            raise found
        return found

    def parsed_text(self, path: str) -> str | None:
        """Le contenu de ``path`` tel que le voient les parseurs (``ReadText``) ; ``None`` s'il
        n'existe pas. Lève ``Refused`` s'il existe mais ne peut pas être réécrit."""
        if not (self.root / path).is_file():
            return None
        return _parsed(self.text(path))


def _read(root: Path, path: str) -> str:
    """Le contenu de ``path`` tel quel, fins de ligne comprises. Lève ``Refused``."""
    full = root / path
    try:
        inside = full.resolve().is_relative_to(root.resolve())
    except OSError:
        inside = False
    if not inside:
        raise Refused(f"{path} : hors du dossier analysé.")
    if full.is_symlink():
        raise Refused(f"{path} : lien symbolique, pas réécrit.")
    try:
        data = full.read_bytes()
    except FileNotFoundError as err:
        raise Refused(f"{path} : introuvable.") from err
    except OSError as err:
        raise Refused(f"{path} : illisible ({err.strerror or err}).") from err
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise Refused(f"{path} : pas en UTF-8, pas réécrit.") from err
    if "\r" in text.replace("\r\n", ""):
        raise Refused(f"{path} : fins de ligne « \\r » seules, pas réécrit.")
    return text


def replace_file(path: Path, data: bytes) -> None:
    """Écrit ``data`` dans ``path`` d'un coup : un fichier temporaire à côté, qui le remplace.
    Les droits du fichier sont gardés."""
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".forceupdate"
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
