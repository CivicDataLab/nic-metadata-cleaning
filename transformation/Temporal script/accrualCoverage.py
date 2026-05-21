import pandas as pd
import uuid

# -------------------------------
# Accrual Periodicity → URI Mapping
# -------------------------------
FREQ_TO_URI = {
    "daily": "http://purl.org/cld/freq/daily",
    "weekly": "http://purl.org/cld/freq/weekly",
    "monthly": "http://purl.org/cld/freq/monthly",
    "quarterly": "http://purl.org/cld/freq/quarterly",
    "yearly": "http://purl.org/cld/freq/annual",
    "annual": "http://purl.org/cld/freq/annual",
    "hourly": "http://purl.org/cld/freq/hourly"
}

# -------------------------------
# Accrual Periodicity → ISO 8601 Duration
# -------------------------------
FREQ_TO_DURATION = {
    "daily": "P1D",
    "weekly": "P7D",
    "monthly": "P1M",
    "quarterly": "P3M",
    "yearly": "P1Y",
    "annual": "P1Y",
    "hourly": "PT1H"
}

# -------------------------------
# Normalize Accrual Periodicity text
# -------------------------------
def normalize_Accrual_Periodicity(freq):
    if pd.isna(freq):
        return None
    return str(freq).strip().lower()

# -------------------------------
# Get Accrual Periodicity
# -------------------------------
def get_accrual_periodicity(freq):
    freq = normalize_Accrual_Periodicity(freq)
    return FREQ_TO_URI.get(freq, "NA")

# -------------------------------
# Get Coverage
# -------------------------------
def get_coverage(freq):
    freq = normalize_Accrual_Periodicity(freq)
    duration = FREQ_TO_DURATION.get(freq)

    if duration:
        return f"{duration}^^xsd:duration"
    else:
        return "NA"

# -------------------------------
# Main Function
# -------------------------------
def process_csv(input_file, output_file):
    try:
        # Read CSV instead of Excel
        df = pd.read_csv(input_file)
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # Check required columns
    required_cols = ["Title", "Accrual Periodicity"]

    for col in required_cols:
        if col not in df.columns:
            print(f"Missing required column: {col}")
            return

    # Generate UUIDs
    df["uuid"] = [str(uuid.uuid4()) for _ in range(len(df))]

    # Generate metadata columns
    df["accrual_periodicity"] = df["Accrual Periodicity"].apply(get_accrual_periodicity)
    df["coverage"] = df["Accrual Periodicity"].apply(get_coverage)

    # Final output columns
    output_df = df[[
        "uuid",
        "Title",
        "accrual_periodicity",
        "coverage"
    ]]

    # Save as Excel
    try:
        output_df.to_excel(output_file, index=False)
        print(f"✅ Output file saved as: {output_file}")
    except Exception as e:
        print(f"Error saving file: {e}")

# -------------------------------
# Run Script
# -------------------------------
if __name__ == "__main__":

    input_file = r"C:\Users\HP\scrape\dublin_core_metadata_.csv"
    output_file = r"C:\Users\HP\scrape\accrualCoverage.xlsx"

    process_csv(input_file, output_file)