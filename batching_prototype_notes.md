# Batched PII Detection — Prototype Notes

Goal: test whether **batched NER inference** improves detection quality vs. **per-cell calls**, before committing to the full GPU rewrite.

## What you're actually testing

You're testing two independent things — don't conflate them:

1. **Speed:** batching reduces overhead per text. Big win on GPU, modest on CPU.
2. **Detections:** batching changes *how* tokenizer truncation, padding, and model context work. Detection counts can shift slightly (usually negligible, occasionally meaningful).

For a CPU prototype, **detection equivalence is the question**. If batched and per-cell give the same entities, you're safe to go ahead with the GPU rewrite. If they diverge, you need to understand why before scaling.

## The core change (one sentence)

Replace `pipe(text)` called N times with `pipe(list_of_texts, batch_size=K)` called once — the HF pipeline handles the batching internally.

## Per-cell vs. batched — code shape

**Per-cell (current):**
```python
for text in texts:
    outputs = pipe(text)        # one call per text
    process(outputs)
```

**Batched (proposed):**
```python
all_outputs = pipe(texts, batch_size=32)   # one call, list in -> list-of-lists out
for outputs in all_outputs:
    process(outputs)
```

That's it. Output structure changes from `list[entity]` to `list[list[entity]]`, indexed parallel to the input texts.

## Minimal prototype script

Use this to A/B test on your CPU machine. Pick ~50–200 representative texts from one of your CSVs.

```python
from transformers import pipeline as hf_pipeline
import time

pipe = hf_pipeline(
    "token-classification",
    model="ai4bharat/IndicNER",
    aggregation_strategy="simple",
    device=-1,  # CPU
)

texts = [...]  # your sample list of strings

# --- Per-cell run ---
t0 = time.time()
per_cell = [pipe(t) for t in texts]
t_per_cell = time.time() - t0

# --- Batched run ---
t0 = time.time()
batched = pipe(texts, batch_size=16)
t_batched = time.time() - t0

# --- Compare ---
print(f"Per-cell: {t_per_cell:.2f}s | Batched: {t_batched:.2f}s")

def normalize(results):
    """Flatten + sort so order doesn't affect comparison."""
    out = []
    for i, ents in enumerate(results):
        for e in ents:
            out.append((i, e["entity_group"], e["start"], e["end"], e["word"]))
    return sorted(out)

a = normalize(per_cell)
b = normalize(batched)

print(f"Per-cell entities: {len(a)} | Batched entities: {len(b)}")
print(f"Identical: {a == b}")

# If not identical, find diffs
if a != b:
    only_a = set(a) - set(b)
    only_b = set(b) - set(a)
    print(f"Only in per-cell: {len(only_a)}")
    print(f"Only in batched:  {len(only_b)}")
    for x in list(only_a)[:5]:
        print("  per-cell only:", x)
    for x in list(only_b)[:5]:
        print("  batched only:", x)
```

## What to expect on CPU

- **Speed:** batched will be slightly faster (10–30%), not dramatically. CPU doesn't benefit much from batching — the win is on GPU. Don't draw speed conclusions from this prototype.
- **Detections:** for short texts (typical CSV cells, < 100 tokens), per-cell and batched should produce **identical** entities. If they don't, see "Gotchas" below.

## Gotchas that can change detections

1. **Truncation length.** Batched mode pads to the longest text in the batch. If a text is longer than `model_max_length` (512 for BERT), it gets truncated — entities past that point are lost. Set explicitly:
   ```python
   pipe.tokenizer.model_max_length = 512
   ```
   Same applies in per-cell mode, but batches expose it more often because one long text can't hide.

2. **`aggregation_strategy`.** Keep this identical between runs. `"simple"` is what your code uses — fine.

3. **Empty / whitespace-only strings.** `pipe("")` returns `[]`; `pipe([""])` returns `[[]]`. Filter empties before batching to keep indices aligned, or accept the empty inner lists.

4. **Score differences in floating point.** Batched runs may produce scores that differ from per-cell at the 5th–6th decimal place due to padding affecting attention. Entity boundaries should still match. Don't compare on `score` equality — compare on `(start, end, label)`.

## What this test does NOT tell you

- **GPU speedup** — that only shows up on actual GPU hardware. Expect 30–80× on a T4 with `batch_size=64` for IndicNER.
- **End-to-end pipeline impact** — Presidio adds its own per-cell loop, regex recognizers, etc. Batching only the HF pipe helps the NER step; the rest stays the same.
- **spaCy batching** — `en_core_web_sm` is a different beast (`nlp.pipe()`, not HF). Test that separately if relevant.

## Decision rule

- **Identical detections + reasonable speed:** ship it. Move to the GPU rewrite.
- **Detection diverges significantly:** investigate truncation and `model_max_length` first. 90% of the time it's that.
- **Detections match but you want to be paranoid:** run on a larger sample (1000+ texts) and check on a per-entity-type basis (PERSON, LOCATION, ORG separately).
