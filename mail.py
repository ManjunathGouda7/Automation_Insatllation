import email
from email.header import decode_header
import imaplib
import json
import os
import re
from datetime import datetime, timedelta, timezone
import requests
import time

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


def _get_msgraph_token(cfg):
    """Retrieves an access token for Microsoft Graph via cached refresh token or interactive Device Code login."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ms_token_cache.json")
    client_id = cfg.get("azure_client_id", "d3590ed6-52b3-4102-aeff-aad2292ab01c")

    # 1. Try loading cached token and refresh it
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                token_data = json.load(f)
            refresh_token = token_data.get("refresh_token")
            if refresh_token:
                token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
                data = {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": "offline_access https://graph.microsoft.com/Mail.Read",
                }
                r = requests.post(token_url, data=data, timeout=30)
                if r.status_code == 200:
                    new_token = r.json()
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(new_token, f)
                    return new_token.get("access_token")
        except Exception:
            pass

    # 2. Start Device Code Flow
    dc_url = "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
    data = {
        "client_id": client_id,
        "scope": "offline_access https://graph.microsoft.com/Mail.Read",
    }
    try:
        r = requests.post(dc_url, data=data, timeout=30)
    except Exception as e:
        print(f"[mail.py] Could not reach Microsoft OAuth2 endpoint: {e}")
        return None

    if r.status_code != 200:
        print(f"[mail.py] Could not initiate Microsoft Device Code: {r.text}")
        return None

    dc_info = r.json()
    user_code = dc_info.get("user_code")
    verification_uri = dc_info.get("verification_uri", "https://login.microsoft.com/device")
    device_code = dc_info.get("device_code")
    interval = int(dc_info.get("interval", 5))

    print("\n" + "=" * 65)
    print("       MICROSOFT 365 MODERN AUTHENTICATION (NO PASSWORDS NEEDED)")
    print("=" * 65)
    print(f"1. Open in your browser:  {verification_uri}")
    print(f"2. Enter the code:        {user_code}")
    print(f"3. Sign in with:          {cfg.get('email_user', 'your work account')}")
    print("=" * 65 + "\n")
    print("[mail.py] Waiting for browser sign-in approval...")

    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    start_poll = time.time()
    while time.time() - start_poll < 300:
        time.sleep(interval)
        poll_data = {
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        }
        res = requests.post(token_url, data=poll_data, timeout=30)
        res_data = res.json()
        if res.status_code == 200 and "access_token" in res_data:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(res_data, f)
            print("[mail.py] Authentication approved! Token saved to cache.")
            return res_data["access_token"]
        elif res_data.get("error") == "access_denied" or "53003" in str(res_data) or "conditional access" in str(res_data).lower():
            print("\n[mail.py] [NOTICE] Microsoft Entra ID Conditional Access Policy blocked the sign-in.")
            print("[mail.py] Corporate IT policy restricts public client Device Code access to your mailbox.")
            return None
        elif res_data.get("error") == "authorization_pending":
            continue
        elif res_data.get("error") == "slow_down":
            time.sleep(5)
        else:
            print(f"[mail.py] Sign-in failed or expired: {res_data}")
            return None

    print("[mail.py] Authentication timed out.")
    return None


def fetch_update_via_msgraph(cfg):
    """Fetches update info via Microsoft Graph API."""
    token = _get_msgraph_token(cfg)
    if not token:
        return None

    target_software = cfg.get("target_software", "V-DPWR-EPR")
    subject_keyword = cfg.get("subject_keyword", target_software)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    graph_url = f'https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$top=15&$search="{subject_keyword}"'
    print(f"[mail.py] Querying Microsoft Graph for messages matching '{subject_keyword}'...")
    try:
        r = requests.get(graph_url, headers=headers, timeout=30)
        if r.status_code != 200:
            graph_url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$top=15&$orderby=receivedDateTime desc"
            r = requests.get(graph_url, headers=headers, timeout=30)
            if r.status_code != 200:
                print(f"[mail.py] Graph API query failed: {r.status_code} {r.text}")
                return None

        messages = r.json().get("value", [])
        print(f"[mail.py] Retrieved {len(messages)} candidate emails from Microsoft Graph.")

        for m in messages:
            subject = m.get("subject", "")
            body_content = m.get("body", {}).get("content", "")
            body_type = m.get("body", {}).get("contentType", "html")

            plain_text = body_content if body_type == "text" else ""
            html_text = body_content if body_type == "html" else ""

            url, version = extract_version_and_download_link(plain_text, html_text, target_software)
            if url:
                print(f"[mail.py] Found matching email via Graph API: '{subject}'")
                print(f"[mail.py] Extracted URL: {url} (Version: {version})")
                return {"url": url, "version": version, "subject": subject}

    except Exception as e:
        print(f"[mail.py] Error fetching from Graph API: {e}")

    return None


def check_local_inbox(inbox_dir="inbox", target_software="V-DPWR-EPR"):
    """Checks the local inbox directory for saved emails or text files (.eml, .msg, .txt, .html).

    Returns an info dict {'url': ..., 'version': ..., 'subject': ...} or None.
    """
    if not os.path.exists(inbox_dir):
        return None

    files = [
        os.path.join(inbox_dir, f)
        for f in os.listdir(inbox_dir)
        if os.path.isfile(os.path.join(inbox_dir, f)) and not f.startswith(".")
    ]
    if not files:
        return None

    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    for fpath in files:
        ext = os.path.splitext(fpath)[1].lower()
        if ext in [".eml", ".msg"]:
            try:
                with open(fpath, "rb") as f:
                    msg = email.message_from_binary_file(f)
                subject = _decode_mime_header(msg.get("Subject", ""))
                plain, html = _extract_email_contents(msg)
                url, ver = extract_version_and_download_link(plain, html, target_software)
                if url:
                    print(f"[mail.py] Found match in local email file: {os.path.basename(fpath)}")
                    if ver:
                        print(f"[mail.py] Detected software version: {ver}")
                    print(f"[mail.py] Extracted URL: {url}")
                    return {"url": url, "version": ver, "subject": subject or os.path.basename(fpath)}
            except Exception as e:
                print(f"[mail.py] Notice: Could not parse email file {fpath}: {e}")
        elif ext in [".txt", ".html", ".htm"]:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                plain = content if ext == ".txt" else ""
                html = content if ext in [".html", ".htm"] else ""
                url, ver = extract_version_and_download_link(plain, html, target_software)
                if url:
                    print(f"[mail.py] Found match in local file: {os.path.basename(fpath)}")
                    if ver:
                        print(f"[mail.py] Detected software version: {ver}")
                    print(f"[mail.py] Extracted URL: {url}")
                    return {"url": url, "version": ver, "subject": os.path.basename(fpath)}
            except Exception as e:
                print(f"[mail.py] Notice: Could not read file {fpath}: {e}")

    return None


def _prompt_for_manual_link(target_software="V-DPWR-EPR"):
    """Interactively prompts user for download link or email text if automated access is blocked."""
    import sys

    if not sys.stdin or not sys.stdin.isatty():
        return None

    print("\n" + "=" * 65)
    print("      ALTERNATIVE: PROVIDE DOWNLOAD LINK OR EMAIL TEXT")
    print("=" * 65)
    print("Due to corporate IT Conditional Access restrictions on email login,")
    print("you can provide the link in any of the following convenient ways:")
    print("  1. Paste the SharePoint / OneDrive link directly below")
    print("  2. Paste the text from the email notification")
    print("  3. Or run: python main.py --url \"<YOUR_LINK>\"")
    print("  4. Or save the email (.eml / .txt) into the 'inbox/' folder")
    print("=" * 65)
    try:
        user_input = input("\nEnter download link or email text (or press Enter to exit): ").strip()
        user_input = user_input.strip("\"' ")
        if user_input:
            url, ver = extract_version_and_download_link(user_input, user_input, target_software)
            found_url = url or (user_input if user_input.startswith("http") else None)
            if found_url:
                print(f"[mail.py] Link accepted: {found_url}")
                if ver:
                    print(f"[mail.py] Detected software version: {ver}")
                return {"url": found_url, "version": ver, "subject": "Interactive Input"}
            else:
                print("[mail.py] [WARNING] Could not find a valid HTTP/HTTPS link in the entered text.")
    except (EOFError, KeyboardInterrupt):
        print("\n[mail.py] Prompt cancelled.")

    return None


def get_latest_update_info(config_path="config.json"):
    """Fetches the latest email matching the software criteria and returns update info dictionary."""
    cfg = load_config(config_path)

    target_software = cfg.get("target_software", "V-DPWR-EPR")
    subject_keyword = cfg.get("subject_keyword", target_software)
    days_back = int(cfg.get("days_back", 2))
    test_download_url = cfg.get("test_download_url", "").strip() or cfg.get("download_url", "").strip()
    inbox_dir = cfg.get("inbox_dir", "inbox")

    # 1. Check local inbox directory
    local_match = check_local_inbox(inbox_dir, target_software)
    if local_match:
        return local_match

    # 2. Check if direct download URL is configured
    if test_download_url:
        print(f"[mail.py] Using configured download URL: {test_download_url}")
        return {"url": test_download_url, "version": None, "subject": "Config URL"}

    # 3. If Graph API is explicitly chosen or forced
    if cfg.get("use_graph") or cfg.get("auth_method") == "graph":
        print("[mail.py] Using Microsoft Graph API authentication...")
        res = fetch_update_via_msgraph(cfg)
        if res:
            return res
        return _prompt_for_manual_link(target_software)

    print(f"[mail.py] Target Software: {target_software}")
    print(f"[mail.py] Date filter: past {days_back} day(s)")

    try:
        print(f"[mail.py] Connecting to IMAP server ({cfg.get('imap_server')})...")
        mail = imaplib.IMAP4_SSL(cfg["imap_server"])
        mail.login(cfg["email_user"], cfg["email_pass"])
    except imaplib.IMAP4.error as e:
        err_msg = str(e)
        print(f"\n[mail.py] [NOTICE] IMAP Authentication Rejected: {err_msg}")
        if "AUTHENTICATE failed" in err_msg or "not supported" in err_msg:
            print("[mail.py] ------------------------------------------------------------------")
            print("[mail.py] Microsoft Office 365 IMAP password authentication is retired.")
            print("[mail.py] Switching automatically to Microsoft 365 Modern Authentication (OAuth2)...")
            print("[mail.py] ------------------------------------------------------------------")
            graph_res = fetch_update_via_msgraph(cfg)
            if graph_res:
                return graph_res
        return _prompt_for_manual_link(target_software)
    except Exception as e:
        print(f"[mail.py] [ERROR] Connection error: {e}")
        return _prompt_for_manual_link(target_software)

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
                return _prompt_for_manual_link(target_software)

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
        return _prompt_for_manual_link(target_software)

    finally:
        try:
            mail.logout()
        except Exception:
            pass


def get_latest_download_link(config_path="config.json"):
    """Fetches the latest email and returns the download URL string."""
    info = get_latest_update_info(config_path)
    return info["url"] if info else None


if __name__ == "__main__":
    link = get_latest_download_link()
    print(f"[mail.py] Result link: {link}")