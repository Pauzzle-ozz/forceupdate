"""git, pour cloner un dépôt d'une forge et y pousser une branche (E18).

Adapté de ``sechunter/core/repo/git_client.py`` d'Argos :

- **le token n'est jamais dans les arguments** de git (donc ni dans la liste des processus, ni
  dans un message) : un *credential helper* éphémère, passé par ``-c``, le lit dans
  l'environnement du seul processus git (``FORCEUPDATE_GIT_PASSWORD``) ; seul le nom de la
  variable est dans les arguments. ``-c credential.helper=`` vide d'abord la liste des helpers
  configurés : le gestionnaire d'identification de Windows ne garde donc pas le token ;
- **jamais dans une adresse** : l'adresse est sans identifiants (refusée sinon), git ne l'écrit
  donc pas dans ``.git/config`` ;
- toute sortie de git rapportée passe par ``redact`` (le token, et toute adresse
  ``user:secret@``) ;
- **sans** ``target_validator`` : on ne parle qu'à des forges connues, l'adresse est construite
  par la forge (``forges.github``), jamais donnée par la personne.

Le clone est superficiel (``--depth 1``), d'une seule branche (la branche par défaut), sans
étiquettes, sans sous-modules et sans les fichiers LFS. La configuration de la personne est
gardée (proxy, certificats), sauf ce qui changerait le résultat : fins de ligne converties
(``core.autocrlf``), hooks, signature des commits. Le commit a pour auteur le compte du token.

``Workspace`` est le dossier de travail temporaire d'une mise à jour, effacé à la sortie
(adapté de ``workspace.py`` d'Argos).
"""

import enum
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from forceupdate.forges.base import ForgeError

logger = logging.getLogger(__name__)

CLONE_TIMEOUT = 600.0
"""Délai maximal d'un clone ou d'un push, en secondes."""
LOCAL_TIMEOUT = 60.0
"""Délai maximal d'une commande sans réseau (commit, état), en secondes."""

USERNAME_VARIABLE = "FORCEUPDATE_GIT_USERNAME"
PASSWORD_VARIABLE = "FORCEUPDATE_GIT_PASSWORD"

_HELPER = (
    '!f() { test "$1" = get && '
    f'printf "username=%s\\npassword=%s\\n" "${USERNAME_VARIABLE}" "${PASSWORD_VARIABLE}"; '
    "}; f"
)
"""Le credential helper : git le lance par ``sh`` (celui de Git pour Windows aussi), et ne lui
demande les identifiants (``get``) qu'au moment de parler à la forge."""

_CONFIG = (
    "core.autocrlf=false",  # le contenu tel qu'il est dans le dépôt, fins de ligne comprises
    "core.eol=lf",
    "core.longpaths=true",  # Windows : sinon « Filename too long » au-delà de 260 caractères
    "core.fsmonitor=false",
    "core.hooksPath=.forceupdate-sans-hooks",  # aucun hook de la personne sur ce clone
    "commit.gpgsign=false",
    "advice.detachedHead=false",
    "gc.auto=0",
)
"""Imposé à chaque commande, par-dessus la configuration de la personne."""

_DROPPED_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_DATE",
        USERNAME_VARIABLE,
        PASSWORD_VARIABLE,
    }
)
"""Ce qui, hérité de l'environnement (d'un hook, d'un autre git), ferait viser un autre dépôt
à git, lui ferait demander un mot de passe, ou changerait l'auteur du commit."""

_ADDED_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_LFS_SKIP_SMUDGE": "1",
    "LC_ALL": "C",  # les messages de git en anglais : ``_diagnose`` les reconnaît
    "LANGUAGE": "C",
}

_SECRET_IN_URL = re.compile(r"([a-z][a-z0-9+.-]*://[^/@\s:]+):[^@/\s]+@", re.IGNORECASE)


