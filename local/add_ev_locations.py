import csv
import io
import math
import ssl
import urllib.request
import urllib.error
from pathlib import Path

import certifi


# ------------------------------------------------------------
# FILE LOCATIONS
# ------------------------------------------------------------

PEOPLE_CSV = Path("local/people_test.csv")
OUTPUT_CSV = Path("local/people_ev_merged.csv")


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


def haversine_miles(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in miles."""
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


def is_open_now(row):
    """
    Checks if an early voting location is currently open by checking
    if ev_has_delayed_opening is null / empty.
    """
    delayed_opening = clean(row.get("ev_has_delayed_opening"))
    return delayed_opening == ""


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

    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urllib.request.urlopen(request, context=ssl_context) as response:
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
    Read early voting locations from the Google Sheet and group
    them by (ev_state, ev_county_fips).

    Filters out locations that have a non-null
    ev_has_delayed_opening value.
    """

    required_columns = {
        "ev_state",
        "ev_county_fips",
        "ev_lat",
        "ev_long",
        "ev_name",
        "ev_street_address",
        "ev_city",
        "ev_zip",
        "ev_registrar_phone",
        "ev_monday_friday",
        "ev_sat",
        "ev_sun",
        "ev_county_lookup_link",
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

    for row in sheet_rows:
        state = clean(row["ev_state"]).upper()
        fips = clean(row["ev_county_fips"])
        lat = to_number(row["ev_lat"])
        lon = to_number(row["ev_long"])

        # Must have valid coordinates and pass the delayed opening check
        if not state or lat is None or lon is None:
            continue

        if not is_open_now(row):
            continue

        location = {
            "main_ev_name": clean(row["ev_name"]),
            "main_ev_street_address": clean(row["ev_street_address"]),
            "main_ev_city": clean(row["ev_city"]),
            "main_ev_state": state,
            "main_ev_zip": clean(row["ev_zip"]),
            "main_ev_location_phone": clean(row.get("ev_location_phone", "")),
            "registrar_phone": clean(row["ev_registrar_phone"]),
            "main_ev_monday_friday": clean(row["ev_monday_friday"]),
            "main_ev_sat": clean(row["ev_sat"]),
            "main_ev_sun": clean(row["ev_sun"]),
            "ev_county_lookup_link": clean(row["ev_county_lookup_link"]),
            "lat": lat,
            "lon": lon,
        }

        key = (state, fips)
        if key not in locations_by_state_fips:
            locations_by_state_fips[key] = []

        locations_by_state_fips[key].append(location)

    return locations_by_state_fips


# ------------------------------------------------------------
# FIND CLOSEST VOTING LOCATION FOR A PERSON
# ------------------------------------------------------------

def find_closest_ev_location(person_lat, person_lon, state, fips, locations_by_state_fips):
    """Finds the closest open EV location matching state and county FIPS."""
    state = clean(state).upper()
    fips = clean(fips)

    candidates = locations_by_state_fips.get((state, fips), [])

    if not candidates or person_lat is None or person_lon is None:
        return None

    closest = None
    closest_distance = None

    for loc in candidates:
        dist = haversine_miles(person_lat, person_lon, loc["lat"], loc["lon"])
        if closest_distance is None or dist < closest_distance:
            closest_distance = dist
            closest = loc

    return closest


# ------------------------------------------------------------
# MAIN PROCESS
# ------------------------------------------------------------

def merge_people_and_early_voting():
    print("Loading open early voting locations from Google Sheet...")
    locations_by_state_fips = load_early_voting_locations()

    ev_target_fields = [
        "main_ev_name",
        "main_ev_street_address",
        "main_ev_city",
        "main_ev_state",
        "main_ev_zip",
        "main_ev_location_phone",
        "registrar_phone",
        "main_ev_monday_friday",
        "main_ev_sat",
        "main_ev_sun",
        "ev_county_lookup_link",
    ]

    with PEOPLE_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        fieldnames = list(reader.fieldnames or []) + ev_target_fields

        rows_to_write = []

        for row in reader:
            p_lat = to_number(row.get("latitude") or row.get("block_latitude"))
            p_lon = to_number(row.get("longitude") or row.get("block_longitude"))
            p_state = row.get("state", "")
            p_fips = row.get("county_fips", "")

            closest_loc = find_closest_ev_location(
                p_lat, p_lon, p_state, p_fips, locations_by_state_fips
            )

            if closest_loc:
                for field in ev_target_fields:
                    row[field] = closest_loc[field]
            else:
                for field in ev_target_fields:
                    row[field] = ""

            rows_to_write.append(row)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_to_write)

    print(f"Successfully generated merged CSV with {len(rows_to_write):,} records at: {OUTPUT_CSV}")


if __name__ == "__main__":
    merge_people_and_early_voting()