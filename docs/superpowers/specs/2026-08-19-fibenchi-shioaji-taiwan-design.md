# Fibenchi Taiwan / Shioaji 純台股版設計規格

日期：2026-08-19  
狀態：使用者已核准設計方向

## 1. 目標

將 Fibenchi 改造成純台股研究與監控系統，保留既有 Groups、Tags、Thesis、Portfolio、技術指標與 Web UI 架構，將 Yahoo Finance 從執行路徑移除，並以永豐金 Shioaji 作為唯一市場行情來源。

第一版支援範圍：

- 台灣上市股票（TSE）
- 台灣上櫃股票（OTC）
- 台灣 ETF
- 即時行情、五檔、盤中分時、歷史 K 線
- RSI / MACD / SMA / EMA / Bollinger Bands / ATR / ADX
- Groups / Tags / Thesis / Portfolio
- 中文名稱與股票代碼搜尋
- LIVE / CACHED / DISCONNECTED 行情狀態

第一版明確不支援：

- 美股與海外 ETF
- Yahoo Finance 執行時 fallback
- Fundamentals
- Earnings
- ETF holdings / ETF 成分股
- 永豐實際持倉同步
- 下單
- 期貨、選擇權、權證、興櫃、ETN、指數等其他商品

## 2. 核心架構決策

### 2.1 Shioaji 採獨立 Sidecar

採用 Shioaji 官方 HTTP / SSE Server 作為獨立服務，不把 Shioaji Python SDK 直接嵌入 Fibenchi FastAPI process。

資料流：

```text
Browser
  -> Fibenchi REST / SSE
  -> Fibenchi Backend
  -> ShioajiPriceProvider
  -> Shioaji HTTP / SSE Server
  -> Sinotrade / Shioaji upstream
```

理由：

- 隔離券商登入與市場資料連線 lifecycle。
- Fibenchi 前端仍只連 Fibenchi，不接觸券商 API。
- API Key / Secret Key 僅存在 Shioaji service 的環境設定。
- Shioaji 暫時斷線不會讓 Fibenchi DB、分類、歷史指標功能一併失效。
- 未來若恢復海外市場，可重新加入其他 PriceProvider，不需重寫前端。

### 2.2 保留 PriceProvider 抽象層

Fibenchi 既有 `PriceProvider` 保留。第一版 registry 只啟用 Shioaji：

```text
PriceProvider
  -> ShioajiPriceProvider
```

預設：

```env
PRICE_PROVIDER=shioaji
```

Yahoo provider 程式碼可暫時保留於 repository 供未來恢復海外市場，但不得出現在純台股模式的 runtime dependency path、search fallback 或 validation fallback。

## 3. Docker / Runtime 拓撲

預期服務：

```text
postgres
shioaji
backend
frontend
```

Fibenchi backend 透過內部 service URL 連 Shioaji server，例如：

```env
SHIOAJI_BASE_URL=http://shioaji:8080
PRICE_PROVIDER=shioaji
```

Shioaji service 自己持有：

```env
SJ_API_KEY=...
SJ_SEC_KEY=...
```

不得：

- 將 API Key / Secret Key 寫入 repository。
- 將憑證送到 browser。
- 將憑證放入 frontend environment。

第一版僅需要行情權限，不實作交易。

## 4. 台股商品識別

### 4.1 Symbol 格式

系統統一使用台灣原始股票代碼：

```text
2330
2454
6488
0050
```

不使用 Yahoo suffix：

```text
2330.TW
6488.TWO
```

### 4.2 商品資料責任

Shioaji：

- Contract 是否存在
- TSE / OTC exchange
- 市場行情
- Kbars
- 即時 Quote
- 商品交易層資訊

TWSE / TPEx 官方 reference data：

- 中文名稱
- stock / ETF 商品分類
- 官方商品名冊

不得從代碼格式推測 ETF，例如禁止 `symbol.startswith("00")` 類 heuristic。

### 4.3 SymbolDirectory

沿用 Fibenchi `symbol_directory`，擴充或調整為台股用途。

最低欄位：

```text
symbol
name
exchange      # TSE / OTC
type          # stock / etf
currency      # TWD
active
last_seen
contract_updated_at
reference_updated_at
```

正式 schema 變更需使用 Alembic migration。

商品只有同時符合以下條件才可作為第一版可加入 Asset：

1. TWSE / TPEx 官方名冊屬於允許範圍（上市、上櫃、台灣 ETF）。
2. Shioaji Contract 中存在對應商品。

## 5. 商品目錄同步與搜尋

### 5.1 同步

建立 `SymbolDirectorySync` 或等價 service：

```text
TWSE reference
TPEx reference
Shioaji Contracts
    -> normalize
    -> merge
    -> upsert SymbolDirectory
```

