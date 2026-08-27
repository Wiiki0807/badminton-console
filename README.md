# 羽球排點所

一個以場邊平板與手機操作為核心的羽球團排點 Web MVP。專案使用原生 HTML、CSS 與 JavaScript，不需要安裝套件或建立後端即可使用。

## 開啟方式

直接用瀏覽器開啟 `index.html` 可單機試用。若要讓手機即時觀看與留言，請使用本機同步服務：

也可以直接雙擊 `start-server.cmd`，它會啟動 `http://127.0.0.1:4173/?view=courts` 並開啟今日排點。

```powershell
python server.py --port 4173
```

再前往 `http://127.0.0.1:4173`。

管理頁右上角的「球友看板」會顯示同一 Wi‑Fi 可開啟的手機網址。球友頁為 `live.html`，每 2 秒同步場上名單、近期比分、勝場與得失分，並支援留言及表情互動。

## 團主離線版（iPad PWA）

管理介面的場次、成員、排點、比分與動態積分原本就保存在瀏覽器的 `localStorage`；現在也會由 Service Worker 快取 HTML、CSS、JavaScript 與圖示，因此安裝後可在球館斷網時重新開啟。

1. iPad 有網路時，以 Safari 開啟正式網站並等待右上角顯示「線上同步」。
2. 點 Safari 的「分享」→「加入主畫面」。
3. 從主畫面的「羽球排點所」開啟一次，完成離線快取。
4. 之後即使球館無網路，仍可建立場次、排點、記錄比分及管理本機資料。

離線期間不提供球友即時看板、LINE 查詢、留言、許願池及跨裝置同步；恢復網路後保持團主版開啟，系統會重新發布最新狀態。每次正式網站部署新版後，iPad 也應連網開啟一次以更新快取。請勿清除 Safari 網站資料，否則這台裝置的本機場次與成員資料會一併刪除。

- 團主登記比分時可填寫 80 字內的單場評語；留空則由系統依比分自動產生
- 球友可從任何近期比分卡點「針對本場留言」，留言會保留該場球場、比分與對戰組合標籤
- 管理頁與球友看板皆使用羽球場俯視線位、球網與場上站位呈現，不再以表格方塊模擬球場
- 球員資料新增性別；備戰卡會醒目標示女性，候選區可切換不限、男雙、女雙及混雙模式
- 球友看板新增許願池：指定搭檔 3 點、指定對手 4 點、混雙 3 點、魔王挑戰 5 點；團主核准後會扣點並直接形成候選組合
- 許願點來源：勝場 +1、每 3 連勝額外 +2、成功挑戰平均高 1 級 +2、正向 Elo 累積 25 分 +1

## 已完成

- 四面球場即時狀態與計時
- 依等待時間、已打場數及兩隊實力差產生候選對戰
- 安排上場、語音叫號、結束比賽、比分與積分更新
- 備戰、休息、未報到名單
- 球友新增、狀態與分數調整
- 成員搜尋、程度篩選與戰績摘要
- 對戰歷史與 CSV 匯出
- 公平性、場地、輪替與趣味設定介面
- 響應式桌面／平板／手機版面
- 8/5 週三真實報名名單：B 時段 16 人、C 時段 22 人，共 35 位唯一球友
- 瀏覽器本機儲存，重新整理後保留操作結果
- 藍色主題球場與整體視覺
- 30 場批次排點模擬、平衡／公平性測試與 JSON 測試報告
- 報名等級與動態積分分離：例如 Lv.7 自動建立 700 初始分
- 雙打 Elo 賽後更新：依兩隊原始實力與勝負計算積分變化

## 操作展示影片

活動模擬資料為「first🥇羽球臨打團」、團長 Grace、地點「板橋奧創」。雙擊 `video/產生操作影片.cmd`，系統會使用 Edge TTS `zh-TW-HsiaoChenNeural` 旁白、自動擷取網站操作畫面並輸出 MP4。

## MVP 資料說明

目前資料保存在瀏覽器 `localStorage`，適合單機展示與場邊試用。正式多人版建議下一階段接上登入、雲端資料庫與即時同步。

## RocketAI LINE 官方帳號

