"""
generate_email_templ.py
Input:  CSV at CSV_PATH (hardcoded below)
Output: 1. List of recipient email addresses
        2. Per-recipient email content, where the context variable
           is the list of other clinicians who submitted patients
           with the same gene (Name, Institution, Email).

Usage: python generate_email_templ.py
"""

import csv
import json
import os
import requests
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# ── Configuration ─────────────────────────────────────────────────────────────

CSV_PATH = os.path.join(os.path.dirname(__file__), "redcap-data.csv")

# How recent a submission must be (in minutes) to be treated as the "newest submitter".
# Default is 1440 (24 h) because Vercel runs in UTC while REDCap timestamps are in the
# project's local timezone – a small window would always reject valid submissions.
RECENCY_WINDOW_MINUTES = int(os.environ.get("RECENCY_WINDOW_MINUTES", "1440"))

# ── REDCap API ────────────────────────────────────────────────────────────────

REDCAP_API_URL   = "https://redcap.tch.harvard.edu/redcap_edc/api/"
REDCAP_API_TOKEN = "CDDA604E9FD4A64F81892DA3F17D930C"       # replace with your project API token
REDCAP_INSTRUMENT = "email"      # redcap_repeat_instrument value
# The REDCap record-ID field name (first field in your project's data dictionary)
REDCAP_RECORD_ID_FIELD = "record_id"

# Mirrors mapping_submitter_institution_v2 from DBSMM_Matcher.R
INSTITUTION_MAP = {
    "1":    "Aarhus University Hospital of Aarhus",
    "2":    "Ankara Yıldırım Beyazıt University Medical Faculty Department of Neurology",
    "3":    "Ann & Robert H. Lurie Children's Hospital of Chicago",
    "4":    "Bambino Gesù Children's Hospital",
    "5":    "Boston Children's Hospital",
    "6":    "Brasilia Children's Hospital Jose Alencar",
    "7":    "Cincinnati Children's Hospital Medical Center",
    "8":    "Children's Health Ireland",
    "9":    "Children's Healthcare of Atlanta/Emory University",
    "10":   "Children's Hospital of Philadelphia",
    "11":   "Children's National Hospital",
    "12":   "CHU de Bordeaux",
    "13":   "CHU Montpellier",
    "14":   "Evelina London Children's Hospital",
    "15":   "Hôpital Fondation Rothschild",
    "16":   "Hospital Italiano Buenos Aires",
    "17":   "Hospital Jose Maria Ramos Mejia",
    "18":   "Hospital Rey Juan Carlos",
    "19":   "Hospital Sant Joan de Deu",
    "20":   "Institute of Neuroscience Kolkata",
    "21":   "ISNB, Neuropsichiatria età pediatrica, Bologna, Italy",
    "22":   "National Institute of Mental Health and Neurosciences (NIMHANS)",
    "23":   "Neurological Institute of Thailand",
    "24":   "Queen Silvia's Children's Hospital Paediatric neurology department",
    "25":   "Royal Children's Hospital Melbourne",
    "26":   "San Borja Arriaran Hospital",
    "27":   "SickKids Hospital, Toronto",
    "28":   "Southmead Hospital, North Bristol NHS Trust",
    "29":   "SRCC Narayana Healthcare Children's Hospital",
    "30":   "Sri Venkateswara Institute of Medical Sciences",
    "31":   "Starship Child Health",
    "32":   "Tanta University - Faculty of Medicine",
    "33":   "Texas Children's/Baylor",
    "34":   "The Children's Hospital at Westmead, Sydney",
    "35":   "UMass Memorial Health",
    "36":   "Unicamp - Universidade Estadual de Campinas",
    "37":   "Uniklinik Köln",
    "38":   "Universiti Malaya, Malaysia",
    "39":   "University Hospitals Bristol NHS Foundation Trust",
    "40":   "UT Southwestern",
    "41":   "Ain Shams University",
    "42":   "AZ Delta",
    "43":   "Maple Valley Movement Neurology",
    "44":   "University of California, San Francisco",
    "45":   "Gillette Children's Specialty Healthcare",
    "46":   "Instituto Roosevelt - Colombia",
    "47":   "Stanford University School of Medicine",
    "48":   "Universidade Federal de São Paulo",
    "49":   "UPMC Children's Hospital of Pittsburgh",
    "1000": "New Institution",
}

