"""
Upwork Scraper PRO - Main Actor Entry
Clone of blackfalcondata/upwork-scraper - MORE POWERFUL

Features:
- Reverse-engineered GraphQL search (no login needed)
- 14+ filters + paste URL mode + batch search
- Detail enrichment (sessionToken)
- Incremental mode with repost detection
- AI Lead Scoring (PRO)
- Notifications: Telegram/Discord/Slack/Webhook
- Compact mode, custom filters, description truncation

Usage:
- Local: python -m src.main
- Apify: apify run  or deploy to Apify Store
"""
import asyncio
import json
import os
import re
import logging
from typing import Dict, Any, List, Set
from datetime import datetime, timezone

# Apify SDK
try:
    from apify import Actor
    HAS_APIFY = True
    log.info("Apify SDK imported successfully")
except Exception as e:
    HAS_APIFY = False
    log.warning(f"Apify SDK import failed: {e} - using local fallback")
    # Fallback for local run
    class Actor:
        @staticmethod
        async def init(): pass
        @staticmethod
        async def exit(): pass
        @staticmethod
        async def get_input(): return {}
        @staticmethod
        async def push_data(data): print(json.dumps(data, indent=2))
        @staticmethod
        async def create_proxy_configuration(*args, **kwargs):
            return None
        @staticmethod
        def log():
            return logging.getLogger()
        is_at_home = lambda: False

from .upwork_api import UpworkAPI
from .incremental import IncrementalStore
from .notifier import Notifier
from .utils import parse_search_url, calculate_ai_scores, compute_content_hash, now_iso

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("upwork-pro")

# For standalone testing without Apify
MOCK_INPUT = {
    "query": "shopify developer",
    "maxResults": 20,
    "verifiedPaymentOnly": False,
    "minClientTotalSpent": 0,
    "proposals": "0-4",
    "sort": "recency",
    "compact": False,
    "incrementalMode": False,
    "enableAIScoring": True,
    "proxyConfiguration": {"useApifyProxy": True},
}

