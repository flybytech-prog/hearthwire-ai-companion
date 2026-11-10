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
import sys
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
            "packaging/debian/rules", "packaging/check-install.sh", "packaging/source-archive.sh", "packaging/check-version.py",
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
    files = [path for path in PACKAGING.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
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
    joined = re.sub(r"\\\n\s*", " ", body)  # Shell line continuations.
    creates = re.findall(re.escape(RELEASE_CLI) + r" create[^\n]*", joined)
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
    assert "needs: [source, arch-build, fedora-build, ubuntu-build, arch-test, fedora-test, ubuntu-test]" in jobs["checksums"]
    assert "packaging/source-archive.sh" in jobs["source"]
    assert "sha256sum -- " in jobs["checksums"] and "SHA256SUMS" in jobs["release"]
    assert "RELEASE_NOTES-$VERSION.md" in jobs["release"]


# --- the audit's supply-chain rules (M1, L1, L2, L3, I1) -------------------------------------------

REQUIREMENTS = ROOT / ".github" / "requirements-test.txt"
CHECK_VERSION = PACKAGING / "check-version.py"
SHA256_CHECK = "sha256sum --check --strict -"


def _workflow_jobs():
    return {job: "\n".join(lines) for job, lines in _jobs(WORKFLOW.read_text(encoding="utf-8")).items()}


def _steps(body):
    """The steps of a job body, one text each (split at ``- name:``)."""
    parts = re.split(r"(?m)^      - (?=name: )", body.split("\n    steps:\n", 1)[1])
    return [part for part in parts if part.strip()]


def _downloads(body):
    return [step for step in _steps(body) if "uses: actions/download-artifact@" in step]


# M1: the tarball job runs no third-party code but checkout and upload-artifact.
ALLOWED_IN_SOURCE = ("actions/checkout@", "actions/upload-artifact@")
FORBIDDEN_IN_SOURCE = re.compile(r"\bpip\b|pytest|venv|setup-python|requirements|npm|make\b|\.\[test\]")


def source_job_problems(body):
    problems = []
    if FORBIDDEN_IN_SOURCE.search(body):
        problems.append("the tarball job installs or runs third-party code")
    for action in re.findall(r"uses: (\S+)", body):
        if not action.startswith(ALLOWED_IN_SOURCE):
            problems.append(f"the tarball job uses {action.split('@')[0]}")
    if re.search(r"(?m)^    needs:", body):
        problems.append("the tarball job waits for another job")
    steps = _steps(body)
    archive = [index for index, step in enumerate(steps) if "packaging/source-archive.sh" in step]
    if len(archive) != 1:
        problems.append("the tarball is not made exactly once")
    return problems


def test_the_tarball_job_runs_no_pip_or_tests():
    jobs = _workflow_jobs()
    assert source_job_problems(jobs["source"]) == []
    assert "fetch-depth: 0" in jobs["source"] and "persist-credentials: false" in jobs["source"]
    assert "sha256: ${{ steps.tarball.outputs.sha256 }}" in jobs["source"]


def test_proof_pip_or_a_test_in_the_tarball_job_is_caught():
    body = _workflow_jobs()["source"]
    for added in ('          python3 -m pip install ".[test]"\n', "          python3 -m pytest\n"):
        mutated = body.replace("      - name: Make the source tarball\n",
                               "      - name: Make the source tarball\n        run: |\n" + added, 1)
        assert "the tarball job installs or runs third-party code" in source_job_problems(mutated)
    with_action = body + "\n      - name: x\n        uses: actions/setup-python@" + "0" * 40 + " # v7.1.0\n"
    assert "the tarball job uses actions/setup-python" in source_job_problems(with_action)
    assert "the tarball job waits for another job" in source_job_problems("    needs: tests\n" + body)


def leaks_from_the_tests_job(jobs):
    problems = []
    tests = jobs["tests"]
    if "upload-artifact" in tests or re.search(r"(?m)^    outputs:", tests):
        problems.append("the tests job can publish something")
    if any("needs.tests.outputs" in body for body in jobs.values()):
        problems.append("a job reads the tests job's outputs")
    if re.search(r"(?m)^    needs:.*\btests\b", jobs["source"]):
        problems.append("the tarball job depends on the tests job")
    return problems


def test_the_tests_job_cannot_feed_the_tarball_or_a_package():
    jobs = _workflow_jobs()
    assert leaks_from_the_tests_job(jobs) == []
    # The builds still wait for the tests to pass.
    for distro in ("arch", "fedora", "ubuntu"):
        assert "    needs: [source, tests]" in jobs[f"{distro}-build"]


def test_proof_a_tests_job_that_uploads_is_caught():
    jobs = _workflow_jobs()
    uploading = dict(jobs, tests=jobs["tests"] + "\n      - name: x\n        uses: actions/upload-artifact@x\n")
    assert leaks_from_the_tests_job(uploading) == ["the tests job can publish something"]
    reading = dict(jobs, release=jobs["release"] + "\n      X: ${{ needs.tests.outputs.sha256 }}\n")
    assert leaks_from_the_tests_job(reading) == ["a job reads the tests job's outputs"]


def requirements_problems(text):
    problems = []
    entries = re.split(r"(?m)^(?=[A-Za-z])", "\n".join(line for line in text.splitlines()
                                                     if not line.lstrip().startswith("#")))
    entries = [entry.strip() for entry in entries if entry.strip()]
    if not entries:
        problems.append("no requirements")
    for entry in entries:
        name = entry.split()[0]
        if not re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.]*", name):
            problems.append(f"{name}: not pinned with ==")
        if not re.search(r"--hash=sha256:[0-9a-f]{64}\b", entry):
            problems.append(f"{name}: no sha256 hash")
    return problems