# Gene names to exclude – mirrors the R script exclusion list
INVALID_GENES = {
    "",
    "still waiting results",
    "Tourette's ",
    "18-p Deletion Syndrome. Karyotype análisis: deletion of the short arm of chromosome 18 . 46,XX, del (18) (p11.2)",
    "6466",
    "PLA2G6 (c.2239C>T (p.Arg747Trp)) (HGNC:9039)",
    "MeCP2",
    "PKAN",
    "18-p deletion ",
    "22q11 duplication ",
}

# Per-record gene corrections keyed by studyid – mirrors R script
STUDYID_GENE_CORRECTIONS = {
    "828454": "PANK2",
    "828455": "PANK2",
    "828456": "PANK2",
    "828464": "MECP2",
    "828500": "18-p deletion",
    "828502": "18-p deletion",
    "21":     "PLA2G6",
}

# REDCap factor mappings for patient / DBS fields
SEX_MAP = {
    "1": "Male",
    "2": "Female",
}

DBS_TARGET_MAP = {
    "1": "GPi",
    "2": "STN",
    "3": "Thalamus",
    "4": "Other",
}

IMPLANTATION_TIME_MAP = {
    "0": "Not implanted yet",
    "1": "< 1 year",
    "2": "1–3 years",
    "3": "3–5 years",
    "4": "> 5 years",
}

DBS_RESPONSE_MAP = {
    "":  "",
    "0": "No response / Worsened",
    "1": "Mild response",
    "2": "Partial response",
    "3": "Good / Excellent response",
}

# ── Email templates ───────────────────────────────────────────────────────────

# Sent to the newest submitter listing all existing matches for their gene.
SUBJECT_TO_NEW = "DBS MatchMaker – Your submission for {gene} has been matched"

TEMPLATE_TO_NEW = """\
Dear {recipient_name},

Thank you for your recent submission to the DBS MatchMaker Registry for the gene {gene}.

We found the following clinicians who have also submitted patients with {gene}. \
We encourage you to reach out to share experience and potentially collaborate:

{submitter_context}
If you have any questions or would like us to facilitate an introduction, \
please reply to this email.

Best regards,
The DBS MatchMaker Team
"""

# Sent to every existing submitter of that gene when a new submission arrives.
SUBJECT_TO_EXISTING = "DBS MatchMaker – New submission for {gene}"

TEMPLATE_TO_EXISTING = """\
Dear {recipient_name},

A new case has been submitted to the DBS MatchMaker Registry for the gene {gene}. \
The details of the new submission are below:

{submitter_context}
We encourage you to reach out to this colleague to share experience and \
potentially collaborate.

If you have any questions or would like us to facilitate an introduction, \
please reply to this email.

Best regards,
The DBS MatchMaker Team
"""

# Sent to the newest submitter when no other cases exist for their gene.
SUBJECT_NO_MATCH = "DBS MatchMaker – No current match for {gene}"

TEMPLATE_NO_MATCH = """\
Dear {recipient_name},

Thank you for your recent submission to the DBS MatchMaker Registry for the gene {gene}.

At this time, there are no other registered cases matching {gene} in our registry. \
We will notify you as soon as a matching submission is received.

If you have any questions, please reply to this email.

Best regards,
The DBS MatchMaker Team
"""


# ── Data loading and cleaning ──────────────────────────────────────────────────

