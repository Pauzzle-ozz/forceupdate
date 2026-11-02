"""Les dépendances d'un fichier de code choisi seul, sans projet autour (E28).

Un script Python à bloc PEP 723 a un vrai manifeste : son bloc (``parsers.python``), avec ses
contraintes, réécrivable. Sinon, ce sont ses imports (``parsers.imports``), sans version :

- **Python** : sans la bibliothèque standard (``sys.stdlib_module_names``, plus les modules
  retirés depuis 3.11 : ``distutils``, ``imp``, ceux de la PEP 594), ni un module posé à côté du
  fichier (``util.py``, ``util/__init__.py``). Le nom du paquet vient de ``IMPORT_PACKAGES``
  quand il diffère de l'import (``yaml`` → ``PyYAML``, ``cv2`` → ``opencv-python``) ; sinon c'est
  l'import. Sous un espace de noms partagé (``NAMESPACES`` : ``google.cloud.storage``,
  ``azure.storage.blob``), le paquet est le plus long des noms possibles que PyPI connaît
  (``google-cloud-storage``), cherché à la vérification (``candidates``) ;
- **JavaScript, TypeScript** : le paquet d'un import (``lodash/fp`` → ``lodash``, ``@scope/a/b``
  → ``@scope/a``), sans ``node:`` ni les modules intégrés de Node (``NODE_BUILTINS``), ni un
  chemin (``./util``, ``/abs``), un import interne (``#lib``), un alias (``@/…``, ``~/…``, et
  depuis E34 les ``paths`` du ``tsconfig.json`` le plus proche, ou un module sous son
  ``baseUrl`` : ``src/utils``) ou une adresse (``https:``…). Les imports de Deno (E34) :
  ``npm:express@4.18.2`` est le paquet npm ``express``, avec sa contrainte (``4.18.2``, à
  réécrire à la main) ; ``jsr:@std/assert`` vient du registre JSR, que forceupdate ne lit pas
  (non vérifiable) ;
- **Go** : sans la bibliothèque standard (un chemin dont le premier élément n'a pas de point :
  ``fmt``, ``net/http``) ni ``C`` (cgo). Un import est rattaché à son module à la vérification :
  le plus long préfixe que le proxy connaît (``golang.org/x/text/language`` →
  ``golang.org/x/text``), comme le fait ``go mod tidy`` (``candidates``).

Un import facultatif (dans un ``try``) est ``optional`` ; un import pour les annotations de types
seulement (``if TYPE_CHECKING:``, ``import type``), ``dev``. ``importlib.import_module("x")`` et
``__import__("x")`` d'un nom écrit en clair sont des imports (E34).

**D'autres fichiers** (E34) : un carnet Jupyter (``.ipynb``), par ses cellules de code (les lignes
``%magie`` et ``!commande`` sautées, une cellule qui ne se lit pas aussi) ; un ``.vue`` ou un
``.svelte``, par ses ``<script>``.
"""

import json
import posixpath
import re
import sys
from collections.abc import Callable, Iterable
from typing import Any

from packaging.utils import canonicalize_name

from forceupdate.detect.code import read_alone
from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Notice, Project, Scope
from forceupdate.parsers import python
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.imports import Import, go_imports, js_imports, python_imports

PYTHON_REMOVED = frozenset(
    {
        # Python 3.12
        "asynchat",
        "asyncore",
        "distutils",
        "imp",
        "smtpd",
        # Python 3.13 (PEP 594), et lib2to3
        "aifc",
        "audioop",
        "cgi",
        "cgitb",
        "chunk",
        "crypt",
        "imghdr",
        "lib2to3",
        "mailcap",
        "msilib",
        "nis",
        "nntplib",
        "ossaudiodev",
        "pipes",
        "sndhdr",
        "spwd",
        "sunau",
        "telnetlib",
        "uu",
        "xdrlib",
    }
)
"""Des modules de la bibliothèque standard de Python 3.11, retirés depuis : un script qui les
importe vise un Python plus ancien, ce ne sont pas des paquets."""

PYTHON_STDLIB = frozenset(sys.stdlib_module_names) | PYTHON_REMOVED