class GitFailure(enum.StrEnum):
    """Ce qui a fait échouer git, d'après ce qu'il a dit."""

    MISSING = "missing"
    """git n'est pas installé."""
    AUTH = "auth"
    """La forge refuse le token."""
    DENIED = "denied"
    """Le token n'a pas le droit (403, droit d'écriture absent)."""
    NOT_FOUND = "not_found"
    """Dépôt ou branche introuvable."""
    PROTECTED = "protected"
    """La branche est protégée, ou une règle du dépôt refuse le push."""
    STALE = "stale"
    """La branche distante a bougé depuis qu'on l'a regardée (``--force-with-lease``)."""
    NETWORK = "network"
    TIMEOUT = "timeout"
    OTHER = "other"


class GitError(ForgeError):
    """git a échoué. Le message, en français, dit ce qui s'est passé ; il ne contient jamais le
    token. ``output`` : ce que git a dit, masqué."""

    def __init__(self, message: str, *, failure: GitFailure, output: str = "") -> None:
        super().__init__(message)
        self.failure = failure
        self.output = output


@dataclass(frozen=True)
class Credentials:
    """Ce que git présente à la forge : un nom (``x-access-token`` sur GitHub) et le token."""

    username: str
    password: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class Author:
    """L'auteur d'un commit : le compte du token."""

    name: str
    email: str


def available() -> bool:
    """git est installé."""
    return _which("git") is not None


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """``text`` sans les secrets : chaque valeur de ``secrets``, et le mot de passe de toute
    adresse ``https://nom:secret@…``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return _SECRET_IN_URL.sub(r"\1:***@", text)


def clone(
    url: str,
    destination: Path,
    *,
    branch: str,
    credentials: Credentials | None,
    depth: int = 1,
) -> str:
    """Clone la branche ``branch`` de ``url`` dans ``destination`` (absent, ou vide), sur
    ``depth`` commits ; rend le commit obtenu. Lève ``GitError``."""
    _check_url(url)
    if destination.exists() and any(destination.iterdir()):
        raise GitError(
            f"Le dossier du clone n'est pas vide : {destination}.", failure=GitFailure.OTHER
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    arguments = ["clone", "--no-tags", "--single-branch", "--no-recurse-submodules"]
    arguments += ["--depth", str(depth), "--branch", branch, "--", url, str(destination)]
    _git(arguments, credentials=credentials, timeout=CLONE_TIMEOUT, action="cloner")
    return head(destination)


def head(checkout: Path) -> str:
    """Le commit de ``HEAD``."""
    return _git(["rev-parse", "HEAD"], cwd=checkout, action="lire le commit").strip()


def tree(checkout: Path) -> str:
    """L'arbre de ``HEAD`` : deux commits au même contenu ont le même."""
    return _git(["rev-parse", "HEAD^{tree}"], cwd=checkout, action="lire l'arbre").strip()


def remote_tree(
    checkout: Path, url: str, branch: str, *, credentials: Credentials | None
) -> str | None:
    """L'arbre du dernier commit de la branche ``branch`` de ``url``, lu par un ``fetch``
    superficiel dans le clone (``HEAD`` et les fichiers n'en changent pas) ; ``None`` si elle
    n'existe pas. Pour une forge dont l'API ne donne pas l'arbre d'un commit (Bitbucket)."""
    _check_url(url)
    arguments = ["fetch", "--no-tags", "--no-recurse-submodules", "--depth", "1"]
    arguments += ["--", url, f"refs/heads/{branch}"]
    try:
        _git(
            arguments,
            cwd=checkout,
            credentials=credentials,
            timeout=CLONE_TIMEOUT,
            action="lire la branche",
        )
    except GitError as err:
        if err.failure is GitFailure.NOT_FOUND:
            return None
        raise
    return _git(["rev-parse", "FETCH_HEAD^{tree}"], cwd=checkout, action="lire l'arbre").strip()


