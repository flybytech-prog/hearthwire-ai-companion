Hearthwire 1.0.1 is a small update to 1.0.0. It makes moving from a script
install to a package safe and easy, and the install hints now fit your
system.

## Download

Pick the package for your system:

- **Arch Linux, CachyOS, Manjaro**: `hearthwire-1.0.1-1-any.pkg.tar.zst`
  ```bash
  sudo pacman -U ./hearthwire-1.0.1-1-any.pkg.tar.zst
  ```
- **Fedora KDE** (Fedora 43 and 44): `hearthwire-1.0.1-1.fc44.noarch.rpm`
  ```bash
  sudo dnf install ./hearthwire-1.0.1-1.fc44.noarch.rpm
  ```
- **Kubuntu / Ubuntu 26.04 LTS** with Plasma 6: `hearthwire_1.0.1-1_all.deb`
  ```bash
  sudo apt install ./hearthwire_1.0.1-1_all.deb
  ```

Check the download first with `sha256sum --check --ignore-missing SHA256SUMS`.
Each package also has a build provenance record. With the GitHub CLI, this
shows which workflow run built it from which commit, and fails for a changed
file:

```bash
gh attestation verify ./FILE --repo flybytech-prog/hearthwire-ai-companion \
  --signer-workflow flybytech-prog/hearthwire-ai-companion/.github/workflows/release.yml \
  --source-ref refs/tags/v1.0.1
```

Then right-click the panel, choose **Add Widgets…**, search for
**Hearthwire** and add it. Restart Plasma or log out and in once if it isn't
listed yet.

## Used the script install before?

Install the package, then remove the script's copy from your checkout and
restart Plasma:

```bash
./scripts/install.sh --remove-script-install --restart-plasma
```

It removes only the script's helper, widget, icons and events file. Your
data, settings and sign-ins stay. Until you do this, the older script copy
keeps running instead of the package.

## Compatibility

Each package is built for its system's Python version:

- **Fedora**: 43 and 44 (Python 3.14). It does not install on Fedora 45,
  which moves to Python 3.15.
- **Arch, CachyOS, Manjaro**: built for Python 3.14. It must be rebuilt when
  Arch moves to Python 3.15.
- **Ubuntu**: 26.04 LTS. Its helper sits in Ubuntu's shared Python folder,
  so a later Python update there doesn't need a rebuild.

## What's new

- The widget warns when an older script install hides the installed
  package. The notice shows on **Settings → General** and in the Usage tab.
- New: `./scripts/install.sh --remove-script-install` removes a script
  install, so the package can take over.
- Install hints now name the right command for Arch, Fedora and
  Debian/Ubuntu. They also show when only a script install is there.
- `install.sh` works better next to an installed package. It decides
  correctly when to use kpackagetool6 in your user folder, and a rollback
  only touches your own helper.
- New helper command: `--install-info`. The widget runs it once at start to
  find a script install that hides the package.
- New screenshots in the README.

## Good to know

- Needs KDE Plasma 6, Qt 6 and Python 3.11 or newer. The helper uses only
  the Python standard library.
- Removing the package never deletes your data: usage history, settings
  backup, the encrypted folder and its KDE Wallet key stay in your home
  folder. The README says how to delete them.
- The source code is in the archives below. The packages are built from the
  tag's `git archive` by the release workflow. It saves the release as a
  draft on the Releases page, and a maintainer checks and publishes it by
  hand.
