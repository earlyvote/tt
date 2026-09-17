import csv
import datetime
import io
import json
import math
import shutil
import urllib.request
import urllib.error
from pathlib import Path


# ------------------------------------------------------------
# FILE LOCATIONS
# ------------------------------------------------------------

BLOCKS_CSV = Path("data/blocks.csv")

OUTPUT_DIR = Path("build/data/blocks")


# ------------------------------------------------------------
# GOOGLE SHEET LOCATION
# ------------------------------------------------------------

# https://docs.google.com/spreadsheets/d/1xAi3sD_DQwjJt28Ed76uzLnIDACHih-jCCHu2oKwtHw/edit?gid=0#gid=0
GOOGLE_SHEET_ID = "1xAi3sD_DQwjJt28Ed76uzLnIDACHih-jCCHu2oKwtHw"
GOOGLE_SHEET_GID = "0"

GOOGLE_SHEET_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"
    f"/export?format=csv&gid={GOOGLE_SHEET_GID}"
)

# On this sheet, row 1 is plain-text/human labels and row 2 has
# the actual field names the rest of this script expects (the
# same names that used to live in the header row of
# ev_locations_test.csv). Data starts on row 3.
#
# Row 1 (index 0): plain text titles      <- skipped
# Row 2 (index 1): real field names       <- used as header
# Row 3+ (index 2+): data                 <- parsed as rows


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def clean(value):
    """Return a CSV value as a clean string."""
    if value is None:
        return ""
    return str(value).strip()


def to_number(value):
    """Convert a value to a float, or return None if invalid."""
    value = clean(value)

    if not value:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def to_coordinate(value):
    """
    Convert latitude/longitude to a float.

    Returns None if the value is missing or invalid.
    """
    number = to_number(value)

    if number is None:
        return None

    return number


DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%B %d, %Y",
    "%b %d, %Y",
)


def parse_date(value):
    """
    Parse a date string using a handful of common formats.

    Returns a date object, or None if the value is empty or
    couldn't be parsed with any of the known formats.
    """

    value = clean(value)

    if not value:
        return None

    for date_format in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(
                value, date_format
            ).date()
        except ValueError:
            continue

    return None


def location_is_open(delayed_opening_raw, today=None):
    """
    Determine whether an early voting location is currently
    open, based on the raw ev_has_delayed_opening value.

    - Empty value: no delayed opening, always open.
    - Value present and parses to a date that has already
      passed (<= today): the delay is over, open.
    - Value present but the date hasn't passed yet, or the
      value couldn't be parsed as a date: not open yet.
    """

    delayed_opening_raw = clean(delayed_opening_raw)

    if not delayed_opening_raw:
        return True

    if today is None:
        today = datetime.date.today()

    opening_date = parse_date(delayed_opening_raw)

    if opening_date is None:
        # Has a value but we couldn't parse it as a date -
        # play it safe and treat it as not yet open rather
        # than silently including it.
        return False

    return opening_date <= today


