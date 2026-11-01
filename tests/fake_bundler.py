"""Un faux Bundler pour les tests : ``bundle lock`` comme le vrai (Bundler 4.0.20), sans Ruby.

Il sert de ``FakeTools.handlers["bundle"]`` (``tests/conftest.py``). Ce qu'il fait, relevé sur le
vrai (voir les notes de E24 dans ``PLAN.md``) :

- une gem dont le ``Gemfile``, un ``.gemspec`` ou une autre gem du lockfile n'accepte plus la
  version figée passe à la plus haute permise (``= V`` : V) ; une gem de ``--update`` aussi ; le
  reste ne bouge pas ;
- ``--remove-platform`` retire une plateforme ;
- les versions publiées sont celles de ``tests/fixtures/rubygems/`` ; une gem qui n'y est pas ne
  bouge jamais.
"""

import re
from pathlib import Path

from conftest import ToolCall

from forceupdate.parsers import ruby
from forceupdate.registries.rubygems import parse_info
from forceupdate.versions.rubygems import RUBYGEMS

RUBYGEMS_FIXTURES = Path(__file__).parent / "fixtures" / "rubygems"


def published_gems(name: str) -> list[str]:
    """Les versions publiées de ``name``, d'après sa réponse enregistrée."""
    text = (RUBYGEMS_FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    return [v.version for v in parse_info(text)]


class FakeBundler:
    """``bundle lock``. ``local`` : la plateforme que le vrai ajoute au lockfile qui ne l'a pas ;
    ``refuse`` : des gems qu'il ne sait pas épingler (une autre gem en exige une autre version) ;
    ``bundled_with`` : sa version, qu'il écrit dans ``BUNDLED WITH``."""

    def __init__(
        self,
        *,
        local: str | None = None,
        refuse: tuple[str, ...] = (),
        bundled_with: str | None = None,
    ) -> None:
        self.local = local
        self.refuse = refuse
        self.bundled_with = bundled_with

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        arguments = call.arguments
        if arguments[:1] != ["lock"]:
            return 15, "", f"commande inattendue : {arguments}"
        gemfile = Path(call.env["BUNDLE_GEMFILE"])
        path = Path(call.env["BUNDLE_LOCKFILE"])
        text = path.read_text(encoding="utf-8")
        if "--remove-platform" in arguments:
            for platform in arguments[arguments.index("--remove-platform") + 1 :]:
                text = text.replace(f"\n  {platform}\n", "\n")
            path.write_text(text, encoding="utf-8")
            return None
        wanted = self.requirements(gemfile)
        for name in self.refuse:
            if any(r.startswith("= ") for r in wanted.get(name, [])):
                return 6, "", f"Could not find compatible versions for gem {name}"
        for name, requirement in re.findall(r"^ {6}(\S+) \((.+)\)$", text, flags=re.M):
            wanted.setdefault(name, []).append(requirement)  # ce qu'exigent les autres gems
        updated = arguments[arguments.index("--update") + 1 :] if "--update" in arguments else []
        locked = ruby.parse_gemfile_lock(path.name, text)
        for name in dict.fromkeys(p.name for p in locked.lockfile.packages):
            if not (RUBYGEMS_FIXTURES / f"{name}.txt").exists():
                continue
            current = locked.packages(name)[0].version
            requirement = ", ".join(wanted.get(name, []))
            if name in updated or not RUBYGEMS.satisfies(requirement, current):
                new = RUBYGEMS.max_satisfying(requirement, published_gems(name))
                if new is None:
                    return 6, "", f"Could not find compatible versions for gem {name}"
                text = re.sub(
                    rf"^(    {re.escape(name)} \()[^-)]*", rf"\g<1>{new}", text, flags=re.M
                )
        if self.local is not None and f"\n  {self.local}\n" not in text:
            text = text.replace("PLATFORMS\n", f"PLATFORMS\n  {self.local}\n")
        if self.bundled_with is not None:
            text = re.sub(r"(BUNDLED WITH\n  ).*", rf"\g<1>{self.bundled_with}", text)
        path.write_text(text, encoding="utf-8")
        return None

    @staticmethod
    def requirements(gemfile: Path) -> dict[str, list[str]]:
        """Ce qu'exigent le ``Gemfile`` (lignes ajoutées comprises) et les ``.gemspec``."""
        found: dict[str, list[str]] = {}
        declared = ruby.parse_gemfile("Gemfile", gemfile.read_text(encoding="utf-8"))
        for spec in sorted(gemfile.parent.rglob("*.gemspec")):
            declared += ruby.parse_gemspec(spec.name, spec.read_text(encoding="utf-8"))
        for dependency in declared:
            if dependency.constraint:
                found.setdefault(dependency.name, []).append(dependency.constraint)
        return found
