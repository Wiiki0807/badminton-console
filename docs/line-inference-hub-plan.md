# LINE × nv_infer_hub 開發與部署計畫

## 結論

應採「parser 優先、LLM fallback」：今日場次、場上、比分、戰績、積分與場數仍由既有
Python 邏輯產生精確答案；只有未命中指令的自然語句才送往 nv_infer_hub。服務故障時不會
破壞原功能，也能避免 LLM 捏造比分或把自然語句誤判成管理操作。

## 已完成的程式範圍

1. `api/shared/inference_hub.py` 呼叫 OpenAI-compatible `POST /chat/completions`。
2. 僅傳送 allow-list 中的公開場次欄位，限制清單數量、總 prompt 長度、輸入與輸出長度。
3. 使用非串流回應、8 秒預設 timeout、低 temperature；任何網路或 JSON 錯誤皆回到舊說明。
4. token 僅從環境變數讀取，不寫入 Git；LINE access token 與 hub token 必須分開。
5. LLM 只可回答公開場次、羽球規則與技巧，不可修改排點或執行管理操作。

## 網路架構決策

目前 Azure Static Web Apps managed Function 與
`http://nv-ws-tommy.tail762218.ts.net:8790` 不在同一 tailnet。MagicDNS 只能在 tailnet 裝置
解析／連線，因此單純新增 `INFERENCE_HUB_URL` 不足以上線。

### 建議正式架構：Azure Container Apps + Tailscale sidecar

將 `api/` 部署為具公開 HTTPS ingress 的 Container App，讓 LINE 呼叫 webhook；同一 app
內的 Tailscale sidecar 加入 tailnet，Python API 再以私有 `*.ts.net` 位址呼叫 hub。Static
Web Apps Standard 可連結 Container Apps 作為 `/api` backend。此方案維持 inference endpoint
為 tailnet-only，適合正式環境。

上線工作：

1. 為 sidecar 建立獨立且最小權限的 Tailscale OAuth client/tag，ACL 只允許連到
   `nv-ws-tommy:8790`。
2. 以 Azure Key Vault／Container Apps secrets 保存 Tailscale auth、LINE secrets 與
   `INFERENCE_HUB_TOKEN`。
3. 建立 Container App、health probe、最少一個常駐 replica，並將 Static Web Apps 升為
   Standard 後連結 backend。
4. workflow 將 managed API deployment 關閉，API 改由獨立 pipeline 部署。
5. 先以新的測試 LINE channel 做 smoke test，再切正式 webhook URL。

### 快速 PoC：Tailscale Funnel

也可用 Funnel 把「專用、限流、只允許 `/chat/completions`」的 gateway 公開為 HTTPS，讓
現有 managed Function 呼叫。這會把入口暴露到公網，不再是 tailnet-only；不可直接把整個
8790 service 公開。至少要使用獨立長 token、request body 上限、rate limit、存取紀錄與
token rotation。此方案只建議用於短期驗證。

### 無 Azure 管理權限時的 PoC 設定

目前 repository owner 提供的 deployment token 只能部署，不能修改 Azure Application
Settings。Production Action 因此可從 GitHub Secret `LINE_INFERENCE_HUB_TOKEN` 與 repository
variables 覆寫 `api/shared/deployment_settings.json`，隨後端 Function artifact 部署。Git 只
保存內容為 `{}` 的 placeholder，PR preview 不注入 secret，程式仍以 Azure environment
variables 為最高優先。

這是無 Azure 權限下的務實 PoC；token 輪替需更新 GitHub Secret 並重新執行 production
deployment。若日後取得 Azure 管理權，應改回加密且可直接輪替的 Application Settings。

## 驗證紀錄（2026-08-28）

- tailnet `GET /health`：HTTP 200，約 204 ms，回報 ready。
- `POST /chat/completions`：HTTP 200、`application/json`，模型
  `openai/openai/gpt-4o-mini`，測試回覆約 1.28 秒。
- `python -m unittest discover -s api/tests -v`：9 項全部通過。
- 覆蓋範圍：舊 parser、個人戰績、下一組、無 LLM 設定 fallback、mock hub request 契約。

## 上線驗收

1. 從實際 Azure runtime（不是開發電腦）呼叫 hub health 與 chat 成功。
2. LINE Developers Verify 成功，webhook 在 10 秒內回覆。
3. 既有指令回歸測試全過；自然語句、hub timeout、401、500 都有可讀 fallback。
4. prompt injection 測試不能取得 secret、system prompt 或觸發管理操作。
5. Azure 與 hub log 不記錄 Bearer token；設定告警監控 timeout、5xx 與延遲。
6. 關閉 hub 或撤銷 token 後，今日場次、比分、戰績等既有功能仍正常。

## 後續擴充順序

1. 第一階段（本次）：自然語句問答、現況摘要、羽球規則與練習建議，只讀不寫。
2. 第二階段：讓 LLM 只輸出結構化 intent，由 Python allow-list 驗證後呼叫既有查詢函式；
   不讓模型直接碰 storage。
3. 第三階段：許願或報名等寫入操作採「模型提出草稿 → 使用者確認 → 後端驗證」；團主
   管理操作另做身分綁定與權限檢查，不能只靠 prompt 保護。
4. 加入每位 LINE user 的 rate limit、延遲／錯誤 metrics，以及短期對話記憶；對話內容須有
   保存期限與刪除政策。
