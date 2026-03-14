#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: scripts/build_macos_release.sh must run on macOS." >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
SPEC_FILE="${SPEC_FILE:-PLI.spec}"
DIST_DIR="${DIST_DIR:-dist}"
BUILD_DIR="${BUILD_DIR:-build}"
APP_PATH="${APP_PATH:-$DIST_DIR/PLI.app}"
ARCHIVE_PATH="${ARCHIVE_PATH:-$DIST_DIR/PLI.zip}"
NOTARY_RESULT_PATH="${NOTARY_RESULT_PATH:-$DIST_DIR/notary-submit.json}"
NOTARY_LOG_PATH="${NOTARY_LOG_PATH:-$DIST_DIR/notary-log.json}"
APPLE_ENTITLEMENTS_FILE="${APPLE_ENTITLEMENTS_FILE:-assets/macos-entitlements.plist}"
SKIP_NOTARIZE="${SKIP_NOTARIZE:-0}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

json_field() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import json
import sys

path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)
value = data.get(key, "")
if value is None:
    value = ""
print(value)
PY
}

require_command "$PYTHON_BIN"
require_command codesign
require_command ditto
require_command spctl
require_command xcrun

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "error: PyInstaller is not installed in $PYTHON_BIN." >&2
  exit 1
fi

if [[ ! -f "$SPEC_FILE" ]]; then
  echo "error: spec file not found: $SPEC_FILE" >&2
  exit 1
fi

if [[ ! -f "$APPLE_ENTITLEMENTS_FILE" ]]; then
  echo "error: entitlements file not found: $APPLE_ENTITLEMENTS_FILE" >&2
  exit 1
fi

: "${APPLE_SIGN_IDENTITY:?APPLE_SIGN_IDENTITY is required.}"
if [[ "$SKIP_NOTARIZE" != "1" ]]; then
  : "${APPLE_NOTARY_PROFILE:?APPLE_NOTARY_PROFILE is required unless SKIP_NOTARIZE=1.}"
fi

rm -rf "$DIST_DIR" "$BUILD_DIR"

echo "==> Building app bundle"
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "$SPEC_FILE"

if [[ ! -d "$APP_PATH" ]]; then
  echo "error: app bundle was not created: $APP_PATH" >&2
  exit 1
fi

echo "==> Signing app bundle"
codesign --force --deep --options runtime --timestamp \
  --entitlements "$APPLE_ENTITLEMENTS_FILE" \
  --sign "$APPLE_SIGN_IDENTITY" \
  "$APP_PATH"

echo "==> Verifying code signature"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "==> Creating notarization archive"
rm -f "$ARCHIVE_PATH" "$NOTARY_RESULT_PATH" "$NOTARY_LOG_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ARCHIVE_PATH"

if [[ "$SKIP_NOTARIZE" == "1" ]]; then
  echo "==> SKIP_NOTARIZE=1, skipping notarization"
else
  echo "==> Submitting archive for notarization"
  submit_cmd=(xcrun notarytool submit --keychain-profile "$APPLE_NOTARY_PROFILE" --wait --output-format json)
  if [[ -n "${APPLE_NOTARY_KEYCHAIN:-}" ]]; then
    submit_cmd+=(--keychain "$APPLE_NOTARY_KEYCHAIN")
  fi
  submit_cmd+=("$ARCHIVE_PATH")

  set +e
  "${submit_cmd[@]}" >"$NOTARY_RESULT_PATH"
  submit_exit=$?
  set -e
  cat "$NOTARY_RESULT_PATH"

  submission_id="$(json_field "$NOTARY_RESULT_PATH" "id")"
  submission_status="$(json_field "$NOTARY_RESULT_PATH" "status")"

  if [[ -n "$submission_id" ]]; then
    echo "==> Downloading notarization log"
    log_cmd=(xcrun notarytool log --keychain-profile "$APPLE_NOTARY_PROFILE")
    if [[ -n "${APPLE_NOTARY_KEYCHAIN:-}" ]]; then
      log_cmd+=(--keychain "$APPLE_NOTARY_KEYCHAIN")
    fi
    log_cmd+=("$submission_id" "$NOTARY_LOG_PATH")
    "${log_cmd[@]}" || true
  fi

  if [[ $submit_exit -ne 0 || "$submission_status" != "Accepted" ]]; then
    echo "error: notarization failed. Inspect $NOTARY_RESULT_PATH and $NOTARY_LOG_PATH." >&2
    exit 1
  fi

  echo "==> Stapling notarization ticket"
  xcrun stapler staple -v "$APP_PATH"
  xcrun stapler validate -v "$APP_PATH"
fi

echo "==> Gatekeeper assessment"
spctl --assess --type execute -vv "$APP_PATH"

echo "Release app: $APP_PATH"
echo "Archive: $ARCHIVE_PATH"
