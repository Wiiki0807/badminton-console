#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as WSL root" >&2
  exit 1
fi

user_name="tommywu"
user_home="/home/${user_name}"
state_dir="${user_home}/.openclaw"
env_file="${state_dir}/.env"
source_dir="${1:-/mnt/c/Users/camkey}"
callback_prefix="${2:-https://mango-bay-0083f4c00.7.azurestaticapps.net/api/}"
hub_env_file="${3:-/mnt/c/Users/tommwu/OneDrive - NVIDIA Corporation/Documents/ChatGPT/nv_infer_hub/.env}"

install -o "${user_name}" -g "${user_name}" -m 700 -d "${state_dir}"
touch "${env_file}"
chown "${user_name}:${user_name}" "${env_file}"
chmod 600 "${env_file}"

get_env() {
  sed -n "s/^${1}=//p" "${env_file}" | tail -n 1
}

set_env() {
  local key="$1" value="$2" temporary
  temporary="$(mktemp "${state_dir}/env.XXXXXX")"
  grep -v "^${key}=" "${env_file}" > "${temporary}" || true
  printf '%s=%s\n' "${key}" "${value}" >> "${temporary}"
  chown "${user_name}:${user_name}" "${temporary}"
  chmod 600 "${temporary}"
  mv -f "${temporary}" "${env_file}"
}

bridge_token="$(get_env OPENCLAW_BRIDGE_TOKEN)"
pair_code="$(get_env OPENCLAW_LINE_PAIR_CODE)"
callback_token=""
[[ -n "${bridge_token}" ]] || bridge_token="$(openssl rand -base64 48 | tr -d '\n')"
[[ -n "${pair_code}" ]] || pair_code="$(openssl rand -hex 6)"
reminder_token_file="/mnt/c/ProgramData/RocketAI/reminder-dispatch-token.txt"
hub_token="$(get_env NV_INFER_HUB_TOKEN)"
tavily_key="$(get_env TAVILY_API_KEY)"
if [[ -z "${tavily_key}" && -f "${hub_env_file}" ]]; then
  tavily_key="$(sed -n -E \
    's/^[[:space:]]*(TAVILY_API_KEY|tavily_key)[[:space:]]*=[[:space:]]*(.*)$/\2/p' \
    "${hub_env_file}" | tail -n 1 | tr -d '\r')"
fi
if [[ -s "${reminder_token_file}" ]]; then
  callback_token="$(tr -d '\r\n' < "${reminder_token_file}")"
elif [[ -n "${hub_token}" ]]; then
  callback_token="$(printf '%s' 'rocketai-line-reminder-dispatch-v1' | \
    openssl dgst -sha256 -hmac "${hub_token}" \
    -binary | xxd -p -c 256)"
fi
[[ -n "${callback_token}" ]] || callback_token="$(openssl rand -hex 32)"

set_env OPENCLAW_BRIDGE_TOKEN "${bridge_token}"
set_env OPENCLAW_LINE_PAIR_CODE "${pair_code}"
set_env OPENCLAW_LINE_CALLBACK_TOKEN "${callback_token}"
set_env OPENCLAW_LINE_CALLBACK_URL_PREFIX "${callback_prefix}"
if [[ -n "${tavily_key}" ]]; then
  set_env TAVILY_API_KEY "${tavily_key}"
fi

if [[ -f "${source_dir}/openclaw.json" ]]; then
  if grep -q '"provider"[[:space:]]*:[[:space:]]*"tavily"' \
      "${source_dir}/openclaw.json" && \
      ! find "${state_dir}/npm/projects" \
        -path '*/node_modules/@openclaw/tavily-plugin/package.json' \
        -type f -print -quit 2>/dev/null | grep -q .; then
    runuser -u "${user_name}" -- env HOME="${user_home}" bash -lc \
      'source "$HOME/.nvm/nvm.sh" && nvm use default >/dev/null && source "$HOME/.openclaw/.env" && openclaw plugins install @openclaw/tavily-plugin'
  fi
  install -o "${user_name}" -g "${user_name}" -m 600 \
    "${source_dir}/openclaw.json" "${state_dir}/openclaw.json"
fi

