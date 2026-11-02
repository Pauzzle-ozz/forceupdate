"""Les parseurs Ruby : ``Gemfile``, ``.gemspec``, ``Gemfile.lock``, et le lien entre eux.

``TestParseGemfileLock.test_specs_section`` est repris de ``reference/argos_sca_parsers_tests.py``
; le reste couvre ce que la reprise a corrigé ou ajouté : toutes les sections du lockfile
(``GIT``, ``PATH``, plusieurs ``GEM``, ``PLATFORMS``, ``DEPENDENCIES``…), les versions à
plateforme, le graphe, et le ``Gemfile`` et le ``.gemspec``, lus par motifs sans être exécutés.
Les extraits de lockfile viennent du vrai Bundler 4.0.20, sauf la section ``GIT``, écrite d'après
son ``LockfileParser`` (cloner un dépôt externe n'a pas été permis pendant la session).
"""

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import find_projects
from forceupdate.models import Location, Notice, Project, Scope
from forceupdate.parsers.base import REASON_GIT, REASON_LOCAL, ParseError
from forceupdate.parsers.ruby import (
    REASON_BUNDLER,
    REASON_OTHER_SOURCE,
    REASON_PLATFORMS,
    REASON_PLUGIN,
    is_rubygems,
    parse_gemfile,
    parse_gemfile_lock,
    parse_gemspec,
)
from forceupdate.parsers.ruby_spans import statements, tokens

RUNTIME, DEV, OPTIONAL = Scope.RUNTIME, Scope.DEV, Scope.OPTIONAL


def parse(files: dict[str, str], path: str = ".") -> Project:
    """Le projet ``path`` de ``files``, avec ses dépendances lues."""
    projects, _ = find_projects(files, include_tests=True)
    project = next(p for p in projects if p.path == path)
    parsers.parse_project(project, files.get)
    return project


def gems(text: str) -> list[tuple[str, str, Scope, str | None]]:
    return [
        (d.name, d.constraint, d.scope, d.unverifiable_reason)
        for d in parse_gemfile("Gemfile", text)
    ]


def spec(*lines: str) -> str:
    """Un ``.gemspec`` fait de ``lines``."""
    body = "".join(f"  {line}\n" for line in lines)
    return f"Gem::Specification.new do |s|\n{body}end\n"


def lock(*sections: str) -> str:
    return "\n".join(sections) + "\n"


GEM = """\
GEM
  remote: https://rubygems.org/
  specs:
    nokogiri (1.19.0-x64-mingw-ucrt)
      racc (~> 1.4)
    nokogiri (1.19.0-x86_64-linux-gnu)
      racc (~> 1.4)
    racc (1.6.0)
    rack (2.2.3)
    rack-protection (2.2.2)
      rack
    sinatra (2.2.2)
      rack (~> 2.2)
      rack-protection (= 2.2.2)
"""
PLATFORMS = """\
PLATFORMS
  x64-mingw-ucrt
  x86_64-linux
"""
BUNDLED = """\
BUNDLED WITH
  4.0.20
"""


# ---------------------------------------------------------------------------
# Les jetons
# ---------------------------------------------------------------------------


class TestTokens:
    def test_strings_symbols_labels_and_positions(self) -> None:
        found = tokens("gem \"rack\", '~> 2.2', require: false, group: :test\n")
        assert [(t.kind, t.value) for t in found if t.kind != "op"] == [
            ("ident", "gem"),
            ("string", "rack"),
            ("string", "~> 2.2"),
            ("label", "require"),
            ("ident", "false"),
            ("label", "group"),
            ("symbol", "test"),
            ("newline", "\n"),
        ]
        rack = found[1]
        assert (rack.line, rack.column, rack.end_column, rack.plain) == (1, 5, 9, True)

    def test_escapes_and_interpolation_are_not_plain(self) -> None:
        found = [
            t for t in tokens('a = "x\\"y"\nb = "v#{1 + "2"}"\nc = \'z\'\n') if t.kind == "string"
        ]
        assert [(t.value, t.plain) for t in found] == [
            ('x\\"y', False),
            ('v#{1 + "2"}', False),
            ("z", True),
        ]

    def test_comments_heredocs_and_end(self) -> None:
        text = (
            "=begin\ngem 'hidden'\n=end\n"
            "desc = <<~TEXT\n  gem 'in a heredoc'\nTEXT\n"
            "gem 'kept' # gem 'comment'\n"
            "__END__\ngem 'after end'\n"
        )
        strings = [t.value for t in tokens(text) if t.kind == "string"]
        assert strings == ["", "kept"]

    def test_percent_literals(self) -> None:
        found = tokens("x = %i[windows jruby]\ny = %q<rack>.freeze\nz = 4 % 2\n")
        assert [(t.kind, t.value) for t in found if t.kind in ("words", "string")] == [
            ("words", "windows jruby"),
            ("string", "rack"),
        ]

    def test_statements_continue_after_a_comma_and_inside_brackets(self) -> None:
        text = 'gem "a",\n  "~> 1.0"\ngem("b",\n  "2.0")\nfoo\n  .bar\ngem "c"; gem "d"\n'
        assert [s.line for s in statements(text)] == [1, 3, 5, 7, 7]


