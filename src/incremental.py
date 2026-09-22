"""
Incremental Mode - MORE POWERFUL than original
- Uses SHA256 contentHash for change detection
- Handles NEW / UPDATED / UNCHANGED / REAPPEARED / EXPIRED
- Repost detection
- State stored in Apify KV Store (or local JSON for standalone)
"""
import json
import hashlib
import os
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import logging

log = logging.getLogger(__name__)

try:
    from apify import Actor
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

class IncrementalStore:
    def __init__(self, state_key: str, inputs: Dict[str, Any]):
        # Auto-derive stateKey if not provided - isolates different searches
        if not state_key:
            # Hash of key inputs
            key_data = "|".join([
                str(inputs.get("query", "")),
                str(inputs.get("location", "")),
                str(inputs.get("jobType", "")),
                str(inputs.get("category", "")),
                str(inputs.get("searchUrl", "")),
                str(inputs.get("startUrls", "")),
            ])
            state_key = "auto_" + hashlib.sha256(key_data.encode()).hexdigest()[:16]
        self.state_key = state_key
        self.store_name = f"upwork-state-{state_key}"
        self.local_path = f"./storage/incremental_{state_key}.json"
        self.state: Dict[str, Dict[str, Any]] = {}  # jobId -> {hash, lastSeen, data}
        self.inputs = inputs

    async def load(self):
        """Load state from Apify KV or local file"""
        if HAS_APIFY:
            try:
                store = await Actor.open_key_value_store(name=self.store_name)
                data = await store.get_value("STATE")
                if data and isinstance(data, dict):
                    self.state = data
                    log.info(f"Loaded incremental state: {len(self.state)} jobs from store {self.store_name}")
                    return
            except Exception as e:
                log.warning(f"KV load failed: {e}, trying local")

        # Local fallback
        if os.path.exists(self.local_path):
            try:
                with open(self.local_path, "r") as f:
                    self.state = json.load(f)
                log.info(f"Loaded local state: {len(self.state)} jobs")
            except Exception as e:
                log.warning(f"Local load failed: {e}")

    async def save(self):
        """Save state"""
        if HAS_APIFY:
            try:
                store = await Actor.open_key_value_store(name=self.store_name)
                await store.set_value("STATE", self.state)
                log.info(f"Saved state: {len(self.state)} jobs")
                return
            except Exception as e:
                log.warning(f"KV save failed: {e}")

        os.makedirs(os.path.dirname(self.local_path) or ".", exist_ok=True)
        with open(self.local_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def diff(self, jobs: List[Dict[str, Any]], skip_reposts: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """
        Compare current jobs vs stored state
        Returns (filtered_jobs, stats)
        """
        now = datetime.now(timezone.utc).isoformat()
        seen_ids = set()
        result: List[Dict[str, Any]] = []
        
        stats = {"NEW": 0, "UPDATED": 0, "UNCHANGED": 0, "REAPPEARED": 0, "EXPIRED": 0, "REPOST": 0}

        # Build hash map of existing hashes for repost detection
        hash_to_id = {v.get("hash"): k for k, v in self.state.items()}

        for job in jobs:
            jid = job.get("jobId")
            if not jid:
                continue
            seen_ids.add(jid)
            curr_hash = job.get("contentHash")
            prev = self.state.get(jid)

            if prev is None:
                # Check if repost (same hash as expired job)
                if curr_hash and curr_hash in hash_to_id and hash_to_id[curr_hash] != jid:
                    job["changeType"] = "REAPPEARED"
                    job["isRepost"] = True
                    job["repostOfId"] = hash_to_id[curr_hash]
                    job["repostDetectedAt"] = now
                    stats["REAPPEARED"] += 1
                    if skip_reposts:
                        stats["REPOST"] += 1
                        continue
                else:
                    job["changeType"] = "NEW"
                    stats["NEW"] += 1
                result.append(job)
            else:
                prev_hash = prev.get("hash")
                if curr_hash != prev_hash:
                    job["changeType"] = "UPDATED"
                    stats["UPDATED"] += 1
                    result.append(job)
                else:
                    job["changeType"] = "UNCHANGED"
                    stats["UNCHANGED"] += 1
                    # Only emit if requested upstream
                    # We'll mark but filter later
                    job["_is_unchanged"] = True
                    result.append(job)

            # Update state
            self.state[jid] = {"hash": curr_hash, "lastSeen": now, "title": job.get("title")}

        # Detect expired
        expired_ids = set(self.state.keys()) - seen_ids
        for eid in expired_ids:
            stats["EXPIRED"] += 1
            # Optionally emit expired pseudo-jobs
            # We keep them in state for repost detection but mark lastSeen old

        # Cleanup old state? Keep for 30 days for repost detection
        return result, stats

    def filter_unchanged(self, jobs: List[Dict[str, Any]], emit_unchanged: bool, emit_expired: bool) -> List[Dict[str, Any]]:
        filtered = []
        for j in jobs:
            ct = j.get("changeType")
            if ct == "UNCHANGED" and not emit_unchanged:
                continue
            if ct == "EXPIRED" and not emit_expired:
                continue
            # Remove internal flag
            j.pop("_is_unchanged", None)
            filtered.append(j)
        return filtered
