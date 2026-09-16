#!/usr/bin/env bash
# Release script for mrcall-desktop: commit, bump versions, tag, push to GitHub.
#
# Same command surface as mrcall-dashboard/update.sh (-m to cut a release,
# -p to backfill the companion tags of the latest one), over this repo's
# release model:
#   - A release IS an annotated `vX.Y.Z` tag on origin:
#     .github/workflows/release.yml builds macOS arm64 + attaches the
#     installers to a GitHub Release on any `v*` tag push. There are no
#     test / beta / production environments here.
#   - `-intel` and `-win` are companion tags on the same commit: they opt
#     the release into the paid macos-13-large runner and the Windows x64
#     sidecar. Off by default.
#   - The release is cut from whatever branch you are on (usually the
#     default branch) and that branch is pushed together with the tag.
#     Tags form one `v0.1.x` series, not one series per branch.
#   - The version lives in THREE places that must stay in sync:
#       (a) the git tag itself (e.g. v0.1.50)
#       (b) app/package.json `"version"` (electron-builder reads it for
#           the .dmg / .exe filename and Sparkle-style updates)
#       (c) engine/pyproject.toml `version` (PyInstaller + zylch CLI)
#     This script bumps (b) and (c) and commits the bump BEFORE creating
#     the tag, so the tag points at a commit whose source tree already
#     declares the new version.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") -m "message"   bump versions, tag, push branch + tag, ask for companion tags
       $(basename "$0") -p             publish missing companion tags for the latest release tag

Options:
  -m, --message   Commit message for pending changes, and annotation for the new tag
  -p, --publish   Publish missing -intel / -win companion tags for the latest tag
  -h, --help      Show this help
EOF
  exit 0
}

die() { echo "Error: $*" >&2; exit 1; }

# Normalize an answer: strip ALL whitespace (including a trailing CR from a
# paste or a remote terminal) and lowercase it, so "y", "Y", "y\r" and
# " yes " all read the same. EOF yields the empty string.
read_answer() {
  local resp
  read -rp "$1" resp || resp=""
  resp="$(printf '%s' "$resp" | tr -d '[:space:]')"
  printf '%s' "${resp,,}"
}

# Defaults to YES on a bare Enter — for steps that are the point of the run.
confirm() {
  local answer
  answer="$(read_answer "$1 [Yn] ")"
  [[ -z "$answer" || "$answer" == "y" || "$answer" == "yes" ]]
}

# Defaults to NO on a bare Enter — for steps where skipping is the safer path.
confirm_no() {
  local answer
  answer="$(read_answer "$1 [yN] ")"
  [[ "$answer" == "y" || "$answer" == "yes" ]]
}

bump_app_version() {
  # Rewrite app/package.json `"version": "..."` to $1 in place, through a
  # small json mutator so key order and indentation survive. node would
  # also work but adds a tooling dependency this script otherwise avoids.
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
# Match the FIRST top-level `version = "..."` line — pyproject's [project]
# table. This is structured TOML, so a targeted regex is fine.
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

# The companion suffixes release.yml understands, in prompt order.
COMPANIONS=(intel win)

companion_note() {
  case "$1" in
    intel) echo "paid Intel macOS runner" ;;
    win)   echo "Windows x64 sidecar + installer" ;;
    *)     echo "opt-in build" ;;
  esac
}

# --- Arguments ---------------------------------------------------
[[ $# -gt 0 ]] || usage

MODE=""
MESSAGE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      [[ -n "${2:-}" ]] || die "-m/--message requires an argument"
      MESSAGE="$2"
      shift 2
      ;;
    -p|--publish)
      MODE="publish"
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ "$MODE" == "publish" ]]; then
  [[ -z "$MESSAGE" ]] || die "-m/--message cannot be combined with -p/--publish"
else
  [[ -n "$MESSAGE" ]] || die "-m/--message is required (or use -p/--publish)"
fi

# --- Origin is the source of truth for release tags --------------
# Sync the v* tags with origin and prune the local v* tags that no longer
# exist remotely, so "latest" is never stale and a tag left behind by a
# half-failed run cannot poison the numbering. The refspec keeps the prune
# inside the release namespace: local-only markers outside it (e.g.
# pre-secret-cleanup-2026-05-01) are not release tags and survive.
git fetch --prune origin "+refs/tags/v*:refs/tags/v*"

# --- Branch ------------------------------------------------------
BRANCH="$(git branch --show-current)"
[[ -n "$BRANCH" ]] || die "detached HEAD, cannot determine the branch to push"

DEFAULT_BRANCH=""
if git symbolic-ref refs/remotes/origin/HEAD >/dev/null 2>&1; then
  DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's@^origin/@@')
fi
if [[ -n "$DEFAULT_BRANCH" && "$BRANCH" != "$DEFAULT_BRANCH" ]]; then
  echo "⚠  You are on '$BRANCH', default branch is '$DEFAULT_BRANCH'"
  confirm_no "Continue anyway?" || die "aborted"
fi

