"""GitHub data source — fetches PR and Issue activity from public repos via REST API."""

import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger("sources.github")

API_BASE = "https://api.github.com"


class GitHubSource:
    """Fetch PR and Issue data from GitHub REST API."""

    def _headers(self, token: str = "") -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def fetch_pull_requests(
        self, owner: str, repo: str, days: int = 3, token: str = ""
    ) -> list[dict]:
        """Fetch PRs updated within the last N days."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        url = f"{API_BASE}/repos/{owner}/{repo}/pulls"
        all_prs = []
        page = 1

        while True:
            params = {
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            }
            logger.info("Fetching PRs from %s/%s page=%d", owner, repo, page)
            resp = requests.get(url, headers=self._headers(token), params=params, timeout=30)
            resp.raise_for_status()
            prs = resp.json()

            if not prs:
                break

            for pr in prs:
                updated = pr.get("updated_at", "")
                if updated < since:
                    # PRs are sorted by updated desc, so we can stop
                    filtered = [p for p in prs if p.get("updated_at", "") >= since]
                    return self._normalize_prs(all_prs + filtered)

                all_prs.append(pr)

            if len(prs) < 100:
                break
            page += 1

        return self._normalize_prs(all_prs)

    def _normalize_prs(self, raw_prs: list[dict]) -> list[dict]:
        """Normalize raw GitHub PR data to a simpler format."""
        result = []
        for pr in raw_prs:
            result.append({
                "number": pr["number"],
                "title": pr["title"],
                "state": "merged" if pr.get("merged_at") else pr["state"],
                "user": pr.get("user", {}).get("login", ""),
                "labels": [l["name"] for l in pr.get("labels", [])],
                "created_at": pr.get("created_at", ""),
                "updated_at": pr.get("updated_at", ""),
                "html_url": pr.get("html_url", ""),
                "merged": bool(pr.get("merged_at")),
                "draft": pr.get("draft", False),
            })
        return result

    def fetch_issues(
        self, owner: str, repo: str, days: int = 3, token: str = ""
    ) -> list[dict]:
        """Fetch issues (excluding PRs) updated within the last N days."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        url = f"{API_BASE}/repos/{owner}/{repo}/issues"
        all_issues = []
        page = 1

        while True:
            params = {
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "since": since,
                "per_page": 100,
                "page": page,
            }
            logger.info("Fetching issues from %s/%s page=%d", owner, repo, page)
            resp = requests.get(url, headers=self._headers(token), params=params, timeout=30)
            resp.raise_for_status()
            issues = resp.json()

            if not issues:
                break

            # Filter out PRs (GitHub includes PRs in issues endpoint)
            real_issues = [i for i in issues if "pull_request" not in i]
            all_issues.extend(real_issues)

            if len(issues) < 100:
                break
            page += 1

        return self._normalize_issues(all_issues)

    def _normalize_issues(self, raw_issues: list[dict]) -> list[dict]:
        """Normalize raw GitHub issue data to a simpler format."""
        result = []
        for issue in raw_issues:
            result.append({
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "user": issue.get("user", {}).get("login", ""),
                "labels": [l["name"] for l in issue.get("labels", [])],
                "created_at": issue.get("created_at", ""),
                "updated_at": issue.get("updated_at", ""),
                "html_url": issue.get("html_url", ""),
                "comments": issue.get("comments", 0),
            })
        return result

    def fetch_activity(
        self, owner: str, repo: str, days: int = 3, token: str = ""
    ) -> dict:
        """Fetch combined PR + Issue activity for a repo."""
        logger.info("Fetching activity for %s/%s (last %d days)", owner, repo, days)
        prs = self.fetch_pull_requests(owner, repo, days, token)
        issues = self.fetch_issues(owner, repo, days, token)

        stats = {
            "total_prs": len(prs),
            "merged_prs": sum(1 for p in prs if p["merged"]),
            "open_prs": sum(1 for p in prs if p["state"] == "open"),
            "closed_prs": sum(1 for p in prs if p["state"] == "closed" and not p["merged"]),
            "total_issues": len(issues),
            "open_issues": sum(1 for i in issues if i["state"] == "open"),
            "closed_issues": sum(1 for i in issues if i["state"] == "closed"),
        }

        logger.info(
            "Activity for %s/%s: %d PRs (%d merged), %d issues",
            owner, repo, stats["total_prs"], stats["merged_prs"], stats["total_issues"],
        )

        return {
            "pulls": prs,
            "issues": issues,
            "stats": stats,
            "repo": f"{owner}/{repo}",
            "days": days,
        }
