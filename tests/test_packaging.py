"""Release packages (packaging/, .github/workflows/release.yml, .gitattributes).

- The source archive the packages are built from (``git archive`` of the tag)
  leaves out tests/, CI, local Claude Code notes and the lab, build output and
  anything git-ignored. Checked with read-only git commands: ``git archive``
  of HEAD with this tree's attributes, and ``git check-attr`` for every file
  a commit of this tree would hold (so new, not yet committed files count).
- pyproject.toml, the helper, metadata.json, the PKGBUILD, the RPM spec, the
  Debian changelog and the README's download names agree on one version.
- No packaging file names an email other than the GitHub no-reply address.
- Packages run no scriptlet of their own and never name a home folder.
- Every workflow pins every action to a commit. The release workflow grants
  contents: write to the release job only, which makes a draft release.
"""

import io
import json
import re
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

import hearthwire


ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
PKGBUILD = PACKAGING / "arch" / "PKGBUILD"
SPEC = PACKAGING / "fedora" / "hearthwire.spec"
DEBIAN = PACKAGING / "debian"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
GITATTRIBUTES = ROOT / ".gitattributes"
GITIGNORE = ROOT / ".gitignore"
README = ROOT / "README.md"
METADATA = ROOT / "plasmoid" / "metadata.json"

PLUGIN = "io.github.flybytechprog.hearthwire"
MAINTAINER = "flybytech-prog <104578369+flybytech-prog@users.noreply.github.com>"
ALLOWED_EMAIL = "104578369+flybytech-prog@users.noreply.github.com"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
INSTALLED_ASSETS = (
    "hearthwire.svg", "hearthwire-settings-general.svg", "hearthwire-settings-ai.svg",
    "hearthwire-settings-chat.svg", "hearthwire.notifyrc",
)

# Top-level folders and files the archive must never hold.
EXCLUDED_TOP = {"tests", ".github", ".claude", "build", "dist", ".gitattributes", ".gitignore", ".venv",
                ".superpowers", ".idea", ".vscode"}
# A lab script or folder anywhere (the Plasma test lab lives under .claude/).
LAB = re.compile(r"(^|/)lab([-._/]|$)", re.IGNORECASE)
# What a package build needs from the archive.
REQUIRED_MEMBERS = {
    "pyproject.toml", "LICENSE", "README.md", "plasmoid/metadata.json", "plasmoid/contents/ui/main.qml",
    "src/hearthwire/__init__.py", "src/hearthwire/__main__.py", "src/hearthwire/cli.py",
    "assets/hearthwire.svg", "assets/hearthwire.notifyrc",
}
# Paths that need not exist: each must be export-ignored should it ever be committed.
DECOYS = (
    ".claude/work/lab/lab.sh", ".claude/settings.local.json", "build/lib/hearthwire/cli.py",
    "dist/hearthwire-1.0.0-py3-none-any.whl", "src/hearthwire/__pycache__/cli.cpython-314.pyc",
    "src/hearthwire.egg-info/PKG-INFO", "secrets/token.json", "notes.local", ".venv/bin/python",
    "tests/conftest.py", ".github/workflows/release.yml", "plasmoid/contents/ui/main.qmlc",
    "fixtures/live/claude.json", ".superpowers/session.md",
)


# --- git helpers (read-only) ---------------------------------------------------------------------


def _git(*args, stdin=None):
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args], input=stdin, capture_output=True, timeout=120, check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"git {args[0]} is not usable here")
    return completed.stdout


def _archive_members():
    """Member names of ``git archive HEAD`` with this tree's .gitattributes."""
    data = _git("archive", "--worktree-attributes", "--format=tar", "HEAD")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return {member.name.rstrip("/") for member in archive.getmembers()}


