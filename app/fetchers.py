from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)


async def fetch_crtsh(client: httpx.AsyncClient, domain: str) -> set[str]:
    """Certificate Transparency logs via crt.sh"""
    try:
        r = await client.get(
            "https://crt.sh/",
            params={"q": f"%.{domain}", "output": "json"},
            timeout=30,
        )
        r.raise_for_status()
        subs: set[str] = set()
        for entry in r.json():
            for line in entry["name_value"].splitlines():
                subs.add(line.lstrip("*.").strip().lower())
        return subs
    except Exception as exc:
        logger.warning("crt.sh error: %s", exc)
        return set()


async def fetch_hackertarget(client: httpx.AsyncClient, domain: str) -> set[str]:
    """HackerTarget passive DNS (free, no key)"""
    try:
        r = await client.get(
            "https://api.hackertarget.com/hostsearch/",
            params={"q": domain},
            timeout=20,
        )
        r.raise_for_status()
        subs: set[str] = set()
        for line in r.text.splitlines():
            if "," in line:
                host = line.split(",")[0].strip().lower()
                if host.endswith(f".{domain}"):
                    subs.add(host)
        return subs
    except Exception as exc:
        logger.warning("hackertarget error: %s", exc)
        return set()


async def fetch_rapiddns(client: httpx.AsyncClient, domain: str) -> set[str]:
    """RapidDNS passive DNS"""
    try:
        r = await client.get(
            f"https://rapiddns.io/subdomain/{domain}",
            params={"full": "1"},
            timeout=20,
        )
        r.raise_for_status()
        subs = set(re.findall(rf"[\w.-]+\.{re.escape(domain)}", r.text))
        return {s.lower() for s in subs}
    except Exception as exc:
        logger.warning("rapiddns error: %s", exc)
        return set()


async def fetch_alienvault(client: httpx.AsyncClient, domain: str) -> set[str]:
    """AlienVault OTX passive DNS"""
    try:
        r = await client.get(
            f"https://otx.alienvault.com/api/v1/indicators/domain/{domain}/passive_dns",
            timeout=20,
        )
        r.raise_for_status()
        subs: set[str] = set()
        for entry in r.json().get("passive_dns", []):
            host = entry.get("hostname", "").lower()
            if host.endswith(f".{domain}") or host == domain:
                subs.add(host)
        return subs
    except Exception as exc:
        logger.warning("alienvault error: %s", exc)
        return set()


async def fetch_urlscan(client: httpx.AsyncClient, domain: str) -> set[str]:
    """urlscan.io"""
    try:
        r = await client.get(
            "https://urlscan.io/api/v1/search/",
            params={"q": f"domain:{domain}", "size": 100},
            timeout=20,
        )
        r.raise_for_status()
        subs: set[str] = set()
        for result in r.json().get("results", []):
            host = result.get("page", {}).get("domain", "").lower()
            if host.endswith(f".{domain}") or host == domain:
                subs.add(host)
        return subs
    except Exception as exc:
        logger.warning("urlscan error: %s", exc)
        return set()


async def fetch_virustotal(
    client: httpx.AsyncClient, domain: str, api_key: str
) -> set[str]:
    """VirusTotal (requires free API key)"""
    if not api_key:
        return set()
    try:
        r = await client.get(
            f"https://www.virustotal.com/api/v3/domains/{domain}/subdomains",
            headers={"x-apikey": api_key},
            params={"limit": 40},
            timeout=20,
        )
        r.raise_for_status()
        subs: set[str] = set()
        for entry in r.json().get("data", []):
            host = entry.get("id", "").lower()
            if host.endswith(f".{domain}"):
                subs.add(host)
        return subs
    except Exception as exc:
        logger.warning("virustotal error: %s", exc)
        return set()


# Ordered map used by the job runner
PASSIVE_SOURCES: dict[str, object] = {
    "crt.sh": fetch_crtsh,
    "hackertarget": fetch_hackertarget,
    "rapiddns": fetch_rapiddns,
    "alienvault": fetch_alienvault,
    "urlscan": fetch_urlscan,
}
