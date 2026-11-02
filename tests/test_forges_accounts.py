"""Les comptes connectés : le token dans le trousseau (simulé, ``conftest.keychain``), le reste
dans ``accounts.json``, jamais le token (``forges.accounts``)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import keyring.backend
import keyring.core
import keyring.errors
import pytest
import respx
from conftest import MemoryKeyring

from forceupdate.forges import accounts as accounts_module
from forceupdate.forges.accounts import Account, Accounts, AccountsError, ConnectMethod
from forceupdate.forges.base import Access, ForgeKind, Grant, Identity, TokenRefused
from forceupdate.net import HttpClient

TOKEN = "gho_jeton-de-test"
KEY = ("forceupdate", "github:github.com")


def identity(login: str = "octo", access: Access = Access.WRITE) -> Identity:
    return Identity(
        forge=ForgeKind.GITHUB,
        host="github.com",
        login=login,
        name="Octo Cat",
        url=f"https://github.com/{login}",
        access=access,
        scopes=("repo", "read:org") if access is not Access.UNKNOWN else None,
        warnings=(),
    )


@pytest.fixture
def store(tmp_path: Path) -> Accounts:
    return Accounts(tmp_path / "état" / "accounts.json")


class BrokenKeyring(keyring.backend.KeyringBackend):
    """Un trousseau qui ne marche pas (Linux sans Secret Service)."""

    priority = 1  # type: ignore[assignment]

    def get_password(self, service: str, username: str) -> str | None:
        raise keyring.errors.NoKeyringError("pas de trousseau")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise keyring.errors.PasswordSetError("refusé")

    def delete_password(self, service: str, username: str) -> None:
        raise keyring.errors.KeyringError("refusé")


def test_the_token_goes_to_the_keyring_and_never_to_the_file(
    store: Accounts, keychain: MemoryKeyring
) -> None:
    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    assert keychain.passwords == {KEY: TOKEN}
    text = store.path.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert "token" not in json.loads(text)["accounts"][0]
    assert account.login == "octo"
    assert account.method is ConnectMethod.OAUTH
    assert account.problem is None
    assert account.connected_at == account.checked_at
    assert account.connected_at.tzinfo is UTC
    assert store.connected() == [account]
    assert store.get(ForgeKind.GITHUB, "github.com") == account
    assert store.token(ForgeKind.GITHUB, "github.com") == TOKEN
    assert TOKEN not in repr(account)


def test_a_long_token_is_kept_in_parts(store: Accounts, keychain: MemoryKeyring) -> None:
    """Un token d'OAuth de Bitbucket (plus de 2 000 caractères) et son refresh token ne tiennent
    pas dans une entrée du trousseau de Windows (1 280 caractères) : en morceaux."""
    expires = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    grant = Grant(access_token="a" * 2400, refresh_token="r" * 600, expires_at=expires)
    store.save(identity(), grant, ConnectMethod.OAUTH)
    main = keychain.passwords[KEY]
    assert main == "forceupdate-parts:4"
    parts = [keychain.passwords[(KEY[0], f"{KEY[1]}#{n}")] for n in range(1, 5)]
    assert all(len(part) <= accounts_module.MAX_PART for part in parts)
    assert store.grant(ForgeKind.GITHUB, "github.com") == grant
    assert store.connected()[0].login == "octo"

    # Renouvelé, plus court : d'un seul tenant, les morceaux d'avant effacés.
    store.renewed(ForgeKind.GITHUB, "github.com", Grant(access_token="court"))
    assert keychain.passwords == {KEY: "court"}
    # Plus long de nouveau, puis déconnecté : plus rien dans le trousseau.
    store.renewed(ForgeKind.GITHUB, "github.com", Grant(access_token="b" * 1500))
    assert len(keychain.passwords) == 3
    account, token = store.remove(ForgeKind.GITHUB, "github.com")
    assert account is not None and token == "b" * 1500
    assert keychain.passwords == {}


def test_a_missing_part_means_no_token(store: Accounts, keychain: MemoryKeyring) -> None:
    store.save(identity(), "c" * 2500, ConnectMethod.TOKEN)
    del keychain.passwords[(KEY[0], f"{KEY[1]}#2")]
    assert store.token(ForgeKind.GITHUB, "github.com") is None
    assert store.connected() == []


def test_the_file_keeps_everything_but_the_token(store: Accounts) -> None:
    store.save(identity(), TOKEN, ConnectMethod.DEVICE)
    document = json.loads(store.path.read_text(encoding="utf-8"))
    assert document["version"] == 1
    (item,) = document["accounts"]
    assert set(item) == {
        "forge",
        "host",
        "login",
        "name",
        "url",
        "access",
        "scopes",
        "warnings",
        "method",
        "connected_at",
        "checked_at",
        "problem",
    }
    assert (item["forge"], item["method"], item["access"]) == ("github", "device", "write")


def test_an_account_without_its_token_does_not_exist(
    store: Accounts, keychain: MemoryKeyring
) -> None:
    store.save(identity(), TOKEN, ConnectMethod.TOKEN)
    keychain.passwords.clear()  # effacé à la main du trousseau
    assert store.connected() == []
    assert store.get(ForgeKind.GITHUB, "github.com") is None
    assert store.token(ForgeKind.GITHUB, "github.com") is None


def test_connecting_again_replaces_the_account(store: Accounts, keychain: MemoryKeyring) -> None:
    store.save(identity("octo"), TOKEN, ConnectMethod.TOKEN)
    second = store.save(identity("autre"), "gho_autre", ConnectMethod.GH)
    assert store.connected() == [second]
    assert keychain.passwords == {KEY: "gho_autre"}


def test_remove_erases_the_token_and_the_account(store: Accounts, keychain: MemoryKeyring) -> None:
    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    assert store.remove(ForgeKind.GITHUB, "github.com") == (account, TOKEN)
    assert keychain.passwords == {}
    assert store.connected() == []
    assert json.loads(store.path.read_text(encoding="utf-8"))["accounts"] == []
    assert store.remove(ForgeKind.GITHUB, "github.com") == (None, None)


def test_checked_and_refused(store: Accounts) -> None:
    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    refused = store.refused(account, "GitHub refuse le token (401).")
    assert store.connected() == [refused]
    assert refused.problem == "GitHub refuse le token (401)."
    checked = store.checked(refused, identity(access=Access.UNKNOWN))
    assert checked.problem is None
    assert checked.access is Access.UNKNOWN
    assert checked.scopes is None
    assert checked.checked_at >= account.checked_at
    assert checked.connected_at == account.connected_at
    assert store.connected() == [checked]


@pytest.mark.parametrize(
    "content",
    [
        "pas du json",
        "[]",
        '{"accounts": 3}',
        '{"accounts": [{"forge": "inconnue"}, 4, {"login": "x"}]}',
    ],
)
def test_an_unreadable_file_is_ignored(store: Accounts, content: str) -> None:
    store.path.parent.mkdir(parents=True)
    store.path.write_text(content, encoding="utf-8")
    assert store.connected() == []
    store.save(identity(), TOKEN, ConnectMethod.TOKEN)
    assert len(store.connected()) == 1


def test_a_broken_keyring(store: Accounts, monkeypatch: pytest.MonkeyPatch) -> None:
    assert store.unavailable() is None
    monkeypatch.setattr(keyring.core, "_keyring_backend", BrokenKeyring())
    reason = store.unavailable() or ""
    assert "Aucun trousseau du système n'est utilisable" in reason
    # Sous Linux sans Secret Service (E31) : en installer un, ou en choisir un autre (keyring).
    assert "GNOME Keyring" in reason and "PYTHON_KEYRING_BACKEND" in reason
    with pytest.raises(AccountsError, match="refuse de garder le token"):
        store.save(identity(), TOKEN, ConnectMethod.TOKEN)
    assert not store.path.exists()


# -- connect, verify ----------------------------------------------------------------


def run(work):  # type: ignore[no-untyped-def]
    async def main():  # type: ignore[no-untyped-def]
        async with HttpClient() as http:
            return await work(http)

    return asyncio.run(main())


USER = {"login": "octo", "name": None, "html_url": "https://github.com/octo"}


@respx.mock
def test_connect_checks_the_token_then_keeps_it(store: Accounts, keychain: MemoryKeyring) -> None:
    respx.get("https://api.github.com/user").respond(
        200, json=USER, headers={"X-OAuth-Scopes": "repo, read:org"}
    )
    account = run(
        lambda http: accounts_module.connect(
            store, http, ForgeKind.GITHUB, TOKEN, ConnectMethod.TOKEN
        )
    )
    assert isinstance(account, Account)
    assert (account.login, account.name, account.access) == ("octo", None, Access.WRITE)
    assert keychain.passwords == {KEY: TOKEN}


@respx.mock
def test_a_refused_token_is_never_kept(store: Accounts, keychain: MemoryKeyring) -> None:
    respx.get("https://api.github.com/user").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(TokenRefused):
        run(
            lambda http: accounts_module.connect(
                store, http, ForgeKind.GITHUB, TOKEN, ConnectMethod.TOKEN
            )
        )
    assert keychain.passwords == {}
    assert store.connected() == []


@respx.mock
def test_verify_rereads_the_rights(store: Accounts) -> None:
    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    route = respx.get("https://api.github.com/user").respond(
        200, json=USER, headers={"X-OAuth-Scopes": "public_repo"}
    )
    checked = run(lambda http: accounts_module.verify(store, http, account))
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert checked.access is Access.PUBLIC
    assert checked.problem is None
    assert store.connected() == [checked]


@respx.mock
def test_verify_notes_a_refused_token(store: Accounts) -> None:
    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    respx.get("https://api.github.com/user").respond(401, json={})
    checked = run(lambda http: accounts_module.verify(store, http, account))
    assert checked.problem is not None
    assert "GitHub refuse le token (401)" in checked.problem
    assert store.connected() == [checked]


def test_verify_without_the_token(store: Accounts, keychain: MemoryKeyring) -> None:
    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    keychain.passwords.clear()
    with pytest.raises(AccountsError, match="n'est plus dans le trousseau"):
        run(lambda http: accounts_module.verify(store, http, account))


def test_methods_that_belong_to_forceupdate() -> None:
    assert {m for m in ConnectMethod if m.from_app} == {ConnectMethod.OAUTH, ConnectMethod.DEVICE}


def test_dates_are_read_back(store: Accounts) -> None:
    saved = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    (read,) = Accounts(store.path).connected()
    assert read == saved
    assert isinstance(read.connected_at, datetime)


def test_reads_and_writes_at_the_same_time_never_lose_the_account(store: Accounts) -> None:
    """Les routes passent par des threads (``asyncio.to_thread``) : relire les droits (une
    écriture) pendant que l'écran liste les comptes (une lecture) ne doit jamais faire
    disparaître le compte. Sous Windows, lire un fichier pendant son ``os.replace`` échoue."""
    import threading

    account = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    lost: list[int] = []
    errors: list[BaseException] = []

    def write() -> None:
        try:
            for _ in range(100):
                store.checked(account, identity())
        except Exception as err:
            errors.append(err)

    def read() -> None:
        for _ in range(200):
            found = store.connected()
            if len(found) != 1:
                lost.append(len(found))

    threads = [threading.Thread(target=work) for work in (write, write, read, read)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert lost == []
    assert len(store.connected()) == 1


# -- GitLab : plusieurs comptes, tokens qui expirent (E19) ---------------------------------


def gitlab_identity(host: str = "gitlab.com") -> Identity:
    return Identity(
        forge=ForgeKind.GITLAB,
        host=host,
        login="renard",
        name="Renard Roux",
        url=f"https://{host}/renard",
        access=Access.WRITE,
        scopes=("api",),
        warnings=(),
    )


def test_one_account_per_host(store: Accounts, keychain: MemoryKeyring) -> None:
    instance = store.save(gitlab_identity("git.example.com"), "glpat-instance", ConnectMethod.TOKEN)
    online = store.save(gitlab_identity(), "glpat-com", ConnectMethod.TOKEN)
    github = store.save(identity(), TOKEN, ConnectMethod.OAUTH)
    # Par forge, le service en ligne avant les instances.
    assert store.connected() == [github, online, instance]
    assert store.token(ForgeKind.GITLAB, "git.example.com") == "glpat-instance"
    assert store.token(ForgeKind.GITLAB, "gitlab.com") == "glpat-com"
    assert ("forceupdate", "gitlab:git.example.com") in keychain.passwords
    store.remove(ForgeKind.GITLAB, "git.example.com")
    assert store.connected() == [github, online]


def test_a_token_that_expires_is_kept_with_its_refresh_token(
    store: Accounts, keychain: MemoryKeyring
) -> None:
    expires = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    grant = Grant(access_token="glo-acces", refresh_token="glo-refresh", expires_at=expires)
    store.save(gitlab_identity(), grant, ConnectMethod.OAUTH)
    stored = json.loads(keychain.passwords[("forceupdate", "gitlab:gitlab.com")])
    assert stored == {
        "access_token": "glo-acces",
        "refresh_token": "glo-refresh",
        "expires_at": expires.isoformat(),
    }
    assert store.grant(ForgeKind.GITLAB, "gitlab.com") == grant
    assert store.token(ForgeKind.GITLAB, "gitlab.com") == "glo-acces"
    assert "glo-" not in store.path.read_text(encoding="utf-8")
    # Se déconnecter rend le token à révoquer, pas son refresh token.
    assert store.remove(ForgeKind.GITLAB, "gitlab.com")[1] == "glo-acces"


class Flow:
    """Une application OAuth qui compte ses renouvellements."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.calls: list[str] = []
        self.refuse = refuse

    async def refresh(self, http: HttpClient, refresh_token: str) -> Grant:
        self.calls.append(refresh_token)
        await asyncio.sleep(0.02)  # le temps qu'un autre renouvellement attende son tour
        if self.refuse:
            raise TokenRefused("GitLab ne renouvelle plus le token")
        serial = len(self.calls)
        return Grant(
            access_token=f"acces-{serial}",
            refresh_token=f"refresh-{serial}",
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        )


