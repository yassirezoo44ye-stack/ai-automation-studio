"""Evidence-first parsing and transparent matching, without remote model calls.
Unrecognised formats are reported, never filled with fabricated jobs.
"""

import base64
import hashlib
import re
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from .models import CareerProfile


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []
        self.hidden = 0
        self.anchor = None
        self.anchors = []
        self.anchor_start = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "br", "tr", "div", "li", "h1", "h2", "h3"):
            self.out.append("\n")
        if tag == "a":
            self.anchor = dict(attrs).get("href")
            self.anchor_start = len("".join(self.out))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.anchor:
            url = canonical_job_url(self.anchor)
            if url:
                end = len("".join(self.out))
                self.anchors.append((url, self.anchor_start, end))
            self.anchor = None
        if tag in ("p", "tr", "div", "li"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.out.append(data)


def html_text(html):
    parser = TextHTML()
    parser.feed(html)
    return "".join(parser.out)


def canonical_job_url(value: str) -> str | None:
    """Allow only direct job identifiers; strip tracking and private email tokens."""
    try:
        url = urlsplit(value.strip().rstrip(".,)"))
        if url.scheme != "https" or url.username or url.password or url.port:
            return None
        host = (url.hostname or "").lower()
        if host in {"linkedin.com", "www.linkedin.com", "ae.linkedin.com"}:
            match = re.search(r"/(?:comm/)?jobs/view/(?:[^/?]*-)?(\d{6,})/?$", url.path)
            if match:
                return "https://www.linkedin.com/jobs/view/" + match[1] + "/"
        if host in {"ae.indeed.com", "www.indeed.com", "indeed.com"}:
            key = parse_qs(url.query).get("jk", [""])[0]
            if re.fullmatch(r"[a-f0-9]{16}", key):
                return "https://ae.indeed.com/viewjob?jk=" + key
    except ValueError:
        pass
    return None


def salary_from_text(text):
    # Salary-period and commission information must survive normalization.
    line = next(
        (
            x.strip()
            for x in text.splitlines()
            if re.search(r"AED|درهم", x, re.IGNORECASE)
        ),
        "",
    )
    if not line:
        return {
            "text": None,
            "min": None,
            "max": None,
            "period": "unknown",
            "kind": "unknown",
        }
    normalized = line.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٬", "0123456789,"))
    nums = [
        float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", normalized)
    ]
    period = (
        "monthly" if re.search(r"month|شهري|الشهر", line, re.IGNORECASE) else "unknown"
    )
    if re.search(r"year|annual|سنوي|السنة", line, re.IGNORECASE):
        period = "annual"
    if re.search(r"hour|ساعة", line, re.IGNORECASE):
        period = "hourly"
    if re.search(r"day|اليوم|يومي", line, re.IGNORECASE):
        period = "daily"
    kind = (
        "estimated"
        if re.search(r"estimat|تقدير", line, re.IGNORECASE)
        else "listed_unverified"
    )
    if re.search(r"OTE|commission.only|عمول", line, re.IGNORECASE):
        kind = "commission_or_ote"
    low, high = (
        (nums[0], nums[1] if len(nums) > 1 else nums[0]) if nums else (None, None)
    )
    if re.search(r"up to|إلى|حتى", line, re.IGNORECASE):
        low = None
    elif re.search(r"from|من ", line, re.IGNORECASE):
        high = None
    return {"text": line[:300], "min": low, "max": high, "period": period, "kind": kind}


def closing_date(text):
    match = re.search(
        r"(?:no later than|closing date|deadline|آخر موعد)[^\n:]*?:?\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return (
                datetime.strptime(" ".join(match.groups()), "%d %B %Y")
                .date()
                .isoformat()
            )
        except ValueError:
            pass
    match = re.search(
        r"(?:deadline|closing date|آخر موعد)\s*:?\s*(20\d{2}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return date.fromisoformat(match[1]).isoformat()
        except ValueError:
            pass
    return None


def parse_alert(text: str, source="manual"):
    if re.search(r"<(?:html|table|div|p)[\s>]", text, re.IGNORECASE):
        parser = TextHTML()
        parser.feed(text)
        raw = "".join(parser.out)
        anchors = []
        for url, start, end in parser.anchors:
            title = raw[start:end].strip()
            if not title or re.fullmatch(
                r"view.*|apply.*|عرض.*|تقد.*", title, re.IGNORECASE
            ):
                continue
            if url not in {x[0] for x in anchors}:
                anchors.append((url, start, end))
        text = ""
        for i, (url, start, end) in enumerate(anchors):
            stop = anchors[i + 1][1] if i + 1 < len(anchors) else len(raw)
            lines = [x.strip() for x in raw[start:stop].splitlines() if x.strip()]
            text += "\n\n" + "\n".join(lines) + "\n" + url
    text = text.replace("\r", "").replace("\u034f", "")
    results, seen, end = [], set(), 0
    for match in re.finditer(r"https://[^\s<>\"]+", text):
        url = canonical_job_url(match[0])
        if not url:
            continue
        previous = text[end : match.start()]
        end = match.end()
        if url in seen:
            continue
        seen.add(url)
        # Standard LinkedIn/Indeed plain MIME bodies: one job paragraph before URL.
        blocks = re.split(r"\n\s*\n|\n-{3,}\n", previous)
        block = next(
            (
                b
                for b in reversed(blocks)
                if len(b.strip()) > 15
                and not b.strip().startswith(("عرض الوظيفة", "View job"))
            ),
            "",
        )
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        lines = [
            x for x in lines if not x.startswith(("عرض الوظيفة", "View job", "http"))
        ]
        if not lines or re.search(
            r"unsubscribe|See matching results|إلغاء الاشتراك", lines[0], re.IGNORECASE
        ):
            continue
        title = lines[0][:300]
        company_line = lines[1] if len(lines) > 1 else ""
        company, _, location = company_line.partition(" - ")
        if (
            not location
            and len(lines) > 2
            and not re.search(r"AED|درهم|apply|تقديم", lines[2], re.IGNORECASE)
        ):
            location = lines[2]
        results.append(
            {
                "key": hashlib.sha256(url.encode()).hexdigest(),
                "url": url,
                "title": title,
                "company": company[:200],
                "location": location[:200],
                "description": block.strip()[:16000],
                "source": "linkedin" if "linkedin.com" in url else "indeed",
                "source_requested": source,
                "verification": "email_only",
                "deadline": closing_date(block),
                "salary": salary_from_text("\n".join(lines[2:])),
            }
        )
    return results


def mime_text(payload):
    """Prefer plain MIME recursively; never download attachments or inline images."""
    plain, html = [], []

    def visit(part):
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") in ("text/plain", "text/html"):
            try:
                decoded = base64.urlsafe_b64decode(
                    data + "=" * (-len(data) % 4)
                ).decode("utf-8", "replace")
                (plain if part["mimeType"] == "text/plain" else html).append(decoded)
            except (ValueError, TypeError):
                pass
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    return "\n".join(plain) if plain else "\n".join(html)


def assess(job, profile: CareerProfile, today=None):
    today = today or date.today()
    text = (job.get("title", "") + "\n" + job.get("description", "")).casefold()
    strengths, gaps, checks = [], [], []
    score = 0
    for name, values, weight in (
        ("roles", profile.roles, 30),
        ("skills", profile.skills, 25),
        ("sectors", profile.sectors, 25),
        ("cities", profile.cities, 10),
    ):
        matches = [v for v in values if v.strip() and v.casefold().strip() in text]
        if matches:
            score += weight
            strengths.append({"kind": name, "evidence": matches[:8]})
    deadline = job.get("deadline")
    expired = (
        bool(deadline and date.fromisoformat(deadline) < today)
        or job.get("verification") == "closed"
    )
    required = re.findall(
        r"[^\n.!?]*(?:required|mandatory|must|يشترط|إلزام)[^\n.!?]*", text
    )
    known_languages = {x.casefold().strip() for x in profile.languages}
    for line in required[:20]:
        if re.search(r"not (?:required|mandatory)|غير (?:مطلوب|إلزامي)", line):
            continue
        if re.search(r"driv|قيادة", line):
            if profile.uae_driving_license is False:
                gaps.append("UAE driving licence required / رخصة قيادة مطلوبة")
            elif profile.uae_driving_license is None:
                checks.append("Confirm UAE driving licence / تحقق من رخصة القيادة")
        languages = [
            language
            for language in (
                "hindi",
                "malayalam",
                "tamil",
                "english",
                "arabic",
                "russian",
            )
            if language in line
            and not re.search(
                language + r"\s+(?:is\s+)?(?:an?\s+)?(?:advantage|preferred)", line
            )
        ]
        choice = re.search(
            r"(?:at least )?(two|three|2|3|one|1) (?:languages|of)", line
        )
        if choice:
            needed = {"one": 1, "two": 2, "three": 3}.get(
                choice[1], int(choice[1]) if choice[1].isdigit() else 1
            )
            if len(set(languages) & known_languages) < needed:
                checks.append(
                    f"Confirm at least {needed} languages from: " + ", ".join(languages)
                )
        else:
            for language in languages:
                if language not in known_languages:
                    checks.append("Required language to confirm: " + language)
    years = re.search(
        r"(?:minimum|at least|experience[: ]*)\s*(\d+)\s*(?:[–-]\s*\d+)?\+?\s*years",
        text,
    )
    if (
        years
        and profile.experience_years is not None
        and profile.experience_years < int(years[1])
    ):
        gaps.append("Experience below stated minimum / الخبرة أقل من الحد المذكور")
    salary = job.get("salary", {})
    salary_ok = (
        salary.get("period") == "monthly" and salary.get("kind") == "listed_unverified"
    )
    if (
        salary_ok
        and salary.get("min") is not None
        and profile.minimum_monthly_aed is not None
    ):
        if salary["min"] >= profile.minimum_monthly_aed:
            score += 10
            strengths.append({"kind": "salary", "evidence": [str(salary["min"])]})
        elif (
            salary.get("max") is not None
            and salary["max"] < profile.minimum_monthly_aed
        ):
            gaps.append("Listed salary below target / الراتب أقل من المطلوب")
    if job.get("verification") == "email_only":
        checks.append("Full requirements unverified / الشروط الكاملة غير متحققة")
    if expired:
        gaps.append("Application deadline passed or listing closed / انتهى الإعلان")
    score = max(0, score - 20 * len(gaps)) if not expired else 0
    return {
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "checks": list(dict.fromkeys(checks)),
        "expired": expired,
        "priority": "expired"
        if expired
        else "review"
        if gaps or checks
        else "consider",
        "next_step": "Check reopening / تحقق من إعادة الفتح"
        if expired
        else "Review requirements, then apply / راجع الشروط ثم قدّم",
        "method": "rule_based_evidence_match",
        "acceptance_probability": None,
    }


def draft_application(job, profile):
    # Only user supplied statements are included; no embellished achievements.
    return (
        f"Subject: Application — {job['title']}\n\nDear Hiring Team,\n\n"
        f"I would like to apply for the {job['title']} position.\n\n"
        f"{profile.summary.strip()}\n\n"
        "I would welcome the opportunity to discuss how my experience relates to your requirements.\n"
        "[Attach your CV before sending.]\n\nKind regards,\n[Your name]"
    )
