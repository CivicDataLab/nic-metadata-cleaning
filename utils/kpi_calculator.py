import pandas as pd

# === Step 1: Load dataset ===
df = pd.read_csv("sample_datasets_metadata/nic_sample_dataset.csv")  # Replace with your actual dataset path

# === Step 2: Define fields from metadata mapping ===
mandatory_fields = [
    'title', 'cdos_state_ministry', 'sector', 'ministry_department', 'created',
    'changed', 'resource_category','govt_type','catalog_title'
]

controlled_fields = [
    'cdos_state_ministry', 'sector', 'sector_resource', 'ministry_department',
    'created', 'published', 'changed', 'resource_category',
    'Duration of Date (from- to)', 'govt_type', 'Access Type (on dataset creation page)',
    'frequency', 'field_show_export', 'field_from_api', 'fied_resource_type',
    'sector_resource', 'field_high_value_dataset', 'is_api_available'
]

# === Step 3: Define controlled vocabularies ===
controlled_vocab = {
    "govt_type": ["Central", "State"],
    "Access Type (on dataset creation page)": ["Public", "Restricted", "Private"],
    "frequency": [
        "irregular", "daily", "weekly", "fortnightly", "monthly", "quarterly",
        "biannual", "annual", "continual"
    ],
    "field_show_export": ["TRUE", "FALSE"],
    "field_from_api": ["TRUE", "FALSE"],
    "field_high_value_dataset": ["TRUE", "FALSE"],
    "is_api_available": ["TRUE", "FALSE"]
    # Add more if needed
}

# === Step 4: KPI 1 - Mandatory field completeness ===
mandatory_filled = df[mandatory_fields].notna().all(axis=1)
kpi1 = mandatory_filled.sum() / len(df) * 100

# === Step 5: KPI 2 - Controlled vocab compliance ===
def check_controlled(field, allowed_values):
    if field not in df.columns:
        return 0.0
    valid = df[field].dropna().astype(str).str.strip().isin(allowed_values)
    return valid.sum() / len(df) * 100

kpi2_results = {}
for field in controlled_fields:
    if field in controlled_vocab:
        kpi2_results[field] = check_controlled(field, controlled_vocab[field])
    else:
        kpi2_results[field] = None  # No vocab defined, skipped

# === Step 6: Print results ===
print(f"\nKPI 1: % of rows with all mandatory fields filled = {kpi1:.2f}%")
print("\nKPI 2: % of values compliant with controlled vocabularies:")
for field, pct in kpi2_results.items():
    if pct is None:
        print(f"  - {field}: [Skipped, no controlled vocab defined]")
    else:
        print(f"  - {field}: {pct:.2f}%")