# --- Enumerate this repo's release tags, newest first ------------
# LATEST_ANY is the newest v* tag of any kind; LATEST_BASE is the newest
# bare release tag (vX.Y.Z, no companion suffix). Only LATEST_BASE feeds
# the patch bump: a companion tag sorts higher under -v:refname, and its
# suffix is not arithmetic.
LATEST_ANY=""
LATEST_BASE=""
while IFS= read -r t; do
  [[ "$t" == v* ]] || continue
  if [[ -z "$LATEST_ANY" ]]; then
    LATEST_ANY="$t"
  fi
  if [[ -z "$LATEST_BASE" && "$t" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    LATEST_BASE="$t"
  fi
done < <(git for-each-ref refs/tags --sort=-v:refname --format='%(refname:short)')

if [[ "$MODE" == "publish" ]]; then
  # --- Publish mode: backfill the companion tags of the latest tag ---
  [[ -n "$LATEST_ANY" ]] || die "no v* tags found in this repository"
  BASE_TAG="$LATEST_ANY"
  for SUFFIX in "${COMPANIONS[@]}"; do
    BASE_TAG="${BASE_TAG%-$SUFFIX}"
  done
  [[ "$BASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "latest tag '$LATEST_ANY' does not reduce to a vX.Y.Z release tag"

  echo "Latest tag: $BASE_TAG"
  BASE_MSG="$(git for-each-ref "refs/tags/$BASE_TAG" --format='%(contents)')"
  [[ -n "${BASE_MSG//[[:space:]]/}" ]] || BASE_MSG="$BASE_TAG"

  for SUFFIX in "${COMPANIONS[@]}"; do
    COMPANION_TAG="$BASE_TAG-$SUFFIX"
    if git rev-parse -q --verify "refs/tags/$COMPANION_TAG" >/dev/null; then
      echo "  $COMPANION_TAG exists, skipping"
      continue
    fi
    if confirm_no "Create and push $COMPANION_TAG ($(companion_note "$SUFFIX"))?"; then
      git tag -a "$COMPANION_TAG" -m "$BASE_MSG"
      git push origin "$COMPANION_TAG"
      echo "  Pushed $COMPANION_TAG"
    else
      echo "  Skipping $SUFFIX"
    fi
  done

  echo "Done."
  exit 0
fi

# --- Compute the next tag ----------------------------------------
[[ -n "$LATEST_BASE" ]] || die "no existing vX.Y.Z tags found"

# v0.1.49 → prefix=v0.1 patch=49
PREFIX="${LATEST_BASE%.*}"
PATCH="${LATEST_BASE##*.}"
NEW_TAG="${PREFIX}.$((PATCH + 1))"
NEW_VERSION="${NEW_TAG#v}"   # strip the leading "v" for package.json / pyproject.toml

if git rev-parse -q --verify "refs/tags/$NEW_TAG" >/dev/null; then
  die "tag $NEW_TAG already exists"
fi

echo "Latest tag: $LATEST_BASE"
echo "Next tag:   $NEW_TAG  (version $NEW_VERSION)"

# --- Commit pending changes (with the user's message) -----------
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo ""
  echo "Changes detected:"
  git status --short
  echo ""
  if confirm "Commit with message '$MESSAGE'?"; then
    git add -u
    for f in $(git ls-files --others --exclude-standard); do
      if confirm "  Add new file '$f'?"; then
        git add "$f"
      fi
    done
    if git diff --cached --quiet; then
      echo "Nothing staged — skipping commit."
    else
      git commit -m "$MESSAGE"
      echo "Committed."
    fi
  else
    echo "Skipped commit."
  fi
else
  # Working tree clean is the normal case when the commits were crafted by
  # hand before running the release script.
  echo ""
  echo "Working tree clean — proceeding with version bump + tag + push."
  echo "Your message will be used as the tag annotation."
fi

echo ""
if ! confirm "Bump app/package.json + engine/pyproject.toml to $NEW_VERSION and tag $NEW_TAG?"; then
  die "aborted"
fi

# --- Bump the version files + dedicated commit ------------------
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
# The annotation carries the user's message so the release notes mean
# something ("Search email and task dedup", not "Release v0.1.50").
git tag -a "$NEW_TAG" -m "$NEW_TAG — $MESSAGE"
echo "Tagged $NEW_TAG."

# --- Push branch + tag ------------------------------------------
if confirm "Push $BRANCH + $NEW_TAG to origin?"; then
  git push origin "$BRANCH"
  git push origin "$NEW_TAG"
  echo "Pushed branch '$BRANCH' and tag '$NEW_TAG'"
else
  echo "Tag created locally but NOT pushed. To push later:"
  echo "  git push origin $BRANCH && git push origin $NEW_TAG"
  exit 0
fi

# --- Companion tags ---------------------------------------------
# release.yml builds macOS arm64 for any `v*` tag. `-intel` adds the
# paid macos-13-large x64 build, `-win` the Windows x64 sidecar and
# installer. Both off by default; `-p` backfills them later.
for SUFFIX in "${COMPANIONS[@]}"; do
  COMPANION_TAG="$NEW_TAG-$SUFFIX"
  if confirm_no "Also push companion tag $COMPANION_TAG ($(companion_note "$SUFFIX"))?"; then
    git tag -a "$COMPANION_TAG" -m "$COMPANION_TAG — $MESSAGE"
    git push origin "$COMPANION_TAG"
    echo "  Pushed $COMPANION_TAG"
  else
    echo "  Skipping $SUFFIX"
  fi
done

echo "Done."
