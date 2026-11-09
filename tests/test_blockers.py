"""Ce que demandent les autres paquets (E37) : une version qu'un paquet installé retient, ou que
l'outil du lockfile refusera, et la version de ce paquet qui l'accepterait.

Les registres sont simulés (``FakeLookup``) ; le reste est le vrai planificateur
(``test_planner.plan``)."""

import dataclasses
from collections.abc import Iterable, Mapping

from test_planner import LODASH, LODASH_ADVISORIES, advisory, dep, info, plan, single

from forceupdate import versions
from forceupdate.models import Dependency, Ecosystem, Project, Requirement, Update, UpdateOption
from forceupdate.registries import PackageInfo, PackageVersion, Requires
from forceupdate.update import blockers
from forceupdate.update.planner import INDIRECT_MAJOR_WARNING, MAJOR_WARNING

NPM, PYPI = Ecosystem.NPM, Ecosystem.PYPI


class FakeLookup:
    """Le registre : ``infos`` (avec ce que demande chaque version), et ce que demandent des
    versions en plus (``requires``, comme l'API JSON de PyPI). Compte les questions."""

    def __init__(
        self,
        infos: Iterable[PackageInfo] = (),
        requires: Mapping[tuple[str, str], Requires] | None = None,
    ) -> None:
        self.infos = {(i.ecosystem, i.name): i for i in infos}
        self.extra = dict(requires or {})
        self.asked: list[tuple[str, str]] = []

    async def package(
        self, project: Project, ecosystem: Ecosystem, name: str
    ) -> PackageInfo | None:
        return self.infos.get((ecosystem, name))

    async def requires(
        self, project: Project, ecosystem: Ecosystem, name: str, version: str
    ) -> Requires | None:
        self.asked.append((name, version))
        if (name, version) in self.extra:
            return self.extra[(name, version)]
        known = self.infos.get((ecosystem, name))
        found = known.get(version) if known is not None else None
        return found.requires if found is not None else None


def registry(
    name: str,
    published: Mapping[str, Requires | None],
    *,
    ecosystem: Ecosystem = NPM,
) -> PackageInfo:
    """Ce que le registre dit de ``name`` : ses versions, et ce que chacune demande."""
    base = info(name, list(published), ecosystem=ecosystem)
    return dataclasses.replace(
        base,
        versions=tuple(PackageVersion(version=v, requires=published[v]) for v in published),
    )


def needs(**ranges: str) -> Requires:
    return Requires(dependencies={k.replace("_", "-"): v for k, v in ranges.items()})


def option(update: Update, version: str) -> UpdateOption:
    found = update.option(version)
    assert found is not None, [o.version for o in update.options]
    return found


def held_lodash(*requirements: Requirement, lockfile: str = "package-lock.json") -> Dependency:
    return dataclasses.replace(
        dep("lodash", "", "4.17.15", direct=False, file=lockfile, lockfile=lockfile),
        required_by=requirements,
    )


NODEMON = Requirement(name="nodemon", version="3.1.14", range="~4.17.0")


# ---------------------------------------------------------------------------
# Une indirecte retenue : la version du paquet qui la tire qui l'accepterait
# ---------------------------------------------------------------------------


def test_the_parent_version_that_accepts_the_fix() -> None:
    lookup = FakeLookup(
        [
            registry(
                "nodemon",
                {
                    "3.1.14": needs(lodash="~4.17.0"),
                    "3.1.15": needs(lodash="~4.17.0"),
                    "3.2.0": needs(lodash="^4.18.0"),
                    "4.0.0": needs(lodash="^5.0.0"),
                    "4.1.0-beta.1": needs(lodash="*"),  # une pré-version n'est pas proposée
                },
            )
        ]
    )
    update = single(
        plan(
            held_lodash(NODEMON),
            infos=[info("lodash", LODASH)],
            advisories=LODASH_ADVISORIES,
            lookup=lookup,
        )
    )
    assert option(update, "4.17.21").blockers == ()
    minor = option(update, "4.18.1")
    assert minor.held_by == ("nodemon 3.1.14",)
    assert minor.refused_by == ()
    (blocker,) = minor.blockers
    assert (blocker.accepting, blocker.checked, blocker.held) == ("3.2.0", True, True)
    assert minor.warnings == (
        "nodemon 3.1.14 demande ~4.17.0 : le lockfile seul ne la fera pas monter ; monter "
        "d'abord nodemon en 3.2.0 (la première version qui l'accepte).",
    )
    assert option(update, "5.0.0").blockers[0].accepting == "4.0.0"
    assert option(update, "5.0.0").warnings[0] == MAJOR_WARNING
    assert update.selected == "4.17.21"


