# macOS Release

PLI の macOS 配布は `scripts/build_macos_release.sh` に統一した。
このスクリプトは `.app` のビルド、Developer ID 署名、notarization、staple、Gatekeeper 検証までを一通り実行する。

## 前提

- macOS 上で実行する
- Xcode Command Line Tools が入っている
- Developer ID Application 証明書がログインキーチェーンに入っている
- `python3 -m PyInstaller` が実行できる

## 事前設定

署名 identity を環境変数で渡す。

```bash
export APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
```

notarytool 用の認証はキーチェーンプロファイルで扱う。Apple ID 方式でも API key 方式でもよいが、配布スクリプトは `--keychain-profile` を使う。

Apple ID 方式の例:

```bash
xcrun notarytool store-credentials pli-notary \
  --apple-id "you@example.com" \
  --team-id "TEAMID1234" \
  --password "app-specific-password" \
  --validate
export APPLE_NOTARY_PROFILE="pli-notary"
```

App Store Connect API key 方式の例:

```bash
xcrun notarytool store-credentials pli-notary \
  --key "/absolute/path/AuthKey_ABC1234567.p8" \
  --key-id "ABC1234567" \
  --issuer "00000000-0000-0000-0000-000000000000" \
  --validate
export APPLE_NOTARY_PROFILE="pli-notary"
```

必要なら専用キーチェーンも指定できる。

```bash
export APPLE_NOTARY_KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
```

デフォルトの entitlements は `assets/macos-entitlements.plist`。
初期状態では追加例外を入れていない。hardened runtime で実際に必要と確認できたキーだけを追加する。

## 実行

```bash
scripts/build_macos_release.sh
```

ローカルで署名だけ確認したい場合:

```bash
SKIP_NOTARIZE=1 scripts/build_macos_release.sh
```

## 出力

- `dist/PLI.app`
- `dist/PLI.zip`
- `dist/notary-submit.json`
- `dist/notary-log.json` （submission ID が取れた場合）

## 検証ポイント

- `codesign --verify --deep --strict --verbose=2 dist/PLI.app`
- `spctl --assess --type execute -vv dist/PLI.app`
- `xcrun stapler validate -v dist/PLI.app`

## 運用メモ

- バージョン文字列は `pyproject.toml` の `project.version` を `PLI.spec` が読む。
- bundle ID を変える場合は `PLI_BUNDLE_ID` を環境変数で渡せる。
- notarization が失敗したら `dist/notary-log.json` を先に見る。
