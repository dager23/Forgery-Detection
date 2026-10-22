# Forensic modules

Every module returns a **suspicion** (0 = clean, 1 = manipulated), a **confidence** (how
applicable the test is to this file), human-readable findings, region boxes and visual maps.
The README's per-module 0-10 score is `10 x (1 - suspicion)`: 8-10 green, 4-8 amber, 0-4 red.

## Fusion and verdict

Without calibration each module contributes at most `weight x confidence x suspicion` and the
contributions are combined with a noisy-OR (one strong, reliable signal is enough; several weak
ones add up). `ml/evaluate_engine.py --calibrate` fits, on labelled data:

1. each module's **operating point** - suspicion 0.5 at about 5 % false positives on genuine files;
2. a **logistic-regression fusion** over `confidence x log-odds(suspicion)` per module, with
   weights constrained to be non-negative (a module that flags a file never makes it look more
   genuine; skipped modules contribute 0);
3. the **verdict thresholds** on the fused authenticity score `100 x (1 - p)`:

| Score | Verdict | README flag |
|---|---|---|
| >= authentic threshold (default 70) | **Accepted** | green |
| between the thresholds | **Suspicious** | amber |
| < tampered threshold (default 40) | **Rejected** | red |

The calibrated values live in `backend/docauth/forensics/deep/weights/calibration.json`; the
measured accuracy (cross-fitted, so no page is scored by a calibration that saw it) is in
[EVALUATION.md](EVALUATION.md).

A module that crashes is reported as `error` and excluded; it never sinks the whole analysis.

## 1. Metadata analysis (README module 1)

* **Images** - EXIF `Software`, XMP `CreatorTool` / `softwareAgent` matched against known
  editors (Photoshop, GIMP, Canva, Snapseed, PicsArt...); XMP edit history; Photoshop resource
  blocks; `DateTimeOriginal` vs `DateTime` (capture vs modification); camera make without ISO or
  capture time (the README's ISO check); EXIF thumbnail compared with the image by SSIM (a
  mismatch means the picture changed after the thumbnail was written); JPEG quality estimated
  from the quantisation table.
* **PDFs** - producer/creator tools; creation vs modification date; **incremental updates**
  (content appended after the original was issued); **whiteout** (white rectangles drawn over a
  scanned page, especially with new text on top); visible digital text over a scan; text spans
  whose font or size differs from the rest of their line (typical of an edited value);
  annotation overlays; embedded scripts.
* Weighted modestly: missing metadata is common (scans, chat apps) and only lowers confidence.

## 2. Error level analysis (README module 2, classical part)

The page is re-saved at JPEG quality 90 (aligned to the original 8x8 grid) and the luminance
error is measured per 16 px block. Raw ELA mostly highlights edges and text, so each block is
compared only with blocks of similar edge density (robust z-score within gradient quantiles).
Compact clusters of outlier blocks become regions.

## 3. Noise consistency

Sensor/scanner noise is estimated per 32 px block from a median-filter residual (edges
excluded) and compared with blocks of similar brightness. Pasted content and digitally typed
text carry a different (usually lower) noise level. Perfectly uniform patches on otherwise noisy
paper are reported as possible whiteout. Confidence drops on near noise-free images (digital
originals), where the test is not informative.

## 4. JPEG compression traces

* **JPEG ghosts** (Farid 2009): re-compressing at qualities 50-95 reveals regions that were
  previously compressed at a different quality (low error at that quality) - and, when the page
  as a whole shows an earlier compression, regions that *lack* it (inserted after the first save).
* **Block-grid alignment**: content pasted from another JPEG usually keeps its own, misaligned
  8x8 grid.
* **Grid offset / double compression** are reported as information (cropping and re-saving are
  not forgery by themselves).
* Edge pixels are excluded and thin strip-shaped clusters (ruled lines, borders) are discarded.

## 5. Copy-move detection

SIFT keypoints are matched against the same image (generalised 2-NN ratio test) and groups of
matches sharing one similarity transform are found with iterative RANSAC. Documents repeat
glyphs and words legitimately, so every candidate is **verified by residual correlation**: a real
clone copies the paper/sensor noise too, while repeated print has independent noise.

## 6. Template matching with SSIM (README module 4)

The page is aligned to a verified original of the same document type (SIFT + RANSAC homography,
so slight rotation/scale from scanning is undone), illumination is normalised, and an SSIM
dissimilarity map is combined with "ink" difference maps. The template's **variable fields**
(name, photo, dates, serials - drawn in the template editor) are ignored. Remaining differences
are boxed as *added*, *missing* or *altered* content. Without an explicit template the engine
tries to recognise one of the registered templates automatically.

## 7. SRM-CNN classifier (README module 2)

See [TRAINING.md](TRAINING.md). The most suspicious patch decides the page's real/fake
evidence (log-odds); all patch probabilities are drawn as a heatmap. Trained on synthetic data
only, it is the weakest of the networks at page level - the calibrated fusion weights it
accordingly.

## 8. Pixel manipulation analyzer (README module 3)

Two-stream RGB + DCT network producing a per-pixel heatmap; the manipulated-pixel percentage
and localised regions are reported. The page evidence is the log-odds of the 99.99th-percentile
pixel probability: a forged value can cover 0.1 % of a page, so area must not dilute it, and the
percentile ignores single noisy pixels. Tiles of 512 px with 64 px overlap are processed at native
resolution with 8-aligned origins so compression traces are preserved.

## Known limitations

* Classical detectors are deliberately conservative on documents (few false alarms); subtle
  digital text edits are mainly caught by the networks and by template matching.
* Heavy downscaling or re-photographing a document destroys compression and noise traces.
* The networks are only as good as their training data. Models trained on the synthetic set
  alone will generalise less well to real forgeries than models trained with CASIA v2 and
  DocTamper - check `docs/EVALUATION.md` and the model sidecar `trained_on` field.
* A network that has only seen documents (`"domain": "documents"` in its sidecar) is unreliable
  on natural photos - the synthetic-only segmenter flags clean photos. The engine therefore
  scales its confidence by how document-like the page is (light, unsaturated paper) and says so
  in the module summary; training with CASIA v2 removes this restriction.
* A verdict is forensic evidence, not proof: confirm critical cases with the issuing authority.
