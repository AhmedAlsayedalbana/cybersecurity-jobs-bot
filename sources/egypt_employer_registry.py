"""Curated Egyptian employer registry.

An entry is intentionally admitted only after both sides of the discovery
contract are known: an official careers page and a stable LinkedIn company
identifier.  The official careers connector owns the first route; the
LinkedIn unified engine owns the second route and tags resulting jobs with the
same stable key.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EgyptEmployer:
    key: str
    company: str
    sector: str
    linkedin_identifier: str
    careers_url: str
    careers_source_key: str
    priority: int

    def linkedin_query(self) -> str:
        return f"{self.company} cybersecurity"


# Career URLs below are the same public URLs actively used by
# ``official_careers.py``.  New companies must first be added there (or to a
# supported ATS adapter), then may be admitted here.
EGYPT_EMPLOYERS: tuple[EgyptEmployer, ...] = (
    EgyptEmployer("nbe", "National Bank of Egypt", "bank", "national-bank-of-egypt", "https://www.nbe.com.eg/NBE/E/#/EN/Employment", "nbe", 10),
    EgyptEmployer("banque_misr", "Banque Misr", "bank", "banque-misr", "https://www.banquemisr.com/en/careers", "banque_misr", 11),
    EgyptEmployer("cib_egypt", "Commercial International Bank", "bank", "commercial-international-bank", "https://www.cibeg.com/en/careers", "cib_egypt", 12),
    EgyptEmployer("qnb_egypt", "QNB Egypt", "bank", "qnb-egypt", "https://www.qnb.com/sites/qnb/qnbegypt/page/en/encareers.html", "qnb_egypt", 13),
    EgyptEmployer("banque_du_caire", "Banque du Caire", "bank", "banque-du-caire", "https://www.bdc.com.eg/bdcwebsite/personal/careers.html", "banque_du_caire", 14),
    EgyptEmployer("vodafone_egypt", "Vodafone Egypt", "telecom", "vodafone-egypt", "https://opportunities.vodafone.com/search/", "vodafone_egypt", 15),
    EgyptEmployer("orange_egypt", "Orange Egypt", "telecom", "orange-egypt", "https://orange.jobs/gb/en/search-results", "orange_egypt", 16),
    EgyptEmployer("telecom_egypt", "Telecom Egypt", "telecom", "telecom-egypt", "https://te.eg/wps/portal/te/Personal/Careers", "telecom_egypt", 17),
    EgyptEmployer("valeo_egypt", "Valeo Egypt", "digital", "valeo", "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs", "valeo_egypt", 30),
    EgyptEmployer("ibm_egypt", "IBM Egypt", "digital", "ibm", "https://www.ibm.com/careers/search", "ibm_egypt", 31),
    EgyptEmployer("siemens_egypt", "Siemens Egypt", "critical", "siemens", "https://jobs.siemens.com/en_US/externaljobs/SearchJobs", "siemens_egypt", 32),
)


def validate_employer_registry() -> None:
    keys: set[str] = set()
    for employer in EGYPT_EMPLOYERS:
        if employer.key in keys:
            raise ValueError(f"Duplicate Egypt employer key: {employer.key}")
        keys.add(employer.key)
        if not employer.linkedin_identifier.strip() or not employer.careers_url.startswith("https://"):
            raise ValueError(f"Employer {employer.key} lacks verified LinkedIn/careers identifiers")


def linkedin_employer_queries() -> list[tuple[str, str, int]]:
    """Return bounded query metadata, ordered by Egyptian business priority."""
    validate_employer_registry()
    return [(row.linkedin_query(), row.key, row.priority) for row in EGYPT_EMPLOYERS]