IMPORT_PACKAGES: dict[str, str] = {
    "_pytest": "pytest",
    "absl": "absl-py",
    "argon2": "argon2-cffi",
    "attr": "attrs",
    "barcode": "python-barcode",
    "Bio": "biopython",
    "bluetooth": "PyBluez",
    "bs4": "beautifulsoup4",
    "bson": "pymongo",
    "cairo": "pycairo",
    "can": "python-can",
    "consul": "python-consul",
    "corsheaders": "django-cors-headers",
    "crispy_forms": "django-crispy-forms",
    "crontab": "python-crontab",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodomex",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dbus": "dbus-python",
    "debug_toolbar": "django-debug-toolbar",
    "discord": "discord.py",
    "django_filters": "django-filter",
    "dns": "dnspython",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "engineio": "python-engineio",
    "environ": "django-environ",
    "factory": "factory-boy",
    "faiss": "faiss-cpu",
    "fitz": "PyMuPDF",
    "frontmatter": "python-frontmatter",
    "gflags": "python-gflags",
    "gi": "PyGObject",
    "git": "GitPython",
    "github": "PyGithub",
    "gitlab": "python-gitlab",
    "google.oauth2": "google-auth",
    "google.protobuf": "protobuf",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "googleapiclient": "google-api-python-client",
    "gridfs": "pymongo",
    "grpc": "grpcio",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "kafka": "kafka-python",
    "ldap": "python-ldap",
    "magic": "python-magic",
    "memcache": "python-memcached",
    "mpl_toolkits": "matplotlib",
    "multipart": "python-multipart",
    "MySQLdb": "mysqlclient",
    "mysql": "mysql-connector-python",
    "nacl": "PyNaCl",
    "nats": "nats-py",
    "newspaper": "newspaper3k",
    "nmap": "python-nmap",
    "OpenGL": "PyOpenGL",
    "OpenSSL": "pyOpenSSL",
    "osgeo": "GDAL",
    "paho": "paho-mqtt",
    "past": "future",
    "PIL": "Pillow",
    "pkg_resources": "setuptools",
    "pptx": "python-pptx",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "pyximport": "Cython",
    "rest_framework": "djangorestframework",
    "RPi": "RPi.GPIO",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "slugify": "python-slugify",
    "socketio": "python-socketio",
    "socks": "PySocks",
    "speech_recognition": "SpeechRecognition",
    "stomp": "stomp.py",
    "strawberry": "strawberry-graphql",
    "telebot": "pyTelegramBotAPI",
    "telegram": "python-telegram-bot",
    "umap": "umap-learn",
    "usb": "pyusb",
    "vcr": "vcrpy",
    "websocket": "websocket-client",
    "whois": "python-whois",
    "win32api": "pywin32",
    "win32clipboard": "pywin32",
    "win32com": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "wx": "wxPython",
    "Xlib": "python-xlib",
    "xdg": "pyxdg",
    "yaml": "PyYAML",
    "zmq": "pyzmq",
}
"""Import → paquet PyPI, quand le nom du paquet n'est pas celui de l'import. Une clé à points
(``google.protobuf``) vaut pour ce module et ce qui est dessous ; la plus longue l'emporte."""

NAMESPACES = frozenset(
    {"azure", "backports", "google", "jaraco", "plone", "ruamel", "sphinxcontrib", "z3c", "zope"}
)
"""Des espaces de noms que se partagent plusieurs paquets PyPI, chacun nommé d'après son module :
``google.cloud.storage`` vient de ``google-cloud-storage``, ``zope.interface`` de
``zope.interface``."""