# ---------------------------------------------------------------------------
# Gemfile
# ---------------------------------------------------------------------------


class TestParseGemfile:
    def test_constraints_as_written_and_their_location(self) -> None:
        text = (
            'source "https://rubygems.org"\n'
            'gem "rack", "~> 2.2.3"\n'
            'gem "nokogiri", ">= 1.19.0", "< 1.20"\n'
            "gem 'puma', ' 5.6.4 '\n"
            'gem("json", [">= 2.0", "< 3"])\n'
            'gem "tzinfo-data"\n'
        )
        found = parse_gemfile("Gemfile", text)
        assert [(d.name, d.constraint) for d in found] == [
            ("rack", "~> 2.2.3"),
            ("nokogiri", ">= 1.19.0, < 1.20"),
            ("puma", "5.6.4"),
            ("json", ">= 2.0, < 3"),
            ("tzinfo-data", ""),
        ]
        assert [d.location for d in found] == [
            Location(line=2, column=13, end_column=21),
            Location(line=3, column=17, end_column=36),
            Location(line=4, column=14, end_column=19),
            Location(line=5, column=14, end_column=27),
            None,
        ]
        lines = text.split("\n")
        assert lines[2][17:36] == '>= 1.19.0", "< 1.20'

    def test_requirements_on_several_lines_have_no_location(self) -> None:
        (found,) = parse_gemfile("Gemfile", 'gem "rack",\n  "~> 2.2",\n  ">= 2.2.3"\n')
        assert (found.constraint, found.location) == ("~> 2.2, >= 2.2.3", None)

    def test_groups(self) -> None:
        text = (
            'gem "rails"\n'
            "group :development, :test do\n"
            '  gem "rspec"\n'
            "end\n"
            "group :production do\n"
            '  gem "pg"\n'
            "end\n"
            'gem "minitest", group: :test\n'
            'gem "debug", groups: [:development, :test]\n'
            'gem "yard", group: "docs"\n'
            "group :docs, optional: true do\n"
            '  gem "kramdown"\n'
            "end\n"
            "group(:test) do\n"
            '  gem "capybara", require: false\n'
            "end\n"
        )
        assert [(n, s) for n, _, s, _ in gems(text)] == [
            ("rails", RUNTIME),
            ("rspec", DEV),
            ("pg", RUNTIME),
            ("minitest", DEV),
            ("debug", DEV),
            ("yard", RUNTIME),
            ("kramdown", OPTIONAL),
            ("capybara", DEV),
        ]

    def test_where_a_gem_comes_from(self) -> None:
        text = (
            'git_source(:company) { |repo| "https://git.example.com/#{repo}.git" }\n'
            'gem "a", git: "https://github.com/x/a.git", branch: "main"\n'
            'gem "b", github: "x/b"\n'
            'gem "c", company: "x/c"\n'
            'gem "d", path: "vendor/d"\n'
            'gem "e", source: "https://gems.example.com"\n'
            'gem "f", source: "https://rubygems.org"\n'
            'source "https://gems.example.com" do\n'
            '  gem "g"\n'
            "end\n"
            'path "engines" do\n'
            '  gem "h"\n'
            "end\n"
            'git "https://github.com/rails/rails.git" do\n'
            '  gem "i"\n'
            "end\n"
            'source "https://gems.example.com", type: "s3" do\n'
            '  gem "j"\n'
            "end\n"
            'gem "k"\n'
        )
        assert [(n, r) for n, _, _, r in gems(text)] == [
            ("a", REASON_GIT),
            ("b", REASON_GIT),
            ("c", REASON_GIT),
            ("d", REASON_LOCAL),
            ("e", REASON_OTHER_SOURCE),
            ("f", None),
            ("g", REASON_OTHER_SOURCE),
            ("h", REASON_LOCAL),
            ("i", REASON_GIT),
            ("j", REASON_PLUGIN),
            ("k", None),
        ]

    def test_what_is_not_read_gives_a_notice(self) -> None:
        text = (
            'rails_version = "~> 7.1"\n'
            'gem "rails", rails_version\n'
            "gem name_of_gem\n"
            'eval_gemfile "Gemfile.local"\n'
            'gem "listen" if RUBY_PLATFORM =~ /darwin/\n'
            "if ENV['DB'] == 'pg'\n"
            '  gem "pg"\n'
            '  gem "pg_search"\n'
            "else\n"
            '  gem "sqlite3"\n'
            "end\n"
            'gem "puma"\n'
        )
        reader = parsers.ruby.read_gemfile("Gemfile", text)
        assert [d.name for d in reader.dependencies] == [
            "rails",
            "listen",
            "pg",
            "pg_search",
            "sqlite3",
            "puma",
        ]
        assert reader.unwritten == {0}
        assert [n.message for n in reader.notices] == [
            "ligne 2 : la contrainte de « rails » n'est pas une chaîne écrite en clair : celle du "
            "Gemfile.lock est prise, à réécrire à la main.",
            "ligne 3 : gem dont le nom n'est pas une chaîne écrite en clair : pas lue.",
            "ligne 4 : eval_gemfile : le fichier chargé n'est pas lu par forceupdate.",
            "ligne 5 : « listen » est déclarée sous condition (if), que forceupdate n'évalue pas : "
            "lue comme toujours déclarée.",
            "ligne 6 : condition que forceupdate n'évalue pas : les gem qu'elle déclare sont lues "
            "comme toujours déclarées.",
        ]

    def test_blocks_close_where_they_should(self) -> None:
        text = (
            "group :test do\n"
            "  [1, 2].each do |i| puts i end\n"
            '  gem "rspec"\n'
            "end\n"
            'gem "rails"\n'
            "install_if -> { RUBY_PLATFORM =~ /darwin/ } do\n"
            '  gem "rb-fsevent"\n'
            "end\n"
            "platforms :jruby do\n"
            '  gem "jdbc"\n'
            "end\n"
            'gem "pg", platforms: :ruby\n'
        )
        reader = parsers.ruby.read_gemfile("Gemfile", text)
        assert [(d.name, d.scope) for d in reader.dependencies] == [
            ("rspec", DEV),
            ("rails", RUNTIME),
            ("rb-fsevent", RUNTIME),
            ("jdbc", RUNTIME),
            ("pg", RUNTIME),
        ]
        assert reader.platform_restricted == {3, 4}
        assert reader.notices == []

    def test_gemspec_and_local_paths(self) -> None:
        text = (
            "gemspec\n"
            'gemspec path: "engines/admin", name: "admin", development_group: :test\n'
            'gem "helper", path: "./helper/"\n'
            'path "gems" do\n  gem "x"\nend\n'
        )
        reader = parsers.ruby.read_gemfile("Gemfile", text)
        assert [(g.path, g.name, g.development_group) for g in reader.gemspecs] == [
            (".", None, "development"),
            ("engines/admin", "admin", "test"),
        ]
        assert reader.paths == (".", "engines/admin", "./helper/", "gems")

    def test_ruby_plugin_and_bundler_itself(self) -> None:
        text = 'ruby "3.3.6"\nplugin "bundler-graph"\ngem "bundler", ">= 2.4"\n'
        assert gems(text) == [("bundler", ">= 2.4", RUNTIME, REASON_BUNDLER)]

    def test_rubygems_addresses(self) -> None:
        assert is_rubygems("https://rubygems.org")
        assert is_rubygems("https://rubygems.org/")
        assert is_rubygems("http://index.rubygems.org")
        assert not is_rubygems("https://gem.coop")
        assert not is_rubygems("https://rubygems.org.example.com")


