import email
from email.header import decode_header
import imaplib
import json
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def load_config(config_path="config.json"):
    """Loads configuration settings from a JSON file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _decode_mime_header(header_value):
    """Safely decodes an encoded MIME header into a Unicode string."""
    if not header_value:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            result.append(str(part))
    return "".join(result)


def _extract_email_contents(msg):
    """Extracts plain text and HTML contents from an email message."""
    plain_texts = []
    html_texts = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition", ""))
            if "attachment" in cdisp.lower():
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"
            decoded_str = payload.decode(charset, errors="ignore")

            if ctype == "text/plain":
                plain_texts.append(decoded_str)
            elif ctype == "text/html":
                html_texts.append(decoded_str)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded_str = payload.decode(charset, errors="ignore")
            if msg.get_content_type() == "text/html":
                html_texts.append(decoded_str)
            else:
                plain_texts.append(decoded_str)

    return "\n".join(plain_texts), "\n".join(html_texts)


def extract_version(text):
    """Extracts variable version numbers from text like:

    - 'Please find the download link for V-DPWR-EPR software (version v1.1.1.3).'
    - 'Please find the download link for V-DPWR-EPR software (version [v1.1.1.X])'
    - 'version [v1.1.1.25]'
    - 'version [1.1.1.3]'
    - 'v1.1.1.5'
    - 'v1.1.x.x'
    """
    if not text:
        return None

    patterns = [
        # Matches: (version v1.1.1.3), (version [v1.1.1.X]), (version 1.1.x.x)
        r"\(version\s*\[?\s*v?([0-9a-zA-Z._-]+)\]?\)",
        # Matches: version [v1.1.1.1], version [1.1.1.25], version (v1.1.1.X), version [v1.1.1.X]
        r"version\s*[\(\[]\s*v?([0-9a-zA-Z._-]+)[\)\]]",
        # Matches: version: v1.1.1.1 or version v1.1.1.1
        r"version\s*[:\s]\s*v?([0-9a-zA-Z]+(?:\.[0-9a-zA-Z_-]+)+)",
        # Matches standalone: [v1.1.1.2] or [1.1.1.2]
        r"\[v?([0-9a-zA-Z]+(?:\.[0-9a-zA-Z_-]+)+)\]",
        # Generic: v1.1.1.2 or v1.1.x.x
        r"\bv([0-9a-zA-Z]+(?:\.[0-9a-zA-Z_-]+)+)\b",
    ]

    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_links_from_content(plain_text, html_text, target_software="V-DPWR-EPR"):
    """Extracts and prioritizes download URLs from plain text and HTML content."""
    collected_urls = []

    # 1. Extract from HTML anchors if BeautifulSoup is available
    if html_text and BeautifulSoup:
        soup = BeautifulSoup(html_text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            anchor_text = a_tag.get_text().strip()
            parent_text = a_tag.find_parent().get_text() if a_tag.find_parent() else ""
            if href.startswith(("http://", "https://")):
                collected_urls.append((href, anchor_text, parent_text))

    # 2. Extract plain text URLs using regex
    combined_text = f"{plain_text}\n{html_text}"
    plain_urls = re.findall(r"https?://[^\s<>\"']+", combined_text)
    for u in plain_urls:
        u_clean = u.rstrip(".,;)>]")
        if not any(u_clean == existing[0] for existing in collected_urls):
            collected_urls.append((u_clean, "", ""))

    if not collected_urls:
        return []

    # Prioritization scoring:
    installer_exts = (".exe", ".msi", ".zip", ".pkg", ".dmg", ".deb")

    def score_url(item):
        url, anchor, parent = item
        score = 0
        url_lower = url.lower()
        anchor_lower = anchor.lower()
        parent_lower = parent.lower()

        # If anchor itself is a version string (e.g. <a href="...">v1.1.1.3</a>)
        if re.match(r"^v?[0-9a-zA-Z]+(?:\.[0-9a-zA-Z_-]+)+$", anchor, re.IGNORECASE):
            score += 200

        # If parent paragraph mentions download link or target software
        if target_software.lower() in parent_lower:
            score += 100
        if "download link" in parent_lower:
            score += 80

        for ext in installer_exts:
            if url_lower.split("?")[0].endswith(ext):
                score += 50
                break

        if target_software.lower() in url_lower or target_software.lower() in anchor_lower:
            score += 30

        if "download" in anchor_lower or "download" in url_lower:
            score += 20

        # Penalize unsubscribe or common footer links
        if any(bad in url_lower for bad in ["unsubscribe", "privacy", "terms", "help", "support"]):
            score -= 100

        return score

    sorted_urls = sorted(collected_urls, key=score_url, reverse=True)
    return [url for url, _, _ in sorted_urls if score_url((url, _, _)) > -50]


def extract_version_and_download_link(plain_text, html_text, target_software="V-DPWR-EPR"):
    """Specifically targets:

    'Please find the download link for V-DPWR-EPR software (version v1.1.1.3).'
    where the link is either the hyperlink on 'v1.1.1.3' itself:
        (version <a href="...">v1.1.1.3</a>)
    or immediately following the version:
        (version v1.1.1.3). https://...
        (version v1.1.1.3) <a href="...">Download</a>

    Returns:
        tuple: (download_url, version_string) or (None, None)
    """
    # 1. Check HTML anchors (like <a href="...">v1.1.1.3</a>)
    if html_text and BeautifulSoup:
        soup = BeautifulSoup(html_text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            anchor_text = a_tag.get_text().strip()
            if not href.startswith(("http://", "https://")):
                continue

            parent_text = a_tag.find_parent().get_text() if a_tag.find_parent() else ""
            combined_context = f"{anchor_text} {parent_text}"

            # Case A: The anchor text IS the version itself (e.g. <a href="...">v1.1.1.3</a>)
            if re.match(r"^v?[0-9a-zA-Z]+(?:\.[0-9a-zA-Z_-]+)+$", anchor_text, re.IGNORECASE):
                if (
                    target_software.lower() in combined_context.lower()
                    or "download link" in combined_context.lower()
                    or "version" in combined_context.lower()
                ):
                    v = extract_version(anchor_text) or anchor_text.lstrip("vV")
                    return href, v

            # Case B: The anchor is inside a block mentioning target software and version
            if target_software.lower() in combined_context.lower() and "version" in combined_context.lower():
                v = extract_version(combined_context)
                if v:
                    return href, v

    # 2. Check Plain Text: URL directly follows the version pattern
    # e.g.: (version v1.1.1.3). https://... or (version [v1.1.1.X]): https://...
    combined_plain = f"{plain_text}\n{html_text}"
    pt_match = re.search(
        r"\(version\s*\[?v?([0-9a-zA-Z._-]+)\]?\)[^a-zA-Z0-9\r\n]*(https?://[^\s<>\"']+)",
        combined_plain,
        re.IGNORECASE,
    )
    if pt_match:
        ver = pt_match.group(1).strip()
        url = pt_match.group(2).rstrip(".,;)>]").strip()
        return url, ver

    # 3. Fallback: General extraction
    ver = extract_version(combined_plain)
    links = extract_links_from_content(plain_text, html_text, target_software)
    if links:
        return links[0], ver

    return None, ver


def get_imap_since_date(days_back=2):
    """Returns date in IMAP SEARCH format (DD-Mon-YYYY) for N days back."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_back)
    return dt.strftime("%d-%b-%Y")