Azure Functions 提供 `/api/line-webhook`，可讓 LINE 球友查詢「今日場次」、「場上」、
「最新比分」、「戰績」、「戰績 姓名」、「我的戰績」、「積分 姓名」、「場數 姓名」
及「猜下一組」。個人戰績會列出本日勝敗、得失分、動態積分與最近對戰比分；「自己」
會先以球友的 LINE 顯示名稱比對本場姓名，若暱稱不同可改用明確姓名查詢。請勿把 LINE
密鑰寫入程式或提交至 Git。

Azure Static Web Apps 的環境變數：

- `LINE_CHANNEL_SECRET`：重新簽發後的 Channel secret
- `LINE_CHANNEL_ACCESS_TOKEN`：Messaging API 的 Channel access token
- `LIVE_BOARD_URL`：公開球友看板網址，例如 `https://你的網站/live.html`
- `INFERENCE_HUB_URL`：OpenAI-compatible hub base URL；未設定時只使用既有指令解析
- `INFERENCE_HUB_TOKEN`：hub 專用 Bearer token，不可與 LINE token 共用
- `INFERENCE_HUB_MODEL`：選填，預設 `openai/openai/gpt-4o-mini`
- `INFERENCE_HUB_TIMEOUT_SECONDS`：選填，預設 8 秒，允許範圍 1–15 秒

已知指令仍優先使用原本的 deterministic parser；只有無法辨識的自然語句會呼叫 LLM。
Hub 逾時、斷線或回傳格式錯誤時，LINE bot 會自動退回原本的指令說明。

目前的 managed Function 不在 Tailscale tailnet 內，不能直接使用 `*.ts.net` 私有位址。
正式啟用前請依 [LINE × Inference Hub 開發與部署計畫](docs/line-inference-hub-plan.md)
完成網路橋接；不要在尚未建立橋接前把私有 URL 填入 Azure 環境變數。

若開發者沒有 Azure management-plane 權限，production workflow 會在 Functions 建置前，
從 GitHub Secret `LINE_INFERENCE_HUB_TOKEN` 與同名前綴的 repository variables 產生後端
專用設定檔。Git 只保存內容為 `{}` 的 placeholder，PR preview 不注入，Azure Application
Settings 若存在仍具有最高優先權。固定測試端點 `POST /api/line-inference-smoke` 使用
`X-Line-Inference-Smoke-Token` 驗證，可測試 Azure → Funnel → Hub，且不接受自訂 prompt。

LINE Developers Console 的 Webhook URL 設為：

`https://你的網站/api/line-webhook`

儲存後按「Verify」，成功後開啟「Use webhook」。

若每次詢問前先出現「感謝您的訊息！很抱歉，本帳號無法個別回覆……」，那是 LINE
Official Account Manager 內建的自動回應，不是 RocketAI 的程式回覆。請到「設定 →
回應設定」，保留 Webhook／Messaging API，並關閉「自動回應訊息」；需要時也可另外
關閉「加入好友的歡迎訊息」。

- 手動排點模式：桌面拖曳或手機點選球友，取代／交換候選對戰位置後安排至空場
- 球友可複選偏好搭檔與拒絕搭檔；智慧排點鼓勵偏好組合並禁止拒絕組合同隊
- 可設定每位球友的到場時間、離場時間與今晚目標場數，依剩餘時間及尚缺場數動態排序
- 11 吋 iPad 觸控最佳化：橫向雙欄排點、直向底部導覽、44px 以上觸控區及點選式手動換人
- 桌面與 iPad 橫向可收合左側選單，收合偏好會保存在目前裝置
- 8/5 報名資料依 B（18:00–20:30）、C（20:30–22:30）與 B+C 時段限制排點；跨時段球友只建立一筆資料
- 備戰區只顯示當下時段可上場球友：B 時段隱藏 C 名單，20:30 後自動切換為 C 與 B+C 名單；未到場前不累計等待時間
- 即時場地依時段自動切換：B 時段僅開放 2 面，C 時段開放 3 面，手動與自動排點都不能使用未開放場地
- 獨立魔王區：小宇、Kevin、阿宏哥、Grace 四位教練級高手，不占 B／C 報名容量，也不會混入一般智慧排點
- 趣味排點活動：魔王挑戰、幸運搭檔與復仇戰；產生後可直接調整名單或安排至空場，賽果照常更新積分與戰績
- 測試屬性採固定種子產生，重新載入不會任意改變：程度 Lv.5.5–9、動態積分為等級 × 100 再加少量差值；單時段目標 5 場、B+C 目標 9 場