def commit(checkout: Path, paths: Iterable[str], message: str, *, author: Author) -> str | None:
    """Ajoute ``paths`` (relatifs, au format POSIX) et en fait un commit sur ``HEAD``, au nom de
    ``author`` ; rend le commit, ou ``None`` si aucun n'a changé (rien n'est commité)."""
    wanted = sorted(dict.fromkeys(paths))
    if not wanted:
        return None
    _git(["--literal-pathspecs", "add", "--", *wanted], cwd=checkout, action="ajouter")
    staged = _git(
        ["diff", "--cached", "--name-only", "-z"], cwd=checkout, action="lire l'index"
    ).strip("\0")
    if not staged:
        return None
    env = {
        "GIT_AUTHOR_NAME": author.name,
        "GIT_AUTHOR_EMAIL": author.email,
        "GIT_COMMITTER_NAME": author.name,
        "GIT_COMMITTER_EMAIL": author.email,
    }
    _git(
        ["commit", "--no-verify", "--quiet", "--cleanup=verbatim", "--file=-"],
        cwd=checkout,
        env=env,
        stdin=message.encode("utf-8"),
        action="commiter",
    )
    return head(checkout)


def push(
    checkout: Path,
    url: str,
    branch: str,
    *,
    credentials: Credentials | None,
    expected: str | None,
) -> None:
    """Pousse ``HEAD`` du clone sur la branche ``branch`` de ``url``, en la remplaçant si
    elle pointe toujours sur ``expected`` (``None`` : elle ne doit pas exister). Si quelqu'un
    l'a changée entre-temps, rien n'est poussé (``GitFailure.STALE``)."""
    _check_url(url)
    ref = f"refs/heads/{branch}"
    lease = f"--force-with-lease={ref}:{expected or ''}"
    arguments = ["push", "--no-verify", "--porcelain", lease, "--", url, f"HEAD:{ref}"]
    _git(
        arguments,
        cwd=checkout,
        credentials=credentials,
        timeout=CLONE_TIMEOUT,
        action="pousser la branche",
    )


class Workspace:
    """Un dossier de travail temporaire, effacé à la sortie, réussite ou échec (adapté de
    ``RepoWorkspace`` d'Argos). Effacer plusieurs fois ne fait rien de plus."""

    def __init__(self, prefix: str = "forceupdate-pr-") -> None:
        self.path = Path(tempfile.mkdtemp(prefix=prefix))
        self.cleaned = False

    def cleanup(self) -> None:
        """Efface le dossier. Un échec est noté, sans lever : on est dans un ``finally``."""
        if self.cleaned:
            return
        try:
            remove_tree(self.path)
        except OSError as err:
            logger.warning("dossier de travail pas entièrement effacé (%s) : %s", self.path, err)
            return
        self.cleaned = True

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()


def remove_tree(path: Path) -> None:
    """Efface ``path`` et son contenu. Sous Windows, git écrit ses objets en lecture seule :
    ``shutil.rmtree`` seul échouerait sur eux."""
    if not path.exists():
        return

    def writable(function: Callable[..., Any], target: str, *_: object) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:  # pragma: no cover - Python 3.11
        shutil.rmtree(path, onerror=writable)


# -- lancer git -------------------------------------------------------------------------


