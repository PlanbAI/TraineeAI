import re
import unittest

from collectors.BrowserCollector import now_iso as browser_now_iso
from collectors.WindowsCollector import now_iso as desktop_now_iso
from collectors.WindowsRdpCollector import now_iso as rdp_now_iso
from scripts.run_windows_collectors import now_iso as manager_now_iso


class TimestampTests(unittest.TestCase):
    def test_supported_windows_timestamps_are_utc_milliseconds(self):
        pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"

        for now in (browser_now_iso, desktop_now_iso, rdp_now_iso, manager_now_iso):
            self.assertRegex(now(), pattern)


if __name__ == "__main__":
    unittest.main()
