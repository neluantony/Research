# Multi-model city recognition on Colab

Open-weight VLMs run on Google Colab's free T4 GPU. They cannot reach the local
database, so Colab is used purely as an inference worker. The loop is:

```
export bundle (local)  ->  run model (Colab)  ->  import results (local)  ->  score + analyse (local)
```

The stimulus is a 2x2 grid of the four blurred cardinal views (top-left north,
top-right east, bottom-left south, bottom-right west), which is one portable
image every model can take. No web search or tools: the models answer from
their weights only.

## 1. Export the bundle (local)

```
python -m inference export-bundle --out colab/bundle_city_grid
```

This writes the 124 pilot points as grid images plus the prompt, answer schema
and a manifest (no ground truth). Zip it for upload:

```
python -c "import shutil; shutil.make_archive('colab/bundle_city_grid','zip','colab/bundle_city_grid')"
```

## 2. Run a model (Colab)

Open `run_vlm.ipynb` in Colab, pick a **T4 GPU** runtime, run the cells, upload
`bundle_city_grid.zip`. Set `HF_ID` to the model you want (it starts on
`Qwen/Qwen2.5-VL-7B-Instruct`). It writes `responses_<model>.jsonl` and offers
it for download. The run resumes if a session drops.

## 3. Import the results (local)

```
python -m inference import-bundle-results --results responses_qwen2.5-vl-7b.jsonl
python -m inference score --write
python -m inference status
```

The import records the exact HF repo and the resolved commit hash, so each run
is reproducible. Responses link to the same four blurred views, so scoring and
the mental-map analyses run unchanged across every model.

## Models to run (ungated, diverse training corpora)

| short name        | HF repo                          | notes                  |
|-------------------|----------------------------------|------------------------|
| qwen2.5-vl-7b     | Qwen/Qwen2.5-VL-7B-Instruct      | multi-image, Apache-2  |
| idefics2-8b       | HuggingFaceM4/idefics2-8b        | native, Mistral+SigLIP |
| smolvlm-instruct  | HuggingFaceTB/SmolVLM-Instruct   | 2B, light but weak     |

Qwen and the Idefics-family models (idefics2-8b, SmolVLM) work with the notebook
as-is, since they load through the standard `AutoProcessor` and `generate`.
InternVL was dropped: its remote-code tokenizer misbehaves under Colab's
transformers build.