同步時機：

- 系統首次啟動需要可建立本地目錄。
- 每日盤前執行一次排程更新。
- 同步失敗不得清空既有目錄；保留上次成功資料並記錄 stale / error 狀態。

### 5.2 搜尋

前端搜尋只查本地 PostgreSQL `symbol_directory`。

支援：

- 股票代碼 exact / prefix / substring
- 中文名稱 substring

不得在使用者每次輸入時呼叫 Shioaji 或 Yahoo。

原本 `search_service.py` 中 Yahoo fallback 必須移除。

### 5.3 Asset 建立

原本 `yahoo_client.validate(symbol)` 流程改成：

```text
symbol
 -> SymbolDirectory lookup
 -> validate active + supported
 -> create Asset
```

Asset 基本欄位由 SymbolDirectory 帶入：

```text
symbol
name
exchange
type
currency=TWD
```

`AAPL`、`NVDA` 等非台股代碼在第一版不得建立，也不得偷偷 fallback Yahoo。

## 6. 台灣市場日曆與 AssetRef

Fibenchi 現有 `XTAI` 可沿用，但必須移除「無 suffix = US / XNYS」對台股模式的影響。

台股 identity 不從 symbol 字串猜 exchange，而從已知 asset / symbol directory metadata 解析：

```text
TSE -> XTAI / TWD
OTC -> XTAI / TWD
```

ETF 與 stock 都使用 XTAI 交易日曆；type 由官方 reference data 決定。

若現有 `AssetRef` 只有 symbol 字串且無法安全取得 exchange，需調整 identity / instrument metadata seam，避免重建新的隱含 heuristic。

## 7. 即時行情

### 7.1 Quote-only 訂閱

第一版使用 Shioaji Quote stream 作為台股 live quote 主來源，讓每檔 tracked symbol 只占一個 subscription slot。

Quote 正規化為 Fibenchi 既有 `Quote` schema，至少包含：

- symbol
- price
- previous_close
- change
- change_pct
- open / high / low
- volume
- bid / ask 相關欄位（若既有 schema / UI 支援）
- market_state
- session_date
- data_status
- updated_at

`data_status` 建議值：

```text
LIVE
CACHED
DISCONNECTED
```

### 7.2 動態訂閱池

Shioaji 上游 subscription 硬限制為 200；Fibenchi 正常運作上限設為 180，保留 headroom。

```env
SHIOAJI_MAX_SUBSCRIPTIONS=180
```

單一 symbol 不論存在多少 Groups / Tags，只占一個 slot。

Wanted set 優先級：

1. 使用者目前正在查看的個股。
2. 標記為 realtime priority 的 Groups。
3. 使用者目前正在看的 Group。
4. 最近瀏覽股票。
5. 其他 tracked assets。

Group 新增明確欄位表示是否為即時優先，不使用 group name magic string，例如：

```text
realtime_priority: bool
```

### 7.3 Subscription Manager

建立獨立 `SubscriptionManager`：

- 維護 current set。
- 計算 wanted set。
- 只 subscribe / unsubscribe 差異。
- 不因頁面切換而重新登入 Shioaji。
- 重連後依當下 priority 重新建立訂閱集合。
- 同一 symbol 去重。
- 超過 180 時採 deterministic priority eviction。

### 7.4 超出池容量的顯示

超出即時池的 symbol 不消失，使用最後一次已知 quote / DB close 顯示為 `CACHED`。

不得使用 Snapshot、Kbars 或 Ticks 週期輪詢冒充即時行情。

CACHED UI 必須呈現最後更新時間，避免將 stale value 表示成 live。

## 8. Fibenchi SSE

Browser 仍只訂閱 Fibenchi `/api/quotes/stream` 或等價 endpoint。

Fibenchi backend 將 Shioaji live state 正規化後再向 browser 發 SSE。前端不得直接連 Shioaji server。

既有 Fibenchi SSE delta compression 可保留，但 poll-based Yahoo fetch loop 需改成 event-driven quote state source 或相容 adapter。

前端仍維持現有 reconnect/backoff 機制；另外顯示 provider data status。

## 9. 盤中分時資料

原版 Yahoo intraday fetch / poll 改為 Shioaji live quote event 聚合。

資料流：

```text
Shioaji Quote stream
  -> intraday aggregator
  -> 1-minute OHLCV
  -> IntradayPrice
  -> Fibenchi intraday SSE / chart
```

盤中不得持續呼叫 Kbars / Snapshot / Ticks 來更新分時圖。

聚合器需：

- 使用 Asia/Taipei / XTAI session。
- 以分鐘 bucket 聚合 open/high/low/close/volume。
- duplicate / reconnect event 不得造成 volume 重複累計。
- 重連缺口不可捏造；標示 gap 或待後續歷史修補。

