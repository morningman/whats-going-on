"""GitHub data source — fetches PR and Issue activity from public repos via REST API."""

import logging
import time
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

    def _request_with_retry(
        self, url: str, params: dict, headers: dict,
        max_retries: int = 3, progress_cb=None,
    ) -> requests.Response:
        """Make a GET request with retry logic and progress reporting."""
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt < max_retries:
                    wait = 2 ** attempt  # exponential backoff: 2, 4, 8s
                    msg = f"请求失败 ({e})，{wait}s 后重试 ({attempt}/{max_retries})..."
                    logger.warning(msg)
                    if progress_cb:
                        progress_cb("retry", msg, attempt=attempt, max_attempts=max_retries)
                    time.sleep(wait)
                else:
                    if progress_cb:
                        progress_cb("error", f"请求失败，已重试 {max_retries} 次: {e}")
                    raise

    def _get_default_branch(
        self, owner: str, repo: str, token: str = "",
        progress_cb=None,
    ) -> str:
        """Get the default branch name of a repo (e.g. 'main' or 'master')."""
        url = f"{API_BASE}/repos/{owner}/{repo}"
        logger.info("Fetching default branch for %s/%s", owner, repo)
        if progress_cb:
            progress_cb("progress", f"正在获取 {owner}/{repo} 的默认分支...", step="fetch_default_branch")
        resp = self._request_with_retry(url, {}, self._headers(token), progress_cb=progress_cb)
        default_branch = resp.json().get("default_branch", "main")
        logger.info("Default branch for %s/%s is '%s'", owner, repo, default_branch)
        if progress_cb:
            progress_cb("progress", f"默认分支：{default_branch}", step="fetch_default_branch_done")
        return default_branch

    def fetch_pull_requests(
        self, owner: str, repo: str, days: int = 3, token: str = "",
        progress_cb=None, since_date: str = None, until_date: str = None,
    ) -> list[dict]:
        """Fetch PRs updated within the last N days, targeting the default branch only."""
        if since_date:
            since = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        else:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        url = f"{API_BASE}/repos/{owner}/{repo}/pulls"
        all_prs = []
        page = 1

        # Only fetch PRs targeting the default branch
        default_branch = self._get_default_branch(owner, repo, token, progress_cb)

        if progress_cb:
            progress_cb("progress", f"正在获取 {owner}/{repo} 提交到 {default_branch} 分支的 Pull Requests...", step="fetch_prs")

        while True:
            params = {
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "base": default_branch,
                "per_page": 100,
                "page": page,
            }
            logger.info("Fetching PRs from %s/%s page=%d", owner, repo, page)
            if progress_cb:
                progress_cb(
                    "progress",
                    f"正在获取 PR 数据 (第 {page} 页)...",
                    step="fetch_prs",
                    detail=f"已获取 {len(all_prs)} 条 PR",
                )

            resp = self._request_with_retry(
                url, params, self._headers(token), progress_cb=progress_cb,
            )
            prs = resp.json()

            if not prs:
                break

            for pr in prs:
                updated = pr.get("updated_at", "")
                if updated < since:
                    # PRs are sorted by updated desc, so we can stop
                    filtered = [p for p in prs if p.get("updated_at", "") >= since]
                    result = self._normalize_prs(all_prs + filtered)
                    # Filter by until_date if provided (upper bound)
                    if until_date:
                        until_iso = datetime.strptime(until_date, "%Y-%m-%d").replace(
                            hour=23, minute=59, second=59, tzinfo=timezone.utc
                        ).isoformat()
                        result = [p for p in result if p["updated_at"] <= until_iso]
                    if progress_cb:
                        progress_cb("progress", f"PR 数据获取完成，共 {len(result)} 条", step="fetch_prs_done")
                    return result

                all_prs.append(pr)

            if len(prs) < 100:
                break
            page += 1

        result = self._normalize_prs(all_prs)
        # Filter by until_date if provided (upper bound)
        if until_date:
            until_iso = datetime.strptime(until_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            ).isoformat()
            result = [p for p in result if p["updated_at"] <= until_iso]
        if progress_cb:
            progress_cb("progress", f"PR 数据获取完成，共 {len(result)} 条", step="fetch_prs_done")
        return result

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
        self, owner: str, repo: str, days: int = 3, token: str = "",
        progress_cb=None, since_date: str = None, until_date: str = None,
    ) -> list[dict]:
        """Fetch issues (excluding PRs) updated within the last N days."""
        if since_date:
            since = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        else:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        url = f"{API_BASE}/repos/{owner}/{repo}/issues"
        all_issues = []
        page = 1

        if progress_cb:
            progress_cb("progress", f"正在获取 Issue 数据...", step="fetch_issues")

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
            if progress_cb:
                progress_cb(
                    "progress",
                    f"正在获取 Issue 数据 (第 {page} 页)...",
                    step="fetch_issues",
                    detail=f"已获取 {len(all_issues)} 条 Issue",
                )

            resp = self._request_with_retry(
                url, params, self._headers(token), progress_cb=progress_cb,
            )
            issues = resp.json()

            if not issues:
                break

            # Filter out PRs (GitHub includes PRs in issues endpoint)
            real_issues = [i for i in issues if "pull_request" not in i]
            all_issues.extend(real_issues)

            if len(issues) < 100:
                break
            page += 1

        result = self._normalize_issues(all_issues)
        # Filter by until_date if provided (upper bound)
        if until_date:
            until_iso = datetime.strptime(until_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            ).isoformat()
            result = [i for i in result if i["updated_at"] <= until_iso]
        if progress_cb:
            progress_cb("progress", f"Issue 数据获取完成，共 {len(result)} 条", step="fetch_issues_done")
        return result

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
        self, owner: str, repo: str, days: int = 3, token: str = "",
        progress_cb=None, since_date: str = None, until_date: str = None,
    ) -> dict:
        """Fetch combined PR + Issue activity for a repo."""
        logger.info("Fetching activity for %s/%s (last %d days, since_date=%s)", owner, repo, days, since_date)
        if progress_cb:
            if since_date:
                from datetime import timedelta as _td
                end_d = datetime.strptime(since_date, "%Y-%m-%d") + _td(days=days - 1)
                range_label = f"{since_date} ~ {end_d.strftime('%Y-%m-%d')}"
                progress_cb("progress", f"开始获取 {owner}/{repo} {range_label} 的活动数据...", step="start")
            else:
                progress_cb("progress", f"开始获取 {owner}/{repo} 最近 {days} 天的活动数据...", step="start")

        prs = self.fetch_pull_requests(owner, repo, days, token, progress_cb=progress_cb, since_date=since_date, until_date=until_date)
        issues = self.fetch_issues(owner, repo, days, token, progress_cb=progress_cb, since_date=since_date, until_date=until_date)

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

        if progress_cb:
            progress_cb(
                "progress",
                f"数据获取完成：{stats['total_prs']} 个 PR ({stats['merged_prs']} 已合并)，{stats['total_issues']} 个 Issue",
                step="complete",
            )

        return {
            "pulls": prs,
            "issues": issues,
            "stats": stats,
            "repo": f"{owner}/{repo}",
            "days": days,
        }
