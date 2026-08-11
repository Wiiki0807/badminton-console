<!--
提交前請完整填寫下列欄位。
請由 @Wiiki0807（code owner）確認後再 merge 到 main。
合併至 main 後會自動部署到 Azure Static Web Apps production。
-->

## 變更內容

<!-- 說明這個 PR 改了什麼、為什麼要改，並列出主要異動檔案。 -->

-

## 測試結果

<!-- 說明你如何驗證，並貼上實際結果（指令、瀏覽器手動測試步驟、截圖）。 -->

- [ ] 本機啟動 `start-server.cmd` 或 `python server.py` 驗證頁面正常
- [ ] 相關手動測試（記分、live 畫面、管理流程）已通過
- 測試指令與結果：

## 是否需要 production deployment

- [ ] 需要（merge 至 main 後自動部署）
- [ ] 不需要（僅文件／註解等不影響線上內容的變更）

## 部署注意事項

<!-- 例如：需要先在 Azure 設定的環境變數、api 相依套件變更、staticwebapp.config.json routing 變更、資料需要重置等。 -->

-

## Rollback 與風險

<!-- 說明風險範圍，以及部署後若出問題要如何還原（例如 revert 哪個 commit、重新以先前的 commit SHA 手動部署）。 -->

- 風險：
- Rollback 方式：

---

## Merge 後的部署確認

Merge 進 `main` 後，請到 **Actions → Deploy to Azure Static Web Apps (production)**
確認 workflow 成功，再檢查 production 網址的管理頁與球友看板。

> 請勿在 PR 或 comment 中貼上任何 secret、deployment token 或連線字串。
