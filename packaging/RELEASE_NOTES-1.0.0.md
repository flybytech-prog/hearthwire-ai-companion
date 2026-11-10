Hearthwire 1.0.0 is the first packaged release. It is an AI companion for
the KDE Plasma 6 panel: chat with AI sites, and see how much of your AI
coding plans is left.

## Download

Pick the package for your system:

- **Arch Linux, CachyOS, Manjaro**: `hearthwire-1.0.0-1-any.pkg.tar.zst`
  ```bash
  sudo pacman -U ./hearthwire-1.0.0-1-any.pkg.tar.zst
  ```
- **Fedora KDE** (Fedora 43 and 44): `hearthwire-1.0.0-1.fc44.noarch.rpm`
  ```bash
  sudo dnf install ./hearthwire-1.0.0-1.fc44.noarch.rpm
  ```
- **Kubuntu / Ubuntu 26.04 LTS** with Plasma 6: `hearthwire_1.0.0-1_all.deb`
  ```bash
  sudo apt install ./hearthwire_1.0.0-1_all.deb
  ```

Check the download first with `sha256sum --check --ignore-missing SHA256SUMS`.
Each package also has a build provenance record. With the GitHub CLI, this
shows which workflow run built it from which commit, and fails for a changed
file:

```bash
gh attestation verify ./FILE --repo flybytech-prog/hearthwire-ai-companion \
  --signer-workflow flybytech-prog/hearthwire-ai-companion/.github/workflows/release.yml \
  --source-ref refs/tags/v1.0.0
```

Then right-click the panel, choose **Add Widgets…**, search for
**Hearthwire** and add it. Restart Plasma or log out and in once if it isn't
listed yet.

## Compatibility

Each package is built for its system's Python version:

- **Fedora**: 43 and 44 (Python 3.14). It does not install on Fedora 45,
  which moves to Python 3.15.
- **Arch, CachyOS, Manjaro**: built for Python 3.14. It must be rebuilt when
  Arch moves to Python 3.15.
- **Ubuntu**: 26.04 LTS. Its helper sits in Ubuntu's shared Python folder,
  so a later Python update there doesn't need a rebuild.

## What's in it

Chat:

- Use Claude, ChatGPT, Grok, Gemini, GitHub Copilot, Microsoft Copilot or a
  local web UI right in the popup.
- Split view shows two chat sites side by side.
- Private by default: chat pages live in memory only. Every site permission
  is denied.
- Optional built-in chat with your own Ollama models. The conversation stays
  in memory.
- Optional "Stay signed in" keeps sign-ins in an encrypted folder with a
  passphrase you choose. It can also open with a key from KDE Wallet.
- A prompt library for prompts and personalities you reuse.

Usage:

- Shows what is left of Claude Code, Codex, Cursor, Antigravity, GitHub
  Copilot, Devin and Grok plans, with reset times.
- A ring around the panel icon shows one reading in warning colors.
- The hover popup lists each provider's readings, each with a colored dot.
- Accent strips tell providers apart. A "Next reset" line names the soonest
  reset.
- Optional notifications when a plan runs low and when it resets.
- New and optional: a 7-day usage history with a small graph under each bar.
  It is off by default and stays on this computer.

Settings:

- Choose the providers, their order and their readings.
- Pick the warning levels and colors, with a live preview.
- Choose what a middle-click on the panel icon does.
- New: export your settings to a backup file and import them again. The
  backup never holds sign-ins.

## Good to know

- Needs KDE Plasma 6, Qt 6 and Python 3.11 or newer. The helper uses only
  the Python standard library.
- The Chat tab needs Qt WebEngine. Stay signed in needs gocryptfs, fuse3 and
  kdialog. The packages recommend or suggest these; install them if you want
  those features.
- Removing the package never deletes your data: usage history, settings
  backup, the encrypted folder and its KDE Wallet key stay in your home
  folder. The README says how to delete them.
- Upgrading from an earlier install made with `scripts/install.sh`, or from
  AI Usage 2.x? Read "Install from a package" in the README first.
- The source code is in the archives below. The packages are built from the
  tag's `git archive` by the release workflow. It saves the release as a
  draft on the Releases page, and a maintainer checks and publishes it by
  hand.
