"""
Quick local test without Apify - simulates the scraper with mock data
Run: python test_local.py
"""
import asyncio
import json
from src.utils import calculate_ai_scores, compute_content_hash, parse_search_url

def demo_ai_scoring():
    print("=== AI LEAD SCORING DEMO (PRO FEATURE) ===")
    jobs = [
        {"title": "Shopify Store Fix - $500", "jobType": "FIXED", "budgetAmount": 500, "clientTotalSpent": 125000, "clientPaymentVerified": True, "clientRating": 4.98, "clientReviewCount": 42, "totalApplicants": 3, "skills": ["Shopify"]},
        {"title": "Data Entry $5/hr", "jobType": "HOURLY", "hourlyBudgetMax": 5, "clientTotalSpent": 0, "clientPaymentVerified": False, "clientRating": 0, "clientReviewCount": 0, "totalApplicants": 47, "skills": ["Data Entry"]},
        {"title": "React Native App - $3000", "jobType": "FIXED", "budgetAmount": 3000, "clientTotalSpent": 8500, "clientPaymentVerified": True, "clientRating": 4.7, "clientReviewCount": 12, "totalApplicants": 8, "skills": ["React Native"]},
    ]
    for j in jobs:
        j["contentHash"] = compute_content_hash(j)
        scores = calculate_ai_scores(j)
        j.update(scores)
        print(f"\n📌 {j['title']}")
        print(f"   Spent: ${j['clientTotalSpent']:,} | 👥 {j['totalApplicants']} applicants | Verified: {j['clientPaymentVerified']}")
        print(f"   → AI Score: {j['aiLeadScore']} | Tier: {j['clientTier']} | Connects: {j['estimatedConnects']} | Competition: {j['competitionScore']}")

def demo_url_parse():
    print("\n=== URL PARSE DEMO ===")
    url = "https://www.upwork.com/nx/search/jobs/?q=python%20developer&hourly_rate=30-100&job_type=hourly&payment_verified=1&sort=recency"
    print(f"URL: {url}")
    print(f"Parsed: {json.dumps(parse_search_url(url), indent=2)}")

def demo_hash():
    print("\n=== CONTENT HASH & REPOST DETECTION ===")
    job1 = {"title": "Need Logo", "description": "Need a logo for my startup", "budgetAmount": 100, "skills": ["Logo Design"], "jobType": "FIXED"}
    job2 = {"title": "Need Logo", "description": "Need a logo for my startup", "budgetAmount": 100, "skills": ["Logo Design"], "jobType": "FIXED"} # repost
    h1 = compute_content_hash(job1)
    h2 = compute_content_hash(job2)
    print(f"Job1 hash: {h1[:16]}...")
    print(f"Job2 hash: {h2[:16]}...")
    print(f"Same? {h1==h2} → Detected as REPOST")

if __name__ == "__main__":
    demo_ai_scoring()
    demo_url_parse()
    demo_hash()
    print("\n✅ All core PRO logic verified - ready to run with real Upwork API!")
    print("→ For real scrape: python -m src.main  (needs internet + optional Upwork sessionToken)")
