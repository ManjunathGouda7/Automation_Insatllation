import os
import tempfile
import unittest
import zipfile

from mail import extract_version, extract_links_from_content, get_imap_since_date
from down import _extract_filename_from_headers
from install import extract_zip


class MockResponse:
    def __init__(self, headers=None, url="https://example.com/downloads/v-dpwr.exe"):
        self.headers = headers or {}
        self.url = url


class TestUpdater(unittest.TestCase):
    def test_extract_version_variable_patterns(self):
        # User requested format: "Please find the download link for V-DPWR-EPR software (version [v1.1.1.X])"
        text1 = "Please find the download link for V-DPWR-EPR software (version [v1.1.1.X])"
        self.assertEqual(extract_version(text1), "1.1.1.X")

        text2 = "Please find the download link for V-DPWR-EPR software (version [v1.1.1.25])"
        self.assertEqual(extract_version(text2), "1.1.1.25")

        text3 = "New release available: version [1.2.0.4]"
        self.assertEqual(extract_version(text3), "1.2.0.4")

        text4 = "V-DPWR-EPR software (version v2.0.1.9)"
        self.assertEqual(extract_version(text4), "2.0.1.9")

        text5 = "Download V-DPWR-EPR [v3.0.0.1]"
        self.assertEqual(extract_version(text5), "3.0.0.1")

    def test_extract_links_from_html_and_text(self):
        html = """
        <html>
            <body>
                <p>Please find the download link for V-DPWR-EPR software (version [v1.1.1.2]):</p>
                <p><a href="https://example.com/files/V-DPWR-EPR_Installer_v1.1.1.2.zip">Download Installer ZIP</a></p>
                <p><a href="https://company.com/privacy">Privacy Policy</a></p>
            </body>
        </html>
        """
        plain = "Please find the download link for V-DPWR-EPR software (version [v1.1.1.2])"

        links = extract_links_from_content(plain, html, target_software="V-DPWR-EPR")
        self.assertTrue(len(links) > 0)
        # Best link should be the zip installer
        self.assertEqual(links[0], "https://example.com/files/V-DPWR-EPR_Installer_v1.1.1.2.zip")

    def test_extract_links_plain_text(self):
        plain = (
            "Hello Team,\nPlease find the download link for V-DPWR-EPR software (version [v1.1.1.5]):\n"
            "https://builds.internal.net/V-DPWR-EPR_v1.1.1.5_setup.exe\n"
            "Thanks,\nRelease Team"
        )
        links = extract_links_from_content(plain, "", target_software="V-DPWR-EPR")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0], "https://builds.internal.net/V-DPWR-EPR_v1.1.1.5_setup.exe")

    def test_imap_since_date(self):
        since = get_imap_since_date(days_back=2)
        # Format must be DD-Mon-YYYY (e.g. 21-Sep-2026)
        parts = since.split("-")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 2)
        self.assertEqual(len(parts[1]), 3)
        self.assertEqual(len(parts[2]), 4)

    def test_filename_extraction_from_headers(self):
        # 1. Content-Disposition with quotes
        resp1 = MockResponse(headers={"Content-Disposition": 'attachment; filename="V-DPWR-EPR_Setup_v1.1.1.2.zip"'})
        self.assertEqual(_extract_filename_from_headers(resp1, "https://example.com/dl"), "V-DPWR-EPR_Setup_v1.1.1.2.zip")

        # 2. Content-Disposition UTF-8 encoded
        resp2 = MockResponse(headers={"Content-Disposition": "attachment; filename*=UTF-8''V-DPWR-EPR_v1.1.1.msi"})
        self.assertEqual(_extract_filename_from_headers(resp2, "https://example.com/dl"), "V-DPWR-EPR_v1.1.1.msi")

        # 3. Fallback to URL path
        resp3 = MockResponse(headers={}, url="https://example.com/files/V-DPWR-EPR_v1.1.1.exe?token=123")
        self.assertEqual(_extract_filename_from_headers(resp3, resp3.url), "V-DPWR-EPR_v1.1.1.exe")

    def test_zip_extraction_and_installer_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "V-DPWR-EPR_v1.1.1.2.zip")
            extract_to = os.path.join(temp_dir, "extracted")

            # Create a mock zip with a dummy installer and readme
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("readme.txt", "Release notes")
                zf.writestr("V-DPWR-EPR_Setup.exe", b"MZDummyExeContent")

            installer = extract_zip(zip_path, extract_dir=extract_to)
            self.assertIsNotNone(installer)
            self.assertTrue(os.path.exists(installer))
            self.assertEqual(os.path.basename(installer), "V-DPWR-EPR_Setup.exe")


if __name__ == "__main__":
    unittest.main()
