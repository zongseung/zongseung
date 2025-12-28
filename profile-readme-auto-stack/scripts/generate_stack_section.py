#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Update README.md between:
<!-- STACK:START --> and <!-- STACK:END -->

Scans:
- User's public repos (fork/archived 제외)
- Root manifests (requirements.txt, pyproject.toml, environment.yml, package.json 등)
- Repo languages endpoint

Builds a neat badge block and injects it into README.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

OWNER = os.getenv("GITHUB_OWNER", "").strip()
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
README_PATH = os.getenv("README_PATH", "README.md")

STACK_START = "<!-- STACK:START -->"
STACK_END = "<!-- STACK:END -->"

# dependency keyword -> (badge label, color, logo)
BADGE_MAP = {
    # ML/DL
    "tensorflow": ("TensorFlow", "FF6F00", "tensorflow"),
    "torch": ("PyTorch", "EE4C2C", "pytorch"),
    "pytorch": ("PyTorch", "EE4C2C", "pytorch"),
    "scikit-learn": ("Scikit--Learn", "F7931E", "scikit-learn"),
    "sklearn": ("Scikit--Learn", "F7931E", "scikit-learn"),
    "statsmodels": ("Statsmodels", "1A1A1A", "python"),

    # Data
    "pyspark": ("Apache%20Spark", "E25A1C", "apachespark"),
    "spark": ("Apache%20Spark", "E25A1C", "apachespark"),
    "pandas": ("Pandas", "150458", "pandas"),
    "numpy": ("NumPy", "013243", "numpy"),

    # Notebook/Dev
    "jupyter": ("Jupyter", "F37626", "jupyter"),
    "ipykernel": ("Jupyter", "F37626", "jupyter"),
}

LANG_BADGE_MAP = {
    "Python": ("Python", "3776AB", "python"),
    "Jupyter Notebook": ("Jupyter", "F37626", "jupyter"),
    "JavaScript": ("JavaScript", "F7DF1E", "javascript"),
    "TypeScript": ("TypeScript", "3178C6", "typescript"),
    "Java": ("Java", "ED8B00", "openjdk"),
    "C++": ("C%2B%2B", "00599C", "cplusplus"),
    "Go": ("Go", "00ADD8", "go"),
    "Rust": ("Rust", "000000", "rust"),
}

MANIFESTS = [
    "requirements.txt",
    "pyproject.toml",
    "environment.yml",
    "environment.yaml",
    "Pipfile",
    "poetry.lock",
    "setup.cfg",
    "setup.py",
    "package.json",
]

@dataclass
class RepoInfo:
    name: str
    fork: bool
    archived: bool

def _api_get(url: str) -> dict | list:
    req = urllib.request.Request(url)
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def list_repos(owner: str) -> List[RepoInfo]:
    repos: List[RepoInfo] = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{owner}/repos?per_page=100&page={page}&sort=updated"
        data = _api_get(url)
        if not data:
            break
        for r in data:
            repos.append(RepoInfo(name=r["name"], fork=bool(r.get("fork", False)), archived=bool(r.get("archived", False))))
        page += 1
        if page > 10:
            break
    return repos

def repo_languages(owner: str, repo: str) -> Dict[str, int]:
    url = f"https://api.github.com/repos/{owner}/{repo}/languages"
    try:
        data = _api_get(url)
        if isinstance(data, dict):
            return {k: int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}

def get_root_file(owner: str, repo: str, path: str) -> Optional[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    try:
        data = _api_get(url)
        if isinstance(data, dict) and data.get("type") == "file" and "content" in data:
            raw = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
            return raw
    except Exception:
        return None
    return None

def extract_deps(text: str) -> Iterable[str]:
    deps = set()

    # line-based best-effort (requirements/environment)
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-r") or s.startswith("--"):
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        s = re.split(r"[<=>;\[\] ]", s, maxsplit=1)[0].strip()
        if s:
            deps.add(s.lower())

    # package.json
    if '"dependencies"' in text or '"devDependencies"' in text:
        try:
            obj = json.loads(text)
            for k in (obj.get("dependencies", {}) or {}).keys():
                deps.add(k.lower())
            for k in (obj.get("devDependencies", {}) or {}).keys():
                deps.add(k.lower())
        except Exception:
            pass

    # simple pyproject.toml key= "x"
    for m in re.finditer(r'^\s*([A-Za-z0-9_.\-]+)\s*=\s*["\']', text, flags=re.M):
        key = m.group(1).strip().lower()
        if key not in {"name", "version", "description", "requires-python"}:
            deps.add(key)

    return deps

def make_badge(label: str, color: str, logo: str) -> str:
    return f'<img src="https://img.shields.io/badge/{label}-{color}?style=for-the-badge&logo={logo}&logoColor=white" />'

def build_section(owner: str) -> str:
    repos = list_repos(owner)

    lang_totals: Dict[str, int] = {}
    deps_found = set()

    for r in repos:
        if r.fork or r.archived:
            continue

        # languages
        langs = repo_languages(owner, r.name)
        for lang, b in langs.items():
            lang_totals[lang] = lang_totals.get(lang, 0) + b

        # manifests
        for mf in MANIFESTS:
            content = get_root_file(owner, r.name, mf)
            if content:
                deps_found.update(extract_deps(content))

    top_langs = sorted(lang_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    lang_badges = []
    for lang, _ in top_langs:
        if lang in LANG_BADGE_MAP:
            label, color, logo = LANG_BADGE_MAP[lang]
            lang_badges.append(make_badge(label, color, logo))

    tool_badges = []
    for dep in sorted(deps_found):
        if dep in BADGE_MAP:
            label, color, logo = BADGE_MAP[dep]
            tool_badges.append(make_badge(label, color, logo))

    lines: List[str] = []
    lines.append('<div align="center">')
    lines.append("")
    lines.append("### Languages (auto)")
    lines.append(" ".join(lang_badges) if lang_badges else "_No mapped languages detected._")
    lines.append("")
    lines.append("### Tools / Frameworks (auto)")
    lines.append(" ".join(tool_badges) if tool_badges else "_No mapped dependencies detected._")
    lines.append("")
    lines.append("</div>")
    return "\n".join(lines)

def update_readme(path: str, new_block: str) -> bool:
    text = open(path, "r", encoding="utf-8").read()
    if STACK_START not in text or STACK_END not in text:
        raise RuntimeError(f"README missing markers: {STACK_START} / {STACK_END}")

    pattern = re.compile(re.escape(STACK_START) + r".*?" + re.escape(STACK_END), flags=re.S)
    replacement = STACK_START + "\n" + new_block.strip() + "\n" + STACK_END
    updated = pattern.sub(replacement, text)

    changed = (updated != text)
    if changed:
        open(path, "w", encoding="utf-8").write(updated)
    return changed

def main() -> int:
    if not OWNER:
        print("GITHUB_OWNER is required", file=sys.stderr)
        return 2
    new_block = build_section(OWNER)
    changed = update_readme(README_PATH, new_block)
    print(f"Updated: {changed}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
