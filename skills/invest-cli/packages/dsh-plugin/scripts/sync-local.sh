#!/usr/bin/env bash
# invest-cli DSH 插件本地同步 —— 源 → 各 profile 装机副本。
#
# 为什么存在：profile 依赖是 file: 协议，pnpm 装进 node_modules 的是复制
# 副本不是软链——只改源不同步，DSH 读的就是旧包（argo 同款教训：设置页
# 一直读旧 bundle 排查半天）。
#
# 用法:
#   bash scripts/sync-local.sh            # 同步所有已装 profile
#   bash scripts/sync-local.sh --check    # 只检测漂移（doctor 的 dsh 项同款判据），漂移 rc=1
#
# 同步后需重启对应 DSH profile 才生效（web: restart-web.sh；desktop: 重开 APP）。
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
PROFILES_ROOT="${DSH_PROFILES_ROOT:-$HOME/.dsh/profiles}"
# 装机面 = package.json 的 `files` 字段（唯一真源），与 doctor.check_dsh 同款展开。
# 过去这里手写 5 个文件名，doctor 另按 package.json 派生，两套判据各自漂移过。
KEYS=$(python3 - "$SRC" <<'PY'
import json, os, sys
src = sys.argv[1]
manifest = json.load(open(os.path.join(src, "package.json"), encoding="utf-8"))
out = ["package.json"]
for entry in manifest.get("files", []):
    p = os.path.join(src, entry)
    if os.path.isfile(p):
        out.append(entry)
    elif os.path.isdir(p):
        for root, _dirs, files in os.walk(p):
            for f in files:
                out.append(os.path.relpath(os.path.join(root, f), src))
print(" ".join(out))
PY
)
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

[[ -d "$PROFILES_ROOT" ]] || { echo "无 $PROFILES_ROOT（非 DSH 环境），无事可做"; exit 0; }

found=0
drift=0
for prof_dir in "$PROFILES_ROOT"/*/; do
  copy="${prof_dir}node_modules/@taxueseek/invest-cli-dsh"
  [[ -d "$copy" ]] || continue
  found=1
  name="$(basename "$prof_dir")"
  bad=()
  for rel in $KEYS; do
    src_f="$SRC/$rel"
    [[ -f "$src_f" ]] || continue
    if [[ ! -f "$copy/$rel" ]] || ! cmp -s "$src_f" "$copy/$rel"; then
      bad+=("$rel")
    fi
  done
  if [[ ${#bad[@]} -eq 0 ]]; then
    echo "[OK]   $name 与源一致"
    continue
  fi
  drift=1
  echo "[DRIFT] $name: ${bad[*]}"
  if [[ $CHECK_ONLY -eq 0 ]]; then
    for rel in "${bad[@]}"; do
      mkdir -p "$(dirname "$copy/$rel")"
      cp "$SRC/$rel" "$copy/$rel"
    done
    echo "       已同步 ${bad[*]} → $copy"
  fi
done

[[ $found -eq 1 ]] || { echo "$PROFILES_ROOT 下无 invest-cli-dsh 装机副本"; exit 0; }
if [[ $CHECK_ONLY -eq 1 && $drift -eq 1 ]]; then
  echo "存在漂移（未同步，--check 模式）。跑本脚本不带参数即同步。"
  exit 1
fi
[[ $drift -eq 0 ]] && echo "全部一致" || echo "同步完成；重启对应 profile 后生效"
