"""
Upwork GraphQL API - Reverse Engineered Core
Replicates & extends blackfalcondata/upwork-scraper logic
Handles both anonymous search + authenticated detail enrichment
"""
import httpx
import asyncio
import json
import re
import hashlib
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone
import logging

log = logging.getLogger(__name__)

# Primary GraphQL endpoints discovered via DevTools
GRAPHQL_ENDPOINTS = [
    "https://www.upwork.com/api/graphql/v1",
    "https://www.upwork.com/graphql",
    "https://api.upwork.com/graphql",
]

# The exact query from reverse engineering - MarketplaceJobPostingsSearch
SEARCH_QUERY = """
query MarketplaceJobPostingsSearch(
  $marketPlaceJobFilter: MarketplaceJobPostingsSearchFilter,
  $searchType: MarketplaceJobPostingSearchType,
  $sortAttributes: [MarketplaceJobPostingSearchSortAttribute]
) {
  marketplaceJobPostingsSearch(
    marketPlaceJobFilter: $marketPlaceJobFilter,
    searchType: $searchType,
    sortAttributes: $sortAttributes
  ) {
    totalCount
    edges {
      node {
        id
        ciphertext
        title
        description
        createdDateTime
        publishedDateTime
        duration
        durationLabel
        engagement
        engagementDuration
        amount {
          rawValue
          currency
          displayValue
        }
        hourlyBudgetMin {
          rawValue
          currency
          displayValue
        }
        hourlyBudgetMax {
          rawValue
          currency
          displayValue
        }
        experienceLevel
        category
        subcategory
        skills {
          name
          prettyName
          uid
          highlighted
        }
        freelancersToHire
        totalApplicants
        enterpriseJob
        premium
        tierText
        client {
          totalSpent {
            rawValue
            currency
            displayValue
          }
          totalHires
          totalPostedJobs
          totalReviews
          totalFeedback
          verificationStatus
          hasFinancialPrivacy
          location {
            country
            countryCode
            city
            timezone
          }
          companyName
          companyRid
          edcUserId
        }
        ontologySkills {
          uid
          prettyName
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

DETAIL_QUERY = """
query GetJobDetails($ciphertext: String!) {
  marketplaceJobPosting(ciphertext: $ciphertext) {
    id
    ciphertext
    title
    description
    questions
    attachments {
      name
      link
    }
    skills {
      name
      uid
    }
    amount {
      rawValue
      currency
    }
    hourlyBudgetMin { rawValue }
    hourlyBudgetMax { rawValue }
    client {
      totalSpent { rawValue }
      totalHires
      totalReviews
      totalFeedback
      verificationStatus
      location {
        country
        city
        timezone
      }
      industry
      companySize
      totalInvites
      lastBuyerActivity
      hireRate
      jobsPosted
    }
    enterpriseJob
    premium
    durationLabel
    engagement
    experienceLevel
    freelancersToHire
    totalApplicants
    createdDateTime
    publishedDateTime
  }
}
"""

class UpworkAPI:
    def __init__(self, proxy_url: Optional[str] = None, session_token: Optional[str] = None):
        self.session_token = session_token
        self.proxy_url = proxy_url
        self.client = httpx.AsyncClient(
            timeout=30,
            headers=self._headers(),
            follow_redirects=True,
            proxy=proxy_url if proxy_url else None,
        )
        self.visitor_token = None

    def _headers(self, authenticated=False):
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.upwork.com",
            "Referer": "https://www.upwork.com/nx/search/jobs/",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if authenticated and self.session_token:
            token = self.session_token.strip()
            if token.lower().startswith("bearer "):
                token = token[7:]
            h["Authorization"] = f"Bearer {token}"
        return h

    async def get_visitor_token(self):
        """Get anonymous visitor token - required for unauthenticated search"""
        try:
            # Upwork sets visitor token via initial page or via /api/graphql visitor flow
            # Fallback: try to fetch search page to get cookies
            resp = await self.client.get("https://www.upwork.com/nx/search/jobs/?q=python")
            # Extract from cookies or page
            for cookie in resp.cookies.jar:
                if "visitor" in cookie.name.lower() or "oauth" in cookie.name.lower():
                    self.visitor_token = cookie.value
            return self.visitor_token
        except Exception as e:
            log.warning(f"visitor token fetch failed: {e}")
            return None

    def build_filter(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Build MarketplaceJobPostingsSearchFilter from actor inputs - replicates original's 14 filters"""
        f: Dict[str, Any] = {}

        # Query -> searchExpression_eq (Lucene)
        query = inputs.get("query")
        if query:
            if isinstance(query, list):
                query = " OR ".join(query)
            f["searchExpression_eq"] = query

        # Category -> occupationIds or categoryIds
        # For simplicity map to searchExpression as well
        # Real actor maps category names to UIDs via ontology lookup

        # Job Type
        job_type = inputs.get("jobType")
        if job_type:
            f["jobType_eq"] = job_type.upper()  # HOURLY / FIXED

        # Experience
        exp = inputs.get("experienceLevel")
        if exp:
            f["experienceLevel_eq"] = exp

        # Workload
        workload = inputs.get("workload")
        if workload:
            mapping = {"as_needed": "AS_NEEDED", "part_time": "PART_TIME", "full_time": "FULL_TIME"}
            f["workload_eq"] = mapping.get(workload, workload)

        # Duration
        duration = inputs.get("duration")
        if duration:
            mapping = {"week": "WEEK", "month": "MONTH", "semester": "SEMESTER", "ongoing": "ONGOING"}
            f["duration_any"] = [mapping.get(duration, duration.upper())]

        # Budget
        budget = inputs.get("budget")
        if budget and "-" in budget:
            try:
                min_b, max_b = budget.split("-")
                rng = {}
                if min_b:
                    rng["from"] = int(min_b)
                if max_b:
                    rng["to"] = int(max_b)
                if rng:
                    f["budgetRange_eq"] = rng
            except:
                pass

        # Hourly rate
        hourly = inputs.get("hourlyRate")
        if hourly and "-" in hourly:
            try:
                min_h, max_h = hourly.split("-")
                rng = {}
                if min_h:
                    rng["from"] = int(min_h)
                if max_h:
                    rng["to"] = int(max_h)
                if rng:
                    f["hourlyRate_eq"] = rng
            except:
                pass

        # Verified payment
        if inputs.get("verifiedPaymentOnly"):
            f["verifiedPaymentOnly_eq"] = True

        # Proposals
        proposals = inputs.get("proposals")
        if proposals and "-" in proposals:
            try:
                min_p, max_p = proposals.split("-")
                f["proposalRange_eq"] = {"from": int(min_p), "to": int(max_p)}
            except:
                pass

        # Client hires
        hires = inputs.get("clientHires")
        if hires:
            if hires == "0":
                f["clientHiresRange_eq"] = {"from": 0, "to": 0}
            elif hires == "1-9":
                f["clientHiresRange_eq"] = {"from": 1, "to": 9}
            elif hires == "10+":
                f["clientHiresRange_eq"] = {"from": 10, "to": 100000}

        # Locations
        locs = inputs.get("location")
        if locs:
            # normalize: handles ["United States"] or [{"type":"COUNTRY","value":"US"}]
            normalized = []
            for l in locs:
                if isinstance(l, dict):
                    normalized.append(l.get("value", ""))
                else:
                    normalized.append(str(l))
            f["locations_any"] = normalized

        # Contract to hire
        if inputs.get("contractToHire"):
            f["contractToHire_eq"] = True

        # Pagination placeholder - set per request
        f["pagination_eq"] = {"after": "0", "first": 50}

        return f

    def build_sort(self, sort_val: str):
        mapping = {
            "recency": [{"field": "RECENCY", "direction": "DESC"}],
            "newest": [{"field": "RECENCY", "direction": "DESC"}],
            "oldest": [{"field": "RECENCY", "direction": "ASC"}],
            "relevance": [{"field": "RELEVANCE", "direction": "DESC"}],
        }
        return mapping.get(sort_val, mapping["recency"])

    async def search(self, inputs: Dict[str, Any], max_results: int = 50) -> AsyncGenerator[Dict[str, Any], None]:
        """Main search generator - yields raw job nodes"""
        filt = self.build_filter(inputs)
        sort_attrs = self.build_sort(inputs.get("sort", "recency"))
        
        # Search type
        search_type = "USER_JOBS_SEARCH"

        cursor = "0"
        fetched = 0
        page_size = min(50, max_results if max_results else 50)

        # Handle batch queries: query can be list
        queries = inputs.get("query")
        if isinstance(queries, str) and queries.startswith("[") and "," in queries:
            try:
                queries = json.loads(queries)
            except:
                queries = [queries]
        if not isinstance(queries, list):
            queries = [queries] if queries else [None]

        # If startUrls provided, they'll be handled upstream - here just search
        for q in queries:
            if q:
                filt["searchExpression_eq"] = q
            elif "searchExpression_eq" in filt and len(queries) > 1:
                pass

            cursor = "0"
            while True:
                if max_results and fetched >= max_results:
                    return
                remaining = max_results - fetched if max_results else page_size
                current_first = min(page_size, remaining) if max_results else page_size

                filt["pagination_eq"] = {"after": cursor, "first": current_first}

                payload = {
                    "query": SEARCH_QUERY,
                    "variables": {
                        "marketPlaceJobFilter": filt,
                        "searchType": search_type,
                        "sortAttributes": sort_attrs,
                    }
                }

                success = False
                last_err = None
                for endpoint in GRAPHQL_ENDPOINTS:
                    try:
                        # Try both authenticated and anon headers
                        headers = self._headers(authenticated=bool(self.session_token))
                        resp = await self.client.post(endpoint, json=payload, headers=headers)
                        if resp.status_code == 200:
                            data = resp.json()
                            # Check for GraphQL errors
                            if "errors" in data and data["errors"]:
                                # Money null error handling (from StackOverflow)
                                # If amount null causes failure, retry with less fields
                                log.warning(f"GraphQL errors: {data['errors']}")
                                # Sometimes need to fallback to next endpoint
                                last_err = data["errors"]
                                continue
                            result = data.get("data", {}).get("marketplaceJobPostingsSearch")
                            if result is None:
                                last_err = "No result key"
                                continue
                            
                            edges = result.get("edges", [])
                            page_info = result.get("pageInfo", {})
                            
                            for edge in edges:
                                node = edge.get("node", {})
                                fetched += 1
                                yield node
                                if max_results and fetched >= max_results:
                                    break

                            has_next = page_info.get("hasNextPage")
                            cursor = page_info.get("endCursor", cursor)
                            
                            if not has_next or not edges:
                                break
                            success = True
                            break
                        elif resp.status_code in (403, 429):
                            # Rate limited - rotate
                            log.warning(f"Rate limited {resp.status_code} at {endpoint}")
                            await asyncio.sleep(2)
                            last_err = f"HTTP {resp.status_code}"
                            continue
                        else:
                            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    except Exception as e:
                        last_err = str(e)
                        log.warning(f"Endpoint {endpoint} failed: {e}")
                        continue
                    if success:
                        break
                
                if not success and last_err:
                    log.error(f"All endpoints failed for query {q}: {last_err}")
                    # Try fallback: scrape HTML via apify proxy (not ideal but fallback)
                    break

                # If we fetched less than page_size, we're done
                if not success:
                    break
                # If no has_next, break outer while
                # checked inside

            # dedupe across queries will be done upstream

    def transform_node(self, node: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Transform raw GraphQL node to actor output schema - matches original's field set"""
        from .utils import compute_content_hash, now_iso
        
        # ID handling - ciphertext is like ~021955...
        ciphertext = node.get("ciphertext") or node.get("id") or ""
        # jobId is numeric part without ~0
        job_id = ciphertext.replace("~", "").lstrip("0")
        if not job_id:
            job_id = str(node.get("id", ""))

        # Amounts
        amount = node.get("amount") or {}
        hourly_min = node.get("hourlyBudgetMin") or {}
        hourly_max = node.get("hourlyBudgetMax") or {}

        # Client
        client = node.get("client") or {}
        total_spent = client.get("totalSpent") or {}
        location = client.get("location") or {}

        # Skills
        skills = node.get("skills") or []
        skills_simple = [s.get("prettyName") or s.get("name") for s in skills if s.get("prettyName") or s.get("name")]
        skills_detailed = [
            {"uid": s.get("uid") or s.get("id"), "name": s.get("prettyName") or s.get("name"), "highlighted": bool(s.get("highlighted"))}
            for s in skills
        ]
        # Fallback ontologySkills
        if not skills_simple and node.get("ontologySkills"):
            skills_simple = [s.get("prettyName") for s in node["ontologySkills"]]
            skills_detailed = [{"uid": s.get("uid"), "name": s.get("prettyName"), "highlighted": False} for s in node["ontologySkills"]]

        # Dates - Upwork returns millis or ISO
        def parse_dt(v):
            if not v:
                return None
            try:
                # Try ISO
                if "T" in str(v):
                    return v
                # Try millis
                ts = int(v) / 1000 if isinstance(v, (int, str)) and str(v).isdigit() else None
                if ts:
                    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            except:
                pass
            return v

        job_type = "HOURLY" if hourly_min or hourly_max or node.get("engagement") else "FIXED"
        # Determine from amount existence
        if amount and amount.get("rawValue"):
            job_type = "FIXED"
        elif hourly_min or hourly_max:
            job_type = "HOURLY"

        job = {
            "jobId": job_id,
            "ciphertext": ciphertext,
            "title": node.get("title"),
            "description": node.get("description"),
            "descriptionHtml": node.get("description"),  # will be converted if needed
            "descriptionMarkdown": node.get("description"),
            "jobType": job_type,
            "experienceLevel": node.get("experienceLevel"),
            "budgetAmount": amount.get("rawValue") if amount else None,
            "budgetCurrency": amount.get("currency") if amount else None,
            "hourlyBudgetMin": hourly_min.get("rawValue") if hourly_min else None,
            "hourlyBudgetMax": hourly_max.get("rawValue") if hourly_max else None,
            "engagementType": node.get("engagement"),
            "engagementDuration": node.get("durationLabel") or node.get("engagementDuration"),
            "engagementDurationWeeks": None,  # parse from durationLabel if needed
            "skills": skills_simple,
            "skillsDetailed": skills_detailed,
            "publishTime": parse_dt(node.get("publishedDateTime") or node.get("createdDateTime")),
            "createTime": parse_dt(node.get("createdDateTime")),
            "totalApplicants": node.get("totalApplicants"),
            "personsToHire": node.get("freelancersToHire") or 1,
            "enterpriseJob": bool(node.get("enterpriseJob")),
            "premium": bool(node.get("premium")),
            "clientCountry": location.get("country"),
            "clientCountryCode": location.get("countryCode"),
            "clientCity": location.get("city"),
            "clientTimezone": location.get("timezone"),
            "clientTotalSpent": total_spent.get("rawValue") if total_spent else None,
            "clientSpentCurrency": total_spent.get("currency") if total_spent else None,
            "clientPaymentVerified": (client.get("verificationStatus") == "VERIFIED") if client.get("verificationStatus") else None,
            "clientRating": client.get("totalFeedback"),
            "clientReviewCount": client.get("totalReviews"),
            "clientTotalHires": client.get("totalHires"),
            "clientTotalJobsPosted": client.get("totalPostedJobs"),
            "clientHasFinancialPrivacy": client.get("hasFinancialPrivacy"),
            "url": f"https://www.upwork.com/jobs/{ciphertext}" if ciphertext else None,
            "portalUrl": f"https://www.upwork.com/jobs/{ciphertext}" if ciphertext else None,
            "scrapedAt": now_iso(),
            "source": "upwork.com",
            "isRepost": False,
        }

        # Engagement weeks parsing
        dur = job["engagementDuration"]
        if dur and "week" in dur.lower():
            try:
                # e.g. "3 to 6 months" -> 18 weeks
                import re
                nums = re.findall(r"\d+", dur)
                if nums:
                    # Rough: months*4
                    if "month" in dur.lower():
                        avg_months = sum(map(int, nums[:2]))/len(nums[:2]) if len(nums)>1 else int(nums[0])
                        job["engagementDurationWeeks"] = int(avg_months * 4.3)
                    elif "week" in dur.lower():
                        job["engagementDurationWeeks"] = int(nums[0])
            except:
                pass

        job["contentHash"] = compute_content_hash(job)

        # Description length truncation
        max_len = inputs.get("descriptionMaxLength", 0)
        if max_len and job.get("description"):
            job["description"] = job["description"][:max_len]
            if job.get("descriptionMarkdown"):
                job["descriptionMarkdown"] = job["descriptionMarkdown"][:max_len]

        return job

    async def fetch_details_batch(self, jobs: List[Dict[str, Any]], concurrency: int = 5) -> List[Dict[str, Any]]:
        """Enrich with detail page - PRO feature"""
        if not self.session_token:
            log.warning("Enrich requested but no sessionToken")
            return jobs
        
        sem = asyncio.Semaphore(concurrency)
        
        async def enrich_one(job):
            async with sem:
                ciphertext = job.get("ciphertext")
                if not ciphertext:
                    return job
                try:
                    payload = {"query": DETAIL_QUERY, "variables": {"ciphertext": ciphertext}}
                    headers = self._headers(authenticated=True)
                    for endpoint in GRAPHQL_ENDPOINTS:
                        try:
                            resp = await self.client.post(endpoint, json=payload, headers=headers)
                            if resp.status_code == 200:
                                data = resp.json()
                                detail = data.get("data", {}).get("marketplaceJobPosting")
                                if detail:
                                    # Merge extra fields
                                    client = detail.get("client") or {}
                                    job["clientIndustry"] = client.get("industry")
                                    job["clientCompanySize"] = client.get("companySize")
                                    job["clientHireRate"] = client.get("hireRate")
                                    job["clientLastActivity"] = client.get("lastBuyerActivity")
                                    job["clientTotalInvites"] = client.get("totalInvites")
                                    job["questions"] = detail.get("questions")
                                    job["attachments"] = detail.get("attachments")
                                    job["detailFetched"] = True
                                    break
                        except Exception as e:
                            log.warning(f"Detail fetch failed for {ciphertext}: {e}")
                            continue
                    await asyncio.sleep(0.3)  # be nice
                except Exception as e:
                    log.warning(f"Enrich error {e}")
                return job

        tasks = [enrich_one(j) for j in jobs]
        return await asyncio.gather(*tasks)

    async def close(self):
        await self.client.aclose()