NODE_BUILTINS = frozenset(
    {
        "_http_agent",
        "_http_client",
        "_http_common",
        "_http_incoming",
        "_http_outgoing",
        "_http_server",
        "_stream_duplex",
        "_stream_passthrough",
        "_stream_readable",
        "_stream_transform",
        "_stream_wrap",
        "_stream_writable",
        "_tls_common",
        "_tls_wrap",
        "assert",
        "assert/strict",
        "async_hooks",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "dns/promises",
        "domain",
        "events",
        "fs",
        "fs/promises",
        "http",
        "http2",
        "https",
        "inspector",
        "inspector/promises",
        "module",
        "net",
        "os",
        "path",
        "path/posix",
        "path/win32",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "readline/promises",
        "repl",
        "stream",
        "stream/consumers",
        "stream/promises",
        "stream/web",
        "string_decoder",
        "sys",
        "timers",
        "timers/promises",
        "tls",
        "trace_events",
        "tty",
        "url",
        "util",
        "util/types",
        "v8",
        "vm",
        "wasi",
        "worker_threads",
        "zlib",
    }
)
"""Les modules intégrés de Node qui se chargent sans ``node:`` :
``require('module').builtinModules`` de Node 24.12, vérifié le 2026-11-02. Les autres
(``node:sea``, ``node:sqlite``, ``node:test``, ``node:test/reporters``) n'existent qu'avec
``node:`` : un ``test`` nu est le paquet npm."""

_NPM_NAME = re.compile(r"^(?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*$", re.IGNORECASE)
"""Un nom de paquet npm, ancien compris (des majuscules, comme ``JSONStream``)."""
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

_GO_HOSTS = {"github.com": 3, "gitlab.com": 3, "bitbucket.org": 3, "golang.org": 3}
"""Les hébergeurs dont un module a au moins trois éléments (``github.com/propriétaire/dépôt``,
``golang.org/x/text``) : les préfixes plus courts ne sont pas demandés au proxy."""


def parse_project(project: Project, read_text: ReadText) -> None:
    """Les dépendances des fichiers de code de ``project`` (ceux de ses manifestes qui n'en sont
    pas : un projet fait d'un fichier de code seul, ``engine.inventory``). Un script Python à
    bloc PEP 723 est lu par ``parsers.python`` ; les autres, par leurs imports."""
    for path in project.manifests:
        if match_dependency_file(path) is not None:
            continue
        try:
            content = read_text(path)
        except ValueError:
            content = None
        if content is None:
            project.notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
            continue
        if python.is_script(path) and python.has_script_block(content):
            python.parse_project(project, read_text)
            continue
        ecosystem = read_alone(path)
        if ecosystem is None:
            project.notices.append(
                Notice(
                    file=path,
                    message=(
                        "forceupdate ne lit pas les imports d'un tel fichier seul : choisir "
                        "son projet (le dossier de son manifeste)."
                    ),
                )
            )
            continue
        try:
            project.dependencies.extend(imported(path, content, ecosystem, read_text))
        except ParseError as err:
            project.notices.append(Notice(file=path, message=str(err)))


def imported(
    path: str, content: str, ecosystem: Ecosystem, read_text: ReadText | None = None
) -> list[Dependency]:
    """Les dépendances qu'importe le fichier ``path`` : un paquet une fois, à l'endroit de son
    premier import ; facultative ou de développement seulement si tous ses imports le sont.
    ``read_text`` dit les modules posés à côté du fichier (Python). Lève ``ParseError`` pour un
    fichier qui ne se lit pas."""
    suffix = posixpath.splitext(path)[1].lower()
    if ecosystem is Ecosystem.PYPI and suffix == ".ipynb":
        pairs = _python_packages(path, notebook_imports(content), read_text)
    elif ecosystem is Ecosystem.PYPI:
        pairs = _python_packages(path, python_imports(content), read_text)
    elif ecosystem is Ecosystem.NPM:
        script = component_scripts(content) if suffix in (".vue", ".svelte") else content
        aliases = _TsConfig.nearest(path, read_text)
        found: list[tuple[str, Import]] = []
        specified: dict[str, Dependency] = {}
        for item in js_imports(script):
            if item.module.startswith(("npm:", "jsr:")):
                dependency = _deno(path, item)
                if dependency is not None:
                    specified.setdefault(dependency.name, dependency)
                continue
            name = npm_package(item.module)
            if name is not None and not aliases.local(item.module):
                found.append((name, item))
        pairs = found
    elif ecosystem is Ecosystem.GO:
        pairs = [
            (item.module, item) for item in go_imports(content) if is_go_module_path(item.module)
        ]
    else:
        raise ValueError(f"imports non lus pour {ecosystem}")
    grouped: dict[str, list[Import]] = {}
    for name, item in pairs:
        grouped.setdefault(name, []).append(item)
    dependencies = [
        Dependency(
            ecosystem=ecosystem,
            name=name,
            scope=_scope(items),
            file=path,
            imported=items[0].module,
        )
        for name, items in grouped.items()
    ]
    if ecosystem is Ecosystem.NPM:
        dependencies += [d for name, d in specified.items() if name not in grouped]
    return dependencies


