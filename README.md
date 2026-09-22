# Upwork Scraper PRO - Clone & More Powerful

> **Clone of `blackfalcondata/upwork-scraper`** - Reverse engineered from Apify Store  
> **Even more powerful**: Adds AI Lead Scoring, Competition Analysis, Premium Client Tiering, and Enhanced Incremental Mode.

**Built for:** Freelancers in Lahore/PK targeting premium US/EU clients without wasting Connects.

---

## 🚀 What Makes This MORE Powerful Than Original?

| Feature | Original (`blackfalcondata`) | **PRO Clone (This)** |
|---|---|---|
| **Core scraping** | GraphQL, 14 filters, exact applicants | ✅ Same + improved re-sort by publishTime |
| **Client Intel** | Country, Spent, Verified, Rating | ✅ + City, Timezone, HireRate, CompanySize, Industry |
| **AI Scoring** | `customJobScore` (0-5) | ✅ **aiLeadScore (0-100), competitionScore, clientTier (PREMIUM/Good/Risky), estimatedConnects** |
| **Incremental** | NEW/UPDATED detection | ✅ + REAPPEARED, EXPIRED, Repost detection via SHA256, auto stateKey |
| **Filters** | 14 filters | ✅ + `customFilters` (any field), `maxAgeMinutes`, `fromDate/toDate`, `include/excludeKeywords` |
| **Paste Mode** | Single searchUrl | ✅ **Batch `startUrls` - multiple URLs in one run, deduped** |
| **Batch Query** | `["term1","term2"]` | ✅ Same + auto-expansion from JSON string |
| **Detail Enrichment** | Requires sessionToken | ✅ + Better error handling (no silent downgrade), 30+ fields |
| **Notifications** | Telegram/Slack/Discord/Webhook | ✅ Same + rich embeds (Discord), Slack blocks, metadata header |
| **Output** | compact, descriptionMaxLength | ✅ + `descriptionFormat` (all/text/html/markdown), `excludeEmptyFields` |
| **Local Run** | Apify only | ✅ **Works locally without Apify (`python -m src.main`) + Apify** |

---

## 📦 Installation

### Option 1: Run on Apify (Recommended)
1. Push to GitHub → Connect to Apify → Deploy
2. Or use Apify CLI:
```bash
apify create --template python
# copy src/ and .actor/ into project
apify push
```

### Option 2: Local Run (No Apify needed)
```bash
git clone <this-repo>
cd upwork-clone-pro
pip install -r requirements.txt
python -m src.main
# Results in output/results.json
```

---

## 🔧 Usage Examples

### 1. Basic - Find Low Competition Shopify Jobs
```json
{
  "query": "shopify developer",
  "maxResults": 50,
  "proposals": "0-4",
  "verifiedPaymentOnly": true,
  "enableAIScoring": true
}
```
→ Output sorted by `aiLeadScore` - 95 for PREMIUM clients with 2 applicants!

### 2. Premium US Clients Only (Save Connects)
```json
{
  "query": "python scraping",
  "location": ["United States"],
  "minClientTotalSpent": 10000,
  "minClientRating": 4.8,
  "minClientReviewCount": 5,
  "budget": "1000-4999",
  "proposals": "0-4"
}
```

### 3. Incremental Tracking (Hourly Cron - 95% Cheaper)
```json
{
  "query": "react native",
  "maxResults": 200,
  "incrementalMode": true,
  "stateKey": "react-native-tracker",
  "telegramToken": "123:ABC",
  "telegramChatId": "-100123456",
  "notifyOnlyChanges": true,
  "notificationLimit": 5
}
```
First run: 200 jobs (baseline). Next runs: only `NEW/UPDATED` (e.g. 5-10 jobs) → billed only for those!

### 4. Batch Search - Multiple Niches One Run
```json
{
  "startUrls": [
    "https://www.upwork.com/nx/search/jobs/?q=shopify&hourly_rate=30-100",
    "https://www.upwork.com/nx/search/jobs/?q=wordpress&amount=500-5000"
  ],
  "maxResults": 100
}
```
→ Single dataset, single Actor start charge ($0.001) vs 2 runs.

