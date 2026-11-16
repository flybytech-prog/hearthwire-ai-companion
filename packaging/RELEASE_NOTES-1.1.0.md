Hearthwire 1.1.0 gives every chat site its own profile, lets you manage all
chat sites in one table, adds sites on this computer and your home network,
and makes settings backups easier and signed.

## Download

Pick the package for your system:

- **Arch Linux, CachyOS, Manjaro**: `hearthwire-1.1.0-1-any.pkg.tar.zst`
  ```bash
  sudo pacman -U ./hearthwire-1.1.0-1-any.pkg.tar.zst
  ```
- **Fedora KDE** (Fedora 43 and 44): `hearthwire-1.1.0-1.fc44.noarch.rpm`
  ```bash
  sudo dnf install ./hearthwire-1.1.0-1.fc44.noarch.rpm
  ```
- **Kubuntu / Ubuntu 26.04 LTS** with Plasma 6: `hearthwire_1.1.0-1_all.deb`
  ```bash
  sudo apt install ./hearthwire_1.1.0-1_all.deb
  ```

Check the download first with `sha256sum --check --ignore-missing SHA256SUMS`.
Each package also has a build provenance record. With the GitHub CLI, this
shows which workflow run built it from which commit, and fails for a changed
file:

```bash
gh attestation verify ./FILE --repo flybytech-prog/hearthwire-ai-companion \
  --signer-workflow flybytech-prog/hearthwire-ai-companion/.github/workflows/release.yml \
  --source-ref refs/tags/v1.1.0
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

Settings backups: Hearthwire 1.1.0 reads the backups of older versions
(they have no signature, so Import shows a warning, and the import still
works). Hearthwire 1.0.1 can't read a backup made by 1.1.0: it says the
file was "made by a different version".

## What's new

- **One profile per chat site.** Every chat site, built-in or added by you,
  has its own sign-ins, cookies and storage, so no site can use or read
  another site's sign-in.
- **One site table in Settings → Chat.** Turn sites on and off, change their
  order, and add, edit and remove your own `https://` sites (up to 200).
  An added site shows the first letter of its name as its icon. Removing a
  site deletes its saved data; the page warns you before you apply.
- **Sites on this computer and your home network.** You can add a server on
  this computer (`localhost`, `127.0.0.1` or `[::1]`). It loads only when
  the program on that port belongs to you, to root or to the `ollama`
  account. You can also add a device on your home network by its private
  IP address, over `http://` or `https://`; for plain `http://` the editor
  notes that the traffic isn't encrypted. Link-local addresses (which
  include the cloud metadata address) and `100.64.0.0/10` (carrier-grade
  NAT) are refused.
- **Settings backups.** The panel menu has **Back up settings** and
  **Restore settings…**. **Back up automatically when settings are applied**
  (off by default) saves a backup after you press Apply, when a backed-up
  setting changed.
- **Signed backups.** Each backup now carries a checksum and a signature
  made with a key kept only on this computer. Import says "Made by
  Hearthwire on this computer." or warns you when a backup came from
  elsewhere or has no signature, and it refuses a damaged file.
- The longer explanations on the **General** page moved into small **?**
  help buttons.

## Upgrading

After the update, sign in once more to each chat site: the old shared
profile is not used again. The Chat tab says so once (**Got it** hides it).
Going back to 1.0.1 is harmless, but its chat sign-ins start empty too, and
upgrading again starts every chat site signed out once more.

## Good to know

- Needs KDE Plasma 6, Qt 6 and Python 3.11 or newer. The helper uses only
  the Python standard library.
- The backup signing key is kept in your data folder
  (`~/.local/share/hearthwire/backup-key`, only you can read it). Like the
  backup itself, it is not removed with the package; delete them by hand if
  you don't want them.
- Removing the package never deletes your data: usage history, settings
  backup, the encrypted folder and its KDE Wallet key stay in your home
  folder. The README says how to delete them.
- The source code is in the archives below. The packages are built from the
  tag's `git archive` by the release workflow. It saves the release as a
  draft on the Releases page, and a maintainer checks and publishes it by
  hand.
