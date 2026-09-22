# 🔍 Upwork Scraper PRO - Pura Walkthrough (Step-by-Step)

> **Bhai ye project kaise kaam karta hai?** Ek ek cheez Roman Urdu me samjhata hun — jaise tum pehli dafa code dekh rahe ho.

---

## 1. Bara Picture - Project Kya Hai?

Socho tum Upwork pe `shopify developer` search karte ho. Browser me jo jobs dikhte hain, wo asal me Upwork ka **GraphQL API** (`api.upwork.com/graphql`) se aate hain. Hamara project **browser ko bypass karke seedha us API ko hit karta hai**, isliye fast hai aur HTML change hone se bhi nahi toot ta.

**Flow:**
```
Tum Input dete ho (query, filters)
        ↓
[1] URL Parse / Filter Build
        ↓
[2] GraphQL API Hit (Upwork ka andar wala API)
        ↓
[3] Raw Jobs → Clean Jobs me Convert
        ↓
[4] Post Filters (Spent, Rating, Keywords)
        ↓
[5] AI Lead Scoring (PREMIUM/Risky)
        ↓
[6] Detail Enrichment (optional, sessionToken)
        ↓
[7] Incremental Check (Naya hai ya Purana?)
        ↓
[8] Dataset me Save + Telegram/Discord Notify
```

---

## 2. Folder Structure Samjho

```
upwork-clone-pro/
├── .actor/
│   ├── actor.json            → Apify ko batata hai ye actor hai, memory kitni chahiye
│   └── input_schema.json     → 49 inputs ka form (Apify UI me jo dikhta hai)
├── src/
│   ├── main.py               → BOSS FILE - sab kuch isi se control hota hai
│   ├── upwork_api.py         → Upwork ke API se baat karne wala
│   ├── utils.py              → AI scoring, hash, helper functions
│   ├── incremental.py        → Purane vs Naye jobs ka hisaab
│   └── notifier.py           → Telegram/Discord pe alert bhejne wala
├── requirements.txt          → Python libraries
├── Dockerfile                → Apify pe kaise chalega
├── demo.html                 → Browser me demo dikhane ke liye
├── test_local.py             → Bina internet ke logic test
├── README.md / QUICKSTART.md → Docs
└── WALKTHROUGH.md            → Ye file
```

---

## 3. Har File Ka Kaam - Detail Me

### A) `src/main.py` - Brain (471 lines)

Ye **manager** hai. Sab steps isi me hote hain:

```python
# 1. Input lo (Apify se ya local se)
inputs = await Actor.get_input()

# 2. Agar searchUrl diya hai to parse karo
# e.g. "https://upwork.com/nx/search/jobs/?q=shopify&hourly_rate=30-"
# → {query:"shopify", hourlyRate:"30-"}

# 3. Har query / har startUrl ke liye loop
for task in search_tasks:
    async for node in api.search(task):
        job = api.transform_node(node)

# 4. Filters lagao (jo GraphQL me nahi ho sake)
jobs = apply_post_filters(jobs)  # minSpent, keywords etc

# 5. AI Score lagao
for job in jobs:
    job.update(calculate_ai_scores(job))  # 0-100

# 6. Agar enrichDetails=true to detail fetch
jobs = await api.fetch_details_batch(jobs)

# 7. Incremental check
if incrementalMode:
    jobs = inc_store.diff(jobs)

# 8. Push to Apify Dataset + Notify
await Actor.push_data(jobs)
await notifier.send_all(jobs)
```

**Simple:** Input → Search → Filter → Score → Save → Notify.

### B) `src/upwork_api.py` - Dil (618 lines) - Reverse Engineering

Ye sab se important hai. Isme Upwork ka **secret GraphQL query** hai:

**Endpoint jo reverse kiya:**
```
https://www.upwork.com/api/graphql/v1  (main)
https://www.upwork.com/graphql        (fallback)
https://api.upwork.com/graphql        (fallback)
```

