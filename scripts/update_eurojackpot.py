#!/usr/bin/env python3
"""Build a static Eurojackpot JSON API from the LOTTO Bayern archive.

The script downloads the public archive ZIP, parses eurojackpot.txt, and writes
JSON/CSV files into ./public/api so GitHub Pages can serve them as an API.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

SOURCE_URL = os.getenv(
    "EUROJACKPOT_ARCHIVE_URL",
    "https://www.lotto-bayern.de/static/gamebroker_2/de/download_files/archiv_eurojackpot.zip",
)
SOURCE_NAME = "LOTTO Bayern Eurojackpot Archiv"
START_DATE = datetime.fromisoformat(os.getenv("START_DATE", "2022-03-25")).date()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = PROJECT_ROOT / "public"
API_DIR = PUBLIC_DIR / "api"
BY_DATE_DIR = API_DIR / "by-date"
TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))


@dataclass(frozen=True)
class Draw:
    date: str
    date_de: str
    weekday: str
    main_numbers: list[int]
    euro_numbers: list[int]

    @property
    def sort_key(self) -> str:
        return self.date

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "date_de": self.date_de,
            "weekday": self.weekday,
            "main_numbers": self.main_numbers,
            "euro_numbers": self.euro_numbers,
        }


def download_archive(url: str) -> bytes:
    response = requests.get(url, timeout=TIMEOUT_SECONDS, headers={"User-Agent": "eurojackpot-static-api/1.0"})
    response.raise_for_status()
    return response.content


def find_txt_member(zip_file: zipfile.ZipFile) -> str:
    candidates = [name for name in zip_file.namelist() if name.lower().endswith(".txt")]
    if not candidates:
        raise FileNotFoundError("No .txt file found inside the ZIP archive")

    preferred = [name for name in candidates if "eurojackpot" in Path(name).name.lower()]
    return preferred[0] if preferred else candidates[0]


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text_from_zip(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
        member_name = find_txt_member(zip_file)
        with zip_file.open(member_name) as txt_file:
            return decode_text(txt_file.read())


def parse_draws(text: str, start_date=START_DATE) -> list[Draw]:
    draws: list[Draw] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not re.match(r"^\d{1,2}\s+\d{1,2}\s+\d{4}\b", line):
            continue

        # The archive line begins with day month year. After that we need the next
        # seven integer values: five main numbers and two Euro numbers.
        tokens = re.findall(r"\d+", line)
        if len(tokens) < 10:
            continue

        day, month, year = map(int, tokens[:3])
        draw_date = datetime(year, month, day).date()
        if draw_date < start_date:
            continue

        numbers = list(map(int, tokens[3:10]))
        main_numbers = numbers[:5]
        euro_numbers = numbers[5:7]

        if not _numbers_look_valid(main_numbers, euro_numbers):
            # Ignore malformed rows instead of publishing suspicious output.
            continue

        draws.append(
            Draw(
                date=draw_date.isoformat(),
                date_de=draw_date.strftime("%d.%m.%Y"),
                weekday=draw_date.strftime("%A"),
                main_numbers=main_numbers,
                euro_numbers=euro_numbers,
            )
        )

    # Newest first and de-duplicated by ISO date.
    by_date: dict[str, Draw] = {}
    for draw in sorted(draws, key=lambda item: item.sort_key):
        by_date[draw.date] = draw

    return sorted(by_date.values(), key=lambda item: item.sort_key, reverse=True)


def _numbers_look_valid(main_numbers: Iterable[int], euro_numbers: Iterable[int]) -> bool:
    main = list(main_numbers)
    euro = list(euro_numbers)
    return (
        len(main) == 5
        and len(euro) == 2
        and all(1 <= value <= 50 for value in main)
        and all(1 <= value <= 12 for value in euro)
    )


def build_stats(draws: list[Draw]) -> dict:
    main_counter: Counter[int] = Counter()
    euro_counter: Counter[int] = Counter()

    for draw in draws:
        main_counter.update(draw.main_numbers)
        euro_counter.update(draw.euro_numbers)

    return {
        "total_draws": len(draws),
        "date_range": {
            "from": draws[-1].date if draws else None,
            "to": draws[0].date if draws else None,
        },
        "main_number_frequency": {str(number): main_counter.get(number, 0) for number in range(1, 51)},
        "euro_number_frequency": {str(number): euro_counter.get(number, 0) for number in range(1, 13)},
        "hot_main_numbers": [number for number, _ in main_counter.most_common(10)],
        "hot_euro_numbers": [number for number, _ in euro_counter.most_common(5)],
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, draws: list[Draw]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["date", "date_de", "main_1", "main_2", "main_3", "main_4", "main_5", "euro_1", "euro_2"])
        for draw in draws:
            writer.writerow([draw.date, draw.date_de, *draw.main_numbers, *draw.euro_numbers])


def build_openapi(base_path: str = "/") -> dict:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Eurojackpot Static API",
            "version": "1.0.0",
            "description": "Static JSON API generated from the LOTTO Bayern Eurojackpot archive.",
        },
        "servers": [{"url": base_path.rstrip("/") or "/"}],
        "paths": {
            "/api/latest.json": {"get": {"summary": "Latest Eurojackpot draw"}},
            "/api/draws.json": {"get": {"summary": "All Eurojackpot draws since 2022-03-25"}},
            "/api/draws.csv": {"get": {"summary": "All Eurojackpot draws as CSV"}},
            "/api/stats.json": {"get": {"summary": "Frequency statistics"}},
            "/api/by-date/{date}.json": {
                "get": {
                    "summary": "Draw by ISO date",
                    "parameters": [
                        {
                            "name": "date",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "format": "date"},
                            "example": "2026-05-15",
                        }
                    ],
                }
            },
        },
    }


def build_index_html(latest: dict | None) -> str:
    latest_html = "No data yet. Run the workflow manually." if not latest else (
        f"{latest['date_de']}: "
        f"{', '.join(map(str, latest['main_numbers']))} + Euro "
        f"{', '.join(map(str, latest['euro_numbers']))}"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Eurojackpot Static API</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f7f7fb; color: #16181d; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 48px 20px; }}
    .card {{ background: white; border: 1px solid #e7e7ef; border-radius: 20px; padding: 24px; box-shadow: 0 10px 30px rgba(20, 20, 40, .06); }}
    code {{ background: #f0f1f6; padding: 2px 6px; border-radius: 8px; }}
    li {{ margin: 10px 0; }}
    a {{ color: #2456d6; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <h1>Eurojackpot Static API</h1>
      <p><strong>Latest draw:</strong> {latest_html}</p>
      <h2>Endpoints</h2>
      <ul>
        <li><a href="api/latest.json"><code>/api/latest.json</code></a> — latest draw</li>
        <li><a href="api/draws.json"><code>/api/draws.json</code></a> — all draws</li>
        <li><a href="api/draws.csv"><code>/api/draws.csv</code></a> — CSV export</li>
        <li><a href="api/stats.json"><code>/api/stats.json</code></a> — number frequencies</li>
        <li><a href="api/openapi.json"><code>/api/openapi.json</code></a> — OpenAPI schema</li>
      </ul>
      <p>Data source: LOTTO Bayern. Data is provided without warranty.</p>
    </div>
  </main>
</body>
</html>
"""


