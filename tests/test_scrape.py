from cb1.scrape import absolute_url, extract_pdf_hrefs

HTML = """
<a href="/assets/brooklyncb1/downloads/pdf/meeting-minutes/jan2016.pdf">January 2016</a>
<a href="/assets/brooklyncb1/downloads/pdf/combined ph and bd mtg minutes 9_18_17.pdf">Sept</a>
<a href="/some/agenda.PDF">agenda</a>
<a href="/assets/brooklyncb1/downloads/pdf/meeting-minutes/jan2016.pdf">dupe</a>
<a href="/not-a-pdf.html">nope</a>
"""


def test_extract_pdf_hrefs_dedupes_and_keeps_order():
    hrefs = extract_pdf_hrefs(HTML)
    assert hrefs == [
        "/assets/brooklyncb1/downloads/pdf/meeting-minutes/jan2016.pdf",
        "/assets/brooklyncb1/downloads/pdf/combined ph and bd mtg minutes 9_18_17.pdf",
        "/some/agenda.PDF",
    ]


def test_absolute_url_quotes_spaces():
    url = absolute_url("/assets/brooklyncb1/downloads/pdf/combined ph minutes 9_18_17.pdf")
    assert url == (
        "https://www.nyc.gov/assets/brooklyncb1/downloads/pdf/"
        "combined%20ph%20minutes%209_18_17.pdf"
    )


def test_absolute_url_passthrough():
    assert absolute_url("https://x.com/a.pdf") == "https://x.com/a.pdf"
