from pathlib import Path
from collections import Counter
import csv
import gzip
import math
import networkx as nx
import osmnx as ox


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
OSM_DIR = REPO_ROOT / "data" / "osm"
DATA_DIR = REPO_ROOT / "data"

GZIP_FILE = OSM_DIR / "dehradun_geu_10km_radius_roads.osm.gz"
XML_FILE = OSM_DIR / "dehradun_geu_10km_radius_roads.osm"

NODES_OUTPUT = DATA_DIR / "road_nodes.csv"
EDGES_OUTPUT = DATA_DIR / "road_edges.csv"

# Keep road categories suitable for emergency-vehicle routing.
ALLOWED_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "residential",
    "unclassified",
    "living_street",
    "service",
}

DENIED_ACCESS_VALUES = {
    "no",
    "private",
    "customers",
}


# ------------------------------------------------------------
# Prepare the XML file
# ------------------------------------------------------------

def prepare_xml():
    if XML_FILE.exists():
        print(f"Using existing XML: {XML_FILE}")
        return

    if not GZIP_FILE.exists():
        raise FileNotFoundError(
            f"OSM input file not found: {GZIP_FILE}"
        )

    print("Decompressing OSM extract...")

    with gzip.open(GZIP_FILE, "rb") as source:
        with XML_FILE.open("wb") as destination:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                destination.write(chunk)

    print(f"Decompressed file: {XML_FILE}")


# ------------------------------------------------------------
# Emergency-vehicle access filtering
# ------------------------------------------------------------

def allowed_for_emergency_vehicle(data):
    """
    Apply the most specific available access rule.

    emergency=yes explicitly permits emergency access.
    Otherwise, motor_vehicle takes precedence over vehicle,
    which takes precedence over general access.

    motorcar is deliberately not used as the deciding tag:
    ResQTech routes ambulances, fire vehicles and police units,
    not ordinary private cars.
    """

    emergency = data.get("emergency")
    if emergency is not None:
        emergency = str(emergency).strip().lower()

        if emergency == "yes":
            return True

        if emergency in DENIED_ACCESS_VALUES:
            return False

    for tag in ("motor_vehicle", "vehicle", "access"):
        value = data.get(tag)

        if value is not None:
            value = str(value).strip().lower()
            return value not in DENIED_ACCESS_VALUES

    return True