def pip_problems(text):
    problems = []
    joined = re.sub(r"\\\n\s*", " ", text)  # Shell line continuations.
    for flat in re.findall(r"pip install[^\n]*", joined):
        if "--require-hashes" not in flat or "-r .github/requirements-test.txt" not in flat:
            problems.append(f"unpinned: {flat.strip()}")
        elif re.search(r"\s(\.|\"\.\[test\]\"|'\.\[test\]')(\s|$)", flat):
            problems.append(f"installs the checkout: {flat.strip()}")
    return problems


def test_test_dependencies_are_pinned_with_hashes_in_every_workflow():
    assert requirements_problems(REQUIREMENTS.read_text(encoding="utf-8")) == []
    names = {entry.split("==")[0].lower() for entry in re.findall(r"(?m)^([A-Za-z][^\s\\]*)",
                                                                    REQUIREMENTS.read_text(encoding="utf-8"))}
    assert "pytest" in names
    installs = 0
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        installs += len(re.findall(r"pip install", text))
        assert pip_problems(text) == [], path.name
    assert installs >= 2  # release.yml's tests job and tests.yml


def test_proof_unpinned_test_dependencies_are_caught():
    assert pip_problems('        run: python -m pip install ".[test]"\n') == ['unpinned: pip install ".[test]"']
    assert pip_problems("pip install --require-hashes -r .github/requirements-test.txt .\n") != []
    assert requirements_problems("pytest==9.2.0\n") == ["pytest==9.2.0: no sha256 hash"]
    assert requirements_problems("pytest>=9 \\\n    --hash=sha256:" + "a" * 64 + "\n") == ["pytest>=9: not pinned with =="]


def download_problems(text):
    problems = []
    for job, body in _jobs(text).items():
        for step in _downloads("\n".join(body)):
            if "pattern:" in step or "merge-multiple" in step:
                problems.append(f"{job}: a download by pattern")
            if not re.search(r"(?m)^          name: [a-z][a-z0-9-]*$", step):
                problems.append(f"{job}: a download without an exact name")
    return problems


def test_every_artifact_is_downloaded_by_its_exact_name():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert download_problems(text) == []
    assert "pattern:" not in text and "merge-multiple" not in text


def test_proof_a_pattern_download_is_caught():
    text = WORKFLOW.read_text(encoding="utf-8")
    mutated = text.replace("          name: package-arch\n          path: ${{ runner.temp }}/arch\n",
                           "          pattern: package-*\n          merge-multiple: true\n"
                           "          path: ${{ runner.temp }}/arch\n", 1)
    assert mutated != text
    assert {problem.split(":")[0] for problem in download_problems(mutated)} == {"checksums"}


