import os
import csv
import xml.etree.ElementTree as ET
import sys
from xml.dom import minidom

# Define the necessary namespace URIs for prefixes
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcin": "http://example.com/dcin#",  # placeholder for India-specific extensions
    "foaf": "http://xmlns.com/foaf/0.1/",
    # Custom vocabulary namespace to type/qualify grouped values (Option C)
    "ex": "https://example.com/vocab/"
}

# Special field groups for custom handling
SUBJECT_FIELDS = {"keyword", "sector", "sector_resource", "group"}
IDENTIFIER_FIELDS = {"uuid", "landing_page", "api_url"}

# Known relation subfields (distribution links and API endpoints)
RELATION_FIELDS = {
    "download_url", "xml_download_url", "json_download_url",
    "ods_download_url", "xls_download_url",
    "csv_endpointURL", "json_endpointURL", "xml_endpointURL"
}

# Map each grouped field to a class name in the ex: namespace
SUBJECT_TYPE_MAP = {
    "keyword": "Keyword",
    "sector": "Sector",
    "sector_resource": "SectorResource",
    "group": "Group",
}

IDENTIFIER_TYPE_MAP = {
    "uuid": "UUID",
    "landing_page": "LandingPage",
    "api_url": "ApiURL",
}

RELATION_TYPE_MAP = {
    "download_url": "DownloadURL",
    "xml_download_url": "XmlDownloadURL",
    "json_download_url": "JsonDownloadURL",
    "ods_download_url": "OdsDownloadURL",
    "xls_download_url": "XlsDownloadURL",
    "csv_endpointURL": "CsvEndpointURL",
    "json_endpointURL": "JsonEndpointURL",
    "xml_endpointURL": "XmlEndpointURL",
}

def is_uri(value: str) -> bool:
    if value is None:
        return False
    v = value.strip()
    return v.startswith("http://") or v.startswith("https://") or v.startswith("urn:")

def split_multi_values(raw: str) -> list[str]:
    """
    Split multi-valued cells that may contain commas and/or semicolons.
    """
    if raw is None:
        return []
    raw = str(raw).strip()
    if not raw or raw.lower() in ("na", "n/a"):
        return []
    # Normalize separators
    raw = raw.replace(";", ",")
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]

def add_qualified_value(parent: ET.Element, predicate_tag: str, type_class: str, value: str):
    """
    Implements Option C: property -> blank node with rdf:type + rdf:value.
    Example:
      <dc:subject>
        <rdf:Description>
          <rdf:type rdf:resource="https://example.com/vocab/Keyword" />
          <rdf:value>Some keyword</rdf:value>
        </rdf:Description>
      </dc:subject>
    """
    prop = ET.SubElement(parent, predicate_tag)
    bnode = ET.SubElement(prop, "rdf:Description")

    # rdf:type
    type_elem = ET.SubElement(bnode, "rdf:type")
    type_elem.set("rdf:resource", f"{NS['ex']}{type_class}")

    # rdf:value
    val_elem = ET.SubElement(bnode, "rdf:value")
    if is_uri(value):
        val_elem.set("rdf:resource", value.strip())
    else:
        val_elem.text = value.strip()