def test_no_version_of_the_parent_accepts_the_fix() -> None:
    lookup = FakeLookup(
        [
            registry(
                "nodemon", {"3.1.14": needs(lodash="~4.17.0"), "3.1.20": needs(lodash="~4.17.0")}
            )
        ]
    )
    update = single(
        plan(
            held_lodash(NODEMON),
            infos=[info("lodash", LODASH)],
            advisories=LODASH_ADVISORIES,
            lookup=lookup,
        )
    )
    (blocker,) = option(update, "4.18.1").blockers
    assert (blocker.accepting, blocker.checked) == (None, True)
    assert option(update, "4.18.1").warnings == (
        "nodemon 3.1.14 demande ~4.17.0 : le lockfile seul ne la fera pas monter, et aucune de "
        "ses versions publiées ne l'accepte.",
    )


def test_a_parent_that_no_longer_requires_it_accepts_it() -> None:
    lookup = FakeLookup(
        [registry("nodemon", {"3.1.14": needs(lodash="~4.17.0"), "3.2.0": needs(chokidar="^4")})]
    )
    update = single(
        plan(
            held_lodash(NODEMON),
            infos=[info("lodash", LODASH)],
            advisories=LODASH_ADVISORIES,
            lookup=lookup,
        )
    )
    assert option(update, "5.0.0").blockers[0].accepting == "3.2.0"


def test_a_range_the_lockfile_does_not_say_is_read_at_the_registry() -> None:
    """pnpm-lock.yaml (et uv.lock) ne disent que le nom du paquet qui la tire."""
    unknown = dataclasses.replace(NODEMON, range="")
    lookup = FakeLookup([registry("nodemon", {"3.1.14": needs(lodash="~4.17.0")})])
    update = single(
        plan(
            held_lodash(unknown, lockfile="pnpm-lock.yaml"),
            infos=[info("lodash", LODASH)],
            advisories=LODASH_ADVISORIES,
            lookup=lookup,
        )
    )
    assert option(update, "4.18.1").held_by == ("nodemon 3.1.14",)
    assert option(update, "4.18.1").blockers[0].range == "~4.17.0"
    # Ce que demandent ceux qui la tirent est connu : plus de « devra peut-être monter aussi ».
    assert INDIRECT_MAJOR_WARNING not in option(update, "5.0.0").warnings
    assert ("nodemon", "3.1.14") in lookup.asked

    # Sans registre : on ne sait rien, rien n'est dit de plus qu'avant.
    alone = single(
        plan(
            held_lodash(unknown, lockfile="pnpm-lock.yaml"),
            infos=[info("lodash", LODASH)],
            advisories=LODASH_ADVISORIES,
        )
    )
    assert option(alone, "4.18.1").held_by == ()
    assert option(alone, "5.0.0").warnings == (MAJOR_WARNING, INDIRECT_MAJOR_WARNING)
    assert alone.selected == "4.18.1"


# ---------------------------------------------------------------------------
# Un refus prévu : une directe, ou une version que l'outil vise exactement
# ---------------------------------------------------------------------------

ARQ = Requirement(name="arq", version="0.26.3", range="")


def redis(*required: Requirement) -> Dependency:
    return dataclasses.replace(dep("redis", ">=5", "5.3.1", ecosystem=PYPI), required_by=required)


REDIS = info("redis", ["5.3.1", "5.3.2", "8.1.0"], ecosystem=PYPI)