**Query kya bhejta hai?**
```graphql
query MarketplaceJobPostingsSearch($marketPlaceJobFilter: ...) {
  marketplaceJobPostingsSearch(...) {
    edges {
      node {
        id, ciphertext (~0219...), title, description,
        amount { rawValue },               # Fixed budget
        hourlyBudgetMin/Max { rawValue },  # Hourly
        client {
          totalSpent { rawValue },         # Kitna kharcha kiya
          verificationStatus,              # Verified?
          location { country, city },
          totalFeedback, totalReviews
        },
        totalApplicants, # Exact count (UI pe 10-15 dikhta hai)
        skills { prettyName }
      }
    }
    pageInfo { hasNextPage, endCursor } # Pagination
  }
}
```

**Build Filter kaise?** Tum `jobType: hourly` dete ho → `jobType_eq: HOURLY` banta hai. `proposals: 0-4` → `proposalRange_eq: {from:0, to:4}`.

**Pagination:** Cursor `0` se start, har page 50 jobs. `hasNextPage=true` ho to `endCursor` se agla page lo. 200 jobs chahiye to 4 pages.

**Transform:** Raw node → Hamara clean format:
```js
ciphertext "~0219..." → jobId "219..."
amount.rawValue → budgetAmount
client.verificationStatus=="VERIFIED" → clientPaymentVerified=true
```

### C) `src/utils.py` - Dimag (AI Scoring)

**1. `parse_search_url()`**
Tum Upwork se URL copy paste karte ho, ye usko parse karke filters banata hai. Same kaam original actor karta hai.

**2. `compute_content_hash()`**
```python
hash = SHA256(title + description[0:500] + budget + skills)
```
Agar 2 jobs ka hash same hai to wo **Repost** hai (client ne delete karke wapas post kiya). Isse duplicate pakda jata hai.

**3. `calculate_ai_scores()` - PRO FEATURE**
Ye original se zyada powerful hai. Logic:

```
Start 50 points
+25 agar spent $100k+
+10 agar verified
-15 agar not verified + spent kam
+15 agar applicants 0-4 (low competition)
-10 agar applicants 20+ (high)
+10 agar rating 4.9+

Final:
85+ → PREMIUM (turant apply karo, 6 Connects)
70+ → Good
50+ → Medium
<50 → Risky (skip karo)
```

Example:
- Shopify $500, US, $125k spent, 3 applicants, 4.98 rating → **100 PREMIUM**
- Data Entry $3, $0 spent, 49 applicants → **10 Risky**

### D) `src/incremental.py` - Yaadadasht

**Problem:** Tum har ghante scrape karte ho, har bar 200 jobs aate hain, lekin 190 purane hote hain. Paise aur time waste.

**Solution:** Pehla run **baseline** save karta hai (Apify KV Store `upwork-state-react-tracker` me). Agla run compare karta hai:

```
Naya jobId → NEW
Purana jobId lekin description/budget change → UPDATED
Same hash lekin naya jobId → REAPPEARED (repost)
Purana jobId same hash → UNCHANGED (default hide)
Pehle tha ab nahi → EXPIRED
```

**State kahan save?**
- Apify pe: Key-Value Store (auto)
- Local pe: `./storage/incremental_*.json`

**Skip Reposts:** Agar `skipReposts=true` to REAPPEARED jobs bhi hide.

### E) `src/notifier.py` - Munh

Jobs milne ke baad alert bhejta hai. 4 channels parallel:

- **Telegram:** `https://api.telegram.org/botTOKEN/sendMessage` → HTML message
- **Discord:** Webhook → Rich embeds (Upwork green color)
- **Slack:** Blocks
- **Generic:** Tumhara n8n/Make URL → `POST {metadata, items}`

Limit: `notificationLimit:5` → sirf top 5 bhejta hai taki spam na ho. `notifyOnlyChanges=true` ho to sirf NEW wale bhejta hai.

---

## 4. Data Ka Safar - Example Ke Sath

**Tum Input dete ho:**
```json
{
  "query": "shopify developer",
  "location": ["United States"],
  "minClientTotalSpent": 5000,
  "proposals": "0-4",
  "maxResults": 10
}
```