def get_latest_download_link(config_path="config.json"):
    """Fetches the latest email matching the software criteria and returns the download URL."""
    cfg = load_config(config_path)

    target_software = cfg.get("target_software", "V-DPWR-EPR")
    subject_keyword = cfg.get("subject_keyword", target_software)
    days_back = int(cfg.get("days_back", 2))
    test_download_url = cfg.get("test_download_url", "").strip()

    print(f"[mail.py] Target Software: {target_software}")
    print(f"[mail.py] Date filter: past {days_back} day(s)")

    try:
        print(f"[mail.py] Connecting to IMAP server ({cfg.get('imap_server')})...")
        mail = imaplib.IMAP4_SSL(cfg["imap_server"])
        mail.login(cfg["email_user"], cfg["email_pass"])
    except imaplib.IMAP4.error as e:
        err_msg = str(e)
        print(f"\n[mail.py] [ERROR] IMAP Authentication Failed: {err_msg}")
        if "AUTHENTICATE failed" in err_msg or "not supported" in err_msg:
            print("[mail.py] ------------------------------------------------------------------")
            print("[mail.py] Office 365 / Outlook Notice:")
            print("[mail.py] Microsoft disables standard password login for IMAP by default.")
            print("[mail.py] To use Office 365 IMAP, you must create an App Password under:")
            print("[mail.py] https://mysignins.microsoft.com/security-info -> Add sign-in method -> App Password")
            print("[mail.py] and paste that password into 'email_pass' in config.json.")
            print("[mail.py] ------------------------------------------------------------------")
        if test_download_url:
            print(f"[mail.py] Using fallback test_download_url from config: {test_download_url}")
            return test_download_url
        return None
    except Exception as e:
        print(f"[mail.py] [ERROR] Connection error: {e}")
        if test_download_url:
            print(f"[mail.py] Using fallback test_download_url from config: {test_download_url}")
            return test_download_url
        return None

    try:
        mail.select("INBOX")
        since_date = get_imap_since_date(days_back)
        search_query = f'(SINCE "{since_date}")'
        print(f"[mail.py] Searching INBOX with query: {search_query}...")

        status, messages = mail.search(None, search_query)
        if status != "OK" or not messages[0]:
            print(f"[mail.py] No emails found since {since_date}.")
            # Fallback search ALL if no recent emails found
            print("[mail.py] Checking recent messages without date filter...")
            status, messages = mail.search(None, "ALL")
            if status != "OK" or not messages[0]:
                print("[mail.py] Inbox is empty.")
                return None

        mail_ids = messages[0].split()
        print(f"[mail.py] Found {len(mail_ids)} candidate emails. Scanning newest first...")

        # Iterate from newest to oldest
        for mid in reversed(mail_ids):
            status, data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_mime_header(msg.get("Subject", ""))
            plain_text, html_text = _extract_email_contents(msg)
            combined_body = f"{plain_text}\n{html_text}"

            # Check if this email is for the target software
            matches_keyword = (
                subject_keyword.lower() in subject.lower()
                or target_software.lower() in subject.lower()
                or target_software.lower() in combined_body.lower()
            )

            if not matches_keyword:
                continue

            print(f"[mail.py] Matched email: '{subject}'")
            url, detected_version = extract_version_and_download_link(plain_text, html_text, target_software)
            if detected_version:
                print(f"[mail.py] Detected software version: {detected_version}")

            if url:
                print(f"[mail.py] Extracted download URL: {url}")
                return {
                    "url": url,
                    "version": detected_version,
                    "subject": subject,
                }

        print(f"[mail.py] No matching emails with download links found for {target_software}.")
        return None

    finally:
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    link = get_latest_download_link()
    print(f"[mail.py] Result link: {link}")