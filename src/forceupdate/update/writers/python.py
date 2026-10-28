"""Les manifestes Python : ``requirements*.txt`` et ``.in``, ``pyproject.toml`` (PEP 621,
PEP 735, Poetry, uv, PDM), ``Pipfile`` et ``setup.cfg``.

La réécriture est la même pour tous (``update.writers``) ; seul le parseur qui relit le fichier
change, celui de l'analyse (``parsers.python``).

Une ligne de ``requirements`` qui porte des empreintes (``--hash``) n'est pas réécrite : ce sont
celles de la version actuelle, et pip refuserait d'installer la nouvelle.
"""

import re

from forceupdate.parsers import python
from forceupdate.update.writers.base import (
    Check,
    Declaration,
    Reader,
    Refused,
    Target,
    dependencies,
)

_COMMENT = re.compile(r"(?:^|\s)#")
_HASH = re.compile(r"(?:^|\s)--hash\b")


def _requirements(path: str, content: str) -> list[Declaration]:
    return dependencies(python.parse_requirements_txt(path, content))


def _pyproject(path: str, content: str) -> list[Declaration]:
    return dependencies(python.parse_pyproject_toml(path, content))


def _pipfile(path: str, content: str) -> list[Declaration]:
    return dependencies(python.parse_pipfile(path, content))


def _setup_cfg(path: str, content: str) -> list[Declaration]:
    return dependencies(python.parse_setup_cfg(path, content))


def _no_hashes(path: str, content: str, target: Target) -> None:
    """Refuse de réécrire une ligne logique (continuée par ``\\``) qui a des ``--hash``."""
    lines = content.split("\n")
    index = target.location.line - 1
    parts = [lines[index].removesuffix("\r")]
    while parts[-1].endswith("\\") and index + 1 < len(lines):
        index += 1
        parts.append(lines[index].removesuffix("\r"))
    text = " ".join(part.removesuffix("\\") for part in parts)
    comment = _COMMENT.search(text)
    if comment is not None:
        text = text[: comment.start()]
    if _HASH.search(text):
        raise Refused(
            f"{path} : ligne {target.location.line}, les empreintes (--hash) sont celles de la "
            "version actuelle ; à réécrire à la main, avec celles de la nouvelle."
        )


READERS: dict[str, Reader] = {
    "requirements*.txt": _requirements,
    "requirements*.in": _requirements,
    "requirements/*.txt": _requirements,
    "requirements/*.in": _requirements,
    "pyproject.toml": _pyproject,
    "Pipfile": _pipfile,
    "setup.cfg": _setup_cfg,
}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``)."""

CHECKS: dict[str, Check] = {
    pattern: _no_hashes
    for pattern in (
        "requirements*.txt",
        "requirements*.in",
        "requirements/*.txt",
        "requirements/*.in",
    )
}
"""Ce qui est vérifié en plus avant de réécrire, par motif."""
