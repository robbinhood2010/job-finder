"""Local helper for hossam-linkedin-jobs.html.

Serves the page on http://127.0.0.1:8765 and fetches job listings from
LinkedIn's public (signed-out) jobs pages, so the page can show them.
Only the Python standard library is used.

    python job_finder.py          start the helper and open the page
    python job_finder.py --test   fetch one search and print the result
"""
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8765
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "hossam-linkedin-jobs.html")
CACHE = os.path.join(HERE, "jobs-cache.json")

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SEARCH_PARAMS = {"keywords", "geoId", "f_TPR", "f_E", "start", "sortBy"}
MIN_GAP = 0.7  # seconds between requests to LinkedIn, to stay polite

_lock = threading.Lock()
_last = [0.0]
_details = {}


def fetch(url):
    """GET a LinkedIn URL, spacing requests out and retrying when rate-limited."""
    for attempt in range(4):
        with _lock:
            wait = _last[0] + MIN_GAP - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 400 or e.code == 404:
                return ""  # LinkedIn answers 400 past the last page
            if e.code == 429 and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    return ""


def text(fragment):
    """Strip tags, decode entities and collapse whitespace."""
    if fragment is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def first(pattern, s, flags=re.S):
    m = re.search(pattern, s, flags)
    return m.group(1) if m else None


def parse_search(body):
    jobs = []
    for card in re.split(r"<li>", body)[1:]:
        job_id = first(r"jobPosting:(\d+)", card) or first(r"/jobs/view/[^\"?]*?-(\d+)\?", card)
        if not job_id:
            continue
        jobs.append({
            "id": job_id,
            "title": text(first(r'<h3 class="base-search-card__title">(.*?)</h3>', card)),
            "company": text(first(r'<h4 class="base-search-card__subtitle">(.*?)</h4>', card)),
            "companyUrl": html.unescape(first(r'<h4 class="base-search-card__subtitle">.*?href="([^"?]+)', card) or ""),
            "location": text(first(r'<span class="job-search-card__location">(.*?)</span>', card)),
            "date": first(r'<time class="job-search-card__listdate[^"]*" datetime="([^"]+)"', card) or "",
            "posted": text(first(r'<time class="job-search-card__listdate[^"]*"[^>]*>(.*?)</time>', card)),
            "salary": text(first(r'class="job-search-card__salary-info"[^>]*>(.*?)</span>', card)),
            "benefit": text(first(r'class="job-posting-benefits__text"[^>]*>(.*?)</span>', card)),
            "logo": html.unescape(first(r'<img[^>]+data-delayed-url="([^"]+)"', card) or ""),
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        })
    return jobs


def description_text(fragment):
    s = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    s = re.sub(r"(?i)</(p|div|ul|ol|h\d)>", "\n\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def parse_detail(body):
    criteria = {}
    for k, v in re.findall(r'description__job-criteria-subheader">(.*?)</h3>\s*'
                           r'<span class="description__job-criteria-text[^"]*">(.*?)</span>', body, re.S):
        criteria[text(k)] = text(v)
    desc = first(r'<div class="show-more-less-html__markup[^"]*">(.*?)</div>\s*<button', body) \
        or first(r'<div class="show-more-less-html__markup[^"]*">(.*?)</div>', body) or ""
    apply_url = first(r'<code id="applyUrl"[^>]*><!--"(.*?)"--></code>', body)
    applicants = text(first(r'class="num-applicants__caption[^"]*"[^>]*>(.*?)<', body)) \
        or text(first(r'<figcaption class="num-applicants__caption">(.*?)</figcaption>', body))
    return {
        "criteria": criteria,
        "applicants": applicants,
        "posted": text(first(r'class="posted-time-ago__text[^"]*"[^>]*>(.*?)</span>', body)),
        "description": description_text(desc),
        "applyUrl": html.unescape(apply_url) if apply_url else "",
        "closed": "No longer accepting applications" in body,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if self.headers.get("Origin") == "null":  # the page opened straight from disk
            self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        try:
            if url.path in ("/", "/index.html", "/hossam-linkedin-jobs.html"):
                with open(PAGE, "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if url.path == "/api/ping":
                return self.send(200, {"ok": True})
            if url.path == "/api/search":
                q = {k: v for k, v in urllib.parse.parse_qsl(url.query) if k in SEARCH_PARAMS}
                return self.send(200, {"jobs": parse_search(fetch(SEARCH_URL + urllib.parse.urlencode(q)))})
            m = re.fullmatch(r"/api/job/(\d+)", url.path)
            if m:
                job_id = m.group(1)
                if job_id not in _details:
                    _details[job_id] = parse_detail(fetch(DETAIL_URL + job_id))
                return self.send(200, _details[job_id])
            if url.path == "/api/cache":
                if not os.path.exists(CACHE):
                    return self.send(200, {})
                with open(CACHE, "rb") as f:
                    return self.send(200, f.read())
            self.send(404, {"error": "not found"})
        except urllib.error.HTTPError as e:
            self.send(502, {"error": f"LinkedIn answered {e.code}" + (" (too many requests, try again in a few minutes)" if e.code == 429 else "")})
        except Exception as e:  # noqa: BLE001 - report any failure to the page
            self.send(502, {"error": str(e)})

    def do_POST(self):
        if self.path != "/api/cache":
            return self.send(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(size)
        json.loads(data)  # refuse anything that is not JSON
        with open(CACHE, "wb") as f:
            f.write(data)
        self.send(200, {"ok": True})


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--test" in sys.argv:
        q = {"keywords": '"Chargeback" OR "Disputes Manager"', "geoId": "104305776",
             "f_TPR": "r2592000", "sortBy": "DD"}
        a = parse_search(fetch(SEARCH_URL + urllib.parse.urlencode({**q, "start": 0})))
        b = parse_search(fetch(SEARCH_URL + urllib.parse.urlencode({**q, "start": len(a)})))
        print(len(a), "jobs on page 1,", len(b), "on page 2, overlap:",
              len({j["id"] for j in a} & {j["id"] for j in b}))
        print(json.dumps(a[0], indent=1, ensure_ascii=False))
        d = parse_detail(fetch(DETAIL_URL + a[0]["id"]))
        print(json.dumps({**d, "description": d["description"][:300]}, indent=1, ensure_ascii=False))
        return
    link = f"http://{HOST}:{PORT}/"
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:  # already running in another window
        print(f"Job Finder is already running. Opening {link}")
        webbrowser.open(link)
        return
    print(f"Job Finder is running at {link}")
    print("Keep this window open while you use the page. Close it to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(link)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
