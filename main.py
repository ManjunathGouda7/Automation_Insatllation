import argparse
import json
import os
import sys

from down import download_software
from install import install_file
from mail import get_latest_download_link


def run(config_path="config.json", dry_run=False, force_silent=None, test_url=None):
    print("=" * 60)
    print("       V-DPWR-EPR Software Auto-Updater")
    print("=" * 60)

    # 1. Load config
    if not os.path.exists(config_path):
        print(f"[main.py] [ERROR] Configuration file '{config_path}' not found.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    target_software = cfg.get("target_software", "V-DPWR-EPR")
    silent_install = cfg.get("silent_install", False) if force_silent is None else force_silent
    download_dir = cfg.get("download_dir", "downloads")

    print(f"[main.py] Target Software: {target_software}")
    print(f"[main.py] Download Directory: {os.path.abspath(download_dir)}")
    print(f"[main.py] Silent Installation: {silent_install}")
    print(f"[main.py] Dry Run Mode: {dry_run}")
    print("-" * 60)

    # 2. Retrieve download link
    url = None
    if test_url:
        print(f"[main.py] Using provided test URL: {test_url}")
        url = test_url
    else:
        print(f"[main.py] Step 1/3: Checking recent emails for {target_software}...")
        url = get_latest_download_link(config_path)

    if not url:
        print("\n[main.py] [ABORT] No valid download link retrieved.")
        sys.exit(1)

    print(f"\n[main.py] Step 2/3: Downloading installer from: {url}")
    try:
        installer_path = download_software(url, download_dir)
    except Exception as e:
        print(f"\n[main.py] [ERROR] Download failed: {e}")
        sys.exit(1)

    # 3. Install software
    if dry_run:
        print("\n[main.py] [DRY RUN] Download completed. Skipping installation as requested.")
        print(f"[main.py] Installer ready at: {os.path.abspath(installer_path)}")
        sys.exit(0)

    print(f"\n[main.py] Step 3/3: Installing software...")
    success = install_file(installer_path, silent=silent_install)
    if not success:
        print("\n[main.py] [ERROR] Installation did not complete successfully.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("       Update Process Completed Successfully!")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V-DPWR-EPR Software Auto-Updater")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Download only, do not run installer")
    parser.add_argument("--silent", action="store_true", help="Perform silent unattended installation")
    parser.add_argument("--test-url", help="Direct test URL to download and install (skips email check)")
    parser.add_argument("--url", dest="test_url", help="Direct download URL (alias for --test-url)")

    args = parser.parse_args()
    cleaned_url = args.test_url.strip("\"' ") if args.test_url else None
    run(
        config_path=args.config,
        dry_run=args.dry_run,
        force_silent=True if args.silent else None,
        test_url=cleaned_url,
    )