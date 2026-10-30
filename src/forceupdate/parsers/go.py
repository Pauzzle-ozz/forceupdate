"""Les parseurs Go : ``go.mod``, ``go.work``, et le lien avec les workspaces.

Fichier lu : ``go.mod``, ses directives, en ligne (``require x v1.2.3``) ou en bloc
(``require ( … )``), comme les lit ``golang.org/x/mod/modfile`` (le paquet dont se sert ``go``) :
des identifiants séparés par des espaces, des chaînes ``"…"`` ou ```…```, des commentaires
``//``.

- ``require`` : une dépendance par module, à sa version. ``// indirect`` en fin de ligne dit
  qu'aucun paquet du module n'importe le module : ``direct=False``, mais elle a un emplacement,
  et c'est là qu'elle se réécrit ;
- ``replace old [v] => new [v]`` : vers un chemin local (``./…``, ``../…``, absolu), la
  dépendance n'est pas vérifiable ; vers un module à une version, c'est lui qui est utilisé, donc
  vérifié, et c'est la version du ``replace`` qui se réécrit. Un ``replace`` à version ne vaut que
  pour cette version du ``require`` ;
- ``exclude`` : des versions écartées, jamais proposées (``Dependency.excluded``) ;
- ``retract`` : les versions que le module lui-même retire. Elles ne concernent que ceux qui
  l'utilisent : lues pour le ``go.mod`` d'une dépendance, que donne le proxy (``registries.
  goproxy``), avec la dépréciation (``// Deprecated:`` avant ou après ``module``) ;
- ``go``, ``toolchain``, ``godebug``, ``tool``, ``ignore`` : lus, sans dépendance (la version de Go
  relève de E27).

**La version installée est celle de go.mod** (``versions.go``) : depuis Go 1.17, ``go mod tidy``
y écrit la version choisie de chaque module qui fournit un paquet au module, indirectes
comprises. ``go.sum`` n'en est pas une source : il garde les empreintes de modules qui ne
fournissent aucun paquet (``gopkg.in/check.v1`` d'un test de ``yaml.v3``, vérifié avec Go 1.27).
Avant Go 1.17 (ou sans directive ``go``), les indirectes ne sont pas toutes listées : le rapport
le dit. Le lockfile d'une dépendance est le ``go.sum`` du module : ``go mod tidy`` le refait.

**Workspaces.** ``go.work`` (``use``, ``replace``) : un module est membre du workspace quand le
``go.work`` le plus proche, en remontant depuis son dossier, le cite dans ``use``. Ce que le module
requiert d'un autre membre est pris dans le workspace : non vérifiable. Un ``replace`` de
``go.work`` l'emporte sur ceux des modules ; sa version se réécrit dans ``go.work``, sans rien
régénérer : ``go mod tidy`` ignore le workspace, et le prochain ``go build`` du workspace complète
``go.work.sum``. Dans un workspace, ``go`` construit avec la plus haute des versions que demandent
ses membres : celle d'un ``go.mod`` peut être plus basse.

Repris de ``reference/argos_sca_parsers.py`` (L857-892), puis réécrit : un vrai lexer à la place
des expressions régulières, ``Dependency`` au lieu de ``SCAComponent``, emplacements, ``//
indirect``, ``replace``, ``exclude``, ``retract``, dépréciation, workspaces, et un fichier
invalide signalé (``ParseError``) au lieu d'une liste vide. ``parse_go_sum`` n'est pas repris :
``go.sum`` n'est plus une source de versions.
"""

import ast
import dataclasses
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project
from forceupdate.parsers.base import REASON_LOCAL, REASON_WORKSPACE, ParseError, ReadText
from forceupdate.parsers.lockfiles import LockedPackage, Lockfile, dirname, join

logger = logging.getLogger(__name__)

MANIFEST = "go.mod"
LOCKFILE = "go.sum"
WORKSPACE = "go.work"

PRUNED_SINCE = (1, 17)
"""Depuis Go 1.17, ``go.mod`` liste chaque module qui fournit un paquet, indirectes comprises."""

_DEPRECATED = re.compile(r"(?s)(?:^|\n\n)Deprecated: *(.*?)(?:$|\n\n)")
"""Le paragraphe ``Deprecated:`` d'un commentaire, comme le cherche ``modfile``."""

_GO_VERSION = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)")


# ---------------------------------------------------------------------------
# Le lexer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    """Un mot d'une ligne : un identifiant, une chaîne (sans ses guillemets) ou une ponctuation."""

    text: str
    column: int
    """Le début du texte (dans les guillemets pour une chaîne)."""
    end_column: int
    exact: bool = True
    """Faux pour une chaîne à échappements : son texte n'est pas celui du fichier."""
    punctuation: bool = False


