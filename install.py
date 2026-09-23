import os
import shutil
import subprocess
import sys
import zipfile


def extract_zip(archive_path, extract_dir=None):
    """Extracts a ZIP archive and searches for the installer file inside."""
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    if not extract_dir:
        base_name = os.path.splitext(os.path.basename(archive_path))[0]
        parent_dir = os.path.dirname(archive_path) or "."
        extract_dir = os.path.join(parent_dir, f"extracted_{base_name}")

    os.makedirs(extract_dir, exist_ok=True)
    print(f"[install.py] Extracting ZIP: {archive_path}")
    print(f"[install.py] Extract destination: {os.path.abspath(extract_dir)}")

    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(extract_dir)

    print("[install.py] Extraction complete. Searching for installer binary...")

    # Look for candidate executables
    candidates = []
    for root, _, files in os.walk(extract_dir):
        for fname in files:
            full_path = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".exe", ".msi", ".bat", ".cmd"):
                candidates.append(full_path)

    if not candidates:
        print(f"[install.py] No executable (.exe, .msi) found inside {extract_dir}.")
        return None

    # Score candidates: prioritize setup/installer/v-dpwr
    def score_candidate(path):
        name = os.path.basename(path).lower()
        score = 0
        if "setup" in name or "install" in name:
            score += 50
        if "v-dpwr" in name or "v_dpwr" in name or "epr" in name:
            score += 40
        if name.endswith(".msi"):
            score += 20
        elif name.endswith(".exe"):
            score += 15
        return score

    sorted_candidates = sorted(candidates, key=score_candidate, reverse=True)
    selected_installer = sorted_candidates[0]
    print(f"[install.py] Selected installer from archive: {selected_installer}")
    return selected_installer


def install_file(file_path, silent=False):
    """Executes the installer depending on file extension and OS."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    # If ZIP, unpack first and get the extracted installer
    if ext == ".zip":
        extracted_target = extract_zip(file_path)
        if not extracted_target:
            print("[install.py] Could not determine installer inside ZIP.")
            return False
        return install_file(extracted_target, silent=silent)

    print(f"\n[install.py] Executing installer: {os.path.abspath(file_path)}")
    print(f"[install.py] Mode: {'Silent/Unattended' if silent else 'Interactive UI'}")

    try:
        if sys.platform.startswith("win32"):
            if ext == ".msi":
                args = (
                    ["msiexec", "/i", os.path.abspath(file_path), "/qn"]
                    if silent
                    else ["msiexec", "/i", os.path.abspath(file_path)]
                )
                print(f"[install.py] Running command: {' '.join(args)}")
                res = subprocess.run(args, check=True)
                print(f"[install.py] Installer exited with code {res.returncode}.")
            elif ext == ".exe":
                # For Windows EXE installers:
                # If silent, try common silent switch /S
                args = [os.path.abspath(file_path), "/S"] if silent else [os.path.abspath(file_path)]
                print(f"[install.py] Running executable: {' '.join(args)}")
                try:
                    res = subprocess.run(args, check=True)
                    print(f"[install.py] Installer exited with code {res.returncode}.")
                except OSError as e:
                    # Windows Error 740: The requested operation requires elevation
                    print(f"[install.py] Elevation required ({e}). Launching with Windows UAC prompt...")
                    os.startfile(file_path)
            else:
                print(f"[install.py] Opening file with default shell handler...")
                os.startfile(file_path)

        elif sys.platform.startswith("darwin"):  # macOS
            if ext == ".pkg":
                subprocess.run(["sudo", "installer", "-pkg", file_path, "-target", "/"], check=True)
            elif ext == ".dmg":
                print("[install.py] DMG detected. Mount manually or pass to hdiutil.")

        elif sys.platform.startswith("linux"):
            if ext == ".deb":
                subprocess.run(["sudo", "dpkg", "-i", file_path], check=True)
            else:
                subprocess.run(["chmod", "+x", file_path], check=True)
                subprocess.run([file_path], check=True)

        print("[install.py] Installation finished successfully.")
        return True

    except subprocess.CalledProcessError as e:
        print(f"[install.py] [ERROR] Installer process exited with non-zero error: {e}")
        return False
    except PermissionError as e:
        print(f"[install.py] [ERROR] Permission denied: {e}")
        print("[install.py] Please run your terminal or script as Administrator.")
        return False
    except Exception as e:
        print(f"[install.py] [ERROR] Installation failed: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        silent_mode = "--silent" in sys.argv
        target = [arg for arg in sys.argv[1:] if not arg.startswith("--")][0]
        install_file(target, silent=silent_mode)
    else:
        print("Usage: python install.py <path_to_installer_or_zip> [--silent]")