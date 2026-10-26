"""Explicit verification of allowlisted public job pages; no arbitrary URL fetches."""

import re

import httpx

from .engine import canonical_job_url, closing_date, html_text, salary_from_text


async def verify_listing(job):
    url = canonical_job_url(job["url"])
    if not url:
        raise ValueError("Unsupported job URL")
    try:
        async with (
            httpx.AsyncClient(timeout=15, follow_redirects=False) as client,
            client.stream(
                "GET", url, headers={"User-Agent": "Flow-Career-Assistant/1.0"}
            ) as response,
        ):
            if response.status_code != 200:
                return {**job, "verification": "unavailable"}
            if "text/html" not in response.headers.get("content-type", ""):
                return {**job, "verification": "unavailable"}
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 1500000:
                    return {**job, "verification": "unavailable"}
                chunks.append(chunk)
        text = html_text(b"".join(chunks).decode("utf-8", "replace"))
    except httpx.HTTPError:
        return {**job, "verification": "unavailable"}
    # Do not mistake a sign-in page or related-jobs list for verified requirements.
    for boundary in ("Similar jobs", "وظائف مشابهة", "Related jobs"):
        text = text.split(boundary)[0]
    closed = bool(
        re.search(
            r"no longer accepting applications|job has expired|لم يعد يقبل|انتهى الإعلان",
            text,
            re.IGNORECASE,
        )
    )
    if closed:
        return {**job, "verification": "closed"}
    markers = re.search(
        r"Full job description|Job Description|Key Responsibilities|About the (?:job|role)|وصف الوظيفة",
        text,
        re.IGNORECASE,
    )
    if not markers or job["title"].casefold() not in text.casefold():
        return {**job, "verification": "unavailable"}
    description = text[markers.start() :][:24000]
    salary = salary_from_text(text)
    return {
        **job,
        "description": description,
        "verification": "page_checked",
        "deadline": closing_date(description),
        "salary": salary if salary["text"] else job["salary"],
    }
