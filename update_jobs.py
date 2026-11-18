"""Fetch matching LinkedIn jobs and build the website into the `site` folder.

Run every day by GitHub Actions (.github/workflows/update.yml).

    python3 update_jobs.py site [URL of the previous jobs.json]
"""
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

import job_finder as jf

# ---- what to search (matches the CV) ----
ROLES = [
    "Disputes Manager", "Chargeback Manager", "Card Disputes", "Chargeback",
    "Dispute Resolution", "Payment Disputes", "Disputes Management",
    "Card Operations Manager", "Cards Operations", "Payments Operations Manager",
    "Fraud and Disputes", "Acquiring Operations", "Merchant Risk", "Card Services Manager",
    "Card Reconciliation",
]
COUNTRIES = {  # LinkedIn geoIds
    "EG": "106155005", "AE": "104305776", "SA": "100459316", "QA": "104170880",
    "KW": "103239229", "BH": "100425729", "OM": "103619019",
}
LEVELS = "4,5"            # Mid-Senior, Director
POSTED = "r2592000"       # last month
PAGES = int(os.environ.get("PAGES", "3"))   # 10 jobs per page
jf.MIN_GAP = float(os.environ.get("MIN_GAP", "1.5"))

# Same scoring as the page: only good matches get their full details fetched
WEIGHTS = [
    (r"chargeback", 6), (r"disput", 6), (r"arbitration", 4), (r"visa|mastercard|card scheme", 3),
    (r"\bcards?\b", 3), (r"payment", 3), (r"fraud", 3), (r"acquir", 3), (r"merchant", 2),
    (r"reconcil", 2), (r"complaint", 3), (r"issuing", 2), (r"settlement|clearing", 2),
    (r"atm|transaction|acceptance", 1), (r"operations?", 1), (r"bank", 1),
    (r"risk|compliance|aml|legal|counsel", 1),
    (r"manager|head|lead|senior|\bsr\b|avp|\bvp\b|director|supervisor", 1),
    (r"intern|trainee|junior", -3),
]


def score(title):
    return sum(w for pattern, w in WEIGHTS if re.search(pattern, title, re.I))


def previous_data(url):
    if not url:
        return {}
    try:
        req = urllib.request.Request(url + "?t=" + str(int(time.time())), headers={"User-Agent": jf.UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:  # first run, or the site is not live yet
        print("No previous jobs:", e)
        return {}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "site"
    old = previous_data(sys.argv[2] if len(sys.argv) > 2 else "")
    old_ids = {j["id"] for j in old.get("jobs", [])}
    old_details = old.get("details", {})

    chunks = [" OR ".join(f'"{r}"' for r in ROLES[i:i + 5]) for i in range(0, len(ROLES), 5)]
    found, failed = {}, 0
    for code, geo in COUNTRIES.items():
        for keywords in chunks:
            for page in range(PAGES):
                q = {"keywords": keywords, "geoId": geo, "f_TPR": POSTED, "f_E": LEVELS,
                     "sortBy": "DD", "start": page * 10}
                try:
                    jobs = jf.parse_search(jf.fetch(jf.SEARCH_URL + urllib.parse.urlencode(q)))
                except Exception as e:
                    print(f"  {code} search failed: {e}")
                    failed += 1
                    break
                for j in jobs:
                    if j["id"] not in found:
                        found[j["id"]] = {**j, "country": code, "isNew": bool(old_ids) and j["id"] not in old_ids}
                if len(jobs) < 10:
                    break
        print(f"{code}: {sum(1 for j in found.values() if j['country'] == code)} jobs")

    if not found:
        sys.exit("LinkedIn returned no jobs, keeping yesterday's page.")

    details = {}
    for j in found.values():
        if score(j["title"]) < 3:
            continue
        if j["id"] in old_details and not old_details[j["id"]].get("error"):
            details[j["id"]] = old_details[j["id"]]
            continue
        try:
            details[j["id"]] = jf.parse_detail(jf.fetch(jf.DETAIL_URL + j["id"]))
        except Exception as e:
            print(f"  details for {j['id']} failed: {e}")

    os.makedirs(out, exist_ok=True)
    for f in ("index.html", "icon.png"):
        shutil.copy(f, os.path.join(out, f))
    data = {"updated": int(time.time() * 1000), "time": POSTED, "failed": failed,
            "jobs": list(found.values()), "details": details}
    with open(os.path.join(out, "jobs.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"Done: {len(found)} jobs, {len(details)} with full details, {failed} failed searches.")


if __name__ == "__main__":
    main()