install -o "${user_name}" -g "${user_name}" -m 700 \
  "${source_dir}/line_openclaw_bridge.py" "${state_dir}/line_openclaw_bridge.py"
install -o "${user_name}" -g "${user_name}" -m 700 \
  "${source_dir}/x1_gesture_control.py" "${state_dir}/x1_gesture_control.py"
install -o "${user_name}" -g "${user_name}" -m 700 \
  "${source_dir}/x1_camera_control.py" "${state_dir}/x1_camera_control.py"
install -o "${user_name}" -g "${user_name}" -m 700 \
  "${source_dir}/x1_locate_control.py" "${state_dir}/x1_locate_control.py"
install -o "${user_name}" -g "${user_name}" -m 700 \
  "${source_dir}/robot_control.py" "${state_dir}/robot_control.py"
install -o "${user_name}" -g "${user_name}" -m 700 \
  "${source_dir}/azure_callback.py" "${state_dir}/azure_callback.py"
workspace_agents="${source_dir}/workspace/AGENTS.md"
if [[ ! -f "${workspace_agents}" ]]; then
  workspace_agents="${source_dir}/openclaw-AGENTS.md"
fi
if [[ -f "${workspace_agents}" ]]; then
  install -o "${user_name}" -g "${user_name}" -m 600 \
    "${workspace_agents}" "${state_dir}/workspace/AGENTS.md"
fi
news_skill_source="${source_dir}/workspace/skills/verified-news-digest/SKILL.md"
if [[ -f "${news_skill_source}" ]]; then
  install -o "${user_name}" -g "${user_name}" -m 700 -d \
    "${state_dir}/workspace/skills/verified-news-digest"
  install -o "${user_name}" -g "${user_name}" -m 600 \
    "${news_skill_source}" \
    "${state_dir}/workspace/skills/verified-news-digest/SKILL.md"
fi
x1_skill_source="${source_dir}/workspace/skills/x1-gesture-control/SKILL.md"
if [[ -f "${x1_skill_source}" ]]; then
  install -o "${user_name}" -g "${user_name}" -m 700 -d \
    "${state_dir}/workspace/skills/x1-gesture-control"
  install -o "${user_name}" -g "${user_name}" -m 600 \
    "${x1_skill_source}" \
    "${state_dir}/workspace/skills/x1-gesture-control/SKILL.md"
fi
camera_skill_source="${source_dir}/workspace/skills/x1-vision-camera/SKILL.md"
if [[ -f "${camera_skill_source}" ]]; then
  install -o "${user_name}" -g "${user_name}" -m 700 -d \
    "${state_dir}/workspace/skills/x1-vision-camera"
  install -o "${user_name}" -g "${user_name}" -m 600 \
    "${camera_skill_source}" \
    "${state_dir}/workspace/skills/x1-vision-camera/SKILL.md"
fi
install -o "${user_name}" -g "${user_name}" -m 644 \
  "${source_dir}/line-openclaw-bridge.service" \
  "${user_home}/.config/systemd/user/line-openclaw-bridge.service"

loginctl enable-linger "${user_name}"
runuser -u "${user_name}" -- env XDG_RUNTIME_DIR=/run/user/1000 \
  systemctl --user daemon-reload
runuser -u "${user_name}" -- env XDG_RUNTIME_DIR=/run/user/1000 \
  systemctl --user enable --now line-openclaw-bridge.service
if runuser -u "${user_name}" -- env XDG_RUNTIME_DIR=/run/user/1000 \
  systemctl --user is-enabled openclaw-gateway.service >/dev/null 2>&1; then
  runuser -u "${user_name}" -- env XDG_RUNTIME_DIR=/run/user/1000 \
    systemctl --user restart openclaw-gateway.service
fi

# Keep the gateway exec policy narrow and reproducible. These executable
# wrappers validate every action/argument internally; never allowlist python3.
for wrapper in x1_camera_control.py x1_locate_control.py; do
  runuser -u "${user_name}" -- env HOME="${user_home}" bash -lc \
    "source \"${user_home}/.nvm/nvm.sh\" && source \"${env_file}\" && openclaw approvals allowlist add --agent main \"${state_dir}/${wrapper}\" >/dev/null"
done

echo "OpenClaw bridge installed and enabled"
echo "PAIR_CODE=${pair_code}"