@dataclass(frozen=True)
class _Line:
    """Une ligne de directive : ses mots, et les commentaires qui l'accompagnent."""

    number: int
    tokens: tuple[_Token, ...]
    suffix: str | None
    """Le commentaire en fin de ligne, sans ``//`` ; ``None`` s'il n'y en a pas."""
    before: tuple[str, ...]
    """Les lignes de commentaire juste au-dessus, sans ``//`` (une vide : un paragraphe)."""
    verb: str | None = None
    """La directive du bloc pour une ligne d'un bloc (``require``) ; ``None`` hors bloc."""
    block: "_Line | None" = None
    """La ligne qui ouvre son bloc : ses commentaires valent pour les lignes qui n'en ont pas."""

    def comments(self) -> list[str]:
        """Ses commentaires, comme ``parseDirectiveComment`` de ``modfile`` : ceux de la ligne,
        sinon ceux de son bloc."""
        if not self.before and self.suffix is None and self.block is not None:
            return self.block.comments()
        return [*self.before, *([self.suffix.strip()] if self.suffix is not None else [])]


def _is_ident(char: str) -> bool:
    return char not in " ()[]{}," and char.isprintable() and not char.isspace()


def _tokens(text: str, number: int) -> tuple[list[_Token], str | None]:
    """Les mots de la ligne ``text`` et son commentaire de fin. Lève ``ParseError``."""
    tokens: list[_Token] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif text.startswith("//", index):
            return tokens, text[index + 2 :]
        elif char in "()[],":
            tokens.append(_Token(char, index, index + 1, punctuation=True))
            index += 1
        elif text.startswith("=>", index):
            tokens.append(_Token("=>", index, index + 2, punctuation=True))
            index += 2
        elif char in '"`':
            end = _string_end(text, index)
            if end is None:
                raise ParseError(f"ligne {number} : chaîne jamais fermée.")
            raw = text[index : end + 1]
            body = raw[1:-1]
            exact = char == "`" or "\\" not in body
            if not exact:
                try:
                    body = ast.literal_eval(raw)
                except (SyntaxError, ValueError) as err:
                    raise ParseError(f"ligne {number} : chaîne illisible ({raw}).") from err
            tokens.append(_Token(body, index + 1, end, exact=exact))
            index = end + 1
        elif _is_ident(char):
            start = index
            while index < len(text) and _is_ident(text[index]) and not text.startswith("//", index):
                index += 1
            tokens.append(_Token(text[start:index], start, index))
        else:
            raise ParseError(f"ligne {number} : caractère inattendu « {char} ».")
    return tokens, None


