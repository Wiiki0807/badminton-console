<!--
提交前請完整填寫下列欄位。
所有 PR 都需要 @Wiiki0807（code owner）review 後才能 merge 到 main。
Production 部署不會自動執行，必須由 repository owner 手動觸發 workflow。
-->

## 變更內容

<!-- 說明這個 PR 改了什麼、為什麼要改，並列出主要異動檔案。 -->

-

## 測試結果

<!-- 說明你如何驗證，並貼上實際結果（指令、瀏覽器手動測試步驟、截圖）。 -->

- [ ] 本機啟動 `start-server.cmd` 或 `python server.py` 驗證頁面正常
- [ ] 相關手動測試（記分、live 畫面、admin 流程）已通過
- 測試指令與結果：

## 是否需要 production deployment

- [ ] 需要（merge 後請通知 owner 手動部署）
- [ ] 不需要（僅文件／註解等不影響線上內容的變更）

## 部署注意事項

<!-- 例如：需要先在 Azure 設定的環境變數、api 相依套件變更、staticwebapp.config.json routing 變更、資料需要重置等。 -->

-

## Rollback 與風險

<!-- 說明風險範圍，以及部署後若出問題要如何還原（例如 revert 哪個 commit、重新以先前的 commit SHA 手動部署）。 -->

- 風險：
- Rollback 方式：

---

## Merge 後的部署通知（必填流程）

Merge 進 `main` 之後，請在這個 PR 留一則 comment，**固定使用以下第一行格式**，讓 owner 收到通知：

```
@Wiiki0807 請部署 production。

- PR：#<PR 編號>
- Merge 後的 main commit SHA：<commit SHA>
- 變更摘要：<一句話說明>
- 測試結果：<已通過的驗證項目>
- 需要的部署設定或注意事項：<沒有則寫「無」>
- Rollback 方式：<例如 revert <SHA> 後重新手動部署>
```

Owner 收到通知後，會到 **Actions → Deploy to Azure Static Web Apps (production) → Run workflow**，
以 `ref = main` 手動觸發部署，並在 `production` environment 核准。

> 請勿在 PR 或 comment 中貼上任何 secret、deployment token 或連線字串。
