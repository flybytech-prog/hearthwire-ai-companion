#!/bin/sh
# Make the source tarball the packages are built from: `git archive` of one
# commit (the release tag), never the working tree. .gitattributes decides
# what is left out (tests, CI, local notes, anything git-ignored).
#
# Usage: packaging/source-archive.sh REF OUTPUT_DIRECTORY
# Writes OUTPUT_DIRECTORY/hearthwire-VERSION.tar.gz with the top folder
# hearthwire-VERSION/, and prints its path. VERSION is pyproject.toml's at REF.
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 REF OUTPUT_DIRECTORY" >&2
    exit 2
fi
ref=$1
output_directory=$2

repository=$(git rev-parse --show-toplevel)
commit=$(git -C "$repository" rev-parse --verify --quiet "$ref^{commit}") || {
    echo "Not a commit: $ref" >&2
    exit 1
}
# The version check and pyproject.toml both come from the commit itself, not
# from the working tree. -I: only the standard library, nothing from the
# working folder or the environment.
checker=$(mktemp)
trap 'rm -f -- "$checker"' EXIT
git -C "$repository" show "$commit:packaging/check-version.py" > "$checker"
version=$(git -C "$repository" show "$commit:pyproject.toml" | python3 -I "$checker") || {
    echo "pyproject.toml at $ref has no plain X.Y.Z version" >&2
    exit 1
}
# The same rule again in sh: digits and exactly two dots, nothing else.
case "$version" in
    *[!0-9.]* | .* | *. | *..* | "")
        echo "pyproject.toml at $ref has no plain X.Y.Z version" >&2
        exit 1
        ;;
esac
case "$version" in
    *.*.*.*) echo "pyproject.toml at $ref has no plain X.Y.Z version" >&2; exit 1 ;;
    *.*.*) ;;
    *) echo "pyproject.toml at $ref has no plain X.Y.Z version" >&2; exit 1 ;;
esac

mkdir -p -- "$output_directory"
# Absolute, since git -C resolves a relative --output against the repository.
output_directory=$(CDPATH= cd -- "$output_directory" && pwd)
archive="$output_directory/hearthwire-$version.tar.gz"
# gzip -n leaves out the name and time, so the same commit gives the same bytes.
git -C "$repository" -c tar.tar.gz.command="gzip -cn" archive \
    --format=tar.gz --prefix="hearthwire-$version/" --output="$archive" "$commit"
printf '%s\n' "$archive"