def _string_end(text: str, start: int) -> int | None:
    """La position du guillemet qui ferme la chaîne ouverte en ``start``."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        if quote == '"' and text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index
        index += 1
    return None


def _lines(content: str) -> Iterator[_Line]:
    """Les lignes de directive de ``content``, celles des blocs avec leur directive. Lève
    ``ParseError`` pour un bloc jamais fermé ou un mot illisible."""
    comments: list[str] = []
    block: _Line | None = None
    for number, raw in enumerate(content.split("\n"), start=1):
        text = raw.removesuffix("\r")
        tokens, suffix = _tokens(text, number)
        if not tokens:
            if suffix is not None:
                comments.append(suffix.strip())
            else:
                comments = []  # une ligne vide sépare les commentaires de ce qui suit
            continue
        before = tuple(comments)
        comments = []
        if block is not None:
            if [t.text for t in tokens] == [")"]:
                block = None
                continue
            yield _Line(number, tuple(tokens), suffix, before, verb=block.verb, block=block)
            continue
        if len(tokens) >= 2 and tokens[1].text == "(" and tokens[1].punctuation:
            opened = _Line(number, (tokens[0],), suffix, before, verb=tokens[0].text)
            if [t.text for t in tokens[2:]] == [")"]:
                continue  # « require () » : un bloc vide
            if len(tokens) > 2:
                raise ParseError(f"ligne {number} : rien n'est permis après « ( ».")
            block = opened
            continue
        yield _Line(number, tuple(tokens), suffix, before)
    if block is not None:
        raise ParseError(f"bloc « {block.verb} ( » de la ligne {block.number} jamais fermé.")


# ---------------------------------------------------------------------------
# go.mod
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Requirement:
    """Un ``require`` : un module à une version."""

    path: str
    version: str
    location: Location | None
    """Celui de la version ; ``None`` pour une chaîne à échappements."""
    indirect: bool = False
    line: int


@dataclass(frozen=True, kw_only=True)
class Replacement:
    """Un ``replace`` : ``old [old_version] => new [new_version]``."""

    old_path: str
    old_version: str | None
    new_path: str
    new_version: str | None
    """``None`` pour un chemin local."""
    location: Location | None
    """Celui de ``new_version``."""
    file: str
    line: int

    @property
    def local(self) -> bool:
        return self.new_version is None

    def applies(self, path: str, version: str) -> bool:
        return self.old_path == path and self.old_version in (None, version)


@dataclass(frozen=True, kw_only=True)
class Retraction:
    """Un ``retract`` : une version, ou un intervalle ``[low, high]``, et sa raison."""

    low: str
    high: str
    rationale: str


@dataclass(kw_only=True)
class GoMod:
    """Un ``go.mod`` (ou un ``go.work``) lu."""

    path: str
    module: str | None = None
    deprecated: str | None = None
    """Le message de ``// Deprecated:`` sur la directive ``module`` ; ``None`` sans."""
    go: str | None = None
    toolchain: str | None = None
    requires: list[Requirement] = field(default_factory=list)
    replaces: list[Replacement] = field(default_factory=list)
    excludes: list[tuple[str, str]] = field(default_factory=list)
    retracts: list[Retraction] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)
    """``go.work`` : les dossiers des modules du workspace, tels qu'écrits."""
    notices: list[Notice] = field(default_factory=list)

    @property
    def pruned(self) -> bool:
        """Vrai si ``go.mod`` liste toutes les indirectes (``go 1.17`` ou plus)."""
        found = _GO_VERSION.match(self.go or "")
        return found is not None and (int(found["major"]), int(found["minor"])) >= PRUNED_SINCE

    def excluded(self, path: str) -> tuple[str, ...]:
        return tuple(version for excluded, version in self.excludes if excluded == path)


_VERBS = frozenset(
    {"module", "go", "toolchain", "godebug", "require", "exclude", "replace", "retract", "tool"}
    | {"ignore", "use"}
)


def parse_go_mod_file(path: str, content: str) -> GoMod:
    """Le ``go.mod`` ou le ``go.work`` ``path`` lu. Une directive illisible donne une remarque
    (``GoMod.notices``) ; lève ``ParseError`` pour un fichier qu'on ne sait pas découper (bloc
    jamais fermé, chaîne jamais fermée)."""
    parsed = GoMod(path=path)
    for line in _lines(content):
        try:
            _directive(parsed, line)
        except ValueError as err:
            parsed.notices.append(Notice(file=path, message=f"ligne {line.number} : {err}"))
    return parsed


def _directive(parsed: GoMod, line: _Line) -> None:
    tokens = list(line.tokens)
    if line.verb is None:
        verb, tokens = tokens[0].text, tokens[1:]
    else:
        verb = line.verb
    if verb not in _VERBS:
        raise ValueError(f"directive « {verb} » inconnue, ignorée.")
    words = [t.text for t in tokens]
    if verb == "module":
        _expect(words, 1, verb)
        parsed.module = words[0]
        message = _DEPRECATED.search("\n".join(line.comments()))
        parsed.deprecated = (message.group(1).strip() or None) if message else None
    elif verb in ("go", "toolchain"):
        _expect(words, 1, verb)
        setattr(parsed, verb, words[0])
    elif verb == "require":
        _expect(words, 2, verb)
        parsed.requires.append(
            Requirement(
                path=words[0],
                version=words[1],
                location=_location(line.number, tokens[1]),
                indirect=_indirect(line.suffix),
                line=line.number,
            )
        )
    elif verb == "exclude":
        _expect(words, 2, verb)
        parsed.excludes.append((words[0], words[1]))
    elif verb == "replace":
        parsed.replaces.append(_replacement(parsed.path, line.number, tokens))
    elif verb == "retract":
        parsed.retracts.append(_retraction(words, line))
    elif verb == "use":
        _expect(words, 1, verb)
        parsed.uses.append(words[0])


def _expect(words: Sequence[str], count: int, verb: str) -> None:
    if len(words) != count:
        raise ValueError(f"« {verb} » illisible ({' '.join(words) or 'vide'}), ignoré.")


def _location(number: int, token: _Token) -> Location | None:
    if not token.exact:
        return None
    return Location(line=number, column=token.column, end_column=token.end_column)