def test_uv_will_refuse_a_major_that_no_version_of_its_parent_accepts() -> None:
    """Session 36 : ``redis`` 8.1.0, qu'``arq`` refuse (``redis<6``), faisait tomber tout le
    ``uv.lock`` ; c'est dit dès le choix."""
    lookup = FakeLookup(
        [registry("arq", {"0.26.3": None, "0.27.0": None}, ecosystem=PYPI)],
        requires={
            ("arq", "0.26.3"): needs(redis="<6,>=4.2.0"),
            ("arq", "0.27.0"): needs(redis="<6,>=4.2.0"),
        },
    )
    update = single(plan(redis(ARQ), infos=[REDIS], lookup=lookup))
    major = option(update, "8.1.0")
    assert major.refused_by == ("arq 0.26.3",)
    assert major.held_by == ()
    assert major.warnings == (
        MAJOR_WARNING,
        "arq 0.26.3 demande <6,>=4.2.0 : uv la refusera, et aucune de ses versions publiées ne "
        "l'accepte.",
    )
    # Le correctif reste dans la plage : pré-coché comme avant.
    assert option(update, "5.3.2").refused_by == ()
    assert update.selected == "5.3.2"


def test_the_first_parent_version_that_accepts_by_dichotomy() -> None:
    """PyPI : une requête par version ; la dernière, puis par dichotomie."""
    published = [f"0.{n}.0" for n in range(26, 46)]  # 0.26.0 … 0.45.0
    requires = {
        ("arq", v): needs(redis="<6,>=4.2.0" if int(v.split(".")[1]) < 38 else ">=4.2.0,<9")
        for v in published
    }
    lookup = FakeLookup(
        [registry("arq", dict.fromkeys(published), ecosystem=PYPI)], requires=requires
    )
    required = dataclasses.replace(ARQ, version="0.26.0")
    update = single(plan(redis(required), infos=[REDIS], lookup=lookup))
    major = option(update, "8.1.0")
    assert major.blockers[0].accepting == "0.38.0"
    assert major.refused_by == ("arq 0.26.0",)
    assert major.warnings[-1] == (
        "arq 0.26.0 demande <6,>=4.2.0 : uv la refusera, sauf si arq monte aussi (en 0.38.0, la "
        "première version qui l'accepte)."
    )
    asked = [v for name, v in lookup.asked if name == "arq" and v != "0.26.0"]
    assert len(asked) <= blockers.MAX_LOOKUPS


def test_a_requirement_the_registry_does_not_know_says_nothing() -> None:
    update = single(plan(redis(ARQ), infos=[REDIS], lookup=FakeLookup()))
    assert option(update, "8.1.0").refused_by == ()
    assert option(update, "8.1.0").warnings == (MAJOR_WARNING,)


def test_npm_a_plain_dependency_does_not_block_a_direct_a_peer_does() -> None:
    """npm installe une copie à part pour un paquet qui en demande une autre version ; pas pour une
    dépendance pair (``openapi-typescript`` et ``typescript`` 7, session 36)."""
    typescript = dataclasses.replace(
        dep("typescript", "^5.9.3", "5.9.3"),
        required_by=(
            Requirement(name="ts-plugin", version="1.0.0", range="^5"),
            Requirement(name="openapi-typescript", version="7.10.1", range="^5.x", peer=True),
        ),
    )
    lookup = FakeLookup(
        [
            registry(
                "openapi-typescript",
                {
                    "7.10.1": Requires(peers={"typescript": "^5.x"}),
                    "7.11.0": Requires(peers={"typescript": "^5.x"}),
                },
            ),
            registry("typescript", {"5.9.3": Requires(), "7.0.2": Requires()}),
        ]
    )
    update = single(plan(typescript, infos=[info("typescript", ["5.9.3", "7.0.2"])], lookup=lookup))
    major = option(update, "7.0.2")
    assert major.refused_by == ("openapi-typescript 7.10.1",)
    assert major.warnings[-1] == (
        "openapi-typescript 7.10.1 demande ^5.x (dépendance pair) : npm la refusera, et aucune de "
        "ses versions publiées ne l'accepte."
    )


