import unittest

from bs4 import BeautifulSoup

from src.scrape.furnishing_fallback import infer_furnishing_status
from src.scrape.scrape_phongtro123 import (
    get_furnishing_status as phongtro123_furnishing_status,
)
from src.scrape.scrape_phongtro_vn import (
    get_furnishing_status as phongtro_vn_furnishing_status,
)


class FurnishingClassificationTests(unittest.TestCase):
    def classify_all(self, text):
        soup = BeautifulSoup("", "html.parser")
        return (
            infer_furnishing_status(body_text=text),
            phongtro_vn_furnishing_status(soup, text),
            phongtro123_furnishing_status(soup, text),
        )

    def test_luxury_phrases_receive_luxury_label_in_all_scrapers(self):
        for phrase in (
            "Nội thất cao cấp",
            "Nội thất sang trọng",
            "Full nội thất cao cấp",
            "Trang bị nội thất cao cấp",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    self.classify_all(phrase),
                    ("Nội thất cao cấp",) * 3,
                )

    def test_regular_full_furnishing_phrases_keep_existing_label(self):
        for phrase in ("Đầy đủ nội thất", "Full tiện nghi"):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    self.classify_all(phrase),
                    ("Đầy đủ nội thất",) * 3,
                )

    def test_negative_furnishing_phrase_has_priority_over_luxury_phrase(self):
        self.assertEqual(
            self.classify_all("Không có nội thất cao cấp"),
            ("Không nội thất",) * 3,
        )


if __name__ == "__main__":
    unittest.main()