# Which job made each artifact, and the env names that carry its sha256.
ARTIFACT_MAKERS = {"source": "source", "package-arch": "arch-build", "package-fedora": "fedora-build",
                   "package-ubuntu": "ubuntu-build"}


def sha256_problems(jobs):
    problems = []
    for build in ("arch-build", "fedora-build", "ubuntu-build"):
        for output in ("file", "sha256"):
            if f"      {output}: ${{{{ steps.package.outputs.{output} }}}}" not in jobs[build]:
                problems.append(f"{build}: no {output} output")
    for job, body in jobs.items():
        steps = _steps(body) if "\n    steps:\n" in body else []
        downloaded = [re.search(r"(?m)^          name: (\S+)$", step).group(1) for step in _downloads(body)]
        for artifact in downloaded:
            maker = ARTIFACT_MAKERS.get(artifact)
            if maker is None or maker == job:
                continue
            if f"${{{{ needs.{maker}.outputs.sha256 }}}}" not in body:
                problems.append(f"{job}: {artifact} is not checked against needs.{maker}.outputs.sha256")
        if downloaded and not any(SHA256_CHECK in step for step in steps):
            problems.append(f"{job}: downloads are never checked")
        # The check comes before anything unpacks, installs or publishes the files.
        checks = [index for index, step in enumerate(steps) if SHA256_CHECK in step]
        uses = [index for index, step in enumerate(steps)
                if re.search(r"tar -xzf|pacman -U|dnf -y install \"/tmp/package|apt-get install -y \"/tmp/package"
                             r"|attest-build-provenance|" + re.escape(RELEASE_CLI), step)]
        if downloaded and uses and (not checks or min(checks) > min(uses)):
            problems.append(f"{job}: a download is used before it is checked")
    return problems


def test_every_download_is_checked_against_the_makers_sha256_output():
    jobs = _workflow_jobs()
    assert sha256_problems(jobs) == []
    # The checksums and release jobs take all three packages by their outputs.
    for job in ("checksums", "release"):
        assert len(re.findall(r"(?m)^          take \w+ ", jobs[job])) == 3
        for distro in ("ARCH", "FEDORA", "UBUNTU"):
            assert f'"${distro}_FILE" "${distro}_SHA256"' in jobs[job]


def test_proof_an_unchecked_download_is_caught():
    jobs = _workflow_jobs()
    unchecked = dict(jobs, **{"fedora-test": jobs["fedora-test"].replace(
        "      PACKAGE_SHA256: ${{ needs.fedora-build.outputs.sha256 }}\n", "")})
    assert sha256_problems(unchecked) == [
        "fedora-test: package-fedora is not checked against needs.fedora-build.outputs.sha256"]
    blind = dict(jobs, **{"arch-test": jobs["arch-test"].replace(SHA256_CHECK, "true")})
    assert "arch-test: downloads are never checked" in sha256_problems(blind)
    no_output = dict(jobs, **{"ubuntu-build": jobs["ubuntu-build"].replace(
        "      sha256: ${{ steps.package.outputs.sha256 }}\n", "")})
    assert sha256_problems(no_output) == ["ubuntu-build: no sha256 output"]


def _check_version(stdin, *arguments):
    completed = subprocess.run([sys.executable, "-I", str(CHECK_VERSION), *arguments], input=stdin,
                               capture_output=True, text=True, timeout=30, check=False)
    return completed.returncode, completed.stdout


@pytest.mark.parametrize("version", ["1.0.0\nversion=9.9.9", "1.0.0 ", "1.0", "1.0.0.1", "v1.0.0", "1.0.0rc1",
                                     "01.0.0x", "", "1.0.0\n"])
def test_the_version_check_refuses_anything_but_x_y_z(version):
    pyproject = "[project]\nversion = " + json.dumps(version) + "\n"
    assert _check_version(pyproject) == (1, "")


@pytest.mark.parametrize("tag", ["1.0.0", "v1.0.0\n", "v1.0.0x", "v1.0", "refs/tags/v1.0.0", "v1.0.0\nx=y", ""])
def test_the_tag_must_be_exactly_v_and_the_version(tag):
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert _check_version(pyproject, "--tag", tag) == (1, "")