def _git(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    credentials: Credentials | None = None,
    env: dict[str, str] | None = None,
    stdin: bytes | None = None,
    timeout: float = LOCAL_TIMEOUT,
    action: str,
) -> str:
    """La sortie de ``git arguments`` ; lève ``GitError`` si git échoue, avec ce qu'il a dit,
    masqué."""
    program = _which("git")
    if program is None:
        raise GitError(
            "git n'est pas installé : il faut git pour cloner.", failure=GitFailure.MISSING
        )
    command = [program]
    for setting in _CONFIG:
        command += ["-c", setting]
    environment = _environment()
    secrets: tuple[str, ...] = ()
    if credentials is not None:
        command += ["-c", "credential.helper=", "-c", f"credential.helper={_HELPER}"]
        environment[USERNAME_VARIABLE] = credentials.username
        environment[PASSWORD_VARIABLE] = credentials.password
        secrets = (credentials.password,)
    else:
        command += ["-c", "credential.helper="]
    environment.update(env or {})
    command += arguments
    try:
        result = _spawn(
            command,
            cwd=cwd,
            env=environment,
            input=stdin if stdin is not None else b"",
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise GitError(
            f"git n'a pas pu {action} : délai dépassé ({timeout:.0f} s).",
            failure=GitFailure.TIMEOUT,
        ) from None
    except OSError as err:
        raise GitError(
            f"git n'a pas pu être lancé ({err.strerror or err}).", failure=GitFailure.MISSING
        ) from None
    finally:
        environment.pop(PASSWORD_VARIABLE, None)
    output = redact(_decode(result.stdout), secrets)
    if result.returncode != 0:
        # ``push --porcelain`` dit ses refus sur la sortie standard.
        said = "\n".join(
            text
            for text in (redact(_decode(result.stderr), secrets).strip(), output.strip())
            if text
        )
        failure = _diagnose(said)
        detail = _last_lines(said)
        message = f"git n'a pas pu {action} : {_REASONS[failure]}"
        if detail:
            message += f" Ce que git a dit : {detail}"
        raise GitError(message, failure=failure, output=said)
    return output


_REASONS = {
    GitFailure.AUTH: "la forge refuse le token.",
    GitFailure.DENIED: "le token n'a pas le droit d'écrire dans ce dépôt.",
    GitFailure.NOT_FOUND: "dépôt ou branche introuvable.",
    GitFailure.PROTECTED: "la branche est protégée, ou une règle du dépôt refuse le push.",
    GitFailure.STALE: "la branche a été changée sur la forge entre-temps ; rien n'est poussé.",
    GitFailure.NETWORK: "la forge ne répond pas (réseau, DNS, certificat).",
    GitFailure.OTHER: "erreur de git.",
}

_PATTERNS = (
    (GitFailure.STALE, r"stale info|\(fetch first\)|non-fast-forward"),
    (
        GitFailure.PROTECTED,
        r"protected branch|GH006|GH013|repository rule violations|pre-receive hook declined",
    ),
    (
        GitFailure.AUTH,
        r"authentication failed|could not read (username|password)|invalid username or "
        r"(password|token)|returned error: 401|terminal prompts disabled",
    ),
    (
        GitFailure.DENIED,
        r"returned error: 403|permission to .* denied|write access to repository not granted"
        r"|access denied",
    ),
    (
        GitFailure.NOT_FOUND,
        r"repository .*not found|returned error: 404|does not appear to be a git repository"
        r"|remote branch .* not found|couldn't find remote ref",
    ),
    (
        GitFailure.NETWORK,
        r"could not resolve host|connection (refused|timed out|reset)|failed to connect"
        r"|tls|ssl|certificate|unable to access",
    ),
)


def _diagnose(stderr: str) -> GitFailure:
    """Ce qui a fait échouer git, d'après sa sortie d'erreur (en anglais : ``LC_ALL=C``)."""
    for failure, pattern in _PATTERNS:
        if re.search(pattern, stderr, re.IGNORECASE):
            return failure
    return GitFailure.OTHER


def _last_lines(text: str, count: int = 3) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[-count:])[:500]


def _check_url(url: str) -> None:
    """Une adresse sans identifiants : sinon git les écrirait dans ``.git/config``."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        raise GitError(
            "Adresse de dépôt refusée : elle porte des identifiants.", failure=GitFailure.OTHER
        )


def _environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() not in _DROPPED_ENV}
    env.update(_ADDED_ENV)
    return env


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def _which(program: str) -> str | None:
    """L'exécutable de ``program`` sur le ``PATH``."""
    return shutil.which(program)


def _spawn(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
    """``subprocess.run``, sans shell. Les tests le surveillent : jamais d'adresse réseau hors
    des tests ``network``."""
    return subprocess.run(command, shell=False, check=False, **options)
