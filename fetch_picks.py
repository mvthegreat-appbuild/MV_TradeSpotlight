import re, json, sys
from urllib.parse import urlparse, parse_qs, quote_plus
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests
from bs4 import BeautifulSoup

DAYS = 10
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
FEEDS = [
    "https://www.bing.com/news/search?q=%22Trade+Spotlight%22+moneycontrol&format=rss&cc=IN&setlang=en-IN",
    "https://www.bing.com/news/search?q=%22Trade+Spotlight%22+how+should+you+trade&format=rss&cc=IN&setlang=en-IN",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/buzzingstocks.xml",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://news.google.com/rss/search?q=%22Trade+Spotlight%22+site:moneycontrol.com+when:10d&hl=en-IN&gl=IN&ceid=IN:en",
]
NUM = r"\d+(?:,\d+)*(?:\.\d+)?"
STOCK = re.compile(r"([^\n|]{2,70}?)\s*[|(]\s*CMP\s*:?\s*(?:Rs\.?|₹)?\s*(" + NUM + ")", re.I)
CALL = re.compile(r"Strategy\s*:?\s*(Buy|Sell)", re.I)
TGT = re.compile(r"Targets?(?:\s*price)?\s*:?\s*((?:Rs\.?\s*|₹\s*)?" + NUM + r"(?:\s*,\s*(?:Rs\.?\s*|₹\s*)?" + NUM + ")*)", re.I)
SL = re.compile(r"Stop[- ]?Loss\s*:?\s*(?:Rs\.?\s*|₹\s*)?(" + NUM + ")", re.I)
PER = re.compile(r"(\d+\s*(?:-|–|to)\s*\d+|\d+)\s*(trading days|trading sessions|days|sessions|weeks|months)|short[- ]term|medium[- ]term|long[- ]term|positional|swing", re.I)
ROLE = re.compile(r"Research|Analyst|Technical|Derivatives|Head|Manager|President|Founder|Strategist|Director|CMT", re.I)
FIRM = re.compile(r"\b(?:at|of|with)\s+([A-Z][A-Za-z&\.\- ]{2,50})\s*$")


def f(x):
    return float(x.replace(",", ""))


def parse_article(text, meta):
    experts = []
    pos = 0
    for line in text.split("\n"):
        s = line.strip()
        if 10 < len(s) < 150 and ROLE.search(s):
            m = FIRM.search(s)
            if m:
                experts.append((pos, m.group(1).strip()))
        pos += len(line) + 1
    ms = list(STOCK.finditer(text))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        seg = text[m.end():end]
        c, t, s = CALL.search(seg), TGT.search(seg), SL.search(seg)
        name = re.sub(r"^\s*\d+\.\s*", "", m.group(1)).strip(" :-")
        if not (c and t):
            print("  SKIPPED:", name[:40], "| call found:", bool(c), "| target found:", bool(t))
            continue
        p = PER.search(seg)
        firm = [e for e in experts if e[0] < m.start()]
        out.append({
            "stock": name,
            "cmp": f(m.group(2)),
            "call": c.group(1).upper(),
            "targets": [f(x) for x in re.findall(NUM, t.group(1))],
            "stop_loss": f(s.group(1)) if s else None,
            "period": re.sub(r"\s+", " ", p.group(0)).strip().capitalize() if p else None,
            "broker": firm[-1][1] if firm else None,
            "date": meta["date"], "link": meta["link"], "title": meta["title"],
        })
    return out


def resolve(url):
    if "bing.com" in url and "url=" in url:
        q = parse_qs(urlparse(url).query).get("url")
        return q[0] if q else None
    if "news.google.com" in url:
        try:
            from googlenewsdecoder import gnewsdecoder
            d = gnewsdecoder(url, interval=1)
            print("  google decode:", d.get("status"), str(d.get("decoded_url") or d.get("message"))[:90])
            return d.get("decoded_url")
        except Exception as e:
            print("  google decode error:", e)
            return None
    return url


def day_feeds():
    out = []
    for i in range(DAYS + 2):
        d = datetime.now(timezone.utc) - timedelta(days=i)
        q = '"Trade Spotlight" "on %s %d" moneycontrol' % (d.strftime("%B"), d.day)
        out.append("https://www.bing.com/news/search?q=" + quote_plus(q) + "&format=rss&cc=IN&setlang=en-IN")
    return out


def discover():
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    seen, items = set(), []
    for feed in FEEDS + day_feeds():
        try:
            r = requests.get(feed, headers=UA, timeout=30)
            print("feed", r.status_code, feed[:70])
            soup = BeautifulSoup(r.content, "xml")
        except Exception as e:
            print("feed error", e)
            continue
        for it in soup.find_all("item"):
            title = it.title.get_text(strip=True) if it.title else ""
            if "trade spotlight" not in title.lower():
                continue
            try:
                dt = parsedate_to_datetime(it.pubDate.get_text(strip=True)).astimezone(timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)
            key = re.sub(r"\W+", "", title.lower()) + dt.strftime("%Y%m%d")
            if dt < cutoff or key in seen:
                continue
            seen.add(key)
            items.append({"title": title, "link": it.link.get_text(strip=True), "date": dt.strftime("%Y-%m-%d")})
    return items


def main():
    items = discover()
    print("articles found:", len(items))
    picks = []
    rows = []
    done = set()
    for it in items:
        url = resolve(it["link"])
        if url and url in done:
            continue
        if url:
            done.add(url)
        if not url or "moneycontrol.com" not in url:
            print("skip (no real moneycontrol link):", it["title"][:50])
            rows.append("%s | NO LINK (%s) | %s" % (it["date"], urlparse(url or it["link"]).netloc, it["title"][30:60]))
            continue
        try:
            r = requests.get(url, headers=UA, timeout=30)
            print(r.status_code, url[:90])
            if r.status_code != 200:
                continue
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
        except Exception as e:
            print("  fetch error", e)
            continue
        got = parse_article(text, {**it, "link": url})
        print("  picks:", len(got), "| stock headers:", len(STOCK.findall(text)), "| Strategy lines:", len(CALL.findall(text)), "| chars:", len(text))
        picks += got
        rows.append("%s | picks %d | headers %d | strategy %d | %s" % (it["date"], len(got), len(STOCK.findall(text)), len(CALL.findall(text)), it["title"][30:60]))
    print("=== SUMMARY ===")
    for row in sorted(rows):
        print(row)
    best = {}
    for p in sorted(picks, key=lambda x: x["date"], reverse=True):
        best.setdefault((p["stock"].lower(), p["call"]), p)
    final = sorted(best.values(), key=lambda x: x["date"], reverse=True)
    if not final:
        print("NO PICKS FOUND - keeping old picks.json")
        sys.exit(1)
    with open("picks.json", "w", encoding="utf-8") as fh:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "days": DAYS,
                   "articles": len(items), "picks": final}, fh, ensure_ascii=False, indent=1)
    print("saved", len(final), "picks")


if __name__ == "__main__":
    main()
