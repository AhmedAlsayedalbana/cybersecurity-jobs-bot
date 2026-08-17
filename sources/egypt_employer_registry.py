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
    # ── Banking ─────────────────────────────────────────────────────────────
    EgyptEmployer("nbe", "National Bank of Egypt", "bank", "national-bank-of-egypt", "https://www.nbe.com.eg/NBE/E/#/EN/Employment", "nbe", 10),
    EgyptEmployer("banque_misr", "Banque Misr", "bank", "banque-misr", "https://www.banquemisr.com/en/careers", "banque_misr", 11),
    EgyptEmployer("cib_egypt", "Commercial International Bank", "bank", "commercial-international-bank-cib", "https://www.cibeg.com/en/careers", "cib_egypt", 12),
    EgyptEmployer("qnb_egypt", "QNB Egypt", "bank", "qnb-egypt", "https://www.qnb.com/sites/qnb/qnbegypt/page/en/encareers.html", "qnb_egypt", 13),
    EgyptEmployer("banque_du_caire", "Banque du Caire", "bank", "banque-du-caire", "https://www.bdc.com.eg/bdcwebsite/personal/careers.html", "banque_du_caire", 14),
    EgyptEmployer("aaib", "Arab African International Bank", "bank", "arab-african-international-bank-aaib", "https://aaib.com.eg/en/careers", "aaib", 20),
    EgyptEmployer("credit_agricole_egypt", "Crédit Agricole Egypt", "bank", "credit-agricicole-egypt", "https://www.ca-egypt.com/en/careers", "credit_agricole_egypt", 21),
    EgyptEmployer("hsbc_egypt", "HSBC Egypt", "bank", "hsbc-egypt", "https://www.hsbc.com/careers", "hsbc_egypt", 22),
    EgyptEmployer("adib_egypt", "Abu Dhabi Islamic Bank Egypt", "bank", "abu-dhabi-islamic-bank-egypt", "https://www.adib.com.eg/careers", "adib_egypt", 23),
    EgyptEmployer("fabmisr", "FABMISR", "bank", "fabmisr", "https://www.fabmisr.com.eg/careers", "fabmisr", 24),
    EgyptEmployer("hdb", "Housing and Development Bank", "bank", "housing-and-development-bank", "https://www.hdb-egypt.com/careers", "hdb", 25),
    EgyptEmployer("emirates_nbd_egypt", "Emirates NBD Egypt", "bank", "emirates-nbd-egypt", "https://www.emiratesnbd.com/egypt/careers", "emirates_nbd_egypt", 26),
    EgyptEmployer("mashreq_egypt", "Mashreq Egypt", "bank", "mashreq-egypt", "https://www.mashreq.com/egypt/careers", "mashreq_egypt", 27),
    EgyptEmployer("al_baraka_bank", "Al Baraka Bank", "bank", "al-baraka-bank", "https://www.albarakabank.com.eg/careers", "al_baraka_bank", 28),
    EgyptEmployer("bank_abc", "Bank ABC", "bank", "bank-abc", "https://www.bankabc.com.eg/careers", "bank_abc", 29),
    EgyptEmployer("saib", "SAIB", "bank", "saib", "https://www.saib.com.eg/careers", "saib", 30),
    EgyptEmployer("bank_nxt", "Bank NXT", "bank", "bank-nxt", "https://banknxt.com/careers", "bank_nxt", 31),
    # ── Telecom / Digital ───────────────────────────────────────────────────
    EgyptEmployer("vodafone_egypt", "Vodafone Egypt", "telecom", "vodafone-egypt", "https://opportunities.vodafone.com/search/", "vodafone_egypt", 15),
    EgyptEmployer("orange_egypt", "Orange Egypt", "telecom", "orange-egypt", "https://orange.jobs/gb/en/search-results", "orange_egypt", 16),
    EgyptEmployer("telecom_egypt", "Telecom Egypt", "telecom", "telecom-egypt", "https://te.eg/wps/portal/te/Personal/Careers", "telecom_egypt", 17),
    EgyptEmployer("raya", "Raya", "digital", "raya", "https://www.raya.com.eg/careers", "raya", 20),
    EgyptEmployer("vois", "VOIS (Vodafone Intelligent Solutions)", "digital", "vois", "https://vois.com.eg/careers", "vois", 21),
    EgyptEmployer("etisalat_egypt", "e& Egypt", "telecom", "etisalat-egypt", "https://careers.etisalat.com.eg", "etisalat_egypt", 22),
    # ── IT / Software / Cloud ───────────────────────────────────────────────
    EgyptEmployer("itida", "ITIDA", "it", "itida", "https://www.itida.gov.eg/careers", "itida", 36),
    EgyptEmployer("smart_village", "Smart Village", "it", "smart-village-egypt", "https://www.smart-village.com/careers", "smart_village", 37),
    # ── Critical / Engineering / Manufacturing ──────────────────────────────
    EgyptEmployer("valeo_egypt", "Valeo Egypt", "digital", "valeo", "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs", "valeo_egypt", 30),
    EgyptEmployer("ibm_egypt", "IBM Egypt", "digital", "ibm", "https://www.ibm.com/careers/search", "ibm_egypt", 31),
    EgyptEmployer("siemens_egypt", "Siemens Egypt", "critical", "siemens", "https://jobs.siemens.com/en_US/externaljobs/SearchJobs", "siemens_egypt", 32),
    EgyptEmployer("orascom_construction", "Orascom Construction", "engineering", "orascom-construction", "https://www.orascom.com/careers", "orascom_construction", 38),
    EgyptEmployer("elsewedy_electric", "Elsewedy Electric", "engineering", "elsewedy-electric", "https://www.elsewedy.com/careers", "elsewedy_electric", 39),
    # ── Cybersecurity ────────────────────────────────────────────────────────
    EgyptEmployer("cybershield", "CyberShield", "cybersecurity", "cybershield-egypt", "https://www.cybershield.com.eg/careers", "cybershield", 40),
    EgyptEmployer("eset_egypt", "ESET Egypt", "cybersecurity", "eset-egypt", "https://www.eset.com.eg/careers", "eset_egypt", 41),
    # ── Consulting (Big Four) ───────────────────────────────────────────────
    EgyptEmployer("pwc_egypt", "PwC Egypt", "consulting", "pwc-egypt", "https://www.pwc.com.eg/careers", "pwc_egypt", 42),
    EgyptEmployer("deloitte_egypt", "Deloitte Egypt", "consulting", "deloitte-egypt", "https://www2.deloitte.com/eg/careers", "deloitte_egypt", 43),
    EgyptEmployer("ey_egypt", "EY Egypt", "consulting", "ey-egypt", "https://www.ey.com/eg/careers", "ey_egypt", 44),
    EgyptEmployer("kpmg_egypt", "KPMG Egypt", "consulting", "kpmg-egypt", "https://www.kpmg.com.eg/careers", "kpmg_egypt", 45),
    # ── Pharma / Healthcare ─────────────────────────────────────────────────
    EgyptEmployer("pharco", "Pharco", "pharma", "pharco", "https://www.pharco.com/careers", "pharco", 46),
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