**Step 1:** `build_filter` →
```json
{
  "searchExpression_eq": "shopify developer",
  "locations_any": ["United States"],
  "proposalRange_eq": {"from":0,"to":4},
  "pagination_eq": {"after":"0","first":50}
}
```

**Step 2:** `POST https://www.upwork.com/api/graphql/v1` → Upwork 50 jobs bhejta hai (lekin unme India wale bhi hain, $0 spent wale bhi).

**Step 3:** `transform_node` har ek ko clean karta hai → `jobId, title, clientCountry, clientTotalSpent, totalApplicants` etc + `contentHash`.

**Step 4:** `apply_post_filters` → `clientTotalSpent < 5000` wale nikal deta hai. 50 me se 22 bache.

**Step 5:** `calculate_ai_scores` → Har ek ko score. `US + $20k + 2 applicants` wala 95 ban gaya.

**Step 6:** Sort by `publishTime` newest first, top 10 kaat lo.

**Step 7:** Agar incremental on hai to check → 10 me se 3 NEW, 7 UNCHANGED → UNCHANGED hide → sirf 3 push.

**Step 8:** `Actor.push_data(3 jobs)` → Apify Dataset me. `Notifier` → Telegram pe 3 messages.

---

## 5. Local Kaise Chalaye? (Bina Apify)

```bash
# 1. Setup
cd upwork-clone-pro
pip install -r requirements.txt

# 2. Logic test (bina internet)
python test_local.py
# Output: AI scores, URL parse, hash demo

# 3. Real scrape
python -m src.main
# Default query="shopify developer" se 20 jobs → output/results.json

# 4. Apni query se
QUERY="python developer" python -m src.main

# 5. Environment se full input (advanced)
# Linux/Mac
QUERY='{"query":"react","minClientTotalSpent":10000}' python -m src.main
```

**Output kahan?** `output/results.json` me. Har job ka JSON.

### Apify Pe Kaise?

1. GitHub repo already push hai: `https://github.com/Bilalkhank10/upwork-scraper-pro`
2. Apify Console → Create Actor → Link GitHub repo → Deploy
3. `apify push` se bhi ho jata hai (local se)

**Apify Input UI:** `input_schema.json` ki wajah se Apify automatically 49 fields ka form bana deta hai (dropdown, checkbox etc). Tumhe code nahi likhna.

**Schedule:** Apify → Schedules → New → `0 * * * *` (har ghante) → Input me `incrementalMode:true` → bas.

---

## 6. Inputs Deep Dive - 49 Fields Samjho

**Search (7):** `query`, `searchUrl`, `startUrls`, `category`, `location`, `excludeLocations`, `customFilters`

**Job Filters (8):** `jobType`, `experienceLevel`, `workload`, `duration`, `budget`, `hourlyRate`, `proposals`, `clientHires`, `contractToHire`, `verifiedPaymentOnly`

**Client Quality (3):** `minClientTotalSpent`, `minClientRating`, `minClientReviewCount` → YE SABSE IMPORTANT hain premium clients ke liye

**Time (3):** `fromDate`, `toDate`, `maxAgeMinutes` → `maxAgeMinutes:60` = sirf last 1h ke jobs

**Keywords (2):** `includeKeywords`, `excludeKeywords` → `{keywords:["React"], matchTitle:true}`

**Output Control (4):** `maxResults`, `descriptionMaxLength`, `compact`, `descriptionFormat`, `excludeEmptyFields`

**Incremental (5):** `incrementalMode`, `stateKey`, `skipReposts`, `emitUnchanged`, `emitExpired`

**Enrichment (3):** `enrichDetails`, `sessionToken` (oauth2v2_int_...), `detailConcurrency`

**AI (1):** `enableAIScoring` → PRO ka jadoo

**Proxy (1):** `proxyConfiguration`

**Notify (8):** `telegramToken`, `telegramChatId`, `discordWebhookUrl`, `slackWebhookUrl`, `webhookUrl`, `webhookHeaders`, `notificationLimit`, `notifyOnlyChanges`

---

## 7. Detail Enrichment Kya Hai?