def test_npm_a_peer_the_new_version_wants_must_move_too() -> None:
    """Session 36 : ``@types/react-dom`` 19 sans ``@types/react`` 19."""
    react_dom = dep("@types/react-dom", "^18.3.1", "18.3.1")
    react = dep("@types/react", "^18.3.5", "18.3.5")
    lookup = FakeLookup(
        [
            registry(
                "@types/react-dom",
                {"18.3.1": Requires(), "19.1.0": Requires(peers={"@types/react": "^19.0.0"})},
            ),
            registry("@types/react", {"18.3.5": None, "19.0.0": None, "19.1.2": None}),
        ]
    )
    project = plan(
        react_dom,
        react,
        infos=[
            info("@types/react-dom", ["18.3.1", "19.1.0"]),
            info("@types/react", ["18.3.5", "19.0.0", "19.1.2"]),
        ],
        lookup=lookup,
    )
    update = next(u for u in project.updates if u.name == "@types/react-dom")
    major = option(update, "19.1.0")
    assert major.refused_by == ("@types/react 18.3.5",)
    (blocker,) = major.blockers
    assert (blocker.companion, blocker.accepting) == (True, "19.0.0")
    assert major.warnings[-1] == (
        "Demande @types/react ^19.0.0 (dépendance pair), et @types/react 18.3.5 est installée : "
        "npm la refusera, sauf si @types/react monte aussi (19.0.0 au moins)."
    )


def test_poetry_holds_an_indirect_uv_refuses_it() -> None:
    """``poetry update --lock x`` la monte aussi haut que possible ; uv la vise exactement."""
    requests = Requirement(name="requests", version="2.28.0", range="<1.27,>=1.21.1")
    urllib3 = ["1.26.18", "2.2.2"]
    advisories = [advisory("U", "urllib3", ("introduced", "0"), ("fixed", "2.2.2"), ecosystem=PYPI)]

    def planned(lockfile: str) -> UpdateOption:
        indirect = dataclasses.replace(
            dep(
                "urllib3",
                "",
                "1.26.18",
                ecosystem=PYPI,
                direct=False,
                file=lockfile,
                lockfile=lockfile,
            ),
            required_by=(requests,),
        )
        update = single(
            plan(
                indirect,
                infos=[info("urllib3", urllib3, ecosystem=PYPI)],
                advisories=advisories,
                lookup=FakeLookup(),
            )
        )
        return option(update, "2.2.2")

    held = planned("poetry.lock")
    assert (held.held_by, held.refused_by) == (("requests 2.28.0",), ())
    refused = planned("uv.lock")
    assert (refused.held_by, refused.refused_by) == ((), ("requests 2.28.0",))
    assert "uv la refusera" in refused.warnings[-1]


def test_an_override_passes_over_the_ranges() -> None:
    """npm : une version forcée (``overrides``) s'impose à ceux qui la tirent."""
    from test_planner import override

    update = single(
        plan(
            held_lodash(NODEMON),
            infos=[info("lodash", LODASH)],
            advisories=LODASH_ADVISORIES,
            overrides=[override("4.17.15")],
            lookup=FakeLookup(),
        )
    )
    assert update.options and all(o.edits for o in update.options)
    assert all(not o.blockers and not o.held_by for o in update.options)


def test_tool_names() -> None:
    assert blockers._tool("a/uv.lock") == "uv"
    assert blockers._tool("requirements.txt") == "pip-compile"
    assert blockers._tool("yarn.lock") == "Yarn"
    assert versions.for_ecosystem(NPM).satisfies("^5.x", "5.9.3")


def test_what_to_say_after_the_update() -> None:
    """Le terminal et la description de PR, pour une version restée en dessous : la version du
    paquet qui la retient qui l'accepterait."""
    from forceupdate.models import Blocker, Gap
    from forceupdate.report import option_fixed, option_unblock
    from forceupdate.update import forge

    nodemon = Blocker(name="nodemon", version="3.1.14", range="^10.2.1", held=True, checked=True)
    held = UpdateOption(
        version="11.0.1",
        gap=Gap.MAJOR,
        reasons=(),
        fixes=("CVE-1",),
        held_by=("nodemon 3.1.14",),
        blockers=(dataclasses.replace(nodemon, accepting="4.0.1"),),
    )
    assert option_unblock(held) == "nodemon 4.0.1 l'accepte"
    assert forge._unblock(held) == " (nodemon 4.0.1 l'accepte)"
    assert option_fixed(held) == "corrigerait 1 faille sur 1"
    none = dataclasses.replace(held, blockers=(nodemon,))
    assert option_unblock(none) == "aucune version de nodemon ne l'accepte"
    unknown = dataclasses.replace(held, blockers=(dataclasses.replace(nodemon, checked=False),))
    assert option_unblock(unknown) == ""
    assert forge._unblock(unknown) == ""