# ---------------------------------------------------------------------------
# .gemspec
# ---------------------------------------------------------------------------


class TestParseGemspec:
    def test_dependencies_and_their_location(self) -> None:
        text = (
            "Gem::Specification.new do |spec|\n"
            '  spec.name = "demo"\n'
            '  spec.add_dependency "mustermann", "~> 2.0"\n'
            "  spec.add_runtime_dependency('tilt', '>= 2.0.10', '< 3')\n"
            '  spec.add_development_dependency "rake"\n'
            '  spec.add_dependency "json", [">= 2.0", "< 3"]\n'
            "end\n"
        )
        found = parse_gemspec("demo.gemspec", text)
        assert [(d.name, d.constraint, d.scope, d.location) for d in found] == [
            ("mustermann", "~> 2.0", RUNTIME, Location(line=3, column=37, end_column=43)),
            ("tilt", ">= 2.0.10, < 3", RUNTIME, Location(line=4, column=39, end_column=55)),
            ("rake", "", DEV, None),
            ("json", ">= 2.0, < 3", RUNTIME, Location(line=6, column=32, end_column=45)),
        ]
        lines = text.split("\n")
        assert [d.location.extract(text) for d in found if d.location] == [  # type: ignore[union-attr]
            "~> 2.0",
            ">= 2.0.10', '< 3",
            '>= 2.0", "< 3',
        ]
        assert lines[2].endswith('"~> 2.0"')
        assert parsers.ruby._parse_gemspec("demo.gemspec", text).name == "demo"

    def test_a_generated_gemspec(self) -> None:
        text = (
            "# stub: demo 0.1.0 ruby lib\n"
            "Gem::Specification.new do |s|\n"
            '  s.name = "demo".freeze\n'
            "  s.description = <<~TEXT\n"
            "    s.add_dependency 'not-a-dependency'\n"
            "  TEXT\n"
            '  s.add_runtime_dependency(%q<rack>.freeze, [">= 2.2".freeze])\n'
            '  s.add_development_dependency(%q<rspec>.freeze, ["~> 3.0".freeze])\n'
            "end\n"
        )
        found = parsers.ruby._parse_gemspec("demo.gemspec", text, development_group="test")
        assert found.name == "demo"
        assert [(d.name, d.constraint, d.scope) for d in found.dependencies] == [
            ("rack", ">= 2.2", RUNTIME),
            ("rspec", "~> 3.0", DEV),
        ]

    def test_name_given_to_new(self) -> None:
        text = 'Gem::Specification.new "demo", "1.0" do |s|\n  s.add_dependency "rack"\nend\n'
        assert parsers.ruby._parse_gemspec("demo.gemspec", text).name == "demo"