def test_the_version_check_accepts_the_release():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = _pyproject_version()
    assert _check_version(pyproject) == (0, version + "\n")
    assert _check_version(pyproject, "--tag", "v" + version) == (0, version + "\n")


def test_proof_the_old_glob_let_a_newline_through():
    import fnmatch

    assert fnmatch.fnmatchcase("1.0.0\nversion=9.9.9", "[0-9]*.[0-9]*.[0-9]*")
    assert _check_version('[project]\nversion = "1.0.0\\nversion=9.9.9"\n') == (1, "")


def test_every_version_and_tag_check_uses_the_strict_checker():
    jobs = _workflow_jobs()
    assert 'python3 -I packaging/check-version.py --tag "$REF_NAME" < pyproject.toml' in jobs["source"]
    assert 'python3 -I packaging/check-version.py --tag "$TAG" < pyproject.toml' in jobs["release"]
    assert '[ "$REF_TYPE" = tag ]' in jobs["source"]
    script = (PACKAGING / "source-archive.sh").read_text(encoding="utf-8")
    assert 'git -C "$repository" show "$commit:packaging/check-version.py"' in script
    assert '| python3 -I "$checker"' in script
    assert "[0-9]*.[0-9]*.[0-9]*" not in script + WORKFLOW.read_text(encoding="utf-8")
    # The version is written to $GITHUB_OUTPUT only after the check.
    source = jobs["source"]
    assert source.index("check-version.py") < source.index('echo "version=$version" >> "$GITHUB_OUTPUT"')


ANCESTOR = 'git merge-base --is-ancestor "$GITHUB_SHA" refs/remotes/origin/main'


def ancestor_problems(body):
    problems = []
    if "fetch-depth: 0" not in body:
        problems.append("main's history is not fetched")
    step = next((step for step in _steps(body) if ANCESTOR in step), None)
    if step is None:
        problems.append("no ancestor check")
    elif not re.search(r'if \[ "\$EVENT_NAME" = push \]; then\n(?:.*\n)*?\s*' + re.escape(ANCESTOR) + r" \\\n"
                       r"\s*\|\| \{ [^\n]*exit 1; \}", step):
        problems.append("the ancestor check does not stop a tag push")
    elif body.index(ANCESTOR) > body.index("packaging/source-archive.sh"):
        problems.append("the tarball is made before the ancestor check")
    return problems


def test_a_tag_push_must_be_on_main():
    assert ancestor_problems(_workflow_jobs()["source"]) == []


def test_proof_a_missing_ancestor_check_is_caught():
    body = _workflow_jobs()["source"]
    assert ancestor_problems(body.replace(ANCESTOR, "true")) == ["no ancestor check"]
    assert ancestor_problems(body.replace("fetch-depth: 0", "fetch-depth: 1")) == ["main's history is not fetched"]
    soft = body.replace('|| { echo "::error::The tagged commit is not on main"; exit 1; }', "|| true")
    assert ancestor_problems(soft) == ["the ancestor check does not stop a tag push"]


def provenance_problems(jobs):
    problems = []
    for job, body in jobs.items():
        grants = re.findall(r"(?m)^      (id-token|attestations): write$", body)
        if job == "release":
            if sorted(grants) != ["attestations", "id-token"]:
                problems.append("the release job lacks id-token or attestations write")
        elif grants:
            problems.append(f"{job}: grants {', '.join(sorted(grants))} write")
        if job != "release" and "attest-build-provenance" in body:
            problems.append(f"{job}: attests")
    release = _steps(jobs["release"])
    attest = [index for index, step in enumerate(release) if "uses: actions/attest-build-provenance@" in step]
    create = [index for index, step in enumerate(release) if RELEASE_CLI + " create" in step]
    if len(attest) != 1:
        problems.append("the release files are not attested exactly once")
    elif not create or attest[0] > create[0]:
        problems.append("the release is created before its files are attested")
    else:
        for name in ("arch-build", "fedora-build", "ubuntu-build"):
            if f"${{{{ needs.{name}.outputs.file }}}}" not in release[attest[0]]:
                problems.append(f"the {name} package is not attested")
        if "/release/SHA256SUMS" not in release[attest[0]]:
            problems.append("SHA256SUMS is not attested")
    return problems