def _export_ignored(paths):
    """The paths ``git archive`` leaves out: the path itself or a parent folder is export-ignore."""
    paths = list(paths)
    prefixes = sorted({"/".join(path.split("/")[:depth]) for path in paths
                       for depth in range(1, path.count("/") + 2)})
    output = _git("check-attr", "-z", "--stdin", "export-ignore", stdin=b"\0".join(p.encode() for p in prefixes))
    fields = output.split(b"\0")
    ignored = {fields[i].decode() for i in range(0, len(fields) - 2, 3) if fields[i + 2] == b"set"}
    return {path for path in paths
            if any("/".join(path.split("/")[:depth]) in ignored for depth in range(1, path.count("/") + 2))}


def _git_ignored(paths):
    """The paths .gitignore (and .git/info/exclude) ignore, whether tracked or not."""
    paths = list(paths)
    if not paths:
        return set()
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index", "-z", "--stdin"],
        input=b"\0".join(p.encode() for p in paths), capture_output=True, timeout=120, check=False,
    )
    if completed.returncode not in (0, 1):
        pytest.skip("git check-ignore is not usable here")
    return {name.decode() for name in completed.stdout.split(b"\0") if name}


def _would_be_committed():
    """Tracked files plus new files git does not ignore: what a commit of this tree holds."""
    return {name.decode() for name in _git("ls-files", "-z", "-c", "-o", "--exclude-standard").split(b"\0") if name}


def archive_problems(members):
    """Problems with a list of archive member names; an empty list means it is clean."""
    problems = []
    for name in sorted(members):
        top = name.split("/", 1)[0]
        if top in EXCLUDED_TOP:
            problems.append(f"{name}: excluded folder or file")
        elif LAB.search(name):
            problems.append(f"{name}: lab file")
    return problems


# --- the source archive --------------------------------------------------------------------------


def test_the_archive_of_head_leaves_out_tests_ci_notes_and_ignored_files():
    members = _archive_members()
    assert archive_problems(members) == []
    assert _git_ignored(members) == set()
    assert REQUIRED_MEMBERS <= members


def test_a_commit_of_this_tree_would_archive_the_packaging_but_not_the_tests():
    candidates = _would_be_committed()
    kept = candidates - _export_ignored(candidates)
    assert archive_problems(kept) == []
    assert _git_ignored(kept) == set()
    assert REQUIRED_MEMBERS <= kept
    assert {"packaging/arch/PKGBUILD", "packaging/fedora/hearthwire.spec", "packaging/debian/control",
            "packaging/debian/rules", "packaging/check-install.sh", "packaging/source-archive.sh",
            "packaging/RELEASE_NOTES-1.0.0.md"} <= kept
    # Everything under tests/ and .github/ is left out, this file included.
    assert "tests/test_packaging.py" in candidates and "tests/test_packaging.py" not in kept
    assert not {name for name in kept if name.startswith((".github/", "tests/"))}


def test_decoys_would_be_left_out_should_they_ever_be_committed():
    assert _export_ignored(DECOYS) == set(DECOYS)


def _gitignore_patterns():
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith(("#", "!"))]


