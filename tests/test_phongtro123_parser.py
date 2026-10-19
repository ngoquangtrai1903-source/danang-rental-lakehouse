import unittest

from bs4 import BeautifulSoup

from src.scrape.scrape_phongtro123 import parse_detail_page, parse_size_m2


def make_detail_html(*, main_size="20 m<sup>2</sup>", recommendations=True):
    recommendation_sections = ""
    if recommendations:
        recommendation_sections = """
        <section>
            <h2>Tin đăng cùng khu vực</h2>
            <article>
                <span class="text-green">4 triệu/tháng</span>
                <span>75 m<sup>2</sup></span>
            </article>
        </section>
        <section>
            <h2>Tin đăng nổi bật</h2>
            <article>
                <span class="text-green">5 triệu/tháng</span>
                <span>90 m<sup>2</sup></span>
            </article>
        </section>
        """

    main_size_markup = f"<span>{main_size}</span>" if main_size else ""
    return f"""
    <main>
        <div class="bg-white shadow-sm rounded p-4 mb-3">
            <header>
                <h1>Phòng trọ mới xây sạch sẽ, có gác lửng. Khu an ninh tốt</h1>
                <div class="d-flex justify-content-between">
                    <div class="d-flex">
                        <span class="text-green fs-5 fw-bold">2.2 triệu/tháng</span>
                        <span class="dot mx-3"></span>
                        {main_size_markup}
                    </div>
                </div>
            </header>
        </div>
        {recommendation_sections}
    </main>
    """


class Phongtro123ParserTests(unittest.TestCase):
    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        return parse_detail_page(
            soup,
            "https://phongtro123.com/phong-tro-pr123456.html",
        )

    def test_extracts_price_and_superscript_area_from_primary_detail_row(self):
        listing = self.parse(make_detail_html())

        self.assertEqual(listing["price_vnd"], 2_200_000)
        self.assertEqual(listing["size_m2"], 20.0)
        self.assertEqual(listing["price_per_m2_vnd"], 110_000)

    def test_does_not_read_area_from_recommended_listing_sections(self):
        listing = self.parse(make_detail_html(main_size=None))

        self.assertIsNone(listing["size_m2"])
        self.assertEqual(listing["price_vnd"], 2_200_000)

    def test_extracts_area_when_recommendations_follow_primary_listing(self):
        listing = self.parse(make_detail_html(recommendations=True))

        self.assertEqual(listing["size_m2"], 20.0)

    def test_parse_size_accepts_superscript_text_spacing_and_decimal_comma(self):
        self.assertEqual(parse_size_m2("20 m 2"), 20.0)
        self.assertEqual(parse_size_m2("12,5 m²"), 12.5)


if __name__ == "__main__":
    unittest.main()
