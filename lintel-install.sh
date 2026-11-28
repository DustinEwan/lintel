#!/bin/sh
set -eu

REPO=${LINTEL_REPO:-DustinEwan/lintel}
TAG=${LINTEL_VERSION:-}
BASE_URL=${LINTEL_BASE_URL:-}
BIN_DIR=${LINTEL_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}

fail() {
  printf 'lintel-install: %s\n' "$1" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required"

if [ -z "$TAG" ]; then
  TAG=$(
    curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" |
      sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' |
      head -n 1
  )
fi
[ -n "$TAG" ] || fail "no release tag found"
VERSION=${TAG#v}

case "$(uname -s)" in
  Linux) OS=linux ;;
  Darwin) OS=macos ;;
  *) fail "unsupported operating system: $(uname -s)" ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ARCH=x86_64 ;;
  arm64|aarch64) ARCH=aarch64 ;;
  *) fail "unsupported architecture: $(uname -m)" ;;
esac

ASSET="lintel-$OS-$ARCH"

if [ -z "$BASE_URL" ]; then
  BASE_URL="https://github.com/$REPO/releases/download/$TAG/"
fi
case "$BASE_URL" in
  */) ;;
  *) BASE_URL="$BASE_URL/" ;;
esac

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

curl -fsSL -o "$TMP/$ASSET" "$BASE_URL$ASSET" || fail "could not download $ASSET"
curl -fsSL -o "$TMP/SHA256SUMS" "${BASE_URL}SHA256SUMS" || fail "could not download SHA256SUMS"

EXPECTED=$(awk -v name="$ASSET" '$2 == name { print $1; exit }' "$TMP/SHA256SUMS")
[ -n "$EXPECTED" ] || fail "no checksum for $ASSET"

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL=$(sha256sum "$TMP/$ASSET" | awk '{ print $1 }')
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL=$(shasum -a 256 "$TMP/$ASSET" | awk '{ print $1 }')
else
  fail "sha256sum or shasum is required"
fi
[ "$ACTUAL" = "$EXPECTED" ] || fail "checksum mismatch for $ASSET"

mkdir -p "$BIN_DIR"
STAGING="$TMP/lintel-installed"
cp "$TMP/$ASSET" "$STAGING"
chmod +x "$STAGING"
mv "$STAGING" "$BIN_DIR/lintel"

printf 'Installed lintel %s to %s/lintel\n' "$VERSION" "$BIN_DIR"
"$BIN_DIR/lintel" version