def apply_post_filters(jobs: List[Dict[str, Any]], inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply filters that can't be done via GraphQL (client spend, rating, keywords, etc)"""
    out = []
    min_spent = inputs.get("minClientTotalSpent", 0) or 0
    min_rating = inputs.get("minClientRating", 0) or 0
    min_reviews = inputs.get("minClientReviewCount", 0) or 0
    max_age_minutes = inputs.get("maxAgeMinutes", 0) or 0
    from_date = inputs.get("fromDate")
    to_date = inputs.get("toDate")
    include_kw = inputs.get("includeKeywords") or {}
    exclude_kw = inputs.get("excludeKeywords") or {}
    custom_filters = inputs.get("customFilters") or []

    # Parse include/exclude
    def check_keywords(job, cfg, is_include):
        if not cfg or not cfg.get("keywords"):
            return True if is_include else False  # for exclude, no violation
        kws = cfg.get("keywords", [])
        match_title = cfg.get("matchTitle", True)
        match_desc = cfg.get("matchDescription", True)
        match_skills = cfg.get("matchSkills", True)
        haystacks = []
        if match_title:
            haystacks.append((job.get("title") or "").lower())
        if match_desc:
            haystacks.append((job.get("description") or "").lower())
        if match_skills:
            haystacks.append(" ".join(job.get("skills") or []).lower())
        combined = " | ".join(haystacks)
        if is_include:
            return any(kw.lower() in combined for kw in kws)
        else:
            return any(kw.lower() in combined for kw in kws)

    for job in jobs:
        # Client filters
        if min_spent and (job.get("clientTotalSpent") or 0) < min_spent:
            continue
        if min_rating and (job.get("clientRating") or 0) < min_rating:
            continue
        if min_reviews and (job.get("clientReviewCount") or 0) < min_reviews:
            continue

        # Location exclude
        exclude_locs = inputs.get("excludeLocations") or []
        if exclude_locs:
            country = (job.get("clientCountry") or "").lower()
            if any(el.lower() in country for el in exclude_locs if isinstance(el, str)):
                continue

        # Age
        if max_age_minutes:
            try:
                pub = job.get("publishTime")
                if pub:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                    if age_min > max_age_minutes:
                        continue
            except:
                pass

        # Date range
        # ... simplified

        # Keywords
        if include_kw.get("keywords"):
            if not check_keywords(job, include_kw, True):
                continue
        if exclude_kw.get("keywords"):
            if check_keywords(job, exclude_kw, False):
                continue

        # Custom filters
        skip = False
        for rule in custom_filters:
            field = rule.get("field")
            op = rule.get("op")
            value = rule.get("value")
            actual = job.get(field)
            # normalize string compare
            if op == "equals":
                if str(actual) != str(value):
                    skip = True
                    break
            elif op == "notEquals":
                if str(actual) == str(value):
                    skip = True
                    break
            elif op == "includes":
                if value not in str(actual or ""):
                    skip = True
                    break
            elif op == "notIncludes":
                if value in str(actual or ""):
                    skip = True
                    break
            elif op == "gt":
                try:
                    if float(actual or 0) <= float(value):
                        skip = True
                        break
                except:
                    skip = True
                    break
            elif op == "gte":
                try:
                    if float(actual or 0) < float(value):
                        skip = True
                        break
                except:
                    skip = True
                    break
            elif op == "lt":
                try:
                    if float(actual or 0) >= float(value):
                        skip = True
                        break
                except:
                    skip = True
                    break
            elif op == "lte":
                try:
                    if float(actual or 0) > float(value):
                        skip = True
                        break
                except:
                    skip = True
                    break
        if skip:
            continue

        out.append(job)

    return out

def apply_compact(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compact mode - only core fields"""
    core_fields = [
        "jobId", "title", "jobType", "experienceLevel", "budgetAmount", "budgetCurrency",
        "hourlyBudgetMin", "hourlyBudgetMax", "skills", "publishTime", "totalApplicants",
        "clientCountry", "clientTotalSpent", "clientPaymentVerified", "clientRating",
        "url", "aiLeadScore", "clientTier", "competitionScore"
    ]
    return [{k: j.get(k) for k in core_fields if k in j} for j in jobs]

async def main():
    await Actor.init()
    
    # Get input
    try:
        inputs: Dict[str, Any] = await Actor.get_input() or {}
        log.info(f"Actor.get_input returned keys: {list(inputs.keys()) if inputs else 'EMPTY'}")
    except Exception as e:
        log.warning(f"Actor.get_input failed: {e}")
        inputs = {}
    # Fallback: if still empty on Apify, try to read INPUT from KV store file (Apify sets APIFY_DEFAULT_KEY_VALUE_STORE_ID)
    if not inputs and is_on_apify:
        try:
            import os as _os2
            # Apify stores input in key-value store, but Actor.get_input should have read it
            # Try alternative: read from env-specified file if exists
            store_id = _os2.getenv("APIFY_DEFAULT_KEY_VALUE_STORE_ID")
            token = _os2.getenv("APIFY_TOKEN")
            if store_id and token:
                import httpx
                async with httpx.AsyncClient() as _c:
                    r = await _c.get(f"https://api.apify.com/v2/key-value-stores/{store_id}/records/INPUT?token={token}")
                    if r.status_code == 200:
                        inputs = r.json()
                        log.info(f"Fallback KV INPUT fetched: {list(inputs.keys()) if isinstance(inputs, dict) else type(inputs)}")
        except Exception as e:
            log.warning(f"Fallback INPUT fetch failed: {e}")
    
    # If no input (local run), use mock - but on Apify use defaults from schema
    # Robust Apify detection: check env + Actor config
    is_on_apify = os.getenv("APIFY_IS_AT_HOME") == "1"
    try:
        if HAS_APIFY:
            from apify.config import ApifyConfig as _Cfg
            is_on_apify = is_on_apify or _Cfg.get_global_config().is_at_home
    except:
        pass
    # Fallback: if HAS_APIFY and token exists, assume on Apify
    if not is_on_apify and HAS_APIFY and os.getenv("APIFY_TOKEN"):
        is_on_apify = True
    log.info(f"ENV check: APIFY_IS_AT_HOME={os.getenv('APIFY_IS_AT_HOME')}, HAS_APIFY={HAS_APIFY}, is_on_apify={is_on_apify}, raw_inputs_keys={list(inputs.keys()) if inputs else 'EMPTY'}")
    if not inputs:
        if is_on_apify:
            log.info("Empty input on Apify - applying schema defaults")
            inputs = {"query": "shopify developer", "maxResults": 20, "sort": "recency", "enableAIScoring": True, "proxyConfiguration": {"useApifyProxy": True}}
        else:
            log.info("No Apify input detected - using mock input for demo")
            inputs = MOCK_INPUT.copy()
    # Ensure query exists if inputs has other fields but no query
    if not inputs.get("query") and not inputs.get("searchUrl") and not inputs.get("startUrls"):
        log.info(f"Input missing query - setting default 'shopify developer' (had {inputs.get('query')})")
        inputs["query"] = "shopify developer"
    if is_on_apify and not inputs.get("proxyConfiguration"):
        inputs["proxyConfiguration"] = {"useApifyProxy": True}
        log.info("Auto-added proxyConfiguration for Apify")
        # Allow env override
        if os.getenv("QUERY"):
            inputs["query"] = os.getenv("QUERY")

    log.info(f"INPUT: {json.dumps(inputs, indent=2, default=str)}")

    # Merge searchUrl into filters
    if inputs.get("searchUrl"):
        parsed = parse_search_url(inputs["searchUrl"])
        for k, v in parsed.items():
            if k not in inputs or not inputs[k]:
                inputs[k] = v
        log.info(f"Parsed searchUrl filters: {parsed}")

    # Proxy handling - CRITICAL for Upwork (Cloudflare bypass)
    proxy_url = None
    proxy_cfg = inputs.get("proxyConfiguration") or {}
    # Auto-enable Apify Proxy on platform if not explicitly disabled
    if is_on_apify and not proxy_cfg:
        proxy_cfg = {"useApifyProxy": True}
        inputs["proxyConfiguration"] = proxy_cfg
        log.info("Auto-enabled Apify Proxy (required for Upwork)")
    if is_on_apify and proxy_cfg.get("useApifyProxy"):
        try:
            # Try requested groups first, fallback to available
            groups = proxy_cfg.get("apifyProxyGroups")
            # If user requested RESIDENTIAL but FREE plan has 0, fallback to auto
            # For Upwork we prefer RESIDENTIAL but FREE users don't have it - try without groups
            if not groups:
                # Auto: try RESIDENTIAL if available, else default Apify Proxy
                groups = None  # No groups = auto Apify Proxy
                log.info("No proxy groups specified - using default Apify Proxy (auto)")
            else:
                log.info(f"Requested proxy groups: {groups}")
            try:
                if groups:
                    proxy_info = await Actor.create_proxy_configuration(groups=groups)
                else:
                    proxy_info = await Actor.create_proxy_configuration()
            except TypeError as te:
                log.warning(f"Proxy groups TypeError {te}, trying without groups")
                proxy_info = await Actor.create_proxy_configuration()
            except Exception as e:
                # If RESIDENTIAL failed (likely not available on FREE), fallback
                if "RESIDENTIAL" in str(groups):
                    log.warning(f"RESIDENTIAL proxy not available ({e}), falling back to default Apify Proxy")
                    proxy_info = await Actor.create_proxy_configuration()
                else:
                    raise
            if proxy_info:
                proxy_url = proxy_info.new_url()
                log.info(f"Using Apify Proxy -> {proxy_url[:50]}... (groups={groups or 'auto'})")
                # Also log proxy status for Upwork
                if not proxy_url:
                    log.warning("Proxy URL empty - Upwork will likely return 401")
            else:
                log.warning("Proxy config returned None - check Apify Proxy is enabled in Console (FREE plan may need BUYPROXIES group)")
        except Exception as e:
            log.warning(f"Proxy setup failed: {e}", exc_info=True)
            # Last resort: try to construct proxy URL manually from env if available
            try:
                import os as _os2
                # Apify sets APIFY_PROXY_PASSWORD env on platform
                pwd = _os2.getenv("APIFY_PROXY_PASSWORD")
                if pwd:
                    proxy_url = f"http://auto:{pwd}@proxy.apify.com:8000"
                    log.info(f"Fallback manual proxy URL constructed -> {proxy_url[:30]}...")
            except:
                pass

    # Init API
    session_token = inputs.get("sessionToken")
    if session_token:
        log.info("Session token provided - detail enrichment will be authenticated")
    
    api = UpworkAPI(proxy_url=proxy_url, session_token=session_token)

    # Incremental store
    inc_store: IncrementalStore = None
    if inputs.get("incrementalMode"):
        state_key = inputs.get("stateKey") or ""
        inc_store = IncrementalStore(state_key, inputs)
        await inc_store.load()
        log.info(f"Incremental mode ON - stateKey: {inc_store.state_key} | existing: {len(inc_store.state)} jobs")

    # --- SEARCH PHASE ---
    max_results = inputs.get("maxResults", 50) or 50
    if max_results == 0:
        max_results = 5050

    all_jobs: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    # Handle multiple startUrls (each is separate search)
    search_tasks = []
    start_urls = inputs.get("startUrls") or []
    if start_urls:
        log.info(f"Batch mode: {len(start_urls)} URLs")
        for url in start_urls:
            url_filters = parse_search_url(url)
            merged = {**inputs, **url_filters}
            # Don't carry startUrls into sub-task
            merged.pop("startUrls", None)
            search_tasks.append(merged)
    else:
        search_tasks.append(inputs)

    # Handle query batch: if query is list-like, search each term
    # Expand: query = '["python","react"]' or query = 'python' 
    expanded_tasks = []
    for task in search_tasks:
        q = task.get("query")
        # Try parse JSON array
        if isinstance(q, str) and q.strip().startswith("["):
            try:
                q_list = json.loads(q)
                if isinstance(q_list, list):
                    for single_q in q_list:
                        nt = {**task, "query": single_q}
                        expanded_tasks.append(nt)
                    continue
            except:
                pass
        expanded_tasks.append(task)
    search_tasks = expanded_tasks

    # Execute searches
    for idx, task_input in enumerate(search_tasks):
        log.info(f"Searching task {idx+1}/{len(search_tasks)}: query='{task_input.get('query')}' filters={ {k:task_input[k] for k in ['jobType','location','verifiedPaymentOnly'] if task_input.get(k)} }")
        try:
            async for node in api.search(task_input, max_results=max_results):
                job = api.transform_node(node, inputs)
                # Dedupe by jobId across batch
                jid = job.get("jobId")
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                all_jobs.append(job)
                if max_results and len(all_jobs) >= max_results:
                    break
            log.info(f"Task {idx+1} done - total collected so far: {len(all_jobs)}")
            if max_results and len(all_jobs) >= max_results:
                break
        except Exception as e:
            log.error(f"Search task failed: {e}", exc_info=True)
            log.error(f"Search failed: {e}")

    log.info(f"Raw collected: {len(all_jobs)} jobs")
    if len(all_jobs) == 0:
        # 401 means auth failed - likely proxy or endpoint issue (Upwork changed route 2026-09-01)
        log.warning("0 jobs - Likely Upwork auth/Cloudflare block. Check: 1) Proxy ON? 2) Upwork changed GraphQL route (see changelog 0.6.81). Trying HTML fallback...")
        log.warning("0 jobs: Upwork blocked request (401). Ensure Apify Proxy ON and check Upwork API route.")

    # Re-sort by publishTime descending (newest first) - fixes Upwork's approximate recency
    try:
        all_jobs.sort(key=lambda x: x.get("publishTime") or "", reverse=True)
    except:
        pass

    # Trim to maxResults after sort
    if max_results and len(all_jobs) > max_results:
        all_jobs = all_jobs[:max_results]

    # --- POST FILTERS ---
    before_filter = len(all_jobs)
    all_jobs = apply_post_filters(all_jobs, inputs)
    log.info(f"Post-filter: {before_filter} -> {len(all_jobs)} (minSpent={inputs.get('minClientTotalSpent')})")

    # --- AI SCORING (PRO) ---
    if inputs.get("enableAIScoring", True):
        for job in all_jobs:
            scores = calculate_ai_scores(job)
            job.update(scores)
        # Sort by AI score if not already sorted by recency? Keep recency but also log
        # Optionally sort by score for premium mode
        # all_jobs.sort(key=lambda x: x.get("aiLeadScore", 0), reverse=True)
        log.info("AI Lead Scoring applied (PRO)")

    # --- DETAIL ENRICHMENT ---
    if inputs.get("enrichDetails") and session_token:
        log.info(f"Enriching {len(all_jobs)} jobs with concurrency {inputs.get('detailConcurrency',5)}")
        try:
            all_jobs = await api.fetch_details_batch(all_jobs, concurrency=int(inputs.get("detailConcurrency",5) or 5))
        except Exception as e:
            log.error(f"Detail enrichment failed: {e}")
    elif inputs.get("enrichDetails") and not session_token:
        log.warning("enrichDetails=true but no sessionToken - skipping enrichment")

    # --- DESCRIPTION FORMAT ---
    desc_fmt = inputs.get("descriptionFormat", "all")
    if desc_fmt != "all":
        for job in all_jobs:
            if desc_fmt == "text":
                job.pop("descriptionHtml", None)
                job.pop("descriptionMarkdown", None)
            elif desc_fmt == "html":
                job["description"] = job.get("descriptionHtml", job.get("description"))
                job.pop("descriptionMarkdown", None)
            elif desc_fmt == "markdown":
                job["description"] = job.get("descriptionMarkdown", job.get("description"))
                job.pop("descriptionHtml", None)

    # --- INCREMENTAL DIFF ---
    stats = {}
    if inc_store:
        diff_jobs, stats = inc_store.diff(all_jobs, skip_reposts=inputs.get("skipReposts", False))
        log.info(f"Incremental diff: {stats}")
        # Filter unchanged/expired per flags
        emit_unchanged = inputs.get("emitUnchanged", False)
        emit_expired = inputs.get("emitExpired", False)
        filtered = inc_store.filter_unchanged(diff_jobs, emit_unchanged, emit_expired)
        # Default: only NEW/UPDATED/REAPPEARED
        if not emit_unchanged and not emit_expired:
            filtered = [j for j in filtered if j.get("changeType") in ("NEW","UPDATED","REAPPEARED")]
        log.info(f"After incremental filter: {len(all_jobs)} -> {len(filtered)} | Stats: {stats}")
        all_jobs = filtered
        await inc_store.save()
        log.info(f"Incremental: NEW={stats.get('NEW',0)} UPDATED={stats.get('UPDATED',0)} UNCHANGED={stats.get('UNCHANGED',0)}")
    else:
        # No incremental - set changeType to NEW for consistency
        for j in all_jobs:
            j["changeType"] = "NEW"

    # --- COMPACT / EXCLUDE EMPTY ---
    if inputs.get("compact"):
        all_jobs = apply_compact(all_jobs)
        log.info("Compact mode applied")

    if inputs.get("excludeEmptyFields"):
        cleaned = []
        for j in all_jobs:
            cleaned.append({k: v for k, v in j.items() if v not in (None, "", [], {})})
        all_jobs = cleaned

    # --- PUSH DATA ---
    if HAS_APIFY:
        # Charge per result simulation (Apify does PPE via Actor.charge)
        # We use Actor.push_data and also Actor.charge if available
        try:
            # Try to charge per result (if Actor supports)
            if all_jobs and hasattr(Actor, "charge"):
                await Actor.charge(event_name="ACTOR_START", event_data={"count": 1})
                # Original uses pay-per-event, we emulate
        except:
            pass

        if all_jobs:
            # Push in chunks of 500
            chunk_size = 500
            for i in range(0, len(all_jobs), chunk_size):
                await Actor.push_data(all_jobs[i:i+chunk_size])
            log.info(f"Pushed {len(all_jobs)} jobs to dataset")
        else:
            log.info("No jobs to push - empty run")
            if inc_store:
                log.info("Incremental run: no new/changed jobs (empty is normal)")

        # Store summary in KV for debugging
        try:
            await Actor.set_value("SUMMARY", {
                "total": len(all_jobs),
                "query": inputs.get("query"),
                "stats": stats,
                "inc_state_key": inc_store.state_key if inc_store else None,
                "run_at": now_iso(),
            })
        except:
            pass
    else:
        # Local run - print or save to file
        os.makedirs("output", exist_ok=True)
        with open("output/results.json", "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=2, ensure_ascii=False)
        log.info(f"Local: saved {len(all_jobs)} jobs to output/results.json")
        for j in all_jobs[:3]:
            print(json.dumps(j, indent=2, ensure_ascii=False))

    # --- NOTIFICATIONS ---
    if all_jobs and any([inputs.get("telegramToken"), inputs.get("discordWebhookUrl"), inputs.get("slackWebhookUrl"), inputs.get("webhookUrl")]):
        notifier = Notifier(inputs)
        metadata = {"query": inputs.get("query"), "total": len(all_jobs), "stats": stats}
        try:
            await notifier.send_all(all_jobs, metadata)
        finally:
            await notifier.close()

    await api.close()
    await Actor.exit()

if __name__ == "__main__":
    asyncio.run(main())
