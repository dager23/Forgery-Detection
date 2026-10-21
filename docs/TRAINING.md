# Training the deep-learning modules

DocAuth ships two networks, trained with PyTorch and served to the backend as ONNX
(the API only needs `onnxruntime`):

| Model | README module | File | Input → output |
|---|---|---|---|
| `SRMPatchNet` | 2 - ELA / SRM CNN classifier | `classifier.onnx` | `patches` [N,3,128,128] RGB 0..1 → `logits` [N,2] (real, fake) |
| `TwoStreamSegNet` | 3 - Pixel manipulation analyzer | `segmenter.onnx` | `image` [1,3,H,W] RGB 0..1 (H,W multiples of 32) → `mask` [1,1,H,W] logits |

* **SRMPatchNet** - the first convolution is initialised with the 30 SRM high-pass filters
  (Fridrich & Kodovsky's rich models, as in Rao & Ni 2016) followed by truncation, then a small
  CNN. It runs densely over 128 px patches; the top-3 % most suspicious patches are averaged
  ("feature fusion") into the image-level real/fake probability.
* **TwoStreamSegNet** - an ImageNet ResNet-18 RGB stream plus a DCT stream: 8x8 block DCT of
  the JPEG luminance channel, one-hot histograms of the low-frequency coefficients (the
  statistic that reveals double compression) and log-magnitudes. The streams are fused at
  stride 8 and 16 and decoded by an FPN into a per-pixel heatmap.

Crops are always taken at multiples of 8 px and augmentations never resample pixels, so the
JPEG block grid that the DCT stream relies on is preserved.

## 1. Datasets

Everything lives under `data/` (git-ignored). Any source that is missing is skipped.

| Source | Where to put it | Notes |
|---|---|---|
| Synthetic certificates | generated: `python ml/generate_synthetic.py` | 5 000 train / 600 val; text replacement, copy-move, splicing, erasure, inserted text, with pixel masks |
| **CASIA v2.0** | `data/datasets/CASIA2/` | Kaggle `divg07/casia-20-image-tampering-detection-dataset`. The loader searches recursively for `Au/`, `Tp/` and a `*Groundtruth*` folder of `*_gt.png` masks |
| **DocTamper** | `data/datasets/DocTamper/` | From github.com/qcf-568/DocTamper. Keep the LMDB folders (`DocTamperV1-TrainingSet`, `-TestingSet`, `-FCD`, `-SCD`, each with `data.mdb`). Research use only - check its licence |

Splits: CASIA and synthetic use a deterministic hash split (88 % train / 12 % val). DocTamper
uses its own TrainingSet / TestingSet; `--doctamper-limit` subsamples the 120k training images.

## 2. Environment

```bash
python -m venv .venv
.venv/Scripts/pip install -e "backend[dev]"            # Windows (use .venv/bin on Linux/macOS)
.venv/Scripts/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv/Scripts/pip install lmdb onnx onnxscript
```

> **GTX 16xx (TU116/TU117) GPUs** produce NaNs in cuDNN fp16 convolutions. The training scripts
> detect these cards and train in fp32 automatically (`--no-amp` forces it elsewhere). A GTX 1650
> (4 GB) trains the segmenter at batch 6 in ~5 min per 800-iteration epoch.

## 3. Train

```bash
python ml/train_segmenter.py  --sources synthetic,casia2,doctamper --epochs 12 --iters 800 --batch 6
python ml/train_classifier.py --sources synthetic,casia2,doctamper --epochs 10 --iters 500 --batch 96
```

Logs (`log.jsonl`) and checkpoints (`best.pt`, `last.pt`) go to `ml/runs/<run>/`. Use
`--weights 1,1,2` to change how often each source is sampled and `--init ml/runs/.../best.pt`
to fine-tune an existing model (for example after adding DocTamper).

## 4. Export to the backend

```bash
python ml/export_onnx.py segmenter  --ckpt ml/runs/segmenter/best.pt
python ml/export_onnx.py classifier --ckpt ml/runs/classifier/best.pt
```

The exporter verifies ONNX Runtime against PyTorch (refusing to install a model that deviates)
and writes `backend/docauth/forensics/deep/weights/{name}.onnx` + a `{name}.json` sidecar with
the operating threshold, validation metrics and training sources. The API picks new models up
on restart; use **Re-run** on an analysis to re-score it.

## 5. Calibrate and evaluate the whole engine

```bash
python ml/evaluate_engine.py --sources synthetic,casia2,doctamper --n 300 --calibrate
```

This runs the real engine (all modules) on validation images and, with `--calibrate`, fits on
one half and reports on the other:

* each module's operating point - suspicion 0.5 at about 5 % false positives on genuine files,
* a logistic-regression fusion over the module outputs (replacing the default noisy-OR),
* the Accepted / Suspicious / Rejected score thresholds from the genuine-score distribution.

Output: `backend/docauth/forensics/deep/weights/calibration.json` (loaded by the engine) and
`docs/EVALUATION.md`. Re-run calibration whenever you retrain a model or add a data source.
