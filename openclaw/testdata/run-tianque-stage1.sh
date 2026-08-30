#!/usr/bin/env bash
set -euo pipefail

node=/home/tommywu/.nvm/versions/node/v24.20.0/bin/node
entry=/home/tommywu/.nvm/versions/node/v24.20.0/lib/node_modules/openclaw/dist/index.js
request=/home/tommywu/.openclaw/workspace/testdata/tianque-stage1-request.txt
output=/home/tommywu/.openclaw/workspace/veo-projects/tianque-mimeng/stage1-run.json

mkdir -p "$(dirname "${output}")"
message="$(cat "${request}")"
exec "${node}" "${entry}" agent --agent main --message "${message}" \
  --session-key agent:main:veo-tianque-stage1 --timeout 600 --json >"${output}"
