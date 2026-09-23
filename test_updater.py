import os
import tempfile
import unittest
import zipfile

from down import _extract_filename_from_headers
from install import extract_zip
from mail import (
    extract_links_from_content,
    extract_version,
    extract_version_and_download_link,
    get_imap_since_date,
)


class MockResponse:
    def __init__(self, headers=None, url="https://example.com/downloads/v-dpwr.exe"):
        self.headers = headers or {}
        self.url = url


class TestUpdater(unittest.TestCase):
    def test_extract_version_variable_patterns(self):
        # User requested exact screenshot format: "Please find the download link for V-DPWR-EPR software (version v1.1.1.3)."
        text0 = "Please find the download link for V-DPWR-EPR software (version v1.1.1.3)."
        self.assertEqual(extract_version(text0), "1.1.1.3")

        text1 = "Please find the download link for V-DPWR-EPR software (version [v1.1.1.X])"
        self.assertEqual(extract_version(text1), "1.1.1.X")

        text2 = "Please find the download link for V-DPWR-EPR software (version v1.1.x.x)"
        self.assertEqual(extract_version(text2), "1.1.x.x")

        text3 = "Please find the download link for V-DPWR-EPR software (version [v1.1.1.25])"
        self.assertEqual(extract_version(text3), "1.1.1.25")

        text4 = "New release available: version [1.2.0.4]"
        self.assertEqual(extract_version(text4), "1.2.0.4")

        text5 = "V-DPWR-EPR software (version v2.0.1.9)"
        self.assertEqual(extract_version(text5), "2.0.1.9")

        text6 = "Download V-DPWR-EPR [v3.0.0.1]"
        self.assertEqual(extract_version(text6), "3.0.0.1")

    def test_screenshot_exact_html_link_on_version(self):
        # Matches the screenshot: "Please find the download link for V-DPWR-EPR software (version v1.1.1.3)."
        # where v1.1.1.3 is the purple hyperlink
        html = '<p>Please find the download link for V-DPWR-EPR software (version <a href="https://files.grl.com/releases/V-DPWR-EPR_Setup_v1.1.1.3.zip">v1.1.1.3</a>).</p>'
        url, version = extract_version_and_download_link("", html, target_software="V-DPWR-EPR")
        self.assertEqual(version, "1.1.1.3")
        self.assertEqual(url, "https://files.grl.com/releases/V-DPWR-EPR_Setup_v1.1.1.3.zip")

    def test_screenshot_html_with_variable_x(self):
        # Matches v1.1.x.x as hyperlink
        html = '<p>Please find the download link for V-DPWR-EPR software (version <a href="https://files.grl.com/releases/setup.exe">v1.1.x.x</a>).</p>'
        url, version = extract_version_and_download_link("", html, target_software="V-DPWR-EPR")
        self.assertEqual(version, "1.1.x.x")
        self.assertEqual(url, "https://files.grl.com/releases/setup.exe")

    def test_plain_text_link_after_version(self):
        # Plain text where URL appears right after (version v1.1.1.3)
        plain = "Please find the download link for V-DPWR-EPR software (version v1.1.1.3). https://files.grl.com/setup.exe"
        url, version = extract_version_and_download_link(plain, "", target_software="V-DPWR-EPR")
        self.assertEqual(version, "1.1.1.3")
        self.assertEqual(url, "https://files.grl.com/setup.exe")

    def test_plain_text_link_after_bracket_version(self):
        plain = "Please find the download link for V-DPWR-EPR software (version [v1.1.1.X]): https://files.grl.com/setup.zip"
        url, version = extract_version_and_download_link(plain, "", target_software="V-DPWR-EPR")
        self.assertEqual(version, "1.1.1.X")
        self.assertEqual(url, "https://files.grl.com/setup.zip")

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
        self.assertEqual(links[0], "https://example.com/files/V-DPWR-EPR_Installer_v1.1.1.2.zip")

    def test_imap_since_date(self):
        since = get_imap_since_date(days_back=2)
        parts = since.split("-")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 2)
        self.assertEqual(len(parts[1]), 3)
        self.assertEqual(len(parts[2]), 4)

    def test_filename_extraction_from_headers(self):
        resp1 = MockResponse(headers={"Content-Disposition": 'attachment; filename="V-DPWR-EPR_Setup_v1.1.1.2.zip"'})
        self.assertEqual(_extract_filename_from_headers(resp1, "https://example.com/dl"), "V-DPWR-EPR_Setup_v1.1.1.2.zip")

        resp2 = MockResponse(headers={"Content-Disposition": "attachment; filename*=UTF-8''V-DPWR-EPR_v1.1.1.msi"})
        self.assertEqual(_extract_filename_from_headers(resp2, "https://example.com/dl"), "V-DPWR-EPR_v1.1.1.msi")

        resp3 = MockResponse(headers={}, url="https://example.com/files/V-DPWR-EPR_v1.1.1.exe?token=123")
        self.assertEqual(_extract_filename_from_headers(resp3, resp3.url), "V-DPWR-EPR_v1.1.1.exe")

    def test_zip_extraction_and_installer_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "V-DPWR-EPR_v1.1.1.2.zip")
            extract_to = os.path.join(temp_dir, "extracted")

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("readme.txt", "Release notes")
                zf.writestr("V-DPWR-EPR_Setup.exe", b"MZDummyExeContent")

            installer = extract_zip(zip_path, extract_dir=extract_to)
            self.assertIsNotNone(installer)
            self.assertTrue(os.path.exists(installer))
            self.assertEqual(os.path.basename(installer), "V-DPWR-EPR_Setup.exe")


if __name__ == "__main__":
    unittest.main()
