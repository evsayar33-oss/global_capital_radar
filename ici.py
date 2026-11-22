"""ICI combined estimated long-term fund flows and ETF net issuance, USD millions."""
from datetime import datetime
from html.parser import HTMLParser


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        if tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.cells.append("".join(self.cell).strip())
            self.cell = None
        if tag == "tr":
            self.rows.append(self.cells)


def parse(page):
    parser = TableRows()
    parser.feed(page)
    labels = {"Domestic", "World", "Hybrid", "Bond", "Commodity"}
    for n, header in enumerate(parser.rows):
        try:
            dates = [datetime.strptime(s, "%m/%d/%Y").date() for s in header[1:]]
        except ValueError:
            continue
        if not dates or len(set(dates)) != len(dates):
            continue
        data = {}
        for cells in parser.rows[n+1:]:
            if cells and cells[0] == "Total":
                break
            if cells and cells[0] in labels and len(cells) == len(header):
                data[cells[0]] = dict(zip(dates, [int(v.replace(",", "")) for v in cells[1:]]))
        if set(data) == labels:
            return data
    raise ValueError("ICI akış tablosu okunamadı")