def saved_grant(store: Accounts, *, expires_in: timedelta) -> Account:
    grant = Grant(
        access_token="acces-0",
        refresh_token="refresh-0",
        expires_at=datetime.now(UTC) + expires_in,
    )
    return store.save(gitlab_identity(), grant, ConnectMethod.OAUTH)


def test_a_token_still_valid_is_not_renewed(store: Accounts) -> None:
    account = saved_grant(store, expires_in=timedelta(hours=1))
    flow = Flow()
    renew = accounts_module.renewer(store, account, flow)  # type: ignore[arg-type]
    assert run(lambda http: renew(http, None)) == "acces-0"
    assert flow.calls == []


def test_a_token_about_to_expire_is_renewed_once_for_everyone(store: Accounts) -> None:
    account = saved_grant(store, expires_in=timedelta(minutes=2))
    flow = Flow()
    renew = accounts_module.renewer(store, account, flow)  # type: ignore[arg-type]

    async def together(http: HttpClient) -> list[str]:
        return list(await asyncio.gather(renew(http, None), renew(http, None), renew(http, None)))

    assert run(together) == ["acces-1", "acces-1", "acces-1"]
    assert flow.calls == ["refresh-0"]  # le refresh token ne sert qu'une fois
    assert store.grant(ForgeKind.GITLAB, "gitlab.com") == Grant(
        access_token="acces-1",
        refresh_token="refresh-1",
        expires_at=store.grant(ForgeKind.GITLAB, "gitlab.com").expires_at,  # type: ignore[union-attr]
    )


