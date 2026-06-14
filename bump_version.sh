#!/bin/bash
# ─────────────────────────────────────────────────────────────
# 버전 일괄 변경 — 한 명령으로 모든 버전 표기 갱신
#   사용:  bash bump_version.sh 1.6
# 갱신 대상: wayaudo2.py(_APP_VERSION + 상단주석) · WSA2.spec · build_intel.sh · version_info.txt
# (푸터·About·시작로그는 _APP_VERSION 상수라 자동. RELEASE_NOTES는 내용이라 수동 추가)
# 끝나면 직접 커밋 + 태그:  git add -A && git commit -m "vX.Y" && git tag vX.Y
# ─────────────────────────────────────────────────────────────
set -e
NEW="$1"
if ! echo "$NEW" | grep -qE '^[0-9]+\.[0-9]+$'; then
  echo "사용법: bash bump_version.sh 1.6   (X.Y 형식)"; exit 1
fi
cd "$(dirname "$0")"
python3 - "$NEW" <<'PY'
import re, sys
new = sys.argv[1]
maj, minr = new.split('.')
v4 = f"{maj}, {minr}, 0, 0"     # version_info filevers/prodvers
v_dot4 = f"{new}.0.0"           # version_info FileVersion/ProductVersion
v_dot3 = f"{new}.0"             # CFBundleVersion

def sub(path, pairs):
    s = open(path).read()
    for pat, rep in pairs:
        if not re.search(pat, s): print(f"  ⚠ 패턴 미일치({path}): {pat}")
        s = re.sub(pat, rep, s)
    open(path, 'w').write(s); print("  ✓", path)

print(f"버전 → {new}")
sub('wayaudo2.py', [
    (r"_APP_VERSION = '[0-9.]+'", f"_APP_VERSION = '{new}'"),
    (r"\(by WAYAUDIO\)  v[0-9.]+", f"(by WAYAUDIO)  v{new}"),
])
for spec in ('WSA2.spec', 'build_intel.sh'):
    sub(spec, [
        (r"'CFBundleShortVersionString': '[0-9.]+'", f"'CFBundleShortVersionString': '{new}'"),
        (r"'CFBundleVersion': '[0-9.]+'", f"'CFBundleVersion': '{v_dot3}'"),
    ])
sub('version_info.txt', [
    (r"filevers=\([0-9, ]+\)", f"filevers=({v4})"),
    (r"prodvers=\([0-9, ]+\)", f"prodvers=({v4})"),
    (r"StringStruct\('FileVersion', '[0-9.]+'\)", f"StringStruct('FileVersion', '{v_dot4}')"),
    (r"StringStruct\('ProductVersion', '[0-9.]+'\)", f"StringStruct('ProductVersion', '{v_dot4}')"),
])
PY
echo ""
echo "✅ 완료. RELEASE_NOTES.md/.html 에 새 버전 항목 추가 후:"
echo "   git add -A && git commit -m \"v$NEW\" && git tag v$NEW"
