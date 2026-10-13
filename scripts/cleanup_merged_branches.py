#!/usr/bin/env python3
"""Preview or safely delete old merged-PR remote branches (dry-run by default)."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys
from shutil import which
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API = "https://api.github.com"
RESERVED = {"main", "master", "develop", "development", "staging", "production", "release"}
RESERVED_PREFIXES = ("release/", "hotfix/", "production/", "stable/")


def credential():
    for env in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(env):
            return os.environ[env]
    if which("gh"):
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise RuntimeError("Set GH_TOKEN/GITHUB_TOKEN or run gh auth login")


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, path, method="GET"):
        url = path if path.startswith("https://") else API + path
        request = Request(url, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nas-file-center-merged-branch-cleaner",
        })
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                return (json.loads(body) if body else None), response.headers.get("Link", "")
        except HTTPError as exc:
            raise RuntimeError(f"GitHub {method} failed ({exc.code}): " +
                               exc.read().decode("utf8", "replace")[:350]) from exc
        except URLError as exc:
            raise RuntimeError("GitHub unavailable: " + str(exc)) from exc

    def paginate(self, path):
        data = []
        while path:
            result, link = self.request(path)
            if not isinstance(result, list):
                raise RuntimeError("Expected paginated list")
            data.extend(result)
            if len(data) > 10000:
                raise RuntimeError("Too many records; fail closed")
            path = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    match = re.search(r"<([^>]+)>", part)
                    if match:
                        path = match.group(1)
        return data


def eligible(branch, pulls, repo, default, cutoff, prefix):
    name = branch["name"]
    if name == default or name in RESERVED or name.startswith(RESERVED_PREFIXES):
        return False, "reserved branch"
    if branch.get("protected"):
        return False, "protected branch"
    if prefix and not name.startswith(prefix):
        return False, "outside requested prefix"
    history = [p for p in pulls if p.get("head", {}).get("ref") == name and
               (p.get("head", {}).get("repo") or {}).get("full_name", "").lower() == repo.lower()]
    if not history:
        return False, "no same-repo merged PR"
    if any(p.get("state") == "open" for p in history):
        return False, "open PR"
    if any(not p.get("merged_at") for p in history):
        return False, "closed/unmerged PR history"
    match = [p for p in history if p.get("head", {}).get("sha") == branch["commit"]["sha"]
             and p.get("base", {}).get("ref") == default]
    if not match:
        return False, "current HEAD not identical to a merged PR into default branch"
    merged = max(datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00")) for p in match)
    if merged > cutoff:
        return False, "within minimum retention period"
    return True, "merged PR #" + str(max(p["number"] for p in match))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="OWNER/REPO, e.g. JinHaocong/nas-file-center")
    parser.add_argument("--prefix", default="", help="Extra safety filter, e.g. feat/console-v2-")
    parser.add_argument("--min-age-days", type=int, default=7, help="Default 7; set 0 deliberately")
    parser.add_argument("--execute", action="store_true", help="Delete approved refs; otherwise dry-run")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Invalid --repo")
    if args.min_age_days < 0:
        parser.error("Negative retention is not allowed")
    client = GitHub(credential())
    base = "/repos/" + args.repo
    details, _ = client.request(base)
    if details.get("archived"):
        raise RuntimeError("Archived repo: refusing to delete")
    default = details["default_branch"]
    branches = client.paginate(base + "/branches?per_page=100")
    pulls = client.paginate(base + "/pulls?state=all&per_page=100")
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.min_age_days)
    approved = []
    print(f"Repo {args.repo} | default {default} | branches {len(branches)} | dry-run={not args.execute}")
    for branch in branches:
        ok, why = eligible(branch, pulls, args.repo, default, cutoff, args.prefix)
        print(f"  {'CANDIDATE' if ok else 'KEEP'} {branch['name']}: {why}")
        if ok:
            approved.append(branch)
    print(f"Eligible: {len(approved)}. No deletion without --execute.")
    if not args.execute:
        return 0
    deleted = 0
    for branch in approved:
        name = branch["name"]
        path = quote(name, safe="/")
        latest, _ = client.request(base + "/branches/" + path)
        if latest.get("protected") or latest["commit"]["sha"] != branch["commit"]["sha"]:
            print(f"  SKIP {name}: protection or HEAD changed")
            continue
        open_pulls = client.paginate(base + "/pulls?state=open&per_page=100")
        if any(p.get("head", {}).get("ref") == name and
               (p.get("head", {}).get("repo") or {}).get("full_name", "").lower() == args.repo.lower()
               for p in open_pulls):
            print(f"  SKIP {name}: new open PR")
            continue
        client.request(base + "/git/refs/heads/" + path, method="DELETE")
        deleted += 1
        print(f"  DELETED {name}")
    print(f"Deleted {deleted} remote branches")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
