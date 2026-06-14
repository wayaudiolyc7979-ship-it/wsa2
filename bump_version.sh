#!/bin/bash
# ─────────────────────────────────────────────────────────────
# 버전 일괄 변경 — 한 명령으로 모든 버전 표기 갱신
#   기능 추가:  bash bump_version.sh 1.6      (마이너)
#   버그 수정:  bash bump_version.sh 1.5.1    (패치)
#   대개편:     bash bump_version.sh 2.0
# 갱신 대상: wayaudo2.py(_APP_VERSION + 상단주석) · WSA2.spec · build_intel.sh · version_info.txt
# (푸터·About·시작로그는 _APP_VERSION 상수라 자동. RELEASE_NOTES는 내용이라 수동 추가)
# 끝나면:  git add -A && git commit -m "vX.Y.Z" && git tag vX.Y.Z
# ─────────────────────────────────────────────────────────────
set -e
NEW="$1"
if ! echo "$NEW" | grep -qE '^[0-9]+\.[0-9]+(\.[0-9]+)?$'; then
  echo "사용법: bash bump_version.sh 1.6  또는  1.5.1   (X.Y 또는 X.Y.Z)"; exit 1
fi
cd "$(dirname "$0")"
python3 - "$NEW" <<'PY'
import re, sys
new = sys.argv[1]                      # "1.6" 또는 "1.5.1" (표시용 그대로)
parts = new.split('.')
maj, minr = parts[0], parts[1]
patch = parts[2] if len(parts) > 2 else '0'
v3 = f"{maj}.{minr}.{patch}"           # CFBundleVersion (항상 3자리)
v4tuple = f"{maj}, {minr}, {patch}, 0" # version_info filevers/prodvers
v4dot = f"{maj}.{minr}.{patch}.0"      # version_info FileVersion/ProductVersion

def sub(path, pairs):
    s = open(path).read()
    for pat, rep in pairs:
        if not re.search(pat, s): print(f"  ⚠ 패턴 미일치({path}): {pat}")
        s = re.sub(pat, rep, s)
    open(path, 'w').write(s); print("  ✓", path)

print(f"버전 → {new}   (표시={new}, 빌드={v3})")
sub('wayaudo2.py', [
    (r"_APP_VERSION = '[0-9.]+'", f"_APP_VERSION = '{new}'"),
    (r"\(by WAYAUDIO\)  v[0-9.]+", f"(by WAYAUDIO)  v{new}"),
])
for spec in ('WSA2.spec', 'build_intel.sh'):
    sub(spec, [
        (r"'CFBundleShortVersionString': '[0-9.]+'", f"'CFBundleShortVersionString': '{new}'"),
        (r"'CFBundleVersion': '[0-9.]+'", f"'CFBundleVersion': '{v3}'"),
    ])
sub('version_info.txt', [
    (r"filevers=\([0-9, ]+\)", f"filevers=({v4tuple})"),
    (r"prodvers=\([0-9, ]+\)", f"prodvers=({v4tuple})"),
    (r"StringStruct\('FileVersion', '[0-9.]+'\)", f"StringStruct('FileVersion', '{v4dot}')"),
    (r"StringStruct\('ProductVersion', '[0-9.]+'\)", f"StringStruct('ProductVersion', '{v4dot}')"),
])
PY
echo ""
echo "✅ 완료. RELEASE_NOTES.md/.html 에 새 버전 항목 추가 후:"
echo "   git add -A && git commit -m \"v$NEW\" && git tag v$NEW"
