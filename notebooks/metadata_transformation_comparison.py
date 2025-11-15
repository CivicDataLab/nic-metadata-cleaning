import argparse
import csv
import os
from typing import Dict, List, Sequence


def readData(path: str) -> Sequence[Dict[str, str]]:
    """Read CSV data as a list of rows (dicts)."""
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({k: (v if v is not None else "") for k, v in row.items()})
        return rows


def pickLevelColumns(columns: List[str]) -> Dict[str, List[str]]:
    """Pick simple column groups for Catalog, Dataset, Distribution levels.

    Heuristic grouping based on common DCAT/Dublin Core fields present in the file.
    """
    colset = [c.strip() for c in columns]

    catalog_keys = {"dcat:incatalog", "dcat:datasetseries", "dcat:inseries"}
    dataset_like = {
        "dcterms:title",
        "dcterms:description",
        "dcat:theme",
        "dcterms:created",
        "dcterms:issued",
        "dcterms:modified",
        "dcterms:type",
        "dcterms:spatial",
        "dcterms:temporal",
        "dcterms:accessright",
        "dcterms:license",
        "dcterms:language",
        "dcat:keyword",
        "dcterms:publisher",
        "dcterms:creator",
        "dcat:contactpoint",
    }
    distribution_like = {
        "dcat:downloadurl",
        "dcat:accessurl",
        "dcat:mediatype",
        "dcat:bytesize",
        "dcat:endpointdescription",
        "foaf:depiction",
    }

    def matchSet(names: List[str], targets: set) -> List[str]:
        picked: List[str] = []
        low = [n.lower() for n in names]
        for i, nlow in enumerate(low):
            for t in targets:
                if t in nlow:
                    picked.append(names[i])
                    break
        return picked

    catalog_cols = matchSet(colset, catalog_keys)
    dataset_cols = matchSet(colset, dataset_like)
    distribution_cols = matchSet(colset, distribution_like)

    return {
        "Catalog": catalog_cols,
        "Dataset": dataset_cols,
        "Distribution": distribution_cols,
    }


def isNonEmpty(value: str) -> bool:
    v = (value or "").strip().lower()
    return v not in {"", "nan", "none", "intentionally kept blank"}


def computeTes(rows: Sequence[Dict[str, str]], levelCols: Dict[str, List[str]]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    total_rows = len(rows)
    for level, cols in levelCols.items():
        if not cols or total_rows == 0:
            out.append({"Level": level, "TES": 0.0})
            continue
        non_empty = 0
        total_cells = total_rows * len(cols)
        for r in rows:
            for c in cols:
                non_empty += 1 if isNonEmpty(r.get(c, "")) else 0
        score = non_empty / total_cells if total_cells else 0.0
        out.append({"Level": level, "TES": score})
    return out


def writeCsv(rows: List[Dict[str, float]], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Level", "TES"])
        writer.writeheader()
        for r in rows:
            writer.writerow({"Level": r["Level"], "TES": r["TES"]})


def plotTes(rows: List[Dict[str, float]], path: str) -> None:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        # Matplotlib not available; skip plotting gracefully
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plt.figure(figsize=(6, 4))
    levels = [r["Level"] for r in rows]
    values = [r["TES"] for r in rows]
    plt.bar(levels, values, color=["#4C78A8", "#F58518", "#54A24B"])
    plt.ylabel("Transformation Effort Score")
    plt.ylim(0, 1)
    for i, v in enumerate(values):
        plt.text(i, v + 0.02, f"{v:.2f}", ha="center")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def run(inputPath: str, csvOut: str, pngOut: str) -> None:
    data = readData(inputPath)
    columns = list(data[0].keys()) if data else []
    groups = pickLevelColumns(columns)
    tes = computeTes(data, groups)
    writeCsv(tes, csvOut)
    plotTes(tes, pngOut)


def main():
    parser = argparse.ArgumentParser(description="Compute simple transformation effort scores by level.")
    parser.add_argument(
        "--input",
        default=os.path.join("..", "data", "original", "metadata_transformation.csv"),
        help="Path to metadata transformation CSV",
    )
    parser.add_argument(
        "--csvout",
        default=os.path.join("results", "kpi_result", "transformation_effort_score.csv"),
        help="Path to write TES CSV",
    )
    parser.add_argument(
        "--pngout",
        default=os.path.join("results", "transformation_effort_score.png"),
        help="Path to write TES plot PNG",
    )
    args = parser.parse_args()
    run(args.input, args.csvout, args.pngout)


if __name__ == "__main__":
    main()
