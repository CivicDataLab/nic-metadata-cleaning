from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import TransformersNlpEngine
from presidio_anonymizer import AnonymizerEngine
text = "मेरा नाम प्रज्ञा है और मेरा फ़ोन नंबर 9783025207 है। मेरा क्रेडिट कार्ड नंबर 8619-3997-5478-1234 है।"

# Define which transformers model to use
model_config = [{"lang_code": "en", "model_name": {
    "spacy": "en_core_web_sm",  # use a small spaCy model for lemmas, tokens etc.
    "transformers": "dslim/bert-base-NER"
    }
}]

nlp_engine = TransformersNlpEngine(models=model_config)

# Set up the engine, loads the NLP module (spaCy model by default) 
# and other PII recognizers
analyzer = AnalyzerEngine(nlp_engine=nlp_engine)

# Call analyzer to get results
results = analyzer.analyze(text=text, language='en')
print(results)

# Analyzer results are passed to the AnonymizerEngine for anonymization

anonymizer = AnonymizerEngine()

anonymized_text = anonymizer.anonymize(text=text, analyzer_results=results)

print(anonymized_text)