# -- Jupyter, Vue, Svelte (E34) --------------------------------------------------------------


def notebook_imports(content: str) -> list[Import]:
    """Les imports des cellules de code d'un carnet Jupyter, leurs lignes comptées de la première
    cellule à la dernière. Une ligne ``%magie`` ou ``!commande`` est sautée ; une cellule
    ``%%magie`` aussi, et une cellule qui ne se lit pas comme du Python. Lève ``ParseError`` pour
    un fichier qui n'est pas un carnet."""
    try:
        data = json.loads(content)
    except ValueError as error:
        raise ParseError(f"pas un carnet Jupyter (JSON illisible : {error}).") from error
    cells = data.get("cells") if isinstance(data, dict) else None
    if not isinstance(cells, list):
        raise ParseError("pas un carnet Jupyter (pas de « cells »).")
    found: list[Import] = []
    offset = 0
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source")
        text = "".join(source) if isinstance(source, list) else str(source or "")
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("%%"):
            offset += len(lines)
            continue
        kept = "\n".join("" if line.lstrip().startswith(("%", "!")) else line for line in lines)
        try:
            imports = python_imports(kept)
        except ParseError:
            imports = []
        found += [item._replace(line=item.line + offset) for item in imports]
        offset += len(lines)
    return found


_SCRIPT = re.compile(r"(<script\b[^>]*>)(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)


def component_scripts(content: str) -> str:
    """Les ``<script>`` d'un composant ``.vue`` ou ``.svelte`` (``<script setup lang="ts">``,
    ``<script context="module">``), le reste remplacé par des lignes vides : les lignes restent
    celles du fichier."""
    kept = []
    position = 0
    for match in _SCRIPT.finditer(content):
        start = match.start(2)
        kept.append("\n" * content.count("\n", position, start))
        kept.append(match.group(2))
        position = match.end(2)
    return "".join(kept)


# -- Deno (E34) ------------------------------------------------------------------------------

REASON_JSR = "vient du registre JSR (jsr:), que forceupdate ne lit pas"
_DENO_NPM = re.compile(r"^npm:/?(?P<name>(?:@[^/@]+/)?[^/@]+)(?:@(?P<version>[^/]+))?(?:/.*)?$")
_DENO_JSR = re.compile(r"^jsr:/?(?P<name>@[^/@]+/[^/@]+)(?:@(?P<version>[^/]+))?(?:/.*)?$")


def _deno(path: str, item: Import) -> Dependency | None:
    """La dépendance d'un import Deno : ``npm:nom@version``, ou ``jsr:@portée/nom@version`` (non
    vérifiable) ; ``None`` pour un spécificateur illisible."""
    npm = _DENO_NPM.match(item.module)
    if npm is not None and _NPM_NAME.match(npm["name"]):
        return Dependency(
            ecosystem=Ecosystem.NPM,
            name=npm["name"],
            constraint=npm["version"] or "",
            scope=_scope([item]),
            file=path,
            imported=item.module,
        )
    jsr = _DENO_JSR.match(item.module)
    if jsr is not None:
        return Dependency(
            ecosystem=Ecosystem.NPM,
            name=f"jsr:{jsr['name']}",
            constraint=jsr["version"] or "",
            scope=_scope([item]),
            file=path,
            imported=item.module,
            unverifiable_reason=REASON_JSR,
        )
    return None


# -- tsconfig.json (E34) ---------------------------------------------------------------------

_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")


class _TsConfig:
    """Les alias d'un ``tsconfig.json`` (ou ``jsconfig.json``) : ``compilerOptions.paths`` (des
    motifs : ``@app/*``, ``utils``) et ``baseUrl`` (un module sous ce dossier : ``src/utils``).
    Son ``extends`` n'est pas suivi."""

    def __init__(
        self, folder: str = ".", data: Any = None, read_text: ReadText | None = None
    ) -> None:
        options = data.get("compilerOptions") if isinstance(data, dict) else None
        options = options if isinstance(options, dict) else {}
        paths = options.get("paths")
        self.patterns = [p for p in paths if isinstance(p, str)] if isinstance(paths, dict) else []
        base = options.get("baseUrl")
        self.base = (
            posixpath.normpath(posixpath.join(folder, base)) if isinstance(base, str) else None
        )
        self.read_text = read_text

    @classmethod
    def nearest(cls, path: str, read_text: ReadText | None) -> "_TsConfig":
        """Celui du dossier de ``path`` ou d'au-dessus, dans la source ; sans alias s'il n'y en a
        pas."""
        if read_text is None:
            return cls()
        folder = posixpath.dirname(path) or "."
        while True:
            for name in ("tsconfig.json", "jsconfig.json"):
                text = _read(read_text, posixpath.join(folder, name) if folder != "." else name)
                if text is not None:
                    return cls(folder, _jsonc(text), read_text)
            if folder in (".", ""):
                return cls()
            folder = posixpath.dirname(folder) or "."

    def local(self, specifier: str) -> bool:
        for pattern in self.patterns:
            prefix, star, _ = pattern.partition("*")
            if (star and specifier.startswith(prefix)) or specifier == pattern:
                return True
        if self.base is None or self.read_text is None:
            return False
        stem = posixpath.normpath(posixpath.join(self.base, specifier))
        if stem.startswith(".."):
            return False
        candidates = [f"{stem}{e}" for e in _EXTENSIONS] + [f"{stem}/index{e}" for e in _EXTENSIONS]
        return any(_read(self.read_text, c.removeprefix("./")) is not None for c in candidates)


def _read(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _jsonc(text: str) -> Any:
    """Un JSON avec commentaires (``//``, ``/* */``) et virgules finales, comme un
    ``tsconfig.json`` ; ``None`` s'il ne se lit pas."""
    out = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\":
                out.append(text[index + 1 : index + 2])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
        elif text.startswith("//", index):
            index = text.find("\n", index)
            index = len(text) if index < 0 else index
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        out.append(char)
        index += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    try:
        return json.loads(cleaned)
    except ValueError:
        return None


def _scope(items: list[Import]) -> Scope:
    if all(item.types_only for item in items):
        return Scope.DEV
    if all(item.optional for item in items):
        return Scope.OPTIONAL
    return Scope.RUNTIME


# -- Python ----------------------------------------------------------------------------------


def _python_modules(item: Import) -> list[str]:
    """Les modules qui désignent un paquet : le premier niveau (``yaml``, ``PIL``) ; sous un
    espace de noms, le module complet, avec les noms importés qui peuvent être des sous-modules
    (en minuscules : ``from google.cloud import storage, bigquery`` donne ``google.cloud.storage``
    et ``google.cloud.bigquery`` ; ``from azure.identity import DefaultAzureCredential``,
    ``azure.identity``)."""
    top = item.module.split(".", 1)[0]
    if top not in NAMESPACES:
        return [top]
    subs = [name for name in item.names if name.islower()] if item.module.count(".") < 2 else []
    return [f"{item.module}.{name}" for name in subs] or [item.module]


def _python_packages(
    path: str, imports: Iterable[Import], read_text: ReadText | None
) -> list[tuple[str, Import]]:
    directory = posixpath.dirname(path)
    local: dict[str, bool] = {}
    pairs = []
    for item in imports:
        top = item.module.split(".", 1)[0]
        if top in PYTHON_STDLIB or top == "__main__":
            continue
        if top not in local:
            local[top] = read_text is not None and _beside(directory, top, read_text)
        if local[top]:
            continue
        pairs += [
            (python_package(module), item._replace(module=module))
            for module in _python_modules(item)
        ]
    return pairs


def without_local_namespaces(
    project: Project, path: str, is_directory: Callable[[str], bool]
) -> None:
    """Retire de ``project`` les imports Python d'un paquet d'espace de noms posé à côté du
    fichier de code ``path`` (E34) : un dossier sans ``__init__.py``, que Python importe comme un
    paquet (PEP 420) ; ``_beside`` ne voit que ``module.py`` et ``module/__init__.py``."""
    directory = posixpath.dirname(path)
    kept = []
    for dependency in project.dependencies:
        imported = dependency.imported
        if (
            dependency.ecosystem is Ecosystem.PYPI
            and imported is not None
            and dependency.file == path
        ):
            top = imported.split(".", 1)[0]
            if is_directory(posixpath.join(directory, top) if directory else top):
                continue
        kept.append(dependency)
    project.dependencies = kept


def _beside(directory: str, module: str, read_text: ReadText) -> bool:
    """Vrai si ``module`` est un module posé à côté du fichier : ``module.py``, ou un paquet
    ``module/__init__.py``."""
    for name in (f"{module}.py", f"{module}/__init__.py"):
        try:
            if read_text(posixpath.join(directory, name)) is not None:
                return True
        except ValueError:
            continue
    return False


def python_package(module: str) -> str:
    """Le paquet PyPI (normalisé) le plus probable pour un module importé : celui de
    ``IMPORT_PACKAGES`` (la plus longue clé qui le couvre), sinon son propre nom ; sous un espace
    de noms, le module complet (``google.cloud.storage`` → ``google-cloud-storage``)."""
    parts = module.split(".")
    for length in range(len(parts), 0, -1):
        known = IMPORT_PACKAGES.get(".".join(parts[:length]))
        if known is not None:
            return canonicalize_name(known)
    if parts[0] in NAMESPACES:
        return canonicalize_name(module.replace("_", "-"))
    return canonicalize_name(parts[0])


# -- JavaScript ------------------------------------------------------------------------------


def npm_package(specifier: str) -> str | None:
    """Le paquet npm d'un import (``lodash/fp`` → ``lodash``, ``@scope/a/b`` → ``@scope/a``) ;
    ``None`` pour un module intégré de Node, un chemin, un import interne, un alias ou une
    adresse (voir la docstring du module)."""
    bare = specifier.split("?", 1)[0]
    if not bare or bare.startswith((".", "/", "#", "~", "\\")) or _SCHEME.match(bare):
        return None
    if bare in NODE_BUILTINS:
        return None  # « punycode/ », avec sa barre, est le paquet npm
    parts = bare.split("/")
    name = "/".join(parts[:2]) if bare.startswith("@") else parts[0]
    return name if _NPM_NAME.match(name) else None


# -- Go --------------------------------------------------------------------------------------


def is_go_module_path(path: str) -> bool:
    """Vrai pour l'import d'un module (``golang.org/x/text/language``), pas de la bibliothèque
    standard (``fmt``, ``net/http`` : un premier élément sans point), ni de cgo (``C``), ni un
    chemin relatif."""
    first = path.split("/", 1)[0]
    return "." in first and not path.startswith((".", "/"))


def go_candidates(path: str) -> list[str]:
    """Les modules qui peuvent fournir l'import ``path``, du plus long au plus court : ses
    préfixes, au moins trois éléments chez les hébergeurs de ``_GO_HOSTS``."""
    parts = path.split("/")
    shortest = _GO_HOSTS.get(parts[0], 1)
    return ["/".join(parts[:length]) for length in range(len(parts), shortest - 1, -1)]


def candidates(dependency: Dependency) -> list[str]:
    """Les noms à essayer, dans l'ordre, pour une dépendance tirée d'un import dont le paquet
    n'est pas sûr : un module Go (``go_candidates``), un paquet PyPI sous un espace de noms (les
    modules de plus en plus courts, au moins deux éléments). Vide quand le nom est sûr."""
    written = dependency.imported
    if written is None:
        return []
    if dependency.ecosystem is Ecosystem.GO:
        return go_candidates(written)
    if dependency.ecosystem is Ecosystem.PYPI and written.split(".", 1)[0] in NAMESPACES:
        parts = written.split(".")
        names = [python_package(".".join(parts[:length])) for length in range(len(parts), 1, -1)]
        return list(dict.fromkeys(names))
    return []
