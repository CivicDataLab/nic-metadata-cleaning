from nltk.corpus import wordnet
import nltk


# nltk.download('wordnet')
synonyms = []

for syn in wordnet.synsets("post", pos=wordnet.NOUN):
    for lm in syn.lemmas():
             synonyms.append(lm.name())

print (set(synonyms))