## 10. 歷史 K 線

Shioaji Kbars 作為唯一歷史 market data source。

建立 `HistoricalDataQueue`：

- 所有 historical request 統一排隊。
- 日期範圍自動切片，每個 upstream request 不超過 Shioaji 支援的最大區間。
- rate limiting。
- retry / timeout。
- request de-duplication。
- 只補 DB 缺少區間。
- 一個 symbol 的錯誤不得中止整批同步。

### 10.1 Daily OHLCV

Shioaji minute bars 依 XTAI 交易日聚合成正式 daily bar，再存入既有 Price table / PriceRepository。

正式 daily bar 只由已完成 session 的歷史資料產生。

原本針對 Yahoo partial daily bar 的 `drop_unsettled_last_bar` / reconciliation 邏輯不得無條件照搬；應以 Shioaji 的「live intraday」與「settled historical daily」分流取代。

### 10.2 初始 Backfill

新增股票時：

- 先補 `1y + indicator warmup`。
- 使用者要求 2y / 5y 時才補缺少區間。
- 不預設把所有 symbol 都 backfill 到 upstream 最早日期。

### 10.3 每日同步

收盤後補最近缺少的已完成交易日，不每天重抓整年。

流程：

```text
DB latest settled day
 -> compute missing XTAI sessions
 -> enqueue missing date ranges
 -> Kbars
 -> daily aggregation
 -> upsert Price
 -> recompute / invalidate indicator cache
```

## 11. 技術指標

沿用 Fibenchi 既有計算層：

- RSI
- SMA
- EMA
- Bollinger Bands
- MACD
- ATR
- ADX

指標只依賴 PostgreSQL settled OHLCV，不直接依賴 Shioaji 連線。

因此 Shioaji disconnected 時，既有歷史圖表與指標仍可正常使用。

保留 indicator warmup 機制，但 historical fetch 改成 Shioaji / local DB 缺口補齊。

## 12. Portfolio / Groups / Tags / Thesis

第一版保留既有功能與資料模型，除非因台股 identity 需要最小必要 migration。

注意：原版 Fibenchi Portfolio 是 grouped assets 的 composite index，不代表券商實際持倉。

第一版「持有」只是一般 Group，可設為 `realtime_priority=true`；不得自動聲稱與永豐實際庫存同步。

未來可獨立新增 Positions Sync，但不在本 spec。

## 13. Yahoo 功能處理

### 13.1 Runtime 必須移除

以下 runtime 路徑不得再依賴 Yahoo：

- quote
- history
- intraday
- symbol search
- asset validation
- currency resolution for supported Taiwan assets
- market calendar inference for supported Taiwan assets

### 13.2 第一版停用 UI / API

如果功能完全依賴 Yahoo 且沒有已核准替代來源，第一版停用而非造假：

- Fundamentals
- Earnings
- ETF Holdings
- Yahoo Finance external links / Yahoo-specific study links

前端不得留會必然 500 / 空白的入口；應明確隱藏或顯示「此台股版本未啟用」。

### 13.3 Yahoo code 是否刪除

不要求物理刪除全部 Yahoo source files。優先目標是：

- runtime 不 import / instantiate Yahoo provider。
- requirements 不因台股模式必須安裝 yahooquery；若測試或 legacy code 尚需保留，需在 implementation plan 明確處理。
- 未來可以低成本恢復海外 provider。

## 14. 斷線與容錯

### 14.1 Shioaji 中斷

狀態轉為：

```text
DISCONNECTED
```

Browser 顯示最後已知價與 timestamp，但不得顯示為 LIVE。

歷史資料、Indicators、Groups、Tags、Thesis、Portfolio 繼續從 DB 正常運作。

### 14.2 重連

採 exponential backoff + health check。

恢復後：

1. 重建 Shioaji SSE connection。
2. SubscriptionManager 重新計算 wanted set。
3. 重新建立最多 180 個 subscriptions。
4. 收到第一批新 event 後把對應 symbol 轉 LIVE。

不得在每次短暫 disconnect 時反覆重新建立券商 login session。

### 14.3 商品目錄同步失敗

保留上次成功的 SymbolDirectory；不得用空回應覆蓋有效資料。

### 14.4 歷史同步失敗

每檔獨立 retry / rollback；單一 symbol failure 不得中止其他股票。

## 15. 資料一致性

- `symbol` 是台股原始代碼，應維持 string，不轉 integer，保留前導 0。
- timezone 統一明確使用 Asia/Taipei / XTAI。
- currency 對本 spec 支援商品固定為 TWD，但仍保留既有 currency 欄位以利未來 provider 擴充。
- exchange 必須來自已驗證 metadata，不從 symbol heuristic 推導。
- stock / ETF 必須來自官方 reference data，不從代碼 heuristic 推導。

