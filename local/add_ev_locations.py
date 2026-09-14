import csv
import math
from pathlib import Path


# ------------------------------------------------------------
# FILE LOCATIONS
# ------------------------------------------------------------

PEOPLE_CSV = Path("local/people_test.csv")
EARLY_VOTING_CSV = Path("local/ev_locations_test.csv")
OUTPUT_CSV = Path("local/people_ev_merged.csv")


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
# LOAD EARLY VOTING LOCATIONS
# ------------------------------------------------------------

def load_early_voting_locations():
    """
    Read early voting locations and group them by (ev_state, ev_county_fips).
    Filters out locations that have a non-null ev_has_delayed_opening value.
    """
    locations_by_state_fips = {}

    with EARLY_VOTING_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
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
    print("Loading open early voting locations...")
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