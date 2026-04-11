"""We Work Remotely — RSS feed for DevOps/Sysadmin (closest to security).
Security jobs will be caught by keyword filter from config.
"""

import logging
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

# DevOps/SysAdmin feed is the most relevant for security roles on WWR
RSS_FEEDS = {
    "DevOps-SysAdmin": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "Full-Stack": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
}


def fetch_wwr() -> list[Job]:
    """Fetch jobs from We Work Remotely RSS feeds."""
    jobs = []
    for category, url in RSS_FEEDS.items():
        xml_text = get_text(url)
        if not xml_text:
            log.warning(f"WWR: no data for {category}")
            continue
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall(".//item"):
                title_raw = item.findtext("title", "")
                link = item.findtext("link", "")

                if ": " in title_raw:
                    company, title = title_raw.split(": ", 1)
                else:
                    company, title = "", title_raw

                jobs.append(Job(
                    title=title.strip(),
                    company=company.strip(),
                    location="Remote",
                    url=link.strip(),
                    source="wwr",
                    tags=[category],
                    is_remote=True,
                ))
        except ET.ParseError as e:
            log.warning(f"WWR: XML parse error for {category}: {e}")

    log.info(f"WWR: fetched {len(jobs)} jobs.")
    return jobs