def haversine_miles(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two latitude/longitude
    points in miles.
    """

    earth_radius_miles = 3958.8

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_miles * c


# ------------------------------------------------------------
# FETCH THE GOOGLE SHEET AS CSV
# ------------------------------------------------------------

def fetch_sheet_csv_text(url):
    """
    Download the Google Sheet's published CSV export and
    return it as decoded text.

    The sheet must be shared as "Anyone with the link can
    view" (or published to the web) for the export URL to
    work without authentication.
    """

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    try:
        with urllib.request.urlopen(request) as response:
            raw_bytes = response.read()

    except urllib.error.HTTPError as error:
        raise RuntimeError(
            "Could not download the Google Sheet CSV export "
            f"(HTTP {error.code}). Make sure the sheet is "
            "shared as \"Anyone with the link can view\"."
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not reach Google Sheets: {error.reason}"
        ) from error

    # utf-8-sig strips a BOM if Google includes one.
    return raw_bytes.decode("utf-8-sig")


def rows_from_sheet_csv(csv_text):
    """
    Parse the sheet's CSV text into dict rows, using row 2
    (index 1) as the field-name header and treating row 1
    (index 0) as a human-readable title row to skip.
    """

    all_rows = list(csv.reader(io.StringIO(csv_text)))

    if len(all_rows) < 2:
        raise ValueError(
            "Early voting Google Sheet does not have enough "
            "rows (expected a title row, then a field-name "
            "row, then data)."
        )

    fieldnames = [name.strip() for name in all_rows[1]]
    data_rows = all_rows[2:]

    dict_rows = []

    for row in data_rows:

        # Skip fully blank rows.
        if not any(clean(value) for value in row):
            continue

        # Pad short rows so zip() doesn't silently drop columns.
        if len(row) < len(fieldnames):
            row = row + [""] * (len(fieldnames) - len(row))

        dict_rows.append(dict(zip(fieldnames, row)))

    return fieldnames, dict_rows


# ------------------------------------------------------------
# LOAD EARLY VOTING LOCATIONS (FROM THE GOOGLE SHEET)
# ------------------------------------------------------------

def load_early_voting_locations():
    """
    Read the early voting Google Sheet and organize locations
    by state + county_fips.
    """

    required_columns = {
        "ev_state",
        "ev_county",
        "ev_name",
        "ev_street_address",
        "ev_city",
        "ev_zip",
        "ev_lat",
        "ev_long",
        "ev_registrar_phone",
        "ev_monday_friday",
        "ev_sat",
        "ev_sun",
        "ev_county_lookup_link",
        "ev_county_fips"
    }

    csv_text = fetch_sheet_csv_text(GOOGLE_SHEET_CSV_URL)

    fieldnames, sheet_rows = rows_from_sheet_csv(csv_text)

    missing = required_columns - set(fieldnames)

    if missing:
        raise ValueError(
            "Early voting Google Sheet is missing columns "
            "in row 2: " + ", ".join(sorted(missing))
        )

    locations_by_state_fips = {}
    locations_by_state = []

    for row in sheet_rows:

        state = clean(row["ev_state"]).upper()
        county_fips = clean(row["ev_county_fips"])

        lat = to_coordinate(row["ev_lat"])
        lon = to_coordinate(row["ev_long"])

        # We cannot calculate distance without coordinates.
        if not state or lat is None or lon is None:
            continue

        delayed_opening_raw = clean(
            row.get("ev_has_delayed_opening", "")
        )

        location = {
            "state": state,
            "county": clean(row["ev_county"]),
            "county_fips": county_fips,

            "main_ev_name": clean(row["ev_name"]),
            "main_ev_street_address": clean(
                row["ev_street_address"]
            ),
            "main_ev_city": clean(row["ev_city"]),
            "main_ev_zip": clean(row["ev_zip"]),

            "main_ev_lat": lat,
            "main_ev_long": lon,

            "registrar_phone": clean(row["ev_registrar_phone"]),

            "main_ev_monday_friday": clean(
                row["ev_monday_friday"]
            ),
            "main_ev_sat": clean(row["ev_sat"]),
            "main_ev_sun": clean(row["ev_sun"]),

            "county_ev_lookup_link": clean(
                row["ev_county_lookup_link"]
            ),

            "ev_has_delayed_opening": delayed_opening_raw,
            "is_open": location_is_open(delayed_opening_raw),
        }

        key = (state, county_fips)

        if key not in locations_by_state_fips:
            locations_by_state_fips[key] = []

        locations_by_state_fips[key].append(location)

        locations_by_state.append(location)

    return locations_by_state_fips, locations_by_state


# ------------------------------------------------------------
# FIND CLOSEST EARLY VOTING LOCATION
# ------------------------------------------------------------

def find_closest_early_voting_location(
    block_lat,
    block_lon,
    state,
    county_fips,
    locations_by_state_fips,
    locations_by_state,
):
    """
    Find the closest early voting location.

    First searches the same state + county_fips.

    If none exist, searches the entire state.
    """

    state = clean(state).upper()
    county_fips = clean(county_fips)

    candidates = [
        location
        for location in locations_by_state_fips.get(
            (state, county_fips),
            []
        )
        if location["is_open"]
    ]

    statewide_fallback = False

    # If there are no open county FIPS locations, search the state.
    if not candidates:
        candidates = [
            location
            for location in locations_by_state
            if location["state"] == state
            and location["is_open"]
        ]

        statewide_fallback = True

    if not candidates:
        return None

    closest = None
    closest_distance = None

    for location in candidates:

        distance = haversine_miles(
            block_lat,
            block_lon,
            location["main_ev_lat"],
            location["main_ev_long"],
        )

        if closest_distance is None or distance < closest_distance:
            closest = location
            closest_distance = distance

    result = dict(closest)

    result["main_ev_distance_miles"] = round(
        closest_distance,
        2
    )

    result["main_ev_state"] = closest["state"]
    result["main_ev_county"] = closest["county"]
    result["main_ev_statewide_fallback"] = statewide_fallback

    return result


# ------------------------------------------------------------
# CREATE ONE JSON FILE PER BLOCK
# ------------------------------------------------------------

def generate_block_files():
    """
    Read the block CSV and create one JSON file for every block.
    """

    if not BLOCKS_CSV.exists():
        raise FileNotFoundError(
            f"Could not find {BLOCKS_CSV}"
        )

    print("Loading early voting locations from Google Sheet...")

    (
        locations_by_state_fips,
        locations_by_state,
    ) = load_early_voting_locations()

    print(
        f"Loaded {len(locations_by_state)} "
        "early voting locations with coordinates."
    )

    # Delete the old generated data.
    if OUTPUT_DIR.exists():
        print(f"Removing old generated files: {OUTPUT_DIR}")
        shutil.rmtree(OUTPUT_DIR)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("Reading block CSV...")

    with BLOCKS_CSV.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("Block CSV has no header row.")

        required_columns = {
            "block_id",
            "block_latitude",
            "block_longitude",
            "county_fips",
            "state",
        }

        missing = required_columns - set(reader.fieldnames)

        if missing:
            raise ValueError(
                "Block CSV is missing columns: "
                + ", ".join(sorted(missing))
            )

        total = 0
        successful = 0
        missing_coordinates = 0
        missing_block_ids = 0

        for row in reader:

            total += 1

            block_id = clean(row["block_id"])

            if not block_id:
                missing_block_ids += 1
                continue

            block_lat = to_coordinate(
                row["block_latitude"]
            )

            block_lon = to_coordinate(
                row["block_longitude"]
            )

            if block_lat is None or block_lon is None:
                missing_coordinates += 1

            # ------------------------------------------------
            # START WITH ALL BLOCK DATA
            # ------------------------------------------------

            output = {}

            for key, value in row.items():
                output[key] = clean(value)

            # Convert coordinates to actual numbers.
            if block_lat is not None:
                output["block_latitude"] = block_lat

            if block_lon is not None:
                output["block_longitude"] = block_lon

            # ------------------------------------------------
            # FIND EARLY VOTING LOCATION
            # ------------------------------------------------

            early_voting = None

            if block_lat is not None and block_lon is not None:

                early_voting = find_closest_early_voting_location(
                    block_lat,
                    block_lon,
                    row["state"],
                    row["county_fips"],
                    locations_by_state_fips,
                    locations_by_state,
                )

            # Add early voting information to the block JSON.
            if early_voting is not None:

                for key, value in early_voting.items():
                    output[key] = value

            else:

                # Keep the fields present even if no EV location
                # could be found.
                output["main_ev_name"] = ""
                output["main_ev_street_address"] = ""
                output["main_ev_city"] = ""
                output["main_ev_zip"] = ""
                output["main_ev_lat"] = None
                output["main_ev_long"] = None
                output["registrar_phone"] = ""
                output["main_ev_monday_friday"] = ""
                output["main_ev_sat"] = ""
                output["main_ev_sun"] = ""
                output["ev_county_lookup_link"] = ""
                output["main_ev_distance_miles"] = None
                output["main_ev_state"] = ""
                output["main_ev_county"] = ""
                output["main_ev_statewide_fallback"] = False

            # ------------------------------------------------
            # WRITE JSON FILE
            # ------------------------------------------------

            output_file = OUTPUT_DIR / f"{block_id}.json"

            with output_file.open(
                "w",
                encoding="utf-8"
            ) as json_file:

                json.dump(
                    output,
                    json_file,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )

            successful += 1

            if total % 1000 == 0:
                print(
                    f"Processed {total:,} blocks..."
                )

    print()
    print("Finished!")
    print(f"Rows read: {total:,}")
    print(f"JSON files created: {successful:,}")

    if missing_block_ids:
        print(
            f"Rows skipped because they had no block_id: "
            f"{missing_block_ids:,}"
        )

    if missing_coordinates:
        print(
            f"Blocks with missing coordinates: "
            f"{missing_coordinates:,}"
        )

    print(
        f"Output directory: {OUTPUT_DIR}"
    )


# ------------------------------------------------------------
# RUN THE PROGRAM
# ------------------------------------------------------------

if __name__ == "__main__":
    generate_block_files()