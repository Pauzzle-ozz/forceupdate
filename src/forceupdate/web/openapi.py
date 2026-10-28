"""Le schéma OpenAPI de l'API, exporté dans ``web/openapi.json`` : les types du front en sont
tirés (E14). Le serveur ne le sert pas.

Pour le refaire après un changement de l'API ou des modèles (un test vérifie qu'il est à
jour) ::

    uv run python -m forceupdate.web.openapi

FastAPI le tire des dataclasses (``models``, ``report.json.Document``, ``web.schemas``). Une
retouche : un champ qui a une valeur par défaut y serait facultatif, alors que les réponses
portent toujours tous leurs champs (``models.to_dict``). Tous les champs des objets que rendent
les réponses (2xx) sont donc marqués requis ; un type ne doit pas servir à la fois en entrée et
en sortie.
"""

import copy
import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from forceupdate.web.app import Settings, create_app

OPENAPI_JSON = Path(__file__).parent / "openapi.json"

_REF = "#/components/schemas/"


def document(app: FastAPI | None = None) -> dict[str, Any]:
    """Le schéma de ``app`` (par défaut, l'application de ``forceupdate ui``), retouché."""
    if app is None:
        app = create_app(Settings(token="", port=0, state_dir=Path()))
    schema = copy.deepcopy(app.openapi())
    components = schema.get("components", {}).get("schemas", {})
    inputs = _reachable(_request_schemas(schema), components)
    outputs = _reachable(_response_schemas(schema), components)
    shared = inputs & outputs
    if shared:
        raise ValueError(f"types à la fois en entrée et en sortie : {', '.join(sorted(shared))}")
    for name in sorted(outputs):
        properties = components[name].get("properties")
        if properties:
            components[name]["required"] = list(properties)
    return schema


def render(app: FastAPI | None = None) -> str:
    return json.dumps(document(app), ensure_ascii=False, indent=2) + "\n"


def _operations(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in schema.get("paths", {}).values():
        yield from item.values()


def _request_schemas(schema: dict[str, Any]) -> Iterator[Any]:
    for operation in _operations(schema):
        yield operation.get("requestBody", {})
        yield operation.get("parameters", [])


def _response_schemas(schema: dict[str, Any]) -> Iterator[Any]:
    for operation in _operations(schema):
        for status, response in operation.get("responses", {}).items():
            if str(status).startswith("2"):
                yield response


def _reachable(roots: Iterable[Any], components: dict[str, Any]) -> set[str]:
    """Les composants que citent ``roots``, de proche en proche."""
    found: set[str] = set()
    pending = [ref for root in roots for ref in _refs(root)]
    while pending:
        name = pending.pop()
        if name not in found:
            found.add(name)
            pending.extend(_refs(components[name]))
    return found


def _refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF):
            yield ref.removeprefix(_REF)
        for item in value.values():
            yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def main() -> None:
    OPENAPI_JSON.write_text(render(), encoding="utf-8", newline="\n")
    sys.stdout.write(f"{OPENAPI_JSON}\n")


if __name__ == "__main__":
    main()
