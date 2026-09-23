import os
import re
import sys
import urllib.parse
import requests


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
    """Downloads a file from a URL with Content-Disposition parsing and progress feedback."""
    os.makedirs(download_dir, exist_ok=True)

    print(f"\n[down.py] Initiating download from: {url}")

    with requests.get(url, stream=True, timeout=120, allow_redirects=True) as resp:
        resp.raise_for_status()

        filename = _extract_filename_from_headers(resp, url)
        target_path = os.path.join(download_dir, filename)

        total_bytes = int(resp.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 64 * 1024  # 64 KB

        print(f"[down.py] Detected filename: {filename}")
        if total_bytes > 0:
            print(f"[down.py] Total size: {total_bytes / (1024 * 1024):.2f} MB")
        print(f"[down.py] Destination: {os.path.abspath(target_path)}")

        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
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