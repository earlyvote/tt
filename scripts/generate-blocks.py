import csv
import json
import math
import shutil
from pathlib import Path


# ------------------------------------------------------------
# FILE LOCATIONS
# ------------------------------------------------------------

BLOCKS_CSV = Path("data/blocks.csv")
EARLY_VOTING_CSV = Path("data/early_voting.csv")

OUTPUT_DIR = Path("build/data/blocks")


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
# LOAD EARLY VOTING LOCATIONS
# ------------------------------------------------------------

def load_early_voting_locations():
    """
    Read the early voting CSV and organize locations by
    state + county.
    """

    required_columns = {
        "state",
        "county",
        "main_ev_name",
        "main_ev_street_address",
        "main_ev_city",
        "main_ev_zip",
        "main_ev_lat",
        "main_ev_long",
        "registrar_phone",
        "main_ev_monday_friday",
        "main_ev_sat",
        "main_ev_sun",
        "county_ev_lookup_link",
    }

    locations_by_state_county = {}
    locations_by_state = []

    with EARLY_VOTING_CSV.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("Early voting CSV has no header row.")

        missing = required_columns - set(reader.fieldnames)

        if missing:
            raise ValueError(
                "Early voting CSV is missing columns: "
                + ", ".join(sorted(missing))
            )

        for row in reader:

            state = clean(row["state"]).upper()
            county = clean(row["county"]).upper()

            lat = to_coordinate(row["main_ev_lat"])
            lon = to_coordinate(row["main_ev_long"])

            # We cannot calculate distance without coordinates.
            if not state or lat is None or lon is None:
                continue

            location = {
                "state": state,
                "county": county,

                "main_ev_name": clean(row["main_ev_name"]),
                "main_ev_street_address": clean(
                    row["main_ev_street_address"]
                ),
                "main_ev_city": clean(row["main_ev_city"]),
                "main_ev_zip": clean(row["main_ev_zip"]),

                "main_ev_lat": lat,
                "main_ev_long": lon,

                "registrar_phone": clean(row["registrar_phone"]),

                "main_ev_monday_friday": clean(
                    row["main_ev_monday_friday"]
                ),
                "main_ev_sat": clean(row["main_ev_sat"]),
                "main_ev_sun": clean(row["main_ev_sun"]),

                "county_ev_lookup_link": clean(
                    row["county_ev_lookup_link"]
                ),
            }

            key = (state, county)

            if key not in locations_by_state_county:
                locations_by_state_county[key] = []

            locations_by_state_county[key].append(location)

            locations_by_state.append(location)

    return locations_by_state_county, locations_by_state


# ------------------------------------------------------------
# FIND CLOSEST EARLY VOTING LOCATION
# ------------------------------------------------------------

def find_closest_early_voting_location(
    block_lat,
    block_lon,
    state,
    county,
    locations_by_state_county,
    locations_by_state,
):
    """
    Find the closest early voting location.

    First searches the same state + county.

    If none exist, searches the entire state.
    """

    state = clean(state).upper()
    county = clean(county).upper()

    candidates = locations_by_state_county.get(
        (state, county),
        []
    )

    statewide_fallback = False

    # If there are no county locations, search the state.
    if not candidates:
        candidates = [
            location
            for location in locations_by_state
            if location["state"] == state
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

    if not EARLY_VOTING_CSV.exists():
        raise FileNotFoundError(
            f"Could not find {EARLY_VOTING_CSV}"
        )

    print("Loading early voting locations...")

    (
        locations_by_state_county,
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
            "county",
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
                    row["county"],
                    locations_by_state_county,
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
                output["county_ev_lookup_link"] = ""
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