# ---------------------------------------------------------------------------
# Gemfile.lock
# ---------------------------------------------------------------------------


class TestParseGemfileLock:
    def test_specs_section(self) -> None:  # repris de reference/
        content = """\
GEM
  remote: https://rubygems.org/
  specs:
    rails (7.1.0)
    nokogiri (1.15.4)
"""
        parsed = parse_gemfile_lock("Gemfile.lock", content)
        assert {p.name for p in parsed.lockfile.packages} == {"rails", "nokogiri"}
        assert all(p.unverifiable_reason is None for p in parsed.lockfile.packages)

    def test_versions_with_a_platform_graph_and_metadata(self) -> None:
        content = lock(
            GEM,
            PLATFORMS,
            "DEPENDENCIES\n  nokogiri (>= 1.19.0, < 1.20)\n  sinatra (~> 2.2)\n  tzinfo-data\n",
            "CHECKSUMS\n  rack (2.2.3) sha256=2638e7eb\n",
            "RUBY VERSION\n  ruby 3.3.6p108\n",
            BUNDLED,
        )
        parsed = parse_gemfile_lock("Gemfile.lock", content)
        assert [(p.name, p.version) for p in parsed.lockfile.packages] == [
            ("nokogiri", "1.19.0"),
            ("nokogiri", "1.19.0"),
            ("racc", "1.6.0"),
            ("rack", "2.2.3"),
            ("rack-protection", "2.2.2"),
            ("sinatra", "2.2.2"),
        ]
        sinatra = parsed.packages("sinatra")[0]
        assert [name for name, _ in sinatra.dependencies] == ["rack", "rack-protection"]
        assert parsed.lockfile.graph
        assert parsed.requirements == {
            "nokogiri": ">= 1.19.0, < 1.20",
            "sinatra": "~> 2.2",
            "tzinfo-data": "",
        }
        assert parsed.platforms == ("x64-mingw-ucrt", "x86_64-linux")
        assert (parsed.bundled_with, parsed.ruby_version) == ("4.0.20", "ruby 3.3.6p108")

    def test_git_path_and_other_sources(self) -> None:
        content = lock(
            "GIT\n  remote: https://github.com/rack/rack-attack.git\n"
            "  revision: 0123456789abcdef0123456789abcdef01234567\n  tag: v6.7.0\n  specs:\n"
            "    rack-attack (6.7.0)\n      rack (>= 1.0, < 4)\n",
            "PATH\n  remote: .\n  specs:\n    demo (0.1.0)\n      mustermann (~> 2.0)\n",
            "PATH\n  remote: helper\n  specs:\n    helper (0.1.0)\n      json (>= 2.0)\n",
            "GEM\n  remote: https://gem.coop/\n  specs:\n    tilt (2.9.0)\n",
            "GEM\n  remote: https://rubygems.org/\n  specs:\n    rack (3.2.8)\n",
            "PLUGIN SOURCE\n  remote: https://example.com\n  type: s3\n  specs:\n"
            "    private (1.0)\n",
            "DEPENDENCIES\n  rack (~> 3.1)\n  tilt (~> 2.4)!\n  demo!\n",
            BUNDLED,
        )
        parsed = parse_gemfile_lock("Gemfile.lock", content)
        assert [(p.name, p.local, p.unverifiable_reason) for p in parsed.lockfile.packages] == [
            ("rack-attack", False, REASON_GIT),
            ("demo", True, None),
            ("helper", False, REASON_LOCAL),
            ("tilt", False, REASON_OTHER_SOURCE),
            ("rack", False, None),
            ("private", False, REASON_PLUGIN),
        ]
        assert parsed.requirements["tilt"] == "~> 2.4"

    def test_a_single_gem_source_is_the_global_one(self) -> None:
        content = lock("GEM\n  remote: https://gems.example.com/\n  specs:\n    rack (2.2.3)\n")
        (rack,) = parse_gemfile_lock("Gemfile.lock", content).lockfile.packages
        assert rack.unverifiable_reason is None  # un miroir : cherché sur rubygems.org

    def test_crlf_and_empty(self) -> None:
        parsed = parse_gemfile_lock("Gemfile.lock", GEM.replace("\n", "\r\n"))
        assert len(parsed.lockfile.packages) == 6
        assert parse_gemfile_lock("Gemfile.lock", "").lockfile.packages == ()

    def test_not_a_lockfile(self) -> None:
        with pytest.raises(ParseError, match=r"pas un Gemfile\.lock"):
            parse_gemfile_lock("Gemfile.lock", "<<<<<<< HEAD\nfoo\n")

    def test_through_parse_lockfile(self) -> None:
        found = parsers.parse_lockfile("gems.locked", GEM)
        assert found.path == "gems.locked" and len(found.packages) == 6


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


