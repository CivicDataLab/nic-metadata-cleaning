from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
import pandas as pd
from collections import Counter
import matplotlib.pyplot as plt
from wordcloud import WordCloud


df = pd.read_csv(r"D:\CDL\OGD\cef25fe2-9231-4128-8aec-2c948fedd43f_d21b5f4697565ad71bae50f3ca17e62a.csv")
col = "KccAns"
text_series = df[col].dropna().astype(str)

#Analyzer engine has default recognizers like US Passport, etc, this can be used to remove those and only use custom ones that can be added
analyzer = AnalyzerEngine(registry=RecognizerRegistry())
#analyzer = AnalyzerEngine()

aadhaar_pattern = Pattern("aadhaar_pattern", r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", 0.9)
aadhaar_recognizer = PatternRecognizer(supported_entity="AADHAAR_NUMBER", patterns=[aadhaar_pattern])
analyzer.registry.add_recognizer(aadhaar_recognizer)

#PAN recognizer
pan_pattern = Pattern("pan_pattern", r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b", 0.9)
pan_recognizer = PatternRecognizer(supported_entity="PAN_CARD", patterns=[pan_pattern])
analyzer.registry.add_recognizer(pan_recognizer)

#Indian Phone Number recognizer (starts with 6–9, 10 digits)
phone_pattern = Pattern("indian_phone_pattern", r"\b[6-9]\d{9}\b", 0.9)
phone_recognizer = PatternRecognizer(supported_entity="INDIAN_PHONE_NUMBER", patterns=[phone_pattern])
analyzer.registry.add_recognizer(phone_recognizer)

# Analyze text
entities_counter = Counter()
all_entities = []

for text in text_series:
    results = analyzer.analyze(text=text, language="en")
    for r in results:
        entities_counter[r.entity_type] += 1
        all_entities.append({
            "text": text,
            "entity": r.entity_type,
            "score": r.score,
            "start": r.start,
            "end": r.end,
            "matched_text": text[r.start:r.end]
        })

# Save results
pii_df = pd.DataFrame(all_entities)
pii_df.to_csv("presidio_pii_entities.csv", index=False)

# Print counts
print("Entity Counts Found:")
for entity, count in entities_counter.items():
    print(f"- {entity}: {count}")

# Word Cloud
all_text = " ".join(text_series)
wordcloud = WordCloud(
    font_path=r"D:\CDL\OGD\noto_sans_hindi\static\NotoSans_Condensed-Regular.ttf",
    background_color="white",
    width=800,
    height=400
).generate(all_text)

plt.figure(figsize=(14, 7))
plt.imshow(wordcloud, interpolation="bilinear")
plt.axis("off")
plt.title("Word Cloud of Hindi Transcript")
plt.show()




import seaborn as sns
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay

# ---------- BAR CHART FOR ENTITY COUNTS ----------
import pandas as pd

# Recompute from saved file just to be safe
pii_df = pd.read_csv("presidio_pii_entities.csv")

entity_counts = pii_df["entity"].value_counts().reset_index()
entity_counts.columns = ["Entity", "Count"]

plt.figure(figsize=(10, 6))
sns.barplot(data=entity_counts, x="Count", y="Entity", palette="magma")
plt.title("Count of PII Entities Detected")
plt.xlabel("Count")
plt.ylabel("Entity")
plt.tight_layout()
plt.show()



# from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
# from presidio_analyzer import RecognizerResult
# import pandas as pd
# import matplotlib.pyplot as plt
# from wordcloud import WordCloud
# from collections import Counter
# import seaborn as sns
# from concurrent.futures import ProcessPoolExecutor, as_completed
# import multiprocessing
# import os

# # ---------- Load Data ----------
# df = pd.read_csv(r"D:\CDL\OGD\cef25fe2-9231-4128-8aec-2c948fedd43f_d21b5f4697565ad71bae50f3ca17e62a.csv")
# col = "KccAns"
# text_series = df[col].dropna().astype(str)

# # ---------- Setup Analyzer with Custom Recognizers ----------
# analyzer = AnalyzerEngine(registry=RecognizerRegistry())

# aadhaar_pattern = Pattern("aadhaar_pattern", r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", 0.9)
# aadhaar_recognizer = PatternRecognizer(supported_entity="AADHAAR_NUMBER", patterns=[aadhaar_pattern])
# analyzer.registry.add_recognizer(aadhaar_recognizer)

# pan_pattern = Pattern("pan_pattern", r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b", 0.9)
# pan_recognizer = PatternRecognizer(supported_entity="PAN_CARD", patterns=[pan_pattern])
# analyzer.registry.add_recognizer(pan_recognizer)

# phone_pattern = Pattern("indian_phone_pattern", r"\b[6-9]\d{9}\b", 0.9)
# phone_recognizer = PatternRecognizer(supported_entity="INDIAN_PHONE_NUMBER", patterns=[phone_pattern])
# analyzer.registry.add_recognizer(phone_recognizer)

# # ---------- Multiprocessing Safe Analyzer Wrapper ----------
# def analyze_text(text):
#     # Instantiate new engine per process (safe multiprocessing)
#     local_analyzer = AnalyzerEngine(registry=RecognizerRegistry())

#     # Re-register recognizers in each subprocess
#     local_analyzer.registry.add_recognizer(aadhaar_recognizer)
#     local_analyzer.registry.add_recognizer(pan_recognizer)
#     local_analyzer.registry.add_recognizer(phone_recognizer)

#     results = local_analyzer.analyze(text=text, language="en")
#     return [{
#         "text": text,
#         "entity": r.entity_type,
#         "score": r.score,
#         "start": r.start,
#         "end": r.end,
#         "matched_text": text[r.start:r.end]
#     } for r in results]

# # ---------- Parallel Analysis ----------
# cpu_count = multiprocessing.cpu_count()
# print(f"Using {cpu_count} CPU cores.")

# all_entities = []
# with ProcessPoolExecutor(max_workers=4) as executor:
#     futures = [executor.submit(analyze_text, text) for text in text_series]
#     for future in as_completed(futures):
#         try:
#             all_entities.extend(future.result())
#         except Exception as e:
#             print("Error analyzing text:", e)

# # ---------- Save Results ----------
# pii_df = pd.DataFrame(all_entities)
# pii_df.to_csv("presidio_pii_entities.csv", index=False)

# # ---------- Entity Counts Plot ----------
# entity_counts = pii_df["entity"].value_counts().reset_index()
# entity_counts.columns = ["Entity", "Count"]

# plt.figure(figsize=(10, 6))
# sns.barplot(data=entity_counts, x="Count", y="Entity", palette="magma")
# for index, row in entity_counts.iterrows():
#     plt.text(row["Count"] + 1, index, row["Count"], va="center")
# plt.title("Count of PII Entities Detected")
# plt.xlabel("Count")
# plt.ylabel("Entity")
# plt.tight_layout()
# plt.show()

# # ---------- Word Cloud ----------
# all_text = " ".join(text_series)
# wordcloud = WordCloud(
#     font_path=r"D:\CDL\OGD\noto_sans_hindi\static\NotoSans_Condensed-Regular.ttf",
#     background_color="white",
#     width=800,
#     height=400
# ).generate(all_text)

# plt.figure(figsize=(14, 7))
# plt.imshow(wordcloud, interpolation="bilinear")
# plt.axis("off")
# plt.title("Word Cloud of Hindi Transcript")
# plt.show()



