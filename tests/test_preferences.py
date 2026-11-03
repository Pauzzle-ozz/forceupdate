"""Les réglages de la personne (E29) : le fichier (``preferences``), la ligne de commande qui les
lit, l'API de l'écran Réglages (``web.routes.settings``) et le cache qu'elle vide. Jamais les
réglages de l'utilisateur : ``user_settings`` est un fichier propre au test."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from forceupdate import preferences
from forceupdate.cli import app
from forceupdate.forges import git
from forceupdate.models import Ecosystem, Gap, SelectionRule
from forceupdate.net import Cache, CacheKind
from forceupdate.preferences import Preferences

Routes = dict[str, respx.Route]
VULNERABLE = Path(__file__).parent / "projects" / "vulnerable"
runner = CliRunner()


# ---------------------------------------------------------------------------
# Le fichier
# ---------------------------------------------------------------------------


def test_without_a_file_the_defaults(user_settings: Path) -> None:
    assert preferences.default_path() == user_settings
    assert preferences.load() == (preferences.DEFAULTS, [])
    assert preferences.DEFAULTS.lock_timeout == 600


def test_no_empty_selection_table(user_settings: Path) -> None:
    """Session 36 : le fichier finissait par une table ``[selection]`` vide."""
    preferences.save(Preferences(ignore=("lodash",)))
    text = user_settings.read_text(encoding="utf-8")
    assert "[selection" not in text
    assert text.endswith("rust-default-toolchain = false\n")
    assert preferences.load() == (Preferences(ignore=("lodash",)), [])


def test_save_then_load(user_settings: Path) -> None:
    value = Preferences(
        ignore=("lodash", "django@>=5", "a\\b"),
        include_tests=True,
        selection=(
            SelectionRule(level=Gap.PATCH, security_only=False),
            SelectionRule(ecosystem=Ecosystem.CRATES_IO, security_only=True),
            SelectionRule(ecosystem=Ecosystem.NPM, level=Gap.MAJOR),
        ),
        excluded_repositories=("github.com/octo/ancien", "gitlab.com/groupe/*"),
        lock_timeout=1200,
        clone_timeout=60,
        rust_default_toolchain=True,
    )
    assert preferences.save(value) == user_settings
    text = user_settings.read_text(encoding="utf-8")
    assert "[selection.cargo]\nsecurity-only = true" in text
    assert 'ignore = ["lodash", "django@>=5", "a\\\\b"]' in text
    assert preferences.load() == (value, [])
    assert not list(user_settings.parent.glob(".forceupdate-*"))  # pas de fichier temporaire


def test_a_wrong_value_gives_the_default_and_says_it(user_settings: Path) -> None:
    user_settings.write_text(
        "\n".join(
            [
                'ignore = ["ok", "deux mots"]',
                'excluded-repositories = ["github.com/octo"]',
                "lock-timeout = 2",
                'clone-timeout = "long"',
                "rust-default-toolchain = 1",
                'exclude = ["legacy"]',
            ]
        ),
        encoding="utf-8",
    )
    value, problems = preferences.load()
    assert value == Preferences(ignore=("ok",))
    assert problems == [
        "forceupdate.toml : ignore[1] : « deux mots » : un nom de paquet sans espace est attendu "
        "(lodash, django@>=5).",
        "forceupdate.toml : exclude : clé inconnue, ignorée.",
        "forceupdate.toml : excluded-repositories[0] : « github.com/octo » : hôte, propriétaire et "
        "dépôt sont attendus (github.com/owner/repo, gitlab.com/groupe/*).",
        "forceupdate.toml : lock-timeout : 2 s : entre 10 et 86400 secondes.",
        "forceupdate.toml : clone-timeout : « 'long' » : un nombre entier de secondes est attendu.",
        "forceupdate.toml : rust-default-toolchain : « 1 » n'est pas true ou false.",
    ]


def test_an_unreadable_file(user_settings: Path) -> None:
    user_settings.write_text("ignore = [", encoding="utf-8")
    value, (problem,) = preferences.load()
    assert value == preferences.DEFAULTS
    assert "TOML invalide" in problem and problem.endswith(": valeurs par défaut.")


def test_excluded_repositories() -> None:
    value = Preferences(excluded_repositories=("github.com/octo/ancien", "gitlab.com/Groupe/*"))
    assert value.excludes("github.com", "octo/ancien")
    assert value.excludes("github.com", "Octo/Ancien")
    assert value.excludes("gitlab.com", "groupe/sous/projet")
    assert not value.excludes("github.com", "octo/ancien-2")
    assert preferences.repository_pattern(" https://github.com/octo/x.git/ ") == "github.com/octo/x"


# ---------------------------------------------------------------------------
# La ligne de commande
# ---------------------------------------------------------------------------


def copy(tmp_path: Path, configuration: str | None = None) -> Path:
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    if configuration is not None:
        (root / "forceupdate.toml").write_text(configuration, encoding="utf-8")
    return root


def test_scan_reads_the_settings(user_settings: Path, tmp_path: Path) -> None:
    preferences.save(Preferences(ignore=("lodash",), include_tests=True))
    root = copy(tmp_path)
    result = runner.invoke(app, ["scan", str(root), "--format", "json", "--offline", "--no-cache"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["options"]["ignore"] == ["lodash"]
    assert document["options"]["include_tests"] is True
    (lodash,) = [
        d for d in document["projects"][0]["dependencies"] if d["name"] == "lodash" and d["direct"]
    ]
    assert lodash["ignored"] == "lodash (réglages)"


def test_unreadable_settings_are_said(user_settings: Path, tmp_path: Path) -> None:
    user_settings.write_text("lock-timeout = 1\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", str(copy(tmp_path)), "--offline", "--no-cache"])
    assert result.exit_code == 0
    assert "forceupdate : réglages : forceupdate.toml : lock-timeout : 1 s" in result.stderr


def test_update_follows_the_project_then_the_settings_then_the_command_line(
    recorded: Routes, tmp_path: Path
) -> None:
    root = copy(tmp_path, '[selection]\nlevel = "patch"\n')
    preferences.save(
        Preferences(selection=(SelectionRule(ecosystem=Ecosystem.NPM, security_only=True),))
    )
    result = runner.invoke(
        app, ["update", str(root), "--dry-run", "--no-cache"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0, result.output
    assert "(--level patch ; npm : --level patch --security-only)" in result.stdout
    asked = runner.invoke(
        app,
        ["update", str(root), "--dry-run", "--no-cache", "--level", "major"],
        env={"COLUMNS": "200"},
    )
    assert "(--level major ; npm : --level major --security-only)" in asked.stdout


# ---------------------------------------------------------------------------
# L'API de l'écran Réglages
# ---------------------------------------------------------------------------


REQUEST: dict[str, Any] = {
    "ignore": ["lodash", "django@>=5"],
    "include_tests": True,
    "selection": [
        {"ecosystem": None, "level": "patch", "security_only": False},
        {"ecosystem": "npm", "level": None, "security_only": True},
    ],
    "excluded_repositories": ["github.com/octo/ancien"],
    "lock_timeout": 900,
    "clone_timeout": 120,
    "rust_default_toolchain": True,
}


def test_get_the_settings(api: TestClient, user_settings: Path) -> None:
    document = api.get("/api/settings").json()
    defaults = {
        "ignore": [],
        "include_tests": False,
        "selection": [],
        "excluded_repositories": [],
        "lock_timeout": 600,
        "clone_timeout": 600,
        "rust_default_toolchain": False,
    }
    assert document["values"] == defaults
    assert document["defaults"] == defaults
    assert document["file"] == user_settings.as_posix()
    assert document["problems"] == []
    assert document["cache"]["entries"] == 0
    assert document["cache"]["enabled"] is True


def test_save_the_settings(api: TestClient, user_settings: Path) -> None:
    response = api.put("/api/settings", json=REQUEST)
    assert response.status_code == 200, response.text
    values = response.json()["values"]
    assert values["selection"] == [
        {"ecosystem": None, "level": "patch", "security_only": False},
        {"ecosystem": "npm", "level": None, "security_only": True},
    ]
    assert values["lock_timeout"] == 900
    saved, problems = preferences.load(user_settings)
    assert not problems
    assert saved.ignore == ("lodash", "django@>=5")
    assert saved.excluded_repositories == ("github.com/octo/ancien",)
    # Le délai du clone vaut tout de suite ; il est remis comme avant à l'arrêt du serveur.
    assert git.CLONE_TIMEOUT == 120.0
    assert api.get("/api/settings").json()["values"] == values


def test_the_clone_timeout_is_put_back_at_shutdown(web_settings: Any, user_settings: Path) -> None:
    from forceupdate.web import create_app

    preferences.save(Preferences(clone_timeout=30))
    before = git.CLONE_TIMEOUT
    with TestClient(create_app(web_settings)):
        assert git.CLONE_TIMEOUT == 30.0
    assert before == git.CLONE_TIMEOUT


def test_refused_settings_say_which_field(api: TestClient, user_settings: Path) -> None:
    body = {
        **REQUEST,
        "ignore": ["ok", "deux mots"],
        "excluded_repositories": ["octo"],
        "lock_timeout": 5,
    }
    response = api.put("/api/settings", json=body)
    assert response.status_code == 400
    rejected = response.json()
    assert rejected["detail"] == "3 valeurs sont refusées : rien n'est enregistré."
    assert [(f["field"], f["index"]) for f in rejected["fields"]] == [
        ("ignore", 1),
        ("excluded_repositories", 0),
        ("lock_timeout", None),
    ]
    assert rejected["fields"][2]["message"] == "5 s : entre 10 et 86400 secondes."
    assert not user_settings.exists()


def test_settings_that_cannot_be_written(
    api: TestClient, user_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(value: Preferences, path: Path | None = None) -> Path:
        raise PermissionError(13, "Accès refusé")

    monkeypatch.setattr(preferences, "save", refuse)
    response = api.put("/api/settings", json=REQUEST)
    assert response.status_code == 409
    assert response.json()["detail"].endswith(": Accès refusé.")


def test_unreadable_settings_are_said_by_the_api(web_settings: Any, user_settings: Path) -> None:
    from forceupdate.web import create_app

    user_settings.write_text("include-tests = 3\n", encoding="utf-8")
    with TestClient(
        create_app(web_settings),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": "Bearer jeton-de-test"},
    ) as client:
        document = client.get("/api/settings").json()
    assert document["problems"] == [
        "forceupdate.toml : include-tests : « 3 » n'est pas true ou false."
    ]


def test_a_scan_takes_the_settings(
    api: TestClient, finished: Any, recorded: Routes, tmp_path: Path
) -> None:
    api.put("/api/settings", json={**REQUEST, "ignore": ["lodash"]})
    root = copy(tmp_path)
    started = api.post("/api/scans", json={"path": str(root)}).json()
    state = finished(f"/api/scans/{started['id']}")
    assert state["options"]["ignore"] == ["lodash"]
    updates = {u["name"]: u for u in state["report"]["projects"][0]["updates"]}
    assert "lodash" not in updates
    assert updates["flask"]["selected"] == "0.12.5"  # correctifs (la règle générale)


def test_clear_the_cache(api: TestClient) -> None:
    cache: Cache = api.app.state.jobs.worker.cache  # type: ignore[attr-defined]
    cache.set(CacheKind.VERSIONS, "https://registry.npmjs.org/lodash", {"versions": []})
    cache.set(CacheKind.LIFECYCLES, "python", {})
    state = api.get("/api/settings").json()["cache"]
    assert state["entries"] == 2
    assert state["size"] > 0
    assert state["oldest"] is not None and state["newest"] is not None
    cleared = api.delete("/api/cache")
    assert cleared.status_code == 200
    assert cleared.json()["entries"] == 0
    assert cleared.json()["oldest"] is None
    assert cache.get(CacheKind.VERSIONS, "https://registry.npmjs.org/lodash") is None


def test_a_disabled_cache(tmp_path: Path) -> None:
    stats = Cache.disabled().stats()
    assert (stats.path, stats.enabled, stats.entries, stats.size) == (None, False, 0, 0)
    cache = Cache(tmp_path / "cache.sqlite3")
    cache.set(CacheKind.VERSIONS, "a", 1)
    cache.clear()
    assert cache.stats().entries == 0
    cache.close()


def test_a_general_rule_that_says_the_defaults_is_dropped(api: TestClient) -> None:
    """« Valeurs par défaut » puis « Enregistrer » : pas de sélection réglée pour rien (un
    rapport dirait sinon « sélection par défaut réglée »)."""
    body = {**REQUEST, "selection": [{"ecosystem": None, "level": "minor", "security_only": False}]}
    assert api.put("/api/settings", json=body).json()["values"]["selection"] == []
    value, _ = preferences.from_table({"selection": {"level": "minor", "npm": {"level": "minor"}}})
    assert value.selection == (SelectionRule(ecosystem=Ecosystem.NPM, level=Gap.MINOR),)