GEMFILE = """\
source "https://rubygems.org"

gemspec

gem "sinatra", "~> 2.2"
gem "nokogiri", ">= 1.19.0", "< 1.20"
gem "jdbc-sqlite3", platforms: :jruby
gem "helper", path: "helper"

group :test do
  gem "rack-test"
end
"""
GEMSPEC = """\
Gem::Specification.new do |spec|
  spec.name = "demo"
  spec.add_dependency "rack", "~> 2.2"
end
"""
PROJECT_LOCK = lock(
    "PATH\n  remote: .\n  specs:\n    demo (0.1.0)\n      rack (~> 2.2)\n",
    "PATH\n  remote: helper\n  specs:\n    helper (0.1.0)\n      json (>= 2.0)\n",
    GEM.replace("    racc (1.6.0)\n", "    json (2.3.0)\n    racc (1.6.0)\n").replace(
        "    rack (2.2.3)\n", "    rack (2.2.3)\n    rack-test (2.1.0)\n      rack (>= 1.3)\n"
    ),
    PLATFORMS,
    BUNDLED,
)


class TestParseProject:
    def test_gemfile_gemspec_and_lockfile(self) -> None:
        files = {
            "Gemfile": GEMFILE,
            "demo.gemspec": GEMSPEC,
            "Gemfile.lock": PROJECT_LOCK,
            "helper/helper.gemspec": 'Gem::Specification.new do |s|\n  s.name = "helper"\n'
            '  s.add_dependency "json", ">= 2.0"\nend\n',
        }
        project = parse(files)
        assert [
            (d.name, d.constraint, d.installed, d.scope, d.file, d.unverifiable_reason)
            for d in project.dependencies
        ] == [
            ("sinatra", "~> 2.2", "2.2.2", RUNTIME, "Gemfile", None),
            ("nokogiri", ">= 1.19.0, < 1.20", "1.19.0", RUNTIME, "Gemfile", None),
            ("jdbc-sqlite3", "", None, RUNTIME, "Gemfile", REASON_PLATFORMS),
            ("helper", "", "0.1.0", RUNTIME, "Gemfile", REASON_LOCAL),
            ("rack-test", "", "2.1.0", DEV, "Gemfile", None),
            ("rack", "~> 2.2", "2.2.3", RUNTIME, "demo.gemspec", None),
            ("json", "", "2.3.0", RUNTIME, "Gemfile.lock", None),
            ("racc", "", "1.6.0", RUNTIME, "Gemfile.lock", None),
            ("rack-protection", "", "2.2.2", RUNTIME, "Gemfile.lock", None),
        ]
        assert {d.lockfile for d in project.dependencies if d.installed} == {"Gemfile.lock"}
        assert project.notices == []
        # La gem locale helper est résolue dans le Gemfile.lock de la racine.
        helper = parse(files, "helper")
        assert helper.lockfiles == ["Gemfile.lock"]
        assert [(d.name, d.installed, d.lockfile, d.direct) for d in helper.dependencies] == [
            ("json", "2.3.0", "Gemfile.lock", True)
        ]

    def test_a_gem_that_the_root_gemfile_does_not_cite_keeps_no_lockfile(self) -> None:
        files = {
            "Gemfile": 'gem "rack"\n',
            "Gemfile.lock": lock(GEM),
            "other/other.gemspec": spec('s.add_dependency "json"'),
        }
        other = parse(files, "other")
        assert other.lockfiles == []
        assert [(d.name, d.installed) for d in other.dependencies] == [("json", None)]

    def test_a_gem_with_its_own_gemfile_is_not_a_member(self) -> None:
        files = {
            "Gemfile": 'gem "x", path: "x"\n',
            "Gemfile.lock": lock(GEM),
            "x/Gemfile": "gemspec\n",
            "x/x.gemspec": 'Gem::Specification.new do |s|\n  s.add_dependency "rack"\nend\n',
        }
        assert parse(files, "x").lockfiles == []

    def test_a_gemspec_the_gemfile_does_not_cite(self) -> None:
        project = parse({"Gemfile": 'gem "rack"\n', "demo.gemspec": GEMSPEC})
        assert [d.name for d in project.dependencies] == ["rack"]
        assert project.notices == [
            Notice(file="demo.gemspec", message="pas cité par le Gemfile (gemspec) : pas lu.")
        ]

    def test_gemspec_name_and_other_folder(self) -> None:
        files = {
            "Gemfile": 'gemspec name: "b"\ngemspec path: "sub"\n',
            "a.gemspec": spec('s.name = "a"', 's.add_dependency "x"'),
            "b.gemspec": spec('s.name = "b"', 's.add_dependency "y"'),
        }
        project = parse(files)
        assert [d.name for d in project.dependencies] == ["y"]
        assert project.notices == [
            Notice(
                file="Gemfile",
                message="ligne 2 : gemspec d'un autre dossier (sub) : lu avec son propre projet.",
            )
        ]

    def test_a_constraint_that_is_not_written_comes_from_the_lockfile(self) -> None:
        files = {
            "Gemfile": 'v = "~> 2.2"\ngem "sinatra", v\n',
            "Gemfile.lock": lock(GEM, "DEPENDENCIES\n  sinatra (~> 2.2)\n"),
        }
        (sinatra, *_) = parse(files).dependencies
        assert (sinatra.constraint, sinatra.location, sinatra.installed) == (
            "~> 2.2",
            None,
            "2.2.2",
        )

    def test_gems_rb_and_gems_locked(self) -> None:
        project = parse({"gems.rb": 'gem "rack"\n', "gems.locked": lock(GEM)})
        assert (project.manifests, project.lockfiles) == (["gems.rb"], ["gems.locked"])
        rack = project.dependencies[0]
        assert (rack.name, rack.installed) == ("rack", "2.2.3")

    def test_an_unreadable_lockfile(self) -> None:
        project = parse({"Gemfile": 'gem "rack"\n', "Gemfile.lock": "pas un lockfile\n"})
        assert [(d.name, d.installed) for d in project.dependencies] == [("rack", None)]
        assert project.notices == [
            Notice(
                file="Gemfile.lock",
                message="ce n'est pas un Gemfile.lock : aucune section connue "
                "(GEM, DEPENDENCIES…).",
            )
        ]