Normal search me 20 fields aate hain. Agar tumhe **30 extra fields** chahiye (hireRate, industry, lastActivity, questions, attachments) to `enrichDetails:true` + `sessionToken` do.

**Token kaise le?**
1. Upwork.com pe login karo
2. F12 → Network tab → `graphql` filter
3. Koi bhi request click → Headers → `authorization: Bearer oauth2v2_int_abc...`
4. `oauth2v2_int_...` copy karo (Bearer hata ke)
5. Input me paste karo

**Note:** Token har kuch din me expire hota hai, renew karna parta hai. Agar galat token doge to ab error dikhega (silent fail nahi).

---

## 8. Notifications Kaise Kaam Karte Hain?

```json
{
  "telegramToken": "123456:ABC...",
  "telegramChatId": "-100123...",
  "notificationLimit": 5,
  "notifyOnlyChanges": true,
  "includeRunMetadata": true
}
```

**Telegram Bot kaise banaye?**
- @BotFather → /newbot → Token milega
- @userinfobot → /start → Tumhari Chat ID milegi

**Discord:** Server Settings → Integrations → Webhooks → New Webhook → URL copy

**Flow:** Har run ke baad `notifier.send_all(jobs)` → Top 5 jobs ka message bana ke POST karta hai. 15 sec timeout, fail ho to log me warning.

---

## 9. Real World Example - Lahore Freelancer

**Tum Lahore se ho, US ke $10k+ clients dhoond rahe ho jo kam applicants wale shopify jobs post kare:**

**Input:**
```json
{
  "query": "shopify developer",
  "location": ["United States"],
  "minClientTotalSpent": 10000,
  "minClientRating": 4.5,
  "verifiedPaymentOnly": true,
  "proposals": "0-4",
  "budget": "500-",
  "maxResults": 20,
  "enableAIScoring": true,
  "incrementalMode": true,
  "stateKey": "shopify-us-lahore",
  "telegramToken": "YOUR_TOKEN",
  "telegramChatId": "YOUR_ID"
}
```

**Kya hoga?**
- Har ghante Apify schedule chalega
- Pehla run: 20 jobs (baseline) → $0.02 cost
- Agle run: sirf 2-3 naye jobs (95% bachat) → $0.003 cost + Telegram alert
- Tumhe 2 applicants wala PREMIUM job 10 min me mil jayega, jabki dusre freelancers ko 2 ghante baad dikhega jab 20 applicants ho chuke honge

**Connects bachat:** Low competition (6 Connects) vs High (16 Connects) → Har job pe 10 Connects bachat!

---

## 10. Troubleshooting

| Problem | Hal |
|---|---|
| `No jobs found` | Query bahut narrow hai, `minClientTotalSpent` kam karo |
| `Detail enrichment skipped` | `sessionToken` galat ya expire, naya lo |
| `Rate limited 429` | `detailConcurrency` 5 pe rakho, 10+ risky |
| `Incremental har bar same jobs` | `stateKey` same rakho, change mat karo |
| `Telegram nahi aa raha` | Token/ChatID check, `notificationLimit` 5 rakho |

---

## 11. Next Steps - Tum Kya Kar Sakte Ho?

1. **Apify pe Deploy:** `apify push` → Store pe publish, $1/1000 charge set karo (jaise original)
2. **GitHub Actions:** Har 30 min auto scrape + Google Sheets me save
3. **AI Upgrade:** OpenAI API se description ka sentiment score bhi add karo
4. **Dashboard:** Streamlit pe apna dashboard banao jisme AI score se filter ho

---

## 12. Security Note

- Kabhi `sessionToken` ya GitHub token Git me commit mat karo (`.gitignore` me hai)
- Token expire ho to renew karo, hardcode mat karo
- GitHub token jo chat me diya tha, **foran revoke kar do** (https://github.com/settings/tokens)

---

**Bas yehi pura system hai!** Ek bar `python -m src.main` chala ke `output/results.json` dekho, sab samajh aa jayega.

Koi step unclear ho to bolo, mai uska **video jaisa screenshot flow** bana dun!