def test_a_refused_token_is_renewed_unless_another_already_did(store: Accounts) -> None:
    account = saved_grant(store, expires_in=timedelta(hours=1))
    flow = Flow()
    renew = accounts_module.renewer(store, account, flow)  # type: ignore[arg-type]
    assert run(lambda http: renew(http, "acces-0")) == "acces-1"
    # Refusé, mais ce n'est plus celui du trousseau : on prend le nouveau, sans renouveler.
    assert run(lambda http: renew(http, "acces-0")) == "acces-1"
    assert flow.calls == ["refresh-0"]


def test_a_token_that_does_not_renew(store: Accounts) -> None:
    account = saved_grant(store, expires_in=timedelta(minutes=1))
    renew = accounts_module.renewer(store, account, Flow(refuse=True))  # type: ignore[arg-type]
    with pytest.raises(TokenRefused, match="ne renouvelle plus"):
        run(lambda http: renew(http, None))
    pasted = store.save(gitlab_identity(), "glpat-colle", ConnectMethod.TOKEN)
    renew = accounts_module.renewer(store, pasted, Flow())  # type: ignore[arg-type]
    with pytest.raises(TokenRefused, match="Se reconnecter"):
        run(lambda http: renew(http, "glpat-colle"))
    assert not store.renewing(ForgeKind.GITLAB, "gitlab.com").locked()