## 16. Migration 策略

預計至少涉及：

- SymbolDirectory 欄位擴充。
- Group `realtime_priority`。
- 如 Asset 本身目前沒有足夠 exchange metadata，新增或建立可靠關聯。
- 如 quote schema 需 data status / updated timestamp，後端 schema + frontend type 一起修改。

Migration 必須可從原 Fibenchi schema 升級，不假設空資料庫。

如果舊 DB 已有 Yahoo-style symbols，第一版 implementation plan 必須明確決定：

- 自動 migrate `2330.TW -> 2330` / `6488.TWO -> 6488`，或
- 提供一次性 migration command。

不得靜默把無法判定的海外 symbol 當台股。

## 17. 測試策略

### 17.1 單元測試

必須覆蓋：

- Shioaji response -> Fibenchi Quote mapping。
- TSE / OTC mapping。
- stock / ETF reference classification。
- leading-zero symbol preservation。
- SymbolDirectory merge / stale handling。
- Subscription priority ordering。
- 180-slot cap。
- duplicate symbol de-duplication。
- subscribe / unsubscribe diff。
- reconnect rebuild。
- LIVE / CACHED / DISCONNECTED transitions。
- historical 30-day chunking。
- historical request de-duplication。
- minute -> daily OHLCV aggregation。
- minute -> intraday 1m aggregation。
- XTAI trading date boundaries。
- failed symbol does not abort batch。

### 17.2 Integration 測試

Shioaji upstream 需用 fake / stub server，不使用真 API Key：

- contracts sync -> SymbolDirectory。
- search -> add asset -> group -> quote stream。
- historical backfill -> PriceRepository -> indicators。
- disconnect / reconnect SSE。
- >180 tracked symbols priority behavior。

### 17.3 Regression

保留並更新原 Fibenchi tests，至少確保：

- Groups
- Tags
- Thesis
- Portfolio
- indicators
- price charts
- asset add/remove
- migrations

### 17.4 CI

CI 不得依賴：

- 真永豐帳號。
- 真 Shioaji API Key。
- 盤中市場是否開盤。
- TWSE / TPEx 即時網路可用性。

所有 upstream responses 使用 fixtures / stub。

## 18. 驗收標準

第一版完成時必須滿足：

1. Docker Compose 可啟動 DB、Shioaji sidecar、backend、frontend。
2. 未設定任何 Yahoo credential / dependency 仍能完成所有台股核心流程。
3. 可用 `2330` / `台積` 搜尋到台積電。
4. 可用 `0050` / 中文名稱搜尋 ETF，且 type 正確。
5. 可建立 Groups / Tags / Thesis，股票可同時屬於多個分類。
6. 台股 symbol 使用原始代碼，不顯示 `.TW` / `.TWO`。
7. 180 檔內可標示 LIVE；超出池的低優先級 symbol 顯示 CACHED，不假裝即時。
8. 打開某 CACHED 個股時可提升其優先級並進入 LIVE（有上游連線時）。
9. Shioaji 斷線後 UI 顯示 DISCONNECTED + last updated time。
10. Shioaji 斷線時歷史 K、Indicators、Groups、Tags、Thesis、Portfolio 仍可使用。
11. 新加入股票可取得 1y + warmup 歷史資料並計算所有既有技術指標。
12. 收盤後只補 DB 缺口，不重抓完整歷史。
13. Yahoo Search / Validation / Quote / History / Intraday 不在純台股 runtime 路徑。
14. Fundamentals / Earnings / ETF holdings 第一版不會呼叫不存在的 backend，而是被停用或明確隱藏。
15. CI 可在沒有 Shioaji 真帳號情況下完整測試。

## 19. 實作順序建議

本文件是 architecture spec，不是 implementation plan。正式 implementation plan 應依下列 dependency order 拆成可驗證 slices：

1. Fork / branch / baseline CI。
2. Taiwan instrument identity + schema migrations。
3. SymbolDirectory reference sync + local search + asset validation replacement。
4. Shioaji sidecar + HTTP client + ShioajiPriceProvider historical/quote mapping。
5. HistoricalDataQueue + daily aggregation + price sync replacement。
6. SubscriptionManager + Shioaji SSE ingestion + quote state cache。
7. Fibenchi SSE integration + LIVE/CACHED/DISCONNECTED frontend。
8. Intraday aggregation。
9. Disable Yahoo-only features / dependencies / links。
10. End-to-end regression + Docker + documentation。

## 20. 非目標 / 後續擴充 seam

未來可以獨立加回：

```text
YahooPriceProvider / other overseas provider
Shioaji Positions sync
FundamentalProvider (TWSE / FinMind / other source)
ETFHoldingsProvider
Order / trading subsystem
```

上述項目不得在第一版順手加入。
