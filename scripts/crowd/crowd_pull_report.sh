#!/usr/bin/env bash
set -Eeuo pipefail

BASE_DIR="/home/eric/Documents/mfCode/crowd"
OUT_DIR="/home/eric/Documents/workspace/tmp"
mkdir -p "$OUT_DIR"

REPORT_FILE="$OUT_DIR/crowd_pull_report.txt"
STATE_FILE="$OUT_DIR/crowd_pull_report_state.json"
NOW="$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S %Z')"

repos=(
  "1|h5-crowdsource|众包前端|$BASE_DIR/h5-crowdsource"
  "2|o2o-crowdsource|众包业务后台|$BASE_DIR/o2o-crowdsource"
  "3|o2o-crowdsourcce|众包配送后台|$BASE_DIR/o2o-crowdsourcce"
)

json_escape() {
  python3 - <<'PY' "$1"
import json,sys
print(json.dumps(sys.argv[1], ensure_ascii=False))
PY
}

trim_multiline() {
  sed '/^[[:space:]]*$/d' | head -n 8
}

summarize_repo() {
  local idx="$1" key="$2" display_name="$3" repo="$4"

  if [[ -z "$display_name" ]]; then
    display_name="【未映射项目】$(basename "$repo")"
  fi

  if [[ ! -d "$repo/.git" ]]; then
    printf '%s. %s：仓库不存在或不是 git 仓库\n' "$idx" "$display_name"
    return
  fi

  local branch before after log_count summary tmp_err
  branch="$(git -C "$repo" branch --show-current 2>/dev/null || echo master)"
  tmp_err="$OUT_DIR/.${key}.pull.err"

  before="$(git -C "$repo" rev-parse HEAD)"

  if ! git -C "$repo" fetch origin "$branch" --quiet 2>"$tmp_err"; then
    local err
    err="$(cat "$tmp_err" | tail -n 3 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
    rm -f "$tmp_err"
    printf '%s. %s：拉取失败（%s）\n' "$idx" "$display_name" "${err:-git 拉取失败}"
    return
  fi

  if ! git -C "$repo" pull --ff-only origin "$branch" --quiet 2>"$tmp_err"; then
    local err
    err="$(cat "$tmp_err" | tail -n 3 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
    rm -f "$tmp_err"
    printf '%s. %s：更新失败（%s）\n' "$idx" "$display_name" "${err:-git 更新失败}"
    return
  fi
  rm -f "$tmp_err"

  after="$(git -C "$repo" rev-parse HEAD)"

  if [[ "$before" == "$after" ]]; then
    printf '%s. %s：无更新\n' "$idx" "$display_name"
    return
  fi

  summary="$({
    git -C "$repo" log --no-merges --pretty='- %s' "$before..$after" 2>/dev/null | trim_multiline
  } || true)"

  log_count="$(git -C "$repo" rev-list --count "$before..$after" 2>/dev/null || echo 0)"

  if [[ -z "$summary" ]]; then
    summary="- 有 ${log_count} 条提交更新"
  fi

  printf '%s. %s：\n%s\n' "$idx" "$display_name" "$summary"
}

{
  printf '代码更新播报\n'
  printf '时间：%s\n\n' "$NOW"
  for item in "${repos[@]}"; do
    IFS='|' read -r idx key display_name repo <<<"$item"
    summarize_repo "$idx" "$key" "$display_name" "$repo"
    printf '\n'
  done
} > "$REPORT_FILE"

python3 - <<'PY' "$REPORT_FILE" "$STATE_FILE"
import json,sys,pathlib
report_path = pathlib.Path(sys.argv[1])
state_path = pathlib.Path(sys.argv[2])
text = report_path.read_text(encoding='utf-8').rstrip() + '\n'
state = {
  'ok': True,
  'report_file': str(report_path),
  'message': text,
}
state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
print(text)
PY
