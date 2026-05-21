---
title: Food Claim Compliance RAG
emoji: 🍃
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: 食品/健康食品宣稱合規檢查 RAG 系統
---

# 食品 / 健康食品宣稱合規檢查 RAG 系統

> 輸入產品宣稱文字，自動回覆三段式分析：
> 1. **法規分析** — 引用食安法、健康食品管理法、認定準則
> 2. **類似裁罰案例** — 從 114/115 年台北市衛生局 400 件裁罰中精準檢索
> 3. **建議修改** — 改寫為合法宣稱

---

## 🎬 兩種使用方式

### 方式 A：直接用主機分享的 ngrok 公開網址
不用 clone、不用裝 Python，**瀏覽器打開就能用**。網址會由主機在群組裡公告（每次重啟會變）。

### 方式 B：本地 clone 自己跑（5 分鐘）
跟著下面步驟。

---

## 📦 內容物

```
rag_app/
├── ingest/              # 一次性資料前處理腳本（你不用跑，索引已 ship）
├── backend/             # FastAPI 後端 + RAG 邏輯
├── frontend/            # 單頁 HTML UI
├── corpus/              # JSONL 中介資料（1,402 筆）
├── data/chroma/         # 已建好的 ChromaDB 向量索引（47MB，省你 1 小時 ingest）
├── .env.example         # 環境變數範本
└── requirements.txt
```

資料層內容：
- **1,002** 個法規 chunk（食安法28/22/45/47/49、健康食品管理法、113標示手冊）
- **400** 件台北市衛生局 114/115 年裁罰案例

---

## 🚀 本地啟動（方式 B）

### 1. 環境

需要 Python ≥ 3.10。建議用虛擬環境：

```bash
git clone <repo-url>
cd rag_app
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 申請 Gemini API key（免費）

1. 開 https://aistudio.google.com/apikey
2. **Create API key** → 選「Create API key in new project」（避免舊專案被擋）
3. 複製 key（開頭 `AIza...`）

> 免費額度：embedding 1000 req/日、chat 1500 req/日。一般測試足夠。

### 3. 建立 `.env`

```bash
cp .env.example .env
# 編輯 .env，填入你剛剛拿到的 key
```

`.env` 內容只需要這幾行：
```
GEMINI_API_KEY=AIza你的key
CHAT_MODEL=gemini-2.5-flash
EMBED_MODEL=gemini-embedding-001
CHROMA_DIR=./data/chroma
```

### 4. 啟動 server

```bash
uvicorn backend.main:app --reload --port 8000
```

開瀏覽器：**http://127.0.0.1:8000**

點右下角「**載入範例宣稱**」→「**送出分析**」，5-10 秒看到三段式結果。

---

## 🧪 範例查詢

試試這幾段違規文案：

| 類型 | 範例 |
|---|---|
| 抗癌療效 | 「本產品可有效抑制癌細胞、預防腫瘤復發、改善肝功能、降低血糖」 |
| 減重瘦身 | 「7 天瘦 5 公斤、燃燒脂肪、加速代謝、消除水腫、不忌口」 |
| 改善睡眠 | 「天然安神配方、深度入眠、徹底解決失眠、改善神經衰弱」 |
| 提升性功能 | 「強腎補陽、增強性能力、男性活力、改善前列腺問題」 |

每次查詢系統會：
1. 對 1,002 段法規 + 400 件案例做雙路向量檢索
2. 拼成結構化 prompt 給 Gemini 2.5 Flash
3. JSON mode 強制回傳三段內容
4. 前端按紅 / 琥珀 / 翠綠三張卡片渲染

---

## 🔧 技術細節

| 元件 | 技術 |
|---|---|
| 後端 | Python 3.12 + FastAPI |
| LLM | Google Gemini 2.5 Flash |
| Embedding | Gemini Embedding 001（3072 維） |
| 向量資料庫 | ChromaDB（本機檔案模式） |
| 前端 | 單檔 HTML + Tailwind CSS + Alpine.js |
| PDF 解析 | PyMuPDF + pdfplumber |

雙 Collection 設計：
- `regulations` — 法規條文、解釋、認定準則
- `violations` — 逐案結構化的裁罰紀錄（含產品、罰鍰、罰則）

---

## ❓ 常見問題

**Q: 查詢回 429 / RESOURCE_EXHAUSTED**
> Gemini 免費額度用完了。embedding 每日 1000 req、chat 每日 1500 req（每天 UTC 0:00 重置 = 台灣下午 3 點左右）。或開 Billing 升級為付費層。

**Q: 想換更強模型？**
> `.env` 改 `CHAT_MODEL=gemini-2.5-pro`，回答品質更好但 token 較貴。

**Q: 想重建向量索引（用更新版資料）？**
```bash
# 1. 把原始 PDF/DOCX 丟回 ingest/ 期望的位置
python ingest/01_extract_regs.py
python ingest/02_extract_cases.py
# 2. 重新嵌入（會跳過已索引的，安全可重跑）
python ingest/03_embed_index.py
```

**Q: 不能用 Gemini，能換 OpenAI / Claude 嗎？**
> 可以，改 `backend/rag.py` 與 `ingest/03_embed_index.py` 裡的 client 即可。但若改 embedding 模型，ChromaDB 必須完全重建（維度不同）。

---

## ⚠️ 法律聲明

本系統為**輔助工具**，回應不構成法律意見。產品上架前的最終合規責任仍由業者承擔，建議重大決策仍經法務複核。

裁罰資料來源：[臺北市政府衛生局](https://health.gov.taipei/) 公開公告之違規廣告處罰案件統計表。

---

## 📄 規劃文件

完整系統規劃書見 [食品宣稱合規檢查系統規劃書.docx](../食品宣稱合規檢查系統規劃書.docx)
