# ⚡ QUICKSTART - 2 Minute Deploy

## 1. Apify pe Deploy (Production)

```bash
cd upwork-clone-pro
apify login  # token from https://console.apify.com/settings/integrations
apify push
```

Apify Console → Actors → upwork-clone-pro → Try for free → Input fill → Run

## 2. Local Run (Testing)

```bash
pip install -r requirements.txt
python test_local.py  # check AI scoring without internet

# Real scrape (anonymous, no login)
python -m src.main

# With env override
QUERY="python developer" python -m src.main

# With Apify env (if you have APIFY_TOKEN)
APIFY_TOKEN=xxx python -m src.main
```

## 3. Input Examples - Copy Paste

**A) Lahore freelancer -> US premium clients:**
```json
{
  "query": "shopify developer",
  "location": ["United States"],
  "minClientTotalSpent": 5000,
  "verifiedPaymentOnly": true,
  "proposals": "0-4",
  "maxResults": 30,
  "enableAIScoring": true
}
```

**B) Hourly monitoring (every 30min via Apify Schedule):**
```json
{
  "query": "react developer",
  "maxResults": 100,
  "maxAgeMinutes": 30,
  "incrementalMode": true,
  "stateKey": "react-30min",
  "telegramToken": "YOUR_BOT_TOKEN",
  "telegramChatId": "YOUR_CHAT_ID",
  "notifyOnlyChanges": true
}
```

**C) Batch - 3 niches one run:**
```json
{
  "startUrls": [
    "https://www.upwork.com/nx/search/jobs/?q=shopify",
    "https://www.upwork.com/nx/search/jobs/?q=wordpress",
    "https://www.upwork.com/nx/search/jobs/?q=webflow"
  ],
  "maxResults": 90,
  "proposals": "0-4"
}
```

## 4. Demo HTML

Open `demo.html` in browser → interactive scoring demo