### 5. Detail Enrichment (30+ Extra Fields)
```json
{
  "query": "AI agent",
  "maxResults": 20,
  "enrichDetails": true,
  "sessionToken": "oauth2v2_int_abc123...",
  "detailConcurrency": 10
}
```
How to get token: Login Upwork → F12 → Network → Filter `graphql` → Click any request → Headers → `authorization: Bearer oauth2v2_int_...` copy value without `Bearer `.

### 6. Custom Advanced Filter (Any Field)
```json
{
  "query": "data entry",
  "customFilters": [
    {"field": "clientCountry", "op": "equals", "value": "United States"},
    {"field": "description", "op": "notIncludes", "value": "wordpress"},
    {"field": "aiLeadScore", "op": "gte", "value": 70}
  ]
}
```

---

## 📤 Output Schema (Example)

```json
{
  "jobId": "2047620102105297516",
  "title": "Full Stack Software Engineer",
  "jobType": "HOURLY",
  "hourlyBudgetMin": 40,
  "hourlyBudgetMax": 100,
  "skills": ["React", "Python"],
  "publishTime": "2026-09-22T10:15:12Z",
  "totalApplicants": 3,
  "clientCountry": "United States",
  "clientTotalSpent": 125000,
  "clientPaymentVerified": true,
  "clientRating": 4.98,
  "clientReviewCount": 42,
  "url": "https://www.upwork.com/jobs/~022047620102105297516",
  "contentHash": "f6a9bb...",
  "changeType": "NEW",
  "aiLeadScore": 92.5,
  "competitionScore": 95,
  "clientTier": "PREMIUM",
  "estimatedConnects": 6,
  "customJobScore": 4.62,
  "scrapedAt": "2026-09-22T10:27:07Z"
}
```

**Extra when enrichDetails=true:** `clientIndustry, clientCompanySize, clientHireRate, clientLastActivity, questions, attachments, hireRate`

---

## 🧠 AI Lead Scoring Explained

We calculate `aiLeadScore` 0-100 so you know where to spend Connects:

- **+25** if spent $100k+, **+20** if $50k+, **+15** if $10k+
- **+10** if payment verified, **-15** if not
- **+15** if 0-4 applicants (low competition), **-10** if 20+ applicants
- **+10** if rating 4.9+, **-5** if <4.0
- **Tier:** PREMIUM (85+), Good (70+), Medium (50+), Risky (<50)

---

## 🔁 Incremental Mode Deep Dive

Original's incremental is good, PRO's is better:

- **State storage:** Apify KV `upwork-state-{stateKey}` or local JSON
- **Auto stateKey:** If empty, SHA256 of query+location+jobType auto-generates isolated state per search
- **Hash:** SHA256(title+desc+budget+skills) → detects UPDATED vs UNCHANGED
- **Repost:** Same hash but new jobId → `REAPPEARED`, `isRepost=true`, `repostOfId`
- **Expired:** Jobs not seen this run → counted but not emitted unless `emitExpired:true`

---

## 🔔 Notifications

Set any combo, all run in parallel (15s timeout, 1 retry):

- **Telegram:** Needs `@BotFather` token + `@userinfobot` for chatId
- **Discord:** Server Settings → Integrations → Webhooks
- **Slack:** Slack App → Incoming Webhooks
- **Generic:** n8n/Make/Zapier → `POST {metadata, items}`

---

## ⚖️ Legal / Ethics

- Only public data, no login required for core fields
- Respect Upwork ToS, GDPR. Don't spam.
- Not affiliated with Upwork.
- `sessionToken` is your password - never commit to Git.

---

## 📁 Project Structure

```
upwork-clone-pro/
├── .actor/
│   ├── actor.json
│   └── input_schema.json  # 42+ params (enhanced)
├── src/
│   ├── main.py            # Actor entry - orchestrates all
│   ├── upwork_api.py      # Reverse-engineered GraphQL
│   ├── incremental.py     # SHA256 diff & repost detection
│   ├── notifier.py        # Telegram/Discord/Slack/Webhook
│   └── utils.py           # AI scoring, hash, URL parse
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## 🚀 Deploy to Apify Store

```bash
apify login
apify push
# Then set pricing: $1.00/1000 results + $0.001/start (like original) or free tier
```

---

**Made for Lahore freelancers 🇵🇰 → Targeting premium clients worldwide 🌍**
*Clone but MORE POWERFUL - Save 80% Connects with AI scoring!*
