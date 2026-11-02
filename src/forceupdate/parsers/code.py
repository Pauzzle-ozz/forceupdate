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
  chemin (``./util``, ``/abs``), un import interne (``#lib``), un alias (``@/…``, ``~/…``) ou
  une adresse (``https:``, ``npm:``, ``jsr:``…) ;
- **Go** : sans la bibliothèque standard (un chemin dont le premier élément n'a pas de point :
  ``fmt``, ``net/http``) ni ``C`` (cgo). Un import est rattaché à son module à la vérification :
  le plus long préfixe que le proxy connaît (``golang.org/x/text/language`` →
  ``golang.org/x/text``), comme le fait ``go mod tidy`` (``candidates``).

Un import facultatif (dans un ``try``) est ``optional`` ; un import pour les annotations de types
seulement (``if TYPE_CHECKING:``, ``import type``), ``dev``.
"""

import posixpath
import re
import sys
from collections.abc import Iterable

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
    if ecosystem is Ecosystem.PYPI:
        pairs = _python_packages(path, python_imports(content), read_text)
    elif ecosystem is Ecosystem.NPM:
        pairs = [(name, item) for item in js_imports(content) if (name := npm_package(item.module))]
    elif ecosystem is Ecosystem.GO:
        pairs = [
            (item.module, item) for item in go_imports(content) if is_go_module_path(item.module)
        ]
    else:
        raise ValueError(f"imports non lus pour {ecosystem}")
    grouped: dict[str, list[Import]] = {}
    for name, item in pairs:
        grouped.setdefault(name, []).append(item)
    return [
        Dependency(
            ecosystem=ecosystem,
            name=name,
            scope=_scope(items),
            file=path,
            imported=items[0].module,
        )
        for name, items in grouped.items()
    ]


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
