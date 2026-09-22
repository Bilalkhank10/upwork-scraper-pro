"""
Notifier - Multi-channel alerts
Supports Telegram, Discord, Slack, Generic Webhook
More powerful: Rich embeds, rate limiting, batch summaries
"""
import httpx
import json
import logging
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)

class Notifier:
    def __init__(self, inputs: Dict[str, Any]):
        self.inputs = inputs
        self.client = httpx.AsyncClient(timeout=15)

    async def send_all(self, jobs: List[Dict[str, Any]], metadata: Dict[str, Any] = None):
        if not jobs:
            return
        limit = int(self.inputs.get("notificationLimit", 5) or 5)
        jobs_to_send = jobs[:limit]

        # Optionally filter to changes only
        if self.inputs.get("notifyOnlyChanges") and self.inputs.get("incrementalMode"):
            jobs_to_send = [j for j in jobs_to_send if j.get("changeType") in ("NEW", "UPDATED", "REAPPEARED")]
            if not jobs_to_send:
                log.info("No changes to notify")
                return

        tasks = []
        if self.inputs.get("telegramToken") and self.inputs.get("telegramChatId"):
            tasks.append(self.send_telegram(jobs_to_send, metadata))
        if self.inputs.get("discordWebhookUrl"):
            tasks.append(self.send_discord(jobs_to_send, metadata))
        if self.inputs.get("slackWebhookUrl"):
            tasks.append(self.send_slack(jobs_to_send, metadata))
        if self.inputs.get("webhookUrl"):
            tasks.append(self.send_generic(jobs_to_send, metadata))
        
        for t in tasks:
            try:
                await t
            except Exception as e:
                log.warning(f"Notify failed: {e}")

    def _fmt_job_line(self, job: Dict[str, Any]) -> str:
        title = job.get("title", "Untitled")[:70]
        budget = job.get("budgetAmount") or f"${job.get('hourlyBudgetMin') or '?'}-${job.get('hourlyBudgetMax') or '?'}"
        if job.get("jobType") == "HOURLY":
            budget = f"${job.get('hourlyBudgetMin')}-{job.get('hourlyBudgetMax')}/hr"
        elif job.get("budgetAmount"):
            budget = f"${job.get('budgetAmount')}"
        country = job.get("clientCountry") or "Unknown"
        spent = job.get("clientTotalSpent")
        spent_s = f"${int(spent):,}" if spent else "N/A"
        applicants = job.get("totalApplicants", "?")
        score = job.get("aiLeadScore") or job.get("customJobScore", "")
        tier = job.get("clientTier", "")
        url = job.get("url", "")
        return f"• <b>{title}</b>\n  {budget} | {country} (Spent {spent_s}) | 👥 {applicants} | ⭐ {score} {tier}\n  {url}"

    async def send_telegram(self, jobs: List[Dict[str, Any]], metadata):
        token = self.inputs["telegramToken"]
        chat_id = self.inputs["telegramChatId"]
        include_meta = self.inputs.get("includeRunMetadata", True)
        
        text = ""
        if include_meta and metadata:
            text += f"🎯 <b>Upwork PRO</b> - {metadata.get('query','search')} | Found {metadata.get('total', len(jobs))} jobs, sending {len(jobs)}\n\n"
        for j in jobs:
            text += self._fmt_job_line(j) + "\n\n"
        
        # Telegram limit 4096
        if len(text) > 4000:
            text = text[:4000] + "..."

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        try:
            r = await self.client.post(url, json=payload)
            log.info(f"Telegram sent: {r.status_code}")
        except Exception as e:
            log.warning(f"Telegram error: {e}")

    async def send_discord(self, jobs: List[Dict[str, Any]], metadata):
        webhook = self.inputs["discordWebhookUrl"]
        embeds = []
        for j in jobs[:5]:  # Discord limit
            title = j.get("title", "Untitled")[:256]
            url = j.get("url", "")
            budget = j.get("budgetAmount") or f"{j.get('hourlyBudgetMin')}-{j.get('hourlyBudgetMax')}/hr"
            desc = (j.get("description") or "")[:300] + "..."
            embeds.append({
                "title": title,
                "url": url,
                "description": desc,
                "color": 0x14A800,  # Upwork green
                "fields": [
                    {"name": "Budget", "value": str(budget), "inline": True},
                    {"name": "Client", "value": f"{j.get('clientCountry','?')} | Spent ${int(j.get('clientTotalSpent') or 0):,} | ⭐ {j.get('clientRating','?')}", "inline": True},
                    {"name": "Applicants", "value": str(j.get("totalApplicants","?")), "inline": True},
                    {"name": "Score", "value": f"{j.get('aiLeadScore','?')} ({j.get('clientTier','')})", "inline": True},
                ]
            })
        payload = {"content": f"🚀 **{len(jobs)} new Upwork jobs** - Upwork PRO", "embeds": embeds}
        try:
            r = await self.client.post(webhook, json=payload)
            log.info(f"Discord sent: {r.status_code}")
        except Exception as e:
            log.warning(f"Discord error: {e}")

    async def send_slack(self, jobs: List[Dict[str, Any]], metadata):
        webhook = self.inputs["slackWebhookUrl"]
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"Upwork PRO - {len(jobs)} new jobs"}}
        ]
        for j in jobs[:5]:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*<{j.get('url','')}|{j.get('title','Untitled')[:70]}>*\nBudget: {j.get('budgetAmount') or str(j.get('hourlyBudgetMin'))+'-'+str(j.get('hourlyBudgetMax'))}/hr | {j.get('clientCountry')} | Spent ${int(j.get('clientTotalSpent') or 0):,} | 👥 {j.get('totalApplicants','?')} | Score {j.get('aiLeadScore','?')}"}
            })
        payload = {"blocks": blocks}
        try:
            r = await self.client.post(webhook, json=payload)
            log.info(f"Slack sent: {r.status_code}")
        except Exception as e:
            log.warning(f"Slack error: {e}")

    async def send_generic(self, jobs: List[Dict[str, Any]], metadata):
        url = self.inputs["webhookUrl"]
        headers = self.inputs.get("webhookHeaders") or {}
        payload = {"metadata": metadata or {}, "items": jobs, "count": len(jobs)}
        try:
            r = await self.client.post(url, json=payload, headers=headers)
            log.info(f"Webhook sent: {r.status_code}")
        except Exception as e:
            log.warning(f"Webhook error: {e}")

    async def close(self):
        await self.client.aclose()
