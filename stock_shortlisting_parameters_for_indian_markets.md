# AI Agent Framework: Stock Shortlisting Parameters for Indian Markets

To build an effective AI Agent for shortlisting Indian stocks, the architecture must integrate **quantifiable fundamental metrics**, **technical momentum triggers**, and **India-specific governance parameters**.

---

## 1. Fundamental Parameters (Financial Health & Valuation)

| Category | Metric / Parameter | Recommended Threshold / Rule | Significance in the Indian Market |
| :--- | :--- | :--- | :--- |
| **Profitability & Capital Efficiency** | **ROCE** (Return on Capital Employed) | $> 15\% - 20\%$ | Crucial metric for identifying high-quality, capital-efficient businesses capable of long-term compounding. |
| | **ROE** (Return on Equity) | $> 15\%$ (3–5 Year Average) | Measures how effectively management yields returns on shareholder capital. |
| **Solvency & Risk Mitigation** | **Debt-to-Equity Ratio (D/E)** | $< 0.5$ (Ideally Debt-Free) | Interest rates in India fluctuate with economic cycles; low debt reduces risk during credit contractions. |
| | **Interest Coverage Ratio** | $> 3.0x$ | Guarantees that operating cash flows comfortable service interest obligations. |
| **Growth Metrics** | **Sales Growth** (YoY & 3Y/5Y CAGR) | $> 10\% - 15\%$ | Reflects top-line market share expansion in line with India's GDP trajectory. |
| | **PAT Growth** (Profit After Tax CAGR) | $> 12\% - 15\%$ | Ensures top-line growth flows through to earnings per share. |
| **Valuation Metrics** | **P/E vs. Industry P/E** | Close to or lower than Industry average | Prevents overpaying for overhyped growth. |
| | **PEG Ratio** (Price/Earnings-to-Growth) | $< 1.0$ | Adjusts P/E relative to actual earnings growth rates. |

---

## 2. Promoter & Ownership Structure (India-Specific Guardrails)

Due to promoter-driven corporate structures in India, monitoring promoter ownership and pledging is critical:

* **Promoter Holding:** Preferred **$> 50\%$**. Consistent reduction in promoter stake across sequential quarters is a primary red flag.
* **Promoter Pledging:** **$< 5\%$ (Ideally $0\%$)**. High pledging exposes the stock to aggressive price cascades upon margin calls.
* **Institutional Flow (FII & DII):** Quarterly increases in **FII** (Foreign Institutional Investor) and **DII** (Domestic Mutual Fund) stakes signal institutional conviction.

---

## 3. Liquidity & Technical Momentum Rules

* **Liquidity Filter:** Minimum average daily trading value $> \text{₹1–2 Crore}$ to minimize slippage and filter out illiquid micro-caps.
* **Trend & Momentum Filters:**
  * **200-day Simple Moving Average (SMA):** Stock price maintained above the 200 SMA signals a secular bull trend.
  * **52-Week High Proximity:** Stocks trading within **15–20%** of 52-week highs frequently show strong momentum.
* **Market Capitalization Classification:**
  * **Large Cap:** $> \text{₹20,000 Cr}$
  * **Mid Cap:** $\text{₹5,000 Cr} - \text{₹20,000 Cr}$
  * **Small Cap:** $< \text{₹5,000 Cr}$

---

## 4. Qualitative & Sentiment Metrics (NLP / LLM Integration)

Your AI Agent can process unstructured data sources to complement quantitative data:

* **Earnings Call Transcripts (Concalls):** Extract guidance on future revenue goals, CAPEX timelines, and operating margin outlooks.
* **Governance Scans:** Detect auditor resignations, regulatory penalties from SEBI, or qualified audit opinions in annual report footnotes.
* **News & Sectoral Sentiment:** Measure sentiment scores from major financial portals (e.g., Moneycontrol, Economic Times).

---

## Proposed AI Agent Architecture

```
                       [ Data Ingestion Layer ]
        (NSE/BSE APIs, Screener Data, Financial Statements)
                                  │
                                  ▼
                   [ Quantitative Screening Engine ]
           (ROCE > 15%, D/E < 0.5, Pledging = 0%, Vol > ₹1Cr)
                                  │
                                  ▼
                  [ Qualitative & NLP Agent (LLM) ]
          (Concall Summaries, Governance Checks, News Sentiment)
                                  │
                                  ▼
                    [ Final Scoring & Shortlist ]
             (Ranked stock output with clear investment thesis)
```