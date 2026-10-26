"""Synthetic term-wide HTML with shared indexes, aliases and uncertain sessions."""

from stars.client.teaching import TeachingSnapshot
from stars.parser.schedule import parse_teaching_schedule


def block(code, rows, au="3 AU"):
    header = f"<table><tr><td>{code}</td><td>Fictional course</td><td>{au}</td></tr></table>"
    labels = ["INDEX", "TYPE", "GROUP", "DAY", "TIME", "VENUE", "REMARK"]
    table = (
        "<table>"
        + "".join("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in [labels, *rows])
        + "</table>"
    )
    return header + table


def page(blocks, year=2030, semester=1):
    return f"<html><body>Class Schedule {year} Semester {semester}" + "".join(blocks) + "</body></html>"


FULL_TIME = page(
    [
        block(
            "ZZ0001",
            [
                ["00001", "LEC", "A", "MON", "1000-1100", "LT1", "Teaching Wk1,3"],
                ["", "TUT", "A", "MON", "1400-1500", "TR+1", "Teaching Wk2,4"],
                ["00002", "LEC", "A", "MON", "1000-1100", "LT1", "Teaching Wk1,3"],
                ["", "TUT", "B", "MON", "0900-1000", "TR+2", "Teaching Wk1-13"],
            ],
        ),
        block(
            "ZY0001",
            [
                ["00003", "LAB", "A", "MON", "1400-1600", "S4-CL1", ""],
                ["", "TUT", "A", "MON", "TBA", "TR+3", "Teaching Wk1-13"],
                ["", "LEC", "A", "MON", "1400-1500", "ONLINE", "Teaching Wk1-13"],
            ],
        ),
        block(
            "ZX0001",
            [
                ["00004", "SEM", "A", "MON", "1100-1200", "LHN-TR+01", "Teaching Wk1-13"],
                ["", "SEM", "B", "MON", "1400-1500", "LHN-TR-1", "Teaching Wk1-13"],
            ],
            au=".5 AU",
        ),
    ]
)
PART_TIME = page(
    [
        block(
            "ZZ0002",
            [
                ["00005", "LEC", "A", "MON", "1400-1600", "TR+2", "Teaching Wk2"],
            ],
        )
    ]
)


def snapshot(year=2030, semester=1, refresh=False):
    term = str(semester)
    return TeachingSnapshot(
        year,
        term,
        parse_teaching_schedule(FULL_TIME, 2030, "1") + parse_teaching_schedule(PART_TIME, 2030, "1"),
        "2030-08-01T00:00:00+00:00",
    )