def convert_records_to_rdf(records, output_dir="rdf_output"):
    for idx, row in enumerate(records):

        # Skip entirely empty rows
        if not any((v or "").strip() for v in row.values()):
            continue

        # Create RDF root with namespace declarations
        ns_map = {f"xmlns:{prefix}": uri for prefix, uri in NS.items()}
        rdf_root = ET.Element("rdf:RDF", ns_map)

        # Determine subject URI (rdf:about)
        subject_uri = None
        landing_page = (row.get("landing_page") or "").strip()
        uuid_val = (row.get("uuid") or "").strip()

        if landing_page and landing_page.lower() not in ("na", "n/a"):
            subject_uri = landing_page
        elif uuid_val and uuid_val.lower() not in ("na", "n/a"):
            subject_uri = f"urn:uuid:{uuid_val}"

        # Create rdf:Description for the dataset
        description = ET.SubElement(rdf_root, "rdf:Description")
        if subject_uri:
            description.set("rdf:about", subject_uri)

        # Buffer special fields so we can append them at the bottom later
        buffered_subjects = []   # list[(type_class, value)]
        buffered_identifiers = []  # list[(type_class, value)]
        buffered_relations = []  # list[(type_class, value)]

        # Collect SUBJECT values (as qualified typed nodes to append later)
        for sf in SUBJECT_FIELDS:
            raw = row.get(sf)
            for term in split_multi_values(raw):
                buffered_subjects.append((SUBJECT_TYPE_MAP[sf], term))

        # Collect IDENTIFIER values (qualified typed nodes)
        for idf in IDENTIFIER_FIELDS:
            raw = (row.get(idf) or "").strip()
            if not raw or raw.lower() in ("na", "n/a"):
                continue
            buffered_identifiers.append((IDENTIFIER_TYPE_MAP[idf], raw))

        # Collect RELATION values (qualified typed nodes)
        for rf in RELATION_FIELDS:
            raw = (row.get(rf) or "").strip()
            if not raw or raw.lower() in ("na", "n/a"):
                continue
            buffered_relations.append((RELATION_TYPE_MAP[rf], raw))


        # 1) OTHER FIELDS (as-is)

        # Output all other namespaced DC/DCTERMS/DCIN/FOAF fields directly,
        # skipping the grouped fields above.
        for field, value in row.items():
            if value is None:
                continue

            value = str(value).strip()
            if value == "" or value.lower() in ("na", "n/a"):
                continue

            # Skip grouped fields (handled above)
            if field in SUBJECT_FIELDS or field in IDENTIFIER_FIELDS or field in RELATION_FIELDS:
                continue

            # Only write fields that have a namespace prefix (dc:, dcterms:, dcin:, foaf:, etc.)
            if ":" not in field:
                continue

            prefix, local = field.split(":", 1)
            if prefix not in NS:
                # Unknown prefix: skip for safety
                continue

            tag = f"{prefix}:{local}"
            elem = ET.SubElement(description, tag)

            if is_uri(value):
                elem.set("rdf:resource", value)
            else:
                elem.text = value

        # 2) Append buffered special fields at the bottom

        # Order: relation, identifiers, then subjects — all at the end
        for type_class, val in buffered_relations:
            add_qualified_value(description, "dc:relation", type_class, val)

        for type_class, val in buffered_identifiers:
            add_qualified_value(description, "dc:identifier", type_class, val)

        for type_class, val in buffered_subjects:
            add_qualified_value(description, "dc:subject", type_class, val)

        # ---------------------------
        # Output filename
        # ---------------------------
        outfile = None

        if uuid_val and uuid_val.lower() not in ("na", "n/a"):
            outfile = f"{uuid_val}.rdf"

        if not outfile and landing_page and landing_page.lower() not in ("na", "n/a"):
            base = landing_page.rstrip("/").split("/")[-1]
            if base:
                outfile = f"{base}.rdf"

        # NOTE: csv.DictReader keys are literal headers; title is likely "dc:title"
        title_val = (row.get("dc:title") or "").strip()
        if not outfile and title_val:
            safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title_val)
            outfile = f"{safe_title[:50]}.rdf"

        if not outfile:
            outfile = f"dataset{idx + 1}.rdf"

        # ---------------------------
        # Write RDF/XML (pretty-printed)
        # ---------------------------
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, outfile)
        tree = ET.ElementTree(rdf_root)

        try:
            ET.indent(tree, space="  ")  # Python 3.9+
            tree.write(output_path, encoding="utf-8", xml_declaration=True)
        except Exception:
            xml_bytes = ET.tostring(rdf_root, encoding="utf-8")
            pretty_xml = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(pretty_xml)

        print(f"Saved RDF/XML for dataset {idx + 1} to {output_path}")


def read_csv_records(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def main():
    if len(sys.argv) < 2:
        print("Usage: python csv_to_rdf.py <csv_file_or_directory> [output_dir]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "rdf_output"

    # Case 1: Single CSV file
    if os.path.isfile(input_path) and input_path.lower().endswith(".csv"):
        records = read_csv_records(input_path)
        convert_records_to_rdf(records, output_dir)

    # Case 2: Directory containing CSV files
    elif os.path.isdir(input_path):
        for filename in os.listdir(input_path):
            if filename.lower().endswith(".csv"):
                csv_path = os.path.join(input_path, filename)
                records = read_csv_records(csv_path)
                convert_records_to_rdf(records, output_dir)

    else:
        print("Error: Input must be a CSV file or a directory of CSV files.")
        sys.exit(1)


if __name__ == "__main__":
    main()