def load_and_clean(csv_path: str) -> list[dict]:
    """
    Load CSV and apply all cleaning steps from DBSMM_Matcher.R:
      - Per-studyid gene name corrections
      - Exclude invalid/malformed gene names
      - Map submitter_institution_v2 numeric code → institution name
        (uses new_institution text when code is 1000)
      - Drop rows with no email address
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    cleaned = []
    for row in rows:
        studyid = row.get("studyid", "").strip()

        # Apply per-record gene corrections
        if studyid in STUDYID_GENE_CORRECTIONS:
            row["gene_name"] = STUDYID_GENE_CORRECTIONS[studyid]

        gene = row.get("gene_name", "").strip()
        if gene in INVALID_GENES and gene!="":
            continue

        # Resolve institution name from numeric code
        inst_code = row.get("submitter_institution_v2", "").strip()
        if inst_code == "1000":
            institution = row.get("new_institution", "").strip() or "New Institution"
        else:
            institution = INSTITUTION_MAP.get(inst_code, inst_code)

        name  = row.get("submitter_name", "").strip()
        email = row.get("submitter_email", "").strip()

        cleaned.append({
            "studyid":              studyid,
            "timestamp":            row.get("timestamp", "").strip(),
            "gene":                 gene,
            "Name":                 name,
            "Institution":          institution,
            "Email":                email,
            "age":                  row.get("patient_agey", "").strip(),
            "sex":                  row.get("patient_sex", "").strip(),
            "dbs_target":           row.get("dbs_target", "").strip(),
            "dbs_target_other":     row.get("dbs_target_other", "").strip(),
            "dbs_implantationtime": row.get("dbs_implantationtime", "").strip(),
            "dbs_response":         row.get("dbs_response", "").strip(),
        })

    return cleaned


def get_newest_submitter(records: list[dict], det_record_id: str | None = None) -> dict | None:
    """
    Return the record matching det_record_id (the REDCap DET 'record' param) when
    provided, bypassing the timestamp check.  Falls back to the highest-studyid
    record within the last RECENCY_WINDOW_MINUTES minutes when no id is given.
    """
    valid = [r for r in records if r["studyid"].isdigit()]
    if not valid:
        return None

    if det_record_id is not None:
        # DET told us exactly which record was just submitted – use it directly.
        matched = [r for r in valid if r["studyid"] == str(det_record_id)]
        if not matched:
            print(f"  ⚠  DET record id {det_record_id!r} not found in CSV – falling back to newest.")
        else:
            newest = matched[0]
            if newest["Email"] == "":
                print(f"  ⚠  Record {det_record_id} has no email – skipping.")
                return None
            if newest["gene"] == "":
                print(f"  ⚠  Record {det_record_id} has no gene – skipping.")
                return None
            return newest

    # No DET id supplied (or not found): fall back to max studyid + recency window.
    newest = max(valid, key=lambda r: int(r["studyid"]))
    if newest["Email"] == "":
        print(f"  ⚠  Newest record (studyid={newest['studyid']}) has no email – skipping.")
        return None
    if newest["gene"] == "":
        print(f"  ⚠  Newest record (studyid={newest['studyid']}) has no gene – skipping.")
        return None
    ts_raw = newest["timestamp"]
    if not ts_raw:
        print(f"  ⚠  Newest record (studyid={newest['studyid']}) has no timestamp – skipping.")
        return None

    # REDCap timestamps: 'YYYY-MM-DD HH:MM:SS'
    try:
        ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        print(f"  ⚠  Cannot parse timestamp '{ts_raw}' – skipping.")
        return None

    cutoff = datetime.now() - timedelta(minutes=RECENCY_WINDOW_MINUTES)
    if ts < cutoff:
        print(f"  ⚠  Newest record (studyid={newest['studyid']}, ts={ts_raw}) "
              f"is older than {RECENCY_WINDOW_MINUTES} min – no emails sent.")
        return None

    return newest


def build_gene_submitter_map(records: list[dict]) -> dict[str, list[dict]]:
    """
    For each gene, collect the deduplicated list of submitters
    (Name, Institution, Email, studyid), keyed by lower-cased email.
    When the same email appears more than once (multiple submissions),
    the highest studyid wins so we attach the email to the most recent record.
    """
    gene_map: dict[str, dict] = defaultdict(dict)
    for r in records:
        key = r["Email"].lower()
        existing = gene_map[r["gene"]].get(key)
        if existing is None or (r["studyid"].isdigit() and
                int(r["studyid"]) > int(existing["studyid"] or 0)):
            gene_map[r["gene"]][key] = {
                "studyid":     r["studyid"],
                "Name":        r["Name"],
                "Institution": r["Institution"],
                "Email":       r["Email"],
            }
    return {gene: list(submitters.values()) for gene, submitters in gene_map.items()}


# ── Email generation ───────────────────────────────────────────────────────────

def format_submitter_context(submitters: list[dict]) -> str:
    """
    Render a list of submitter dicts (Name, Institution, Email) as
    plain-text lines suitable for embedding in an email body.
    """
    lines = []
    for i, s in enumerate(submitters, start=1):
        lines.append(f"  {i}. {s['Name']}")
        lines.append(f"     Institution: {s['Institution']}")
        lines.append(f"     Email:       {s['Email']}")
        lines.append("")
    return "\n".join(lines)


def format_newest_context(newest: dict) -> str:
    """
    Render the full submitter + patient + DBS detail block for the newest
    submission.  Fields that are empty or whose raw value has no entry in
    the relevant mapping dict are omitted entirely.
    """
    def raw_line(label: str, value: str) -> str | None:
        """Include line only when value is non-empty."""
        return f"  {label}: {value}" if value.strip() else None

    def mapped_line(label: str, raw: str, mapping: dict) -> str | None:
        """Include line only when raw value exists in the mapping and
        the resolved label is non-empty."""
        resolved = mapping.get(raw)          # None if not in map
        return f"  {label}: {resolved}" if resolved else None

    submitter = [
        raw_line("Name",        newest["Name"]),
        raw_line("Institution", newest["Institution"]),
        raw_line("Email",       newest["Email"]),
    ]
    patient = [
        raw_line("Gene", newest["gene"]),
        raw_line("Age",  newest["age"]),
        mapped_line("Sex", newest["sex"], SEX_MAP),
    ]
    dbs = [
        mapped_line("Target",                  newest["dbs_target"],           DBS_TARGET_MAP),
        raw_line(   "Other Target (if any)",   newest["dbs_target_other"]),
        mapped_line("Time Since Implantation", newest["dbs_implantationtime"], IMPLANTATION_TIME_MAP),
        mapped_line("Response to DBS",         newest["dbs_response"],         DBS_RESPONSE_MAP),
    ]

    sections = []
    submitter = [l for l in submitter if l]
    patient   = [l for l in patient   if l]
    dbs       = [l for l in dbs       if l]

    if submitter:
        sections.append("SUBMITTER DETAILS\n" + "\n".join(submitter))
    if patient:
        sections.append("PATIENT INFORMATION\n" + "\n".join(patient))
    if dbs:
        sections.append("DBS INFORMATION\n" + "\n".join(dbs))

    return "\n\n".join(sections) + "\n"


def generate_email_for_newest(
    newest: dict,
    gene_submitter_map: dict[str, list[dict]],
):
    """
    Yield one (to_address, subject, body) to the newest submitter listing
    every other unique submitter for the same gene.
    Yields nothing if there are no existing matches.
    """
    gene = newest["gene"]
    submitters = gene_submitter_map.get(gene, [])
    others = [
        s for s in submitters
        if s["Email"].lower() != newest["Email"].lower()
    ]
    if not others:
        return
    subject = SUBJECT_TO_NEW.format(gene=gene)
    body = TEMPLATE_TO_NEW.format(
        recipient_name=newest["Name"],
        gene=gene,
        submitter_context=format_submitter_context(others),
    )
    yield newest["Email"], subject, body


def generate_emails_for_existing(
    newest: dict,
    gene_submitter_map: dict[str, list[dict]],
):
    """
    Yield one (studyid, to_address, subject, body) per unique existing submitter
    of the same gene, notifying them that a new case was submitted.
    The newest submitter is excluded as a recipient.
    studyid is the recipient's own REDCap record id so the email is stored
    under their record, not the newest submitter's.
    """
    gene = newest["gene"]
    submitters = gene_submitter_map.get(gene, [])
    new_context = format_newest_context(newest)
    seen: set[str] = set()
    for recipient in submitters:
        key = recipient["Email"].lower()
        if key == newest["Email"].lower() or key in seen:
            continue
        seen.add(key)
        subject = SUBJECT_TO_EXISTING.format(gene=gene)
        body = TEMPLATE_TO_EXISTING.format(
            recipient_name=recipient["Name"],
            gene=gene,
            submitter_context=new_context,
        )
        yield recipient["studyid"], recipient["Email"], subject, body


def generate_email_no_match(newest: dict):
    """
    Yield a single (to_address, subject, body) to the newest submitter
    informing them that no matching cases currently exist for their gene.
    """
    gene = newest["gene"]
    subject = SUBJECT_NO_MATCH.format(gene=gene)
    body = TEMPLATE_NO_MATCH.format(
        recipient_name=newest["Name"],
        gene=gene,
    )
    yield newest["Email"], subject, body


# ── REDCap import ─────────────────────────────────────────────────────────────

def push_emails_to_redcap(newest_studyid: str, emails: list[tuple[str, str, str, int]]):
    """
    Import email records into REDCap as repeating instances on the newest
    submitter's record.

    emails: list of (to_address, subject, body, instance_number)
      instance 1  = email to newest submitter
      instance 2+ = emails to existing/previous submitters
    """
    records = []
    for to_addr, subject, body, instance in emails:
        records.append({
            REDCAP_RECORD_ID_FIELD:    newest_studyid,
            "redcap_repeat_instrument": REDCAP_INSTRUMENT,
            "redcap_repeat_instance":   str(instance),
            "address":            to_addr,
            "subject":            subject,
            "content":              body,
            "email_complete":       "2",   # mark as complete
        })

    payload = {
        "token":             REDCAP_API_TOKEN,
        "content":           "record",
        "format":            "json",
        "type":              "flat",
        "overwriteBehavior": "normal",
        "data":              json.dumps(records),
        "returnContent":     "count",
        "returnFormat":      "json",
    }

    response = requests.post(REDCAP_API_URL, data=payload, timeout=30)
    if not response.ok:
        print(f"REDCap API error {response.status_code}: {response.text}")
        response.raise_for_status()
    result = response.json()
    print(f"REDCap import: {result} record(s) written for studyid={newest_studyid}.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main(det_record_id: str | None = None):
    if not os.path.isfile(CSV_PATH):
        raise FileNotFoundError(f"CSV not found: {CSV_PATH}")

    # ── Debug: print raw CSV row for the highest studyid ─────────────────────
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as fh:
        raw_rows = list(csv.DictReader(fh))
    numeric_rows = [r for r in raw_rows if r.get("studyid", "").strip().isdigit()]
    if numeric_rows:
        raw_newest = max(numeric_rows, key=lambda r: int(r["studyid"].strip()))
        print("DEBUG raw newest row:")
        for k, v in raw_newest.items():
            if v.strip():
                print(f"  {k}: {v!r}")
    # ─────────────────────────────────────────────────────────────────────────

    records = load_and_clean(CSV_PATH)
    gene_map = build_gene_submitter_map(records)

    newest = get_newest_submitter(records, det_record_id=det_record_id)
    if newest is None:
        print("No recent submission found. No emails generated.")
        return

    print(f"Newest submitter: {newest['Name']} ({newest['Email']}) "
          f"– gene: {newest['gene']} – studyid: {newest['studyid']}")

    email_to_new       = list(generate_email_for_newest(newest, gene_map))
    emails_to_existing = list(generate_emails_for_existing(newest, gene_map))

    # If no matches exist, send a single no-match notice to the newest submitter
    if not email_to_new and not emails_to_existing:
        print(f"No existing matches for gene '{newest['gene']}'. Sending no-match notice.")
        no_match_emails = list(generate_email_no_match(newest))
        for to_addr, subject, body in no_match_emails:
            print(f"\nTO:      {to_addr}")
            print(f"SUBJECT: {subject}")
            print("-" * 40)
            print(body)
        # Push no-match email to REDCap (instance 1)
        redcap_records = [(to_addr, subject, body, 1) for to_addr, subject, body in no_match_emails]
        push_emails_to_redcap(newest["studyid"], redcap_records)
        return

    all_emails = email_to_new + [(addr, subj, bod) for _, addr, subj, bod in emails_to_existing]

    # ── Output 1: unique recipient email addresses ────────────────────────────
    unique_addresses = sorted({addr for addr, _, _ in all_emails})
    print()
    print("=" * 60)
    print(f"RECIPIENT EMAIL ADDRESSES ({len(unique_addresses)} unique)")
    print("=" * 60)
    for addr in unique_addresses:
        print(addr)

    # ── Output 2: full email content ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"EMAIL CONTENT ({len(all_emails)} emails)")
    print("=" * 60)

    if email_to_new:
        print("\n── EMAIL 1: TO NEWEST SUBMITTER ──")
        for to_addr, subject, body in email_to_new:
            print(f"\nTO:      {to_addr}")
            print(f"SUBJECT: {subject}")
            print("-" * 40)
            print(body)
            print("=" * 60)

    if emails_to_existing:
        print(f"\n── EMAIL 2: TO EXISTING SUBMITTERS ({len(emails_to_existing)}) ──")
        for rec_studyid, to_addr, subject, body in emails_to_existing:
            print(f"\nTO:      {to_addr}")
            print(f"SUBJECT: {subject}")
            print("-" * 40)
            print(body)
            print("=" * 60)

    print(f"\nDone: {len(all_emails)} email(s) across {len(unique_addresses)} recipient(s).")

    # ── Push to REDCap ────────────────────────────────────────────────────────
    # Email to newest → stored under newest's own record (instance 1)
    redcap_records_new: list[tuple[str, str, str, int]] = []
    for i, (to_addr, subject, body) in enumerate(email_to_new, start=1):
        redcap_records_new.append((to_addr, subject, body, i))
    if redcap_records_new:
        push_emails_to_redcap(newest["studyid"], redcap_records_new)

    # Emails to existing submitters → each stored under their own record (instance 1)
    for rec_studyid, to_addr, subject, body in emails_to_existing:
        push_emails_to_redcap(rec_studyid, [(to_addr, subject, body, 1)])


if __name__ == "__main__":
    main()

