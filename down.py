import os
import re
import sys
import urllib.parse
import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def _transform_sharepoint_url(url):
    """If SharePoint or OneDrive sharing link without download=1, appends download=1 to bypass web preview."""
    lower_url = url.lower()
    if any(domain in lower_url for domain in ["sharepoint.com", "1drv.ms", "onedrive.live.com"]):
        if "download=1" not in lower_url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}download=1"
    return url


def _extract_download_link_from_preview_html(html_content, base_url):
    """Finds direct download link from web preview pages like SharePoint/OneDrive."""
    if not html_content:
        return None

    # 1. Search with BeautifulSoup
    if BeautifulSoup:
        soup = BeautifulSoup(html_content, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            anchor_text = a_tag.get_text().strip().lower()
            aria_label = str(a_tag.get("aria-label", "")).lower()
            if "download" in anchor_text or "download" in aria_label or "download.aspx" in href.lower():
                return urllib.parse.urljoin(base_url, href)

    # 2. Search scripts for downloadUrl: "https://..."
    patterns = [
        r'"downloadUrl"\s*:\s*"([^"]+)"',
        r'"fileDownloadUrl"\s*:\s*"([^"]+)"',
        r'href\s*=\s*["\']([^"\']*download\.aspx[^"\']*)["\']',
        r'["\'](https?://[^\s"\'<>]*(?:download\.aspx|download=1)[^\s"\'<>]*)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html_content, re.IGNORECASE)
        if m:
            clean_url = m.group(1).replace("\\u0026", "&").replace("\\/", "/")
            return urllib.parse.urljoin(base_url, clean_url)

    return None


def _extract_filename_from_headers(response, fallback_url):
    """Extracts the filename from the Content-Disposition header, or falls back to URL."""
    cdisp = response.headers.get("Content-Disposition", "")
    filename = None

    if cdisp:
        # Check RFC 5987 filename*
        star_match = re.search(r"filename\*\s*=\s*(?:UTF-8''|utf-8'')([^;\s]+)", cdisp, re.IGNORECASE)
        if star_match:
            filename = urllib.parse.unquote(star_match.group(1).strip("\"'"))
        else:
            # Check standard filename=
            match = re.search(r'filename\s*=\s*(?:"([^"]+)"|([^;\s]+))', cdisp, re.IGNORECASE)
            if match:
                filename = (match.group(1) or match.group(2)).strip("\"'")

    # Fallback to URL path
    if not filename:
        parsed_url = urllib.parse.urlparse(response.url or fallback_url)
        path_name = os.path.basename(parsed_url.path)
        if path_name and "." in path_name:
            filename = path_name

    # Ultimate fallback
    if not filename:
        filename = "software_installer.exe"

    # Sanitize Windows file name: remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    return filename


def download_software(url, download_dir="downloads"):
    """Downloads a file from a URL with Content-Disposition parsing, SharePoint preview handling,

    magic-byte binary detection, and progress feedback.
    """
    os.makedirs(download_dir, exist_ok=True)

    target_url = _transform_sharepoint_url(url)
    print(f"\n[down.py] Initiating download from: {target_url}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    })

    resp = session.get(target_url, stream=True, timeout=120, allow_redirects=True)
    resp.raise_for_status()

    # Check if page is an HTML preview page (like SharePoint 'Can't preview this file')
    ctype = resp.headers.get("content-type", "").lower()
    if "text/html" in ctype:
        html_preview = resp.text
        if "can't preview this file" in html_preview.lower() or "download" in html_preview.lower():
            print("[down.py] Detected cloud preview page ('Can't preview this file').")
            direct_link = _extract_download_link_from_preview_html(html_preview, resp.url)
            if direct_link and direct_link != target_url:
                print(f"[down.py] Resolved direct download button link: {direct_link}")
                resp.close()
                target_url = direct_link
                resp = session.get(target_url, stream=True, timeout=120, allow_redirects=True)
                resp.raise_for_status()

    filename = _extract_filename_from_headers(resp, target_url)
    target_path = os.path.join(download_dir, filename)

    total_bytes = int(resp.headers.get("content-length", 0))
    downloaded = 0
    chunk_size = 64 * 1024  # 64 KB

    print(f"[down.py] Detected filename: {filename}")
    if total_bytes > 0:
        print(f"[down.py] Total size: {total_bytes / (1024 * 1024):.2f} MB")
    print(f"[down.py] Destination: {os.path.abspath(target_path)}")

    # Stream chunks and check magic bytes on the first chunk
    content_iter = resp.iter_content(chunk_size=chunk_size)
    try:
        first_chunk = next(content_iter)
    except StopIteration:
        raise ValueError(f"Downloaded file from {target_url} was empty.")

    # Magic byte inspection:
    # b"MZ" = Windows PE executable (.exe)
    # b"PK" = ZIP archive (.zip)
    if first_chunk.startswith(b"MZ") and not filename.lower().endswith(".exe"):
        old_path = target_path
        filename = f"{filename}.exe" if "." not in filename else f"{os.path.splitext(filename)[0]}.exe"
        target_path = os.path.join(download_dir, filename)
        print(f"[down.py] Detected Windows executable binary header (MZ). Target file: {filename}")
    elif first_chunk.startswith(b"PK") and not filename.lower().endswith(".zip"):
        filename = f"{filename}.zip" if "." not in filename else f"{os.path.splitext(filename)[0]}.zip"
        target_path = os.path.join(download_dir, filename)
        print(f"[down.py] Detected ZIP archive header (PK). Target file: {filename}")

    with open(target_path, "wb") as f:
        f.write(first_chunk)
        downloaded += len(first_chunk)

        for chunk in content_iter:
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)
            mb_done = downloaded / (1024 * 1024)
            if total_bytes > 0:
                pct = min(100.0, (downloaded / total_bytes) * 100)
                mb_total = total_bytes / (1024 * 1024)
                sys.stdout.write(f"\r[down.py] Progress: {pct:5.1f}% ({mb_done:6.2f}/{mb_total:6.2f} MB)")
            else:
                sys.stdout.write(f"\r[down.py] Downloaded: {mb_done:6.2f} MB")
            sys.stdout.flush()

    sys.stdout.write("\n")
    print(f"[down.py] Download completed successfully: {target_path}")
    return target_path


if __name__ == "__main__":
    test_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://example.com/test_installer.exe"
    )
    download_software(test_url)