def _indirect(suffix: str | None) -> bool:
    """``// indirect``, ou ``// indirect; …`` : comme ``isIndirect`` de ``modfile``."""
    if suffix is None:
        return False
    words = suffix.split()
    return (len(words) == 1 and words[0] == "indirect") or (
        len(words) > 1 and words[0] == "indirect;"
    )


def _replacement(path: str, number: int, tokens: Sequence[_Token]) -> Replacement:
    words = [t.text for t in tokens]
    if "=>" not in words:
        raise ValueError(f"« replace » sans « => » ({' '.join(words)}), ignoré.")
    arrow = words.index("=>")
    old, new = words[:arrow], tokens[arrow + 1 :]
    if len(old) not in (1, 2) or len(new) not in (1, 2):
        raise ValueError(f"« replace » illisible ({' '.join(words)}), ignoré.")
    target = new[0].text
    if is_directory_path(target) != (len(new) == 1):
        raise ValueError(
            f"« replace » illisible ({' '.join(words)}) : un chemin local n'a pas de version, "
            "un module en a une."
        )
    return Replacement(
        old_path=old[0],
        old_version=old[1] if len(old) == 2 else None,
        new_path=target,
        new_version=new[1].text if len(new) == 2 else None,
        location=_location(number, new[1]) if len(new) == 2 else None,
        file=path,
        line=number,
    )


def _retraction(words: Sequence[str], line: _Line) -> Retraction:
    rationale = "\n".join(line.comments()).strip()
    if len(words) == 1:
        return Retraction(low=words[0], high=words[0], rationale=rationale)
    if len(words) == 5 and words[0] == "[" and words[2] == "," and words[4] == "]":
        return Retraction(low=words[1], high=words[3], rationale=rationale)
    raise ValueError(f"« retract » illisible ({' '.join(words)}), ignoré.")


def is_directory_path(path: str) -> bool:
    """Vrai si la cible d'un ``replace`` est un dossier : ``IsDirectoryPath`` de ``modfile``,
    qui reconnaît les chemins Unix et Windows."""
    return (
        path in (".", "..")
        or path.startswith(("./", ".\\", "../", "..\\", "/", "\\"))
        or (len(path) >= 2 and path[0].isascii() and path[0].isalpha() and path[1] == ":")
    )