def test_provenance_permissions_are_on_the_release_job_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert provenance_problems(_workflow_jobs()) == []
    head = text.split("\njobs:", 1)[0]
    assert "id-token" not in head and "attestations" not in head
    assert re.search(r"uses: actions/attest-build-provenance@[0-9a-f]{40} # v\d+\.\d+\.\d+", text)


def test_proof_provenance_permissions_elsewhere_are_caught():
    jobs = _workflow_jobs()
    leaky = dict(jobs, tests=jobs["tests"].replace("      contents: read\n",
                                                   "      contents: read\n      id-token: write\n", 1))
    assert provenance_problems(leaky) == ["tests: grants id-token write"]
    missing = dict(jobs, release=jobs["release"].replace("      attestations: write\n", ""))
    assert provenance_problems(missing) == ["the release job lacks id-token or attestations write"]
    unattested = dict(jobs, release=jobs["release"].replace("uses: actions/attest-build-provenance@", "uses: x/y@"))
    assert provenance_problems(unattested) == ["the release files are not attested exactly once"]


def rebuild_problems(body):
    problems = []
    steps = _steps(body)
    rebuild = [index for index, step in enumerate(steps)
               if "packaging/source-archive.sh" in step and "cmp -- " in step and SHA256_CHECK in step]
    create = [index for index, step in enumerate(steps) if RELEASE_CLI + " create" in step]
    if not re.search(r"uses: actions/checkout@", steps[0]):
        problems.append("the release job does not check out the tag first")
    if len(rebuild) != 1:
        problems.append("the tarball is not rebuilt and compared")
    elif not create or rebuild[0] > create[0]:
        problems.append("the release is created before the rebuild is compared")
    return problems


def test_the_release_job_rebuilds_the_tarball_and_compares_the_bytes():
    assert rebuild_problems(_workflow_jobs()["release"]) == []


def test_proof_a_release_without_the_rebuild_is_caught():
    body = _workflow_jobs()["release"]
    assert rebuild_problems(body.replace('cmp -- "$rebuilt"', 'true "$rebuilt"')) == [
        "the tarball is not rebuilt and compared"]


def test_the_tarball_is_reproducible_for_the_same_commit(tmp_path):
    # Two archives of HEAD, the way source-archive.sh makes them, are the same bytes.
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    archives = []
    for name in ("a.tar.gz", "b.tar.gz"):
        output = tmp_path / name
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "-c", "tar.tar.gz.command=gzip -cn", "archive", "--format=tar.gz",
             "--prefix=hearthwire-test/", f"--output={output}", "HEAD"],
            capture_output=True, timeout=120, check=False)
        if completed.returncode != 0:
            pytest.skip("git archive is not usable here")
        archives.append(output.read_bytes())
    assert archives[0] == archives[1]
    script = (PACKAGING / "source-archive.sh").read_text(encoding="utf-8")
    assert '-c tar.tar.gz.command="gzip -cn" archive' in script


def plain_scalar_problems(text):
    """Plain (unquoted, one-line) values holding ": " or " #", which YAML misreads."""
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r"\s*(?:- )?[A-Za-z_-]+: (.*)", line)
        if not match:
            continue
        value = match.group(1)
        if value[:1] in ("|", ">", '"', "'", "[", "{", "&", "*", "!") or value.startswith("${{"):
            continue
        body = value.split(" # ", 1)[0] if re.search(r"@[0-9a-f]{40} # ", value) else value
        if ": " in body or body.endswith(":"):
            problems.append(f"line {number}: {line.strip()}")
    return problems


def test_no_workflow_has_a_plain_value_yaml_would_misread():
    for path in WORKFLOWS:
        assert plain_scalar_problems(path.read_text(encoding="utf-8")) == [], path.name


def test_proof_a_colon_in_a_plain_run_value_is_caught():
    line = "        run: python -m pip install --only-binary=:all: -r x.txt"
    assert plain_scalar_problems(line) == ["line 1: run: python -m pip install --only-binary=:all: -r x.txt"]
    assert plain_scalar_problems("        run: |\n          pip install --only-binary=:all: -r x\n") == []