def build_api() -> None:
    zip_bytes = download_archive(SOURCE_URL)
    text = extract_text_from_zip(zip_bytes)
    draws = parse_draws(text)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    latest = draws[0].as_dict() if draws else None
    draw_items = [draw.as_dict() for draw in draws]

    if BY_DATE_DIR.exists():
        shutil.rmtree(BY_DATE_DIR)
    BY_DATE_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "source_name": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "generated_at": generated_at,
        "start_date": START_DATE.isoformat(),
        "total_draws": len(draws),
        "latest_date": latest["date"] if latest else None,
        "disclaimer": "Alle Angaben ohne Gewähr. This static API is not affiliated with LOTTO Bayern.",
    }

    write_json(API_DIR / "meta.json", meta)
    write_json(API_DIR / "latest.json", latest or {})
    write_json(API_DIR / "draws.json", {**meta, "draws": draw_items})
    write_json(API_DIR / "stats.json", {**meta, **build_stats(draws)})
    write_json(API_DIR / "openapi.json", build_openapi())
    write_csv(API_DIR / "draws.csv", draws)

    for draw in draws:
        write_json(BY_DATE_DIR / f"{draw.date}.json", draw.as_dict())

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(build_index_html(latest), encoding="utf-8")
    (PUBLIC_DIR / ".nojekyll").touch()

    print(f"Generated {len(draws)} draws. Latest: {latest['date'] if latest else 'n/a'}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory():
        build_api()