def parse_go_mod(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``go.mod``, ses directes puis ses indirectes, dans l'ordre du
    fichier, avec ses propres ``replace``. Lève ``ParseError`` si le fichier ne se découpe pas."""
    parsed = parse_go_mod_file(path, content)
    return _dependencies(parsed, _Context(lockfile=join(dirname(path), LOCKFILE)))


@dataclass(frozen=True, kw_only=True)
class _Context:
    """Ce qui vaut autour d'un ``go.mod`` : son ``go.sum``, et son workspace s'il en a un."""

    lockfile: str
    workspace: GoMod | None = None
    members: frozenset[str] = frozenset()
    """Les chemins des modules du workspace."""


def _dependencies(parsed: GoMod, context: _Context) -> list[Dependency]:
    directs, indirects = [], []
    for requirement in parsed.requires:
        dependency = _dependency(parsed, requirement, context)
        (indirects if requirement.indirect else directs).append(dependency)
    return directs + indirects


def _dependency(parsed: GoMod, requirement: Requirement, context: _Context) -> Dependency:
    base = Dependency(
        ecosystem=Ecosystem.GO,
        name=requirement.path,
        constraint=requirement.version,
        installed=requirement.version,
        lockfile=context.lockfile,
        direct=not requirement.indirect,
        file=parsed.path,
        location=requirement.location,
        excluded=parsed.excluded(requirement.path),
    )
    replacement = _replacement_of(requirement, parsed, context.workspace)
    if replacement is not None and replacement.local:
        return dataclasses.replace(
            base, installed=None, lockfile=None, excluded=(), unverifiable_reason=REASON_LOCAL
        )
    if requirement.path in context.members:
        return dataclasses.replace(
            base, installed=None, lockfile=None, excluded=(), unverifiable_reason=REASON_WORKSPACE
        )
    if replacement is None:
        return base
    assert replacement.new_version is not None
    in_workspace = context.workspace is not None and replacement.file == context.workspace.path
    return dataclasses.replace(
        base,
        name=replacement.new_path,
        constraint=replacement.new_version,
        installed=replacement.new_version,
        # go mod tidy ignore go.work : rien à y régénérer, le prochain go build du workspace
        # complète go.work.sum (vérifié avec Go 1.27).
        lockfile=None if in_workspace else base.lockfile,
        file=replacement.file,
        location=replacement.location,
        excluded=(),
    )


def _replacement_of(
    requirement: Requirement, parsed: GoMod, workspace: GoMod | None
) -> Replacement | None:
    """Le ``replace`` qui vaut pour ``requirement`` : celui de ``go.work``, puis celui du
    ``go.mod`` ; à version de préférence."""
    for source in (workspace, parsed):
        if source is None:
            continue
        found = [r for r in source.replaces if r.applies(requirement.path, requirement.version)]
        if found:
            return min(found, key=lambda r: r.old_version is None)
    return None


def locked_versions(path: str, content: str) -> Lockfile:
    """Les modules d'un ``go.mod`` à leur version utilisée (après ses ``replace``), comme un
    lockfile : ce que ``update.lockfiles`` relit après ``go mod tidy``. Lève ``ParseError``."""
    dependencies = parse_go_mod(path, content)
    packages = tuple(
        LockedPackage(name=d.name, version=d.installed or "")
        for d in dependencies
        if d.installed is not None
    )
    return Lockfile(path=path, ecosystem=Ecosystem.GO, packages=packages)


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def parse_project(project: Project, read_text: ReadText) -> None:
    """Lit le ``go.mod`` de ``project`` et remplit ses dépendances : les directes, puis les
    indirectes (``// indirect``), dans l'ordre du fichier. Un ``go.work`` seul n'en donne pas : ses
    modules sont des projets à part."""
    manifest = next((p for p in project.manifests if _is(p, MANIFEST)), None)
    if manifest is None:
        return
    content = _read(read_text, manifest)
    if content is None:
        project.notices.append(
            Notice(file=manifest, message="introuvable, illisible ou trop gros : pas lu.")
        )
        return
    try:
        parsed = parse_go_mod_file(manifest, content)
    except ParseError as err:
        project.notices.append(Notice(file=manifest, message=str(err)))
        return
    project.notices.extend(parsed.notices)
    workspace = _workspace(project.path, read_text)
    members = _members(workspace, read_text) if workspace is not None else frozenset()
    context = _Context(
        lockfile=join(project.path, LOCKFILE),
        workspace=workspace,
        members=members - {parsed.module},
    )
    dependencies = _dependencies(parsed, context)
    project.dependencies.extend(dependencies)
    if dependencies and not parsed.pruned:
        written = f"go {parsed.go}" if parsed.go else "sans directive go"
        project.notices.append(
            Notice(
                file=manifest,
                message=(
                    f"{written} : avant Go 1.17, go.mod ne liste pas toutes les dépendances "
                    "indirectes, qui ne sont donc pas toutes vérifiées."
                ),
            )
        )


def _read(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _workspace(directory: str, read_text: ReadText) -> GoMod | None:
    """Le ``go.work`` dont le module de ``directory`` est membre : le plus proche en remontant
    (``go`` s'arrête au premier), s'il le cite dans ``use``. ``None`` sinon."""
    for candidate in [directory, *_ancestors(directory)]:
        path = join(candidate, WORKSPACE)
        content = _read(read_text, path)
        if content is None:
            continue
        try:
            workspace = parse_go_mod_file(path, content)
        except ParseError:
            return None  # la remarque vient avec le projet du go.work
        uses = {_normalize(join(candidate, use)) for use in workspace.uses}
        return workspace if directory in uses else None
    return None


def _members(workspace: GoMod, read_text: ReadText) -> frozenset[str]:
    """Les chemins des modules du workspace, lus dans le ``go.mod`` de chaque dossier ``use``."""
    found = set()
    root = dirname(workspace.path)
    for use in workspace.uses:
        folder = _normalize(join(root, use))
        if folder is None:
            continue
        content = _read(read_text, join(folder, MANIFEST))
        if content is None:
            continue
        try:
            module = parse_go_mod_file(join(folder, MANIFEST), content).module
        except ParseError:
            continue
        if module is not None:
            found.add(module)
    return frozenset(found)


def _ancestors(directory: str) -> list[str]:
    """Les dossiers parents de ``directory``, du plus proche à la racine ``.``."""
    if directory == ".":
        return []
    parts = directory.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + ["."]


def _normalize(path: str) -> str | None:
    """``path`` sans ``.`` ni ``..`` ; ``None`` s'il sort de la source."""
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or "."


def _is(path: str, pattern: str) -> bool:
    match = match_dependency_file(path)
    return match is not None and match.ecosystem is Ecosystem.GO and match.pattern == pattern
