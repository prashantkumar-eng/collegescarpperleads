"""College & Faculty Lead Generation Workflow (Serverless-safe).

Refactor of the original script for predictable execution in serverless.

- No file I/O.
- No stdout prints.
- Configurable limits and timeouts.
- Optional polite delays.
- Better DuckDuckGo URL extraction (handles DDG redirect links).

This is best-effort scraping: different websites need custom rules for
perfect extraction.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


@dataclass
class ScrapeConfig:
    request_timeout_s: int = 10
    max_faculty_pages: int = 2
    max_faculty_per_page: int = 8
    include_linkedin: bool = False
    polite_delay_s: float = 0.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


class CollegeLeadScraper:
    def __init__(self, config: Optional[ScrapeConfig] = None):
        self.config = config or ScrapeConfig()
        self.session = requests.Session()
        self.headers = {"User-Agent": self.config.user_agent}

    # ---------- helpers ----------
    @staticmethod
    def extract_emails(text: str) -> List[str]:
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        return sorted(set(re.findall(email_pattern, text)))

    @staticmethod
    def extract_phones(text: str) -> List[str]:
        phone_patterns = [
            r"\+?91[-.\s]?\d{10}",
            r"\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
            r"\d{3}[-.\s]?\d{3}[-.\s]?\d{4}",
        ]
        phones: List[str] = []
        for pattern in phone_patterns:
            phones.extend(re.findall(pattern, text))
        return sorted(set(p.strip() for p in phones if p.strip()))

    @staticmethod
    def _unwrap_duckduckgo_redirect(href: str) -> str:
        """DDG HTML results often use https://duckduckgo.com/l/?uddg=<url-encoded>"""
        try:
            parsed = urlparse(href)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                qs = parse_qs(parsed.query)
                if "uddg" in qs and qs["uddg"]:
                    return qs["uddg"][0]
        except Exception:
            pass
        return href

    def _get(self, url: str) -> Optional[requests.Response]:
        for attempt in range(2):
            try:
                return self.session.get(url, headers=self.headers, timeout=self.config.request_timeout_s)
            except Exception:
                if attempt == 0:
                    time.sleep(0.2)
        return None

    def _maybe_delay(self) -> None:
        if self.config.polite_delay_s and self.config.polite_delay_s > 0:
            time.sleep(self.config.polite_delay_s)

    # ---------- workflow ----------
    def search_college_website(self, college_name: str) -> Optional[str]:
        query = f"{college_name} official website"
        search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

        resp = self._get(search_url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.content, "html.parser")
        result = soup.find("a", class_="result__a")
        if not result:
            return None

        href = result.get("href") or ""
        href = self._unwrap_duckduckgo_redirect(href)

        # Sanity: ensure it's http(s)
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return None

    def scrape_college_info(self, website: str) -> Dict[str, Any]:
        college_data: Dict[str, Any] = {
            "website": website,
            "emails": [],
            "phones": [],
            "faculty_pages": [],
        }

        resp = self._get(website)
        if not resp:
            return college_data

        soup = BeautifulSoup(resp.content, "html.parser")
        text = soup.get_text(" ")
        college_data["emails"] = self.extract_emails(text)
        college_data["phones"] = self.extract_phones(text)

        faculty_keywords = ["faculty", "staff", "professor", "teachers", "department", "people", "directory"]
        pages: List[str] = []
        for link in soup.find_all("a", href=True):
            link_text = (link.get_text() or "").lower()
            link_href = (link.get("href") or "").lower()
            if any(k in link_text or k in link_href for k in faculty_keywords):
                full_url = urljoin(website, link.get("href"))
                if full_url not in pages:
                    pages.append(full_url)
        college_data["faculty_pages"] = pages
        return college_data

    def scrape_faculty_page(self, faculty_url: str) -> List[Dict[str, Any]]:
        resp = self._get(faculty_url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.content, "html.parser")
        faculty_list: List[Dict[str, Any]] = []

        # Strategy 1: tables
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                row_text = " ".join(cell.get_text(" ", strip=True) for cell in cells)
                row_emails = self.extract_emails(row_text)
                if row_emails:
                    faculty_list.append({
                        "name": self._guess_name_from_row(cells),
                        "emails": row_emails,
                        "source": "table",
                        "text": row_text,
                        "page": faculty_url,
                    })

        # Strategy 2: profile-like blocks
        sections = soup.find_all(["div", "section", "article"], class_=re.compile(r"faculty|staff|profile|member", re.I))
        for section in sections:
            section_text = section.get_text(" ", strip=True)
            section_emails = self.extract_emails(section_text)
            if not section_emails:
                continue
            name_tag = section.find(["h2", "h3", "h4", "strong", "b"])
            name = name_tag.get_text(" ", strip=True) if name_tag else "Unknown"
            faculty_list.append({
                "name": name,
                "emails": section_emails,
                "source": "section",
                "text": section_text[:300],
                "page": faculty_url,
            })

        # De-dup by email
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for item in faculty_list:
            key = ",".join(sorted(item.get("emails", [])))
            if key and key not in seen:
                seen.add(key)
                deduped.append(item)

        return deduped

    @staticmethod
    def _guess_name_from_row(cells) -> str:
        # Try first cell, else Unknown
        first = cells[0].get_text(" ", strip=True) if cells else ""
        # Simple heuristic: name-like if has letters and spaces
        if first and re.search(r"[A-Za-z]", first):
            return first
        return "Unknown"

    def search_linkedin(self, name: str, college_name: str) -> List[str]:
        query = f"{name} {college_name} site:linkedin.com"
        search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

        resp = self._get(search_url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.content, "html.parser")
        profiles: List[str] = []
        for link in soup.find_all("a", class_="result__a"):
            href = link.get("href", "")
            href = self._unwrap_duckduckgo_redirect(href)
            if "linkedin.com" in href:
                profiles.append(href)
        return profiles[:5]

    def run_workflow(self, college_name: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "config": {
                "request_timeout_s": self.config.request_timeout_s,
                "max_faculty_pages": self.config.max_faculty_pages,
                "max_faculty_per_page": self.config.max_faculty_per_page,
                "include_linkedin": self.config.include_linkedin,
                "polite_delay_s": self.config.polite_delay_s,
            }
        }

        results: Dict[str, Any] = {
            "college_name": college_name,
            "college_website": None,
            "college_contacts": {"emails": [], "phones": []},
            "faculty_members": [],
            "meta": meta,
        }

        website = self.search_college_website(college_name)
        if not website:
            meta["error"] = "website_not_found"
            return results

        results["college_website"] = website

        self._maybe_delay()
        college_data = self.scrape_college_info(website)
        results["college_contacts"] = {
            "emails": college_data.get("emails", []),
            "phones": college_data.get("phones", []),
        }

        faculty_pages = (college_data.get("faculty_pages") or [])[: self.config.max_faculty_pages]
        for page in faculty_pages:
            self._maybe_delay()
            faculty_list = self.scrape_faculty_page(page)[: self.config.max_faculty_per_page]

            if self.config.include_linkedin:
                for f in faculty_list:
                    name = f.get("name") or "Unknown"
                    if name != "Unknown":
                        self._maybe_delay()
                        f["linkedin_profiles"] = self.search_linkedin(name, college_name)

            results["faculty_members"].extend(faculty_list)

        return results
