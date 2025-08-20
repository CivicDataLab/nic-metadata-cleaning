from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
import pandas as pd
from collections import Counter
import matplotlib.pyplot as plt
from wordcloud import WordCloud
from presidio_evaluator.evaluation import Evaluator, ModelError, Plotter
import seaborn as sns
from presidio_analyzer import EntityRecognizer, RecognizerResult
import spacy

class HindiSpacyNERRecognizer(EntityRecognizer):
    def __init__(self, supported_entities=None, name="HindiSpacyNERRecognizer"):
        self.nlp = spacy.load("xx_ent_wiki_sm")  # basic NER model
        self.supported_entities = supported_entities or ["PERSON", "ORG", "GPE"]
        super().__init__(supported_entities=self.supported_entities, name=name)

    def load(self):
        pass 

    def analyze(self, text, entities, nlp_artifacts=None):
        results = []
        doc = self.nlp(text)
        for ent in doc.ents:
            if ent.label_ in self.supported_entities:
                results.append(
                    RecognizerResult(
                        entity_type=ent.label_,
                        start=ent.start_char,
                        end=ent.end_char,
                        score=0.65  # confidence threshold (adjust if needed)
                    )
                )
        return results



df = pd.read_csv(r"D:\CDL\OGD\cef25fe2-9231-4128-8aec-2c948fedd43f_d21b5f4697565ad71bae50f3ca17e62a.csv")
col = "KccAns"
text_series = df[col].dropna().astype(str)


analyzer = AnalyzerEngine(registry=RecognizerRegistry())

#Aadhaar recognizer
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

from presidio_analyzer import AnalyzerEngine

# Reuse existing analyzer
hindi_ner_recognizer = HindiSpacyNERRecognizer()
analyzer.registry.add_recognizer(hindi_ner_recognizer)


# Analyze text
entities_counter = Counter()
all_entities = []



from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

def analyze_text(text):
    local_results = analyzer.analyze(text=text, language="en")
    return [{
        "text": text,
        "entity": r.entity_type,
        "score": r.score,
        "start": r.start,
        "end": r.end,
        "matched_text": text[r.start:r.end]
    } for r in local_results]

# Use all CPU cores
cpu_count = multiprocessing.cpu_count()

print(f"Using {cpu_count} CPU cores")

all_entities = []
entities_counter = Counter()

with ProcessPoolExecutor(max_workers=cpu_count) as executor:
    futures = [executor.submit(analyze_text, text) for text in text_series]

    for future in as_completed(futures):
        try:
            results = future.result()
            all_entities.extend(results)
            for r in results:
                entities_counter[r["entity"]] += 1
        except Exception as e:
            print("Error:", e)



# Save results
pii_df = pd.DataFrame(all_entities)
pii_df.to_csv("presidio_pii_entities.csv", index=False)

# Count and print entity frequencies
entities_counter = Counter(pii_df['entity'])
print("Entity Counts Found:")
for entity, count in entities_counter.items():
    print(f"- {entity}: {count}")

# Prepare data for plotting
entity_counts = pd.DataFrame(entities_counter.items(), columns=['entity', 'count']).sort_values(by='count', ascending=False)

# Plot bar graph of entity counts
plt.figure(figsize=(10, 6))
sns.barplot(data=entity_counts, x='count', y='entity', palette="magma")

# Add value labels to bars
for index, row in entity_counts.iterrows():
    plt.text(row['count'] + 1, index, row['count'], color='black', va='center')

# Titles and labels
plt.title("📊 Count of PII Entities Detected")
plt.xlabel("Count")
plt.ylabel("PII Entity")
plt.tight_layout()
plt.show()

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
