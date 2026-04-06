# Volunteer 專案重新設計文件

**日期**：2026-04-06  
**狀態**：已確認

---

## 目標

建立一個供小團體使用的台北/新北志工活動查詢靜態網站，透過手動執行爬蟲更新資料，部署於 GitHub Pages。

---

## 專案結構

```
volunteer/
├── index.html          ← 從 web/ 移至根目錄
├── data/
│   └── events.json
├── scraper.py
├── requirements.txt
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-06-volunteer-redesign-design.md
```

`index.html` 中 `DATA_URL` 由 `"../data/events.json"` 改為 `"data/events.json"`。

---

## 資料來源

| 來源 | 類型 | 抓取方式 |
|---|---|---|
| 環境部海岸淨灘平台 | 淨灘 | POST JSON API（現有實作保留）|
| 中華民國保護動物協會 APATW | 動物志工 | HTML 爬取，`apatw.org/news/term/6?page=N` |

**移除**：台北市動保處（網站無法連線）、台灣 SPCA（靜態頁面）

`events.json` 資料格式維持現有欄位結構不變。

---

## 部署

- **平台**：GitHub Pages
- **Repo**：新建 `ghoo1125/volunteer`
- **分支**：`main`，從根目錄提供
- **網址**：`https://ghoo1125.github.io/volunteer`

---

## 使用流程

**首次設定（一次性）：**
1. 調整專案結構
2. 建立 GitHub repo `volunteer`
3. 推送程式碼
4. 啟用 GitHub Pages（main branch, root）

**每次更新資料：**
```bash
python scraper.py
git add data/events.json
git commit -m "update events"
git push
```

---

## 不在範圍內

- 自動排程（crontab、GitHub Actions）
- 後端或資料庫
- 使用者登入或權限管理
