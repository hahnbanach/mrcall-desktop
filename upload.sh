#!/usr/bin/env bash
# Upload script for mrcall-desktop: commit, bump versions, tag, push to GitHub.
#
# Modeled on mrcall-dashboard/upload.sh, adapted for this repo:
#   - Remote is GitHub (not GitLab); default-branch check uses git/gh
#     instead of glab.
#   - No env-branch merging (test-env / beta-env / production-env do
#     not exist here — the release pipeline is tag-driven via
#     .github/workflows/release.yml listening for `v*`).
#   - Versions live in THREE places that must stay in sync:
#       (a) the git tag itself (e.g. v0.1.26)
#       (b) app/package.json `"version"` (electron-builder reads it
#           for the .dmg / .exe filename and Sparkle-style updates)
#       (c) engine/pyproject.toml `version` (PyInstaller + zylch CLI)
#     This script bumps (b) and (c) BEFORE creating the tag and
#     commits the bump, so the tag points at a commit whose source
#     tree already declares the new version.
#
# Usage: ./upload.sh 'commit message'

set -euo pipefail

confirm() {
  read -rp "$1 [Yn] " answer
  [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]
}

get_latest_tag() {
  # `head -1` is fine here: this is a SORTED stream from git, not a
  # truncated search result. The "fetch them all" rule applies to
  # query/list capping, not to "give me the maximum element".
  git tag --sort=-v:refname --list 'v[0-9]*' | head -1 || true
}

bump_app_version() {
  # Rewrite app/package.json `"version": "..."` to $1 in place.
  # Uses python -m json.tool through a small json mutator so we
  # preserve key order and indentation. node would also work but
  # adds a tooling dependency this script otherwise doesn't need.
  local new_ver="$1"
  python3 - "$new_ver" <<'PY'
import json, sys
new_ver = sys.argv[1]
path = "app/package.json"
with open(path) as f:
    data = json.load(f)
data["version"] = new_ver
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

bump_engine_version() {
  # Rewrite engine/pyproject.toml `version = "..."` to $1.
  local new_ver="$1"
  python3 - "$new_ver" <<'PY'
import re, sys
new_ver = sys.argv[1]
path = "engine/pyproject.toml"
with open(path) as f:
    src = f.read()
# Match the FIRST top-level `version = "..."` line — pyproject's
# [project] table. This is structured TOML, so a targeted regex is
# fine; we are not parsing free prose here.
new_src, n = re.subn(
    r'(?m)^version\s*=\s*"[^"]+"',
    f'version = "{new_ver}"',
    src,
    count=1,
)
if n != 1:
    raise SystemExit(f"could not find a single `version = \"...\"` in {path}")
with open(path, "w") as f:
    f.write(new_src)
PY
}

MSG="${1:?Usage: ./upload.sh 'commit message'}"

# --- Default-branch check (no glab needed) -----------------------
DEFAULT_BRANCH=""
if git symbolic-ref refs/remotes/origin/HEAD >/dev/null 2>&1; then
  DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's@^origin/@@')
fi
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [[ -n "$DEFAULT_BRANCH" && "$CURRENT_BRANCH" != "$DEFAULT_BRANCH" ]]; then
  echo "⚠  You are on '$CURRENT_BRANCH', default branch is '$DEFAULT_BRANCH'"
  read -rp "Continue anyway? [yN] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

# --- Commit pending changes (with the user's message) -----------
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "Changes detected:"
  git status --short
  echo ""
  if confirm "Commit with message '$MSG'?"; then
    git add -u
    for f in $(git ls-files --others --exclude-standard); do
      if confirm "  Add new file '$f'?"; then
        git add "$f"
      fi
    done
    if git diff --cached --quiet; then
      echo "Nothing staged — skipping commit."
    else
      git commit -m "$MSG"
      echo "Committed."
    fi
  else
    echo "Skipped commit."
  fi
else
  # Working tree is clean. This is the normal case when the user
  # crafted commits by hand before running the release script. The
  # alarming-looking "No working-tree changes to commit" wording
  # used to live here, but it reads like an error to the eye even
  # though it just means "you're already up-to-date locally" —
  # phrase positively so the user doesn't bail out thinking the
  # script didn't pick up their commits.
  echo "Working tree clean — proceeding with version bump + tag + push."
  echo "Your message will be used as the tag annotation."
fi

# --- Compute next tag --------------------------------------------
LATEST_TAG=$(get_latest_tag)
if [[ -z "$LATEST_TAG" ]]; then
  echo "Error: no existing v* tags found."
  exit 1
fi

# Split tag into parts: v0.1.25 → prefix=v0.1 patch=25
PREFIX="${LATEST_TAG%.*}"
PATCH="${LATEST_TAG##*.}"
NEXT_PATCH=$((PATCH + 1))
NEW_TAG="${PREFIX}.${NEXT_PATCH}"
NEW_VERSION="${NEW_TAG#v}"   # strip leading "v" for package.json / pyproject.toml

echo "Latest tag: $LATEST_TAG"
echo "Next tag:   $NEW_TAG  (version $NEW_VERSION)"

if ! confirm "Bump app/package.json + engine/pyproject.toml to $NEW_VERSION and tag $NEW_TAG?"; then
  echo "Aborted."; exit 0
fi

# --- Bump version files + dedicated commit ----------------------
bump_app_version "$NEW_VERSION"
bump_engine_version "$NEW_VERSION"

git add app/package.json engine/pyproject.toml
if git diff --cached --quiet; then
  echo "Versions already at $NEW_VERSION — skipping bump commit."
else
  git commit -m "chore(release): bump version to $NEW_VERSION"
  echo "Committed version bump."
fi

# --- Create the annotated tag -----------------------------------
# Tag annotation: prefer the user-supplied $MSG so the release notes
# carry meaning ("Search email and task dedup", not "Release v0.1.26").
# Falls back to a generic placeholder only if $MSG is empty (it's
# required upstream but be defensive).
TAG_MSG="${MSG:-Release $NEW_TAG}"
git tag -a "$NEW_TAG" -m "$NEW_TAG — $TAG_MSG"
echo "Tagged $NEW_TAG."

# --- Push branch + tag ------------------------------------------
if confirm "Push $CURRENT_BRANCH + $NEW_TAG to origin?"; then
  git push origin "$CURRENT_BRANCH"
  git push origin "$NEW_TAG"
  echo "Pushed."
else
  echo "Tag created locally but NOT pushed. To push later:"
  echo "  git push origin $CURRENT_BRANCH && git push origin $NEW_TAG"
  exit 0
fi

# --- Optional: also publish a -intel companion tag --------------
# The release workflow listens for `v*` (default macOS arm64 +
# Windows x64). A separate tag `v*-intel` opts into the paid
# macos-13-large runner for an Intel x64 .dmg. Off by default; ask.
INTEL_TAG="${NEW_TAG}-intel"
if confirm "Also push companion tag $INTEL_TAG (paid Intel macOS runner)?"; then
  git tag -a "$INTEL_TAG" -m "$INTEL_TAG — $TAG_MSG (Intel x64 opt-in)"
  git push origin "$INTEL_TAG"
  echo "Pushed $INTEL_TAG."
fi