# ------------------------------------------------------------
# Main conversion
# ------------------------------------------------------------

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OSM_DIR.mkdir(parents=True, exist_ok=True)

    prepare_xml()

    print("\nConfiguring OSM tags...")

    required_tags = {
        "access",
        "vehicle",
        "motor_vehicle",
        "motorcar",
        "emergency",
    }

    ox.settings.useful_tags_way = list(
        dict.fromkeys(
            ox.settings.useful_tags_way + sorted(required_tags)
        )
    )

    print("Loading directed road graph from local OSM XML...")
    print("This may take a little time.")

    graph = ox.graph_from_xml(
        str(XML_FILE),
        bidirectional=False,
        simplify=False,
        retain_all=True,
    )

    print("\nOriginal graph loaded.")
    print(f"Original nodes: {graph.number_of_nodes():,}")
    print(f"Original directed edges: {graph.number_of_edges():,}")

    # --------------------------------------------------------
    # Filter edges and collect their endpoint nodes
    # --------------------------------------------------------

    accepted_edges = []
    used_nodes = set()

    highway_counts = Counter()
    excluded_highways = Counter()
    excluded_access = Counter()

    oneway_edge_count = 0

    for source, destination, key, attributes in graph.edges(
        keys=True,
        data=True,
    ):
        highway = attributes.get("highway")

        if isinstance(highway, (list, tuple, set)):
            highway_values = {
                str(value).strip().lower()
                for value in highway
            }
        elif highway is None:
            highway_values = set()
        else:
            highway_values = {
                str(highway).strip().lower()
            }

        if not highway_values or not highway_values.issubset(
            ALLOWED_HIGHWAYS
        ):
            category = (
                ", ".join(sorted(highway_values))
                if highway_values
                else "missing_highway"
            )
            excluded_highways[category] += 1
            continue

        if not allowed_for_emergency_vehicle(attributes):
            access_reason = (
                attributes.get("motor_vehicle")
                or attributes.get("vehicle")
                or attributes.get("access")
                or "restricted"
            )
            excluded_access[str(access_reason).lower()] += 1
            continue

        distance = attributes.get("length")

        if distance is None:
            raise ValueError(
                f"Missing distance on edge {source} -> {destination}"
            )

        distance = float(distance)

        if not math.isfinite(distance) or distance <= 0:
            raise ValueError(
                f"Invalid distance on edge {source} -> {destination}: "
                f"{distance}"
            )

        accepted_edges.append(
            (source, destination, distance)
        )

        used_nodes.add(source)
        used_nodes.add(destination)

        for category in highway_values:
            highway_counts[category] += 1

        if attributes.get("oneway") is True:
            oneway_edge_count += 1

    if not accepted_edges or not used_nodes:
        raise RuntimeError(
            "Filtering produced an empty road network. "
            "No output files were written."
        )

    # --------------------------------------------------------
    # Validate endpoints and coordinates before writing
    # --------------------------------------------------------

    node_rows = []

    for node_id in sorted(used_nodes):
        attributes = graph.nodes[node_id]

        latitude = float(attributes["y"])
        longitude = float(attributes["x"])

        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            raise ValueError(
                f"Invalid coordinates for OSM node {node_id}"
            )

        node_rows.append(
            (node_id, latitude, longitude)
        )

    for source, destination, distance in accepted_edges:
        if source not in used_nodes or destination not in used_nodes:
            raise RuntimeError(
                "An edge references a node missing from the node set."
            )

        if not math.isfinite(distance) or distance <= 0:
            raise RuntimeError("Invalid edge distance detected.")

    # --------------------------------------------------------
    # Connectivity report
    # --------------------------------------------------------

    connectivity_graph = nx.DiGraph()
    connectivity_graph.add_edges_from(
        (source, destination)
        for source, destination, distance in accepted_edges
    )

    weak_components = list(
        nx.weakly_connected_components(connectivity_graph)
    )

    largest_component = (
        max(len(component) for component in weak_components)
        if weak_components
        else 0
    )

    # --------------------------------------------------------
    # Write temporary CSV files first
    # --------------------------------------------------------

    nodes_temp = NODES_OUTPUT.with_suffix(".csv.tmp")
    edges_temp = EDGES_OUTPUT.with_suffix(".csv.tmp")

    with nodes_temp.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            ["node_id", "latitude", "longitude"]
        )

        writer.writerows(node_rows)

    # Sort for reproducible output.
    accepted_edges.sort(
        key=lambda edge: (
            edge[0],
            edge[1],
            edge[2],
        )
    )

    with edges_temp.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            ["source", "destination", "distance"]
        )

        for source, destination, distance in accepted_edges:
            writer.writerow(
                [source, destination, f"{distance:.3f}"]
            )

    # Replace final files only after both temporary files
    # have been written successfully.
    nodes_temp.replace(NODES_OUTPUT)
    edges_temp.replace(EDGES_OUTPUT)

    # --------------------------------------------------------
    # OSM attribution
    # --------------------------------------------------------

    attribution_file = OSM_DIR / "ATTRIBUTION.txt"

    attribution_file.write_text(
        "Road network data derived from OpenStreetMap.\n"
        "© OpenStreetMap contributors\n"
        "https://www.openstreetmap.org/copyright\n\n"
        "OpenStreetMap data is available under the "
        "Open Database License (ODbL) 1.0.\n"
        "https://opendatacommons.org/licenses/odbl/1-0/\n",
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Final report
    # --------------------------------------------------------

    print("\n" + "=" * 58)
    print("RESQTECH OSM ROAD-NETWORK CONVERSION REPORT")
    print("=" * 58)

    print(f"\nOriginal OSM nodes:       {graph.number_of_nodes():,}")
    print(f"Original directed edges:  {graph.number_of_edges():,}")

    print(f"\nExported road nodes:      {len(node_rows):,}")
    print(f"Exported directed edges:  {len(accepted_edges):,}")
    print(f"One-way directed edges:   {oneway_edge_count:,}")

    print("\nIncluded road categories:")
    for category, count in sorted(highway_counts.items()):
        print(f"  {category:<20} {count:>8,}")

    print("\nExcluded road categories:")
    for category, count in sorted(excluded_highways.items()):
        print(f"  {category:<20} {count:>8,}")

    print("\nExcluded access restrictions:")
    if excluded_access:
        for reason, count in sorted(excluded_access.items()):
            print(f"  {reason:<20} {count:>8,}")
    else:
        print("  None")

    print("\nConnectivity:")
    print(f"  Weakly connected components: {len(weak_components):,}")
    print(f"  Largest component nodes:     {largest_component:,}")

    print("\nGenerated files:")
    print(f"  {NODES_OUTPUT}")
    print(f"  {EDGES_OUTPUT}")
    print(f"  {attribution_file}")

    print("\nConversion completed successfully.")
    print("=" * 58)


if __name__ == "__main__":
    main()