def test_every_gitignore_pattern_is_export_ignored_too():
    attributes = {line.split()[0] for line in GITATTRIBUTES.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#") and line.split()[1:] == ["export-ignore"]}
    missing = [pattern for pattern in _gitignore_patterns() if pattern.rstrip("/") not in attributes]
    assert missing == [], "add these .gitignore patterns to .gitattributes as export-ignore: " + ", ".join(missing)


def test_a_sample_of_every_gitignore_pattern_is_left_out():
    samples = []
    for pattern in _gitignore_patterns():
        sample = pattern.rstrip("/").replace("[cod]", "c").replace("*", "sample")
        samples.append(sample + "/file" if pattern.endswith("/") else sample)
    assert _git_ignored(samples) == set(samples)
    assert _export_ignored(samples) == set(samples)


def test_proof_archive_problems_catch_excluded_names():
    members = {"README.md", "tests/conftest.py", ".claude/work/lab/lab.sh", "build/lib/x.py",
               "scripts/lab-init", "docs/lab/notes.md", ".gitattributes", "src/hearthwire/labels.py"}
    assert archive_problems(members) == [
        ".claude/work/lab/lab.sh: excluded folder or file", ".gitattributes: excluded folder or file",
        "build/lib/x.py: excluded folder or file", "docs/lab/notes.md: lab file", "scripts/lab-init: lab file",
        "tests/conftest.py: excluded folder or file",
    ]


# --- one version -----------------------------------------------------------------------------------


def _assignment(text, name):
    found = re.findall(rf"(?m)^{name}=(\S+)$", text)
    assert len(found) == 1, f"{name}= appears {len(found)} times"
    return found[0].strip("'\"")


def _spec_field(text, name):
    found = re.findall(rf"(?m)^{name}:\s*(\S+)", text)
    assert len(found) == 1, f"{name}: appears {len(found)} times"
    return found[0]


def recipe_versions(pkgbuild, spec, changelog, metadata):
    """{source: (version, release)} as each recipe states it."""
    debian = re.match(r"hearthwire \((?P<version>[^-)]+)-(?P<release>[^)]+)\) ", changelog)
    assert debian, "debian/changelog does not start with 'hearthwire (VERSION-RELEASE) '"
    return {
        "PKGBUILD": (_assignment(pkgbuild, "pkgver"), _assignment(pkgbuild, "pkgrel")),
        "spec": (_spec_field(spec, "Version"), _spec_field(spec, "Release").replace("%{?dist}", "")),
        "debian/changelog": (debian["version"], debian["release"]),
        "metadata.json": (json.loads(metadata)["KPlugin"]["Version"], None),
    }


def version_problems(version, versions):
    problems = [f"{source} says {stated}, pyproject.toml {version}"
                for source, (stated, _) in versions.items() if stated != version]
    releases = {release for _, release in versions.values() if release is not None}
    if len(releases) != 1:
        problems.append(f"package releases differ: {sorted(releases)}")
    return problems


def _pyproject_version():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _texts():
    return (PKGBUILD.read_text(encoding="utf-8"), SPEC.read_text(encoding="utf-8"),
            (DEBIAN / "changelog").read_text(encoding="utf-8"), METADATA.read_text(encoding="utf-8"))


def test_every_recipe_has_the_pyproject_version():
    version = _pyproject_version()
    assert hearthwire.__version__ == version
    assert version_problems(version, recipe_versions(*_texts())) == []
    assert (PACKAGING / f"RELEASE_NOTES-{version}.md").is_file()


def test_proof_a_version_mismatch_is_caught():
    # Mutated in memory only; the real files are never written.
    pkgbuild, spec, changelog, metadata = _texts()
    version = _pyproject_version()
    stale = re.sub(r"(?m)^Version:(\s*)\S+", r"Version:\g<1>0.9.0", spec)
    assert version_problems(version, recipe_versions(pkgbuild, stale, changelog, metadata)) == [
        f"spec says 0.9.0, pyproject.toml {version}"]
    data = json.loads(metadata)
    data["KPlugin"]["Version"] = "2.0.0"
    assert len(version_problems(version, recipe_versions(pkgbuild, spec, changelog, json.dumps(data)))) == 1
    bumped = re.sub(r"(?m)^pkgrel=\S+", "pkgrel=2", pkgbuild)
    assert version_problems(version, recipe_versions(bumped, spec, changelog, metadata)) == [
        "package releases differ: ['1', '2']"]


def test_the_download_names_in_the_readme_and_notes_match_the_packages():
    version = _pyproject_version()
    release = recipe_versions(*_texts())["PKGBUILD"][1]
    fedora = re.findall(r"(?m)^\s*container: fedora:(\d+)$", WORKFLOW.read_text(encoding="utf-8"))
    assert len(set(fedora)) == 1
    names = (f"hearthwire-{version}-{release}-any.pkg.tar.zst",
             f"hearthwire-{version}-{release}.fc{fedora[0]}.noarch.rpm",
             f"hearthwire_{version}-{release}_all.deb")
    notes = (PACKAGING / f"RELEASE_NOTES-{version}.md").read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    for name in names:
        assert name in readme
        assert name in notes
    for text in (readme, notes):
        listed = set(re.findall(r"hearthwire[-_][0-9][\w.+~-]*\.(?:pkg\.tar\.zst|rpm|deb)", text))
        assert listed <= set(names), f"stale package names: {sorted(listed - set(names))}"


def test_the_release_notes_state_the_python_ties():
    notes = (PACKAGING / f"RELEASE_NOTES-{_pyproject_version()}.md").read_text(encoding="utf-8")
    compatibility = notes.split("## Compatibility\n", 1)[1].split("\n## ", 1)[0]
    flat = re.sub(r"\s+", " ", compatibility)
    assert "- **Fedora**: 43 and 44" in flat
    assert re.search(r"- \*\*Arch[^-]*rebuilt when Arch moves to Python 3\.15", flat)
    assert "- **Ubuntu**: 26.04" in flat
    assert "draft" in notes.lower()


def test_ubuntu_target_is_26_04_lts_everywhere():
    # 26.04 LTS (resolute) is the first Ubuntu LTS with Plasma 6.
    assert re.match(r"hearthwire \([^)]+\) resolute;", (DEBIAN / "changelog").read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert set(re.findall(r"(?m)^\s*container: ubuntu:(\S+)$", workflow)) == {"26.04"}


# --- emails, maintainers ---------------------------------------------------------------------------


def _packaging_files():
    files = [path for path in PACKAGING.rglob("*") if path.is_file()]
    return files + [WORKFLOW, GITATTRIBUTES]


def email_problems(text):
    problems = []
    if "@gmail.com" in text.lower():
        problems.append("a @gmail.com address")
    problems += [f"email {found}" for found in EMAIL.findall(text) if found != ALLOWED_EMAIL]
    return problems


def test_no_packaging_file_names_a_personal_email():
    problems = {str(path.relative_to(ROOT)): email_problems(path.read_text(encoding="utf-8"))
                for path in _packaging_files()}
    assert {path: found for path, found in problems.items() if found} == {}


def test_the_maintainer_is_the_no_reply_identity():
    assert f"# Maintainer: {MAINTAINER}\n" in PKGBUILD.read_text(encoding="utf-8")
    assert f"\nMaintainer: {MAINTAINER}\n" in (DEBIAN / "control").read_text(encoding="utf-8")
    assert f" -- {MAINTAINER}  " in (DEBIAN / "changelog").read_text(encoding="utf-8")
    assert re.search(rf"(?m)^\* \w{{3}} \w{{3}} [ \d]\d \d{{4}} {re.escape(MAINTAINER)} - ",
                     SPEC.read_text(encoding="utf-8"))
    assert f'PACKAGER="{MAINTAINER}"' in WORKFLOW.read_text(encoding="utf-8")


def test_proof_a_personal_email_is_caught():
    assert email_problems(f"# Maintainer: Someone <someone@GMail.com>\n# {MAINTAINER}") == [
        "a @gmail.com address", "email someone@GMail.com"]
    assert email_problems("Maintainer: me <me@example.org>") == ["email me@example.org"]


# --- what the packages install -------------------------------------------------------------------


def test_every_recipe_installs_the_plasmoid_icons_and_events_system_wide():
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    install = (DEBIAN / "install").read_text(encoding="utf-8")
    assert "_plugin=" + PLUGIN in pkgbuild and "usr/share/plasma/plasmoids/$_plugin" in pkgbuild
    assert "%global plugin " + PLUGIN in spec and "%{_datadir}/plasma/plasmoids/%{plugin}" in spec
    assert f"usr/share/plasma/plasmoids/{PLUGIN}/" in install
    assert "usr/share/icons/hicolor/scalable/apps" in pkgbuild and "usr/share/knotifications6" in pkgbuild
    for asset in INSTALLED_ASSETS:
        assert f"assets/{asset} usr/share/" in install
        assert asset in spec
        assert asset.rsplit(".", 1)[0] in pkgbuild
    # The helper is the Python package, so `python3 -P -m hearthwire` finds it.
    assert "python -m installer" in pkgbuild
    assert "%pyproject_install" in spec and "%pyproject_save_files -l hearthwire" in spec
    assert "--buildsystem=pybuild" in (DEBIAN / "rules").read_text(encoding="utf-8")


def test_the_packages_need_qt_quick_shapes_and_python_3_11():
    assert "'qt6-declarative'" in PKGBUILD.read_text(encoding="utf-8")
    assert re.search(r"(?m)^Requires:\s+qt6-qtdeclarative$", SPEC.read_text(encoding="utf-8"))
    control = (DEBIAN / "control").read_text(encoding="utf-8")
    assert " qml6-module-qtquick-shapes," in control
    assert " python3 (>= 3.11)," in control
    assert re.search(r"(?m)^Requires:\s+python3 >= 3.11$", SPEC.read_text(encoding="utf-8"))
    with (ROOT / "pyproject.toml").open("rb") as handle:
        assert tomllib.load(handle)["project"]["requires-python"] == ">=3.11"


def test_no_scriptlets_and_no_home_folders():
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*install=", pkgbuild)
    assert not re.search(r"(?m)^%(pre|post|preun|postun|pretrans|posttrans|triggerin|triggerun|filetriggerin)\b", spec)
    for name in ("preinst", "postinst", "prerm", "postrm", "triggers", "hearthwire.preinst",
                 "hearthwire.postinst", "hearthwire.prerm", "hearthwire.postrm"):
        assert not (DEBIAN / name).exists()
    home = re.compile(r"\$HOME|\$\{HOME\}|~/|/home/|XDG_(CONFIG|DATA|CACHE)_HOME")
    for path in (PKGBUILD, SPEC, *[p for p in DEBIAN.rglob("*") if p.is_file()]):
        assert not home.search(path.read_text(encoding="utf-8")), path


def test_the_shell_scripts_parse():
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no sh")
    for script in (PACKAGING / "check-install.sh", PACKAGING / "source-archive.sh"):
        completed = subprocess.run([sh, "-n", str(script)], capture_output=True, text=True, timeout=30, check=False)
        assert completed.returncode == 0, completed.stderr
        assert script.stat().st_mode & 0o111
    assert (DEBIAN / "rules").stat().st_mode & 0o111
    assert (DEBIAN / "rules").read_text(encoding="utf-8").startswith("#!/usr/bin/make -f\n")


# --- the workflow -----------------------------------------------------------------------------------


def _jobs(text):
    """{job id: its lines}, read by indentation (no YAML parser in the standard library)."""
    jobs, current, inside = {}, None, False
    for line in text.splitlines():
        if line == "jobs:":
            inside = True
            continue
        if not inside:
            continue
        match = re.fullmatch(r"  ([a-z][a-z0-9-]*):", line)
        if match:
            current = match.group(1)
            jobs[current] = []
        elif current is not None:
            jobs[current].append(line)
    return jobs


def test_the_workflow_triggers_on_tags_and_by_hand_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    head = text.split("\njobs:", 1)[0]
    assert re.search(r'(?m)^on:\n  push:\n    tags:\n      - "v\*"\n  workflow_dispatch:\n', head)
    assert "pull_request" not in head and "branches" not in head
    assert re.search(r"(?m)^permissions: \{\}$", head)


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


def pin_problems(text):
    """Actions not pinned to a full commit SHA with a ``# vX.Y.Z`` comment; empty when all are."""
    problems = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(?:- )?uses:\s*(\S+)(.*)", line)
        if not match:
            continue
        action, comment = match.groups()
        if action.startswith("./"):
            continue  # A local action in this repository.
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action):
            problems.append(f"{action}: not pinned to a commit")
        elif not re.fullmatch(r" # v\d+(\.\d+)*", comment):
            problems.append(f"{action}: no version comment")
    return problems


def test_every_action_in_every_workflow_is_pinned_to_a_commit_with_its_version():
    assert {path.name for path in WORKFLOWS} >= {"release.yml", "tests.yml"}
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^\s*(?:- )?uses:", text), path.name
        assert pin_problems(text) == [], path.name


def test_proof_an_unpinned_action_is_caught():
    sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert pin_problems(f"      - uses: actions/checkout@{sha} # v7.0.1\n        uses: ./local") == []
    assert pin_problems("      - uses: actions/checkout@v7\n") == ["actions/checkout@v7: not pinned to a commit"]
    assert pin_problems(f"        uses: actions/checkout@{sha}\n") == [f"actions/checkout@{sha}: no version comment"]
    assert pin_problems(f"        uses: actions/checkout@{sha[:12]} # v7\n") != []


# The CLI's name and subcommand, split so this file's text never holds the command itself.
RELEASE_CLI = "gh" + " release"


def release_problems(body):
    """The release job must make exactly one draft release, never publish one."""
    creates = re.findall(re.escape(RELEASE_CLI) + r" create[^\n]*(?:\\\n[^\n]*)*", body)
    problems = []
    if len(creates) != 1:
        problems.append(f"{len(creates)} release create commands")
    problems += ["a release that is not a draft" for command in creates
                 if not re.search(r"(?<![\w-])--draft(?![\w=-])", command)]
    if re.search(re.escape(RELEASE_CLI) + r" edit|gh api|draft=false", body):
        problems.append("a step that publishes the release")
    return problems


def test_proof_a_published_release_is_caught():
    body = f'    run: |\n      {RELEASE_CLI} create "$TAG" --verify-tag --draft \\\n        --title "x" ./a.deb\n'
    assert release_problems(body) == []
    assert release_problems(body.replace(" --draft", "")) == ["a release that is not a draft"]
    assert release_problems(body.replace("--draft", "--draft=false")) == [
        "a release that is not a draft", "a step that publishes the release"]
    assert release_problems(body + f'      {RELEASE_CLI} edit "$TAG" --draft=false\n') == [
        "a step that publishes the release"]
    assert release_problems("    run: echo\n") == ["0 release create commands"]


def test_only_the_release_job_may_write_and_only_for_a_tag():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = _jobs(text)
    assert {"source", "arch-build", "arch-test", "fedora-build", "fedora-test", "ubuntu-build", "ubuntu-test",
            "checksums", "release"} <= set(jobs)
    for job, lines in jobs.items():
        body = "\n".join(lines)
        if job == "release":
            assert "    permissions:\n      contents: write" in body
            assert "    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in body
            assert release_problems(body) == []
        else:
            assert "contents: write" not in body and "write-all" not in body, job
            assert re.search(r"(?m)^    permissions: \{\}$|^    permissions:\n      contents: read$", body), job
    assert "secrets." not in text
    assert text.count("${{ github.token }}") == 1
    assert "${{ github.ref_name }}" not in "\n".join(line for line in text.splitlines() if "run:" in line)


def test_each_distro_builds_lints_and_install_tests_in_its_own_container():
    jobs = {job: "\n".join(lines) for job, lines in _jobs(WORKFLOW.read_text(encoding="utf-8")).items()}
    expected = {"arch": ("archlinux:", "namcap"), "fedora": ("fedora:44", "rpmlint"),
                "ubuntu": ("ubuntu:26.04", "lintian")}
    for distro, (image, lint) in expected.items():
        assert f"container: {image}" in jobs[f"{distro}-build"]
        assert f"container: {image}" in jobs[f"{distro}-test"]
        assert lint in jobs[f"{distro}-build"] + jobs[f"{distro}-test"]
        assert "packaging/check-install.sh" in jobs[f"{distro}-test"]
        assert f"needs: [source, {distro}-build]" in jobs[f"{distro}-test"]
    assert "needs: [source, arch-test, fedora-test, ubuntu-test]" in jobs["checksums"]
    assert "packaging/source-archive.sh" in jobs["source"]
    assert "sha256sum -- " in jobs["checksums"] and "SHA256SUMS" in jobs["release"]
    assert "RELEASE_NOTES-$VERSION.md" in jobs["release"]
