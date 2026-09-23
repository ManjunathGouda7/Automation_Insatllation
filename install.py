import os
import shutil
import subprocess
import sys
import time
import zipfile

try:
    import win32gui
    import win32con
    HAVE_WIN32 = True
except ImportError:
    HAVE_WIN32 = False


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


def _find_window_buttons(parent_hwnd):
    """Finds all child buttons inside a window and maps their text to hwnd."""
    buttons = {}
    if not HAVE_WIN32:
        return buttons

    def enum_children(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            cls = win32gui.GetClassName(hwnd).lower()
            text = win32gui.GetWindowText(hwnd).strip()
            if "button" in cls or cls == "#32770":
                buttons[text] = hwnd
    try:
        win32gui.EnumChildWindows(parent_hwnd, enum_children, None)
    except Exception:
        pass
    return buttons


def automate_nsis_wizard(file_path, timeout=300):
    """Automates the V-DPWR-EPR setup wizard:

    1. Welcome Screen: Clicks 'Next >'
    2. License Agreement: Clicks 'I Agree'
    3. Driver Console: Sends Enter key to 'Press any key to continue . . .'
    4. Completion Screen: Clicks 'Finish'
    """
    if not HAVE_WIN32 or not sys.platform.startswith("win32"):
        print("[install.py] Win32 automation not supported on this platform. Launching directly...")
        os.startfile(file_path)
        return True

    print(f"\n[install.py] Launching automated installer wizard: {os.path.abspath(file_path)}")
    print("[install.py] If Windows prompts for Administrator access (UAC), please click 'Yes'...")

    try:
        os.startfile(os.path.abspath(file_path))
    except Exception as e:
        print(f"[install.py] Could not start installer via shell: {e}")
        return False

    start_time = time.time()
    next_clicked = False
    agree_clicked = False
    driver_cleared = False
    finish_clicked = False

    print("[install.py] Monitoring installer wizard windows...")

    while time.time() - start_time < timeout:
        time.sleep(0.8)

        # 1. Enumerate visible windows
        setup_hwnds = []
        console_hwnds = []

        def enum_windows(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                cls = win32gui.GetClassName(hwnd)
                if ("v-dpwr" in title.lower() and "setup" in title.lower()) or "v-dpwr" in title.lower():
                    setup_hwnds.append((hwnd, title))
                elif cls == "ConsoleWindowClass" or "cmd.exe" in title.lower() or "driver" in title.lower() or "administrator" in title.lower():
                    console_hwnds.append((hwnd, title))

        try:
            win32gui.EnumWindows(enum_windows, None)
        except Exception:
            pass

        # Handle Setup Wizard Dialogs
        for s_hwnd, title in setup_hwnds:
            buttons = _find_window_buttons(s_hwnd)

            # Step 1: Welcome Screen -> Click 'Next >'
            if not next_clicked and "Next >" in buttons:
                print(f"[install.py] Found Welcome Screen ('{title}'). Clicking 'Next >'...")
                win32gui.PostMessage(buttons["Next >"], win32con.BM_CLICK, 0, 0)
                next_clicked = True
                time.sleep(1.2)
                continue

            # Step 2: License Agreement -> Click 'I Agree'
            if not agree_clicked and "I Agree" in buttons:
                print(f"[install.py] Found License Agreement ('{title}'). Clicking 'I Agree'...")
                win32gui.PostMessage(buttons["I Agree"], win32con.BM_CLICK, 0, 0)
                agree_clicked = True
                time.sleep(1.2)
                continue

            # Step 4: Completion Screen -> Click 'Finish'
            if "Finish" in buttons:
                # Optionally uncheck Show Readme if present
                for b_text, b_hwnd in buttons.items():
                    if "readme" in b_text.lower():
                        win32gui.SendMessage(b_hwnd, win32con.BM_SETCHECK, win32con.BST_UNCHECKED, 0)

                print(f"[install.py] Found Completion Screen ('{title}'). Clicking 'Finish'...")
                win32gui.PostMessage(buttons["Finish"], win32con.BM_CLICK, 0, 0)
                finish_clicked = True
                time.sleep(1.0)
                print("[install.py] Installation completed successfully!")
                return True

        # Step 3: Handle Driver Installation Script Console Window
        for c_hwnd, c_title in console_hwnds:
            print(f"[install.py] Detected Driver Console ('{c_title}'). Sending Enter key to continue...")
            win32gui.PostMessage(c_hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            win32gui.PostMessage(c_hwnd, win32con.WM_CHAR, 13, 0)
            win32gui.PostMessage(c_hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
            driver_cleared = True
            time.sleep(1.0)

        # If finish was clicked and wizard window has closed
        if finish_clicked and not setup_hwnds:
            print("[install.py] Setup wizard closed. All steps finished.")
            return True

    if finish_clicked:
        return True

    print("[install.py] Timed out waiting for installer wizard completion.")
    return False


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

    print(f"\n[install.py] Target installer: {os.path.abspath(file_path)}")

    try:
        if sys.platform.startswith("win32"):
            if ext == ".msi":
                args = (
                    ["msiexec", "/i", os.path.abspath(file_path), "/qn"]
                    if silent
                    else ["msiexec", "/i", os.path.abspath(file_path)]
                )
                print(f"[install.py] Running MSI: {' '.join(args)}")
                res = subprocess.run(args, check=True)
                print(f"[install.py] Installer exited with code {res.returncode}.")
                return True
            elif ext == ".exe":
                # Automate the NSIS wizard (Next > -> I Agree -> Driver Console -> Finish)
                return automate_nsis_wizard(file_path)
            else:
                print(f"[install.py] Opening file with default shell handler...")
                os.startfile(file_path)
                return True

        elif sys.platform.startswith("darwin"):  # macOS
            if ext == ".pkg":
                subprocess.run(["sudo", "installer", "-pkg", file_path, "-target", "/"], check=True)
            elif ext == ".dmg":
                print("[install.py] DMG detected. Mount manually or pass to hdiutil.")
            return True

        elif sys.platform.startswith("linux"):
            if ext == ".deb":
                subprocess.run(["sudo", "dpkg", "-i", file_path], check=True)
            else:
                subprocess.run(["chmod", "+x", file_path], check=True)
                subprocess.run([file_path], check=True)
            return True

    except subprocess.CalledProcessError as e:
        print(f"[install.py] [ERROR] Installer process error: {e}")
        return False
    except PermissionError as e:
        print(f"[install.py] [ERROR] Permission denied: {e}")
        print("[install.py] Please run as Administrator.")
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