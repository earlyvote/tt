#!/usr/bin/env python3

import csv
import json
import re
import shutil
import sys
from pathlib import Path


SOURCE_CSV = Path("data/blocks.csv")
OUTPUT_DIR = Path("dist")
JSON_DIR = OUTPUT_DIR / "data" / "blocks"


COLUMN_CANDIDATES = {
    "evTitle": [
        "Closest Early Voting Location Title",
        "EV Location Title"
    ],
    "evAddress": [
        "Closest Early Voting Location Address",
        "EV Location Address"
    ],
    "evHours": [
        "Closest Early Voting Location Hours",
        "EV Location Hours"
    ],
    "blockId": [
        "Block ID",
        "BlockID"
    ],
    "blockName": [
        "Block Name",
        "BlockName"
    ],
    "lat": [
        "Block Latitude",
        "Latitude",
        "Lat"
    ],
    "lng": [
        "Block Longitude",
        "Longitude",
        "Lng",
        "Long"
    ],
    "latlng": [
        "Block Latitude & Longitude",
        "Block Lat/Long",
        "Lat/Long"
    ],
    "t5": [
        "Block Turnout - 5 days ago",
        "Block Turnout 5 days ago",
        "Turnout 5 days ago"
    ],
    "t3": [
        "Block Turnout - 3 days ago",
        "Block Turnout 3 days ago",
        "Turnout 3 days ago"
    ],
    "tc": [
        "Block Turnout - Current",
        "Block Turnout Current",
        "Current Turnout"
    ],
    "closest1": [
        "Closest Block ID 1",
        "Closest Block ID1",
        "Nearest Block ID 1"
    ],
    "closest2": [
        "Closest Block ID 2",
        "Closest Block ID2",
        "Nearest Block ID 2"
    ],
    "closest3": [
        "Closest Block ID 3",
        "Closest Block ID3",
        "Nearest Block ID 3"
    ],
    "closest4": [
        "Closest Block ID 4",
        "Closest Block ID4",
        "Nearest Block ID 4"
    ]
}


def normalize_header(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def find_column(headers, candidates):
    normalized_headers = {
        normalize_header(header): header
        for header in headers
    }

    for candidate in candidates:
        match = normalized_headers.get(normalize_header(candidate))
        if match:
            return match

    return None


def parse_percent(value):
    if value is None:
        return None

    text = str(value).strip().replace("%", "")

    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def parse_float(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def clean_text(value):
    return str(value or "").strip()


def safe_filename(block_id):
    """
    Keeps the generated filename valid and avoids path traversal.
    URLs use encodeURIComponent on the front end, but the actual file names
    should be conservative and predictable.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", block_id)


def prepare_deployment_directory():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for item in Path(".").iterdir():
        if item.name in {
            ".git",
            ".github",
            "data",
            "scripts",
            "dist",
            ".gitignore"
        }:
            continue

        destination = OUTPUT_DIR / item.name

        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)

    JSON_DIR.mkdir(parents=True, exist_ok=True)

    (OUTPUT_DIR / ".nojekyll").touch()


def load_blocks():
    if not SOURCE_CSV.exists():
        raise FileNotFoundError(
            f"Source CSV not found: {SOURCE_CSV}"
        )

    with SOURCE_CSV.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError("The source CSV has no header row.")

        headers = reader.fieldnames

        columns = {
            key: find_column(headers, candidates)
            for key, candidates in COLUMN_CANDIDATES.items()
        }

        required_keys = [
            "blockId",
            "blockName",
            "t5",
            "t3",
            "tc",
            "closest1",
            "closest2",
            "closest3",
            "closest4"
        ]

        missing = [
            key for key in required_keys
            if not columns.get(key)
        ]

        if missing:
            expected = ", ".join(missing)
            raise ValueError(
                "Could not find required CSV columns for: "
                f"{expected}"
            )

        blocks = {}

        for row in reader:
            block_id = clean_text(row.get(columns["blockId"]))

            if not block_id or block_id in blocks:
                continue

            lat = None
            lng = None

            if columns.get("lat") and columns.get("lng"):
                lat = parse_float(row.get(columns["lat"]))
                lng = parse_float(row.get(columns["lng"]))

            elif columns.get("latlng"):
                raw_latlng = clean_text(row.get(columns["latlng"]))
                parts = raw_latlng.split(",")

                if len(parts) >= 2:
                    lat = parse_float(parts[0])
                    lng = parse_float(parts[1])

            closest_ids = []

            for closest_key in [
                "closest1",
                "closest2",
                "closest3",
                "closest4"
            ]:
                closest_id = clean_text(
                    row.get(columns[closest_key])
                )

                if closest_id and closest_id != block_id:
                    closest_ids.append(closest_id)

            blocks[block_id] = {
                "id": block_id,
                "name": clean_text(
                    row.get(columns["blockName"])
                ) or block_id,
                "lat": lat,
                "lng": lng,
                "t5": parse_percent(row.get(columns["t5"])),
                "t3": parse_percent(row.get(columns["t3"])),
                "tc": parse_percent(row.get(columns["tc"])),
                "evTitle": clean_text(
                    row.get(columns["evTitle"])
                ) if columns.get("evTitle") else "",
                "evAddress": clean_text(
                    row.get(columns["evAddress"])
                ) if columns.get("evAddress") else "",
                "evHours": clean_text(
                    row.get(columns["evHours"])
                ) if columns.get("evHours") else "",
                "closestIds": closest_ids
            }

    return blocks


def public_subject(block):
    return {
        "id": block["id"],
        "name": block["name"],
        "lat": block["lat"],
        "lng": block["lng"],
        "t5": block["t5"],
        "t3": block["t3"],
        "tc": block["tc"],
        "evTitle": block["evTitle"],
        "evAddress": block["evAddress"],
        "evHours": block["evHours"]
    }


def public_nearby_block(block):
    return {
        "id": block["id"],
        "name": block["name"],
        "lat": block["lat"],
        "lng": block["lng"],
        "t5": block["t5"],
        "t3": block["t3"],
        "tc": block["tc"]
    }


def build_json_files(blocks):
    written = 0
    missing_neighbors = 0
    used_filenames = {}

    for block_id, subject in blocks.items():
        nearby_blocks = []

        for nearby_id in subject["closestIds"]:
            nearby = blocks.get(nearby_id)

            if nearby:
                nearby_blocks.append(
                    public_nearby_block(nearby)
                )
            else:
                missing_neighbors += 1

        payload = {
            "subject": public_subject(subject),
            "nearbyBlocks": nearby_blocks
        }

        filename = safe_filename(block_id)

        existing_id = used_filenames.get(filename)

        if existing_id and existing_id != block_id:
            raise ValueError(
                "Filename collision after sanitizing IDs: "
                f"{existing_id!r} and {block_id!r} "
                f"both become {filename!r}"
            )

        used_filenames[filename] = block_id

        output_path = JSON_DIR / f"{filename}.json"

        with output_path.open(
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                payload,
                file,
                ensure_ascii=False,
                separators=(",", ":")
            )

        written += 1

    return written, missing_neighbors


def main():
    prepare_deployment_directory()
    blocks = load_blocks()
    written, missing_neighbors = build_json_files(blocks)

    print(f"Built {written:,} block JSON files.")

    if missing_neighbors:
        print(
            f"Warning: {missing_neighbors:,} referenced "
            "closest-block IDs were not found in the CSV.",
            file=sys.stderr
        )


if __name__ == "__main__":
    main()