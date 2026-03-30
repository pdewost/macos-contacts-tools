# Hybrid Extraction A/B Test - Comparison Report (Template)
Generated: [Current Date]
Batch: [Group Name] / Simulation Mode

## 1. Executive Summary
| Metric | Branch A (Surgical + Gemini) | Branch B (Hybrid OCR + Gemini) | Delta |
| :--- | :--- | :--- | :--- |
| **Success Rate (Name)** | % | % | + |
| **Success Rate (Contact)** | % | % | + |
| **Avg. Duration (s)** | s | s | - |
| **Avg. API Tokens/Call** | tokens | tokens | - |

---

## 2. Detailed Findings by Contact

### [Contact Name]
*   **Target Profile**: [LinkedIn URL]
*   **Comparison Breakdown**:
| Field | Branch A (Current) | Branch B (Hybrid OCR) | 🏆 Match Status |
| :--- | :--- | :--- | :--- |
| **Full Name** | [Value] | [Value] | Identical / Improved |
| **Job Title** | [Value] | [Value] | ... |
| **Phone** | [Value] | [Value] | New Found / N.A. |
| **LinkedIn URL** | [Value] | [Value] | Consistent |

*   **Latency Analysis**:
    *   Surgical Scrape: [ms]
    *   OCR Capture: [ms]
    *   OCR Processing: [ms]
    *   Gemini Fallback: [Used/Not Used]

---

## 3. Analysis of Method B (OCR) Performance
*   **Artifacts Captured**:
    *   `backups/[contact]/header_snapshot.png`
    *   `backups/[contact]/contact_box_snapshot.png`
*   **Observations**: [e.g. "OCR successfully extracted the phone number where Surgical Scrape's regex failed due to non-standard character encoding."]
