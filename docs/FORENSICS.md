# Forensic modules

Every module returns a **suspicion** (0 = clean, 1 = manipulated), a **confidence** (how
applicable the test is to this file), human-readable findings, region boxes and visual maps.
The README's per-module 0-10 score is `10 x (1 - suspicion)`: 8-10 green, 4-8 amber, 0-4 red.

## Fusion and verdict

By default each module contributes at most `weight x confidence x suspicion` and contributions
are combined with a noisy-OR (one strong, reliable signal is enough; several weak ones add up).
After `ml/evaluate_engine.py --calibrate` the engine instead uses a logistic regression fitted
on labelled data. The fused authenticity score is `100 x (1 - p)`:

| Score | Verdict | README flag |
|---|---|---|
| >= 70 (calibrated) | **Accepted** | green |
| 40 - 70 | **Suspicious** | amber |
| < 40 | **Rejected** | red |

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

See [TRAINING.md](TRAINING.md). Patch probabilities are fused into a real/fake decision and
drawn as a heatmap.

## 8. Pixel manipulation analyzer (README module 3)

Two-stream RGB + DCT network producing a per-pixel heatmap; the manipulated-pixel percentage
and localised regions are reported. Tiles of 512 px with 64 px overlap are processed at native
resolution with 8-aligned origins so compression traces are preserved.

## Known limitations

* Classical detectors are deliberately conservative on documents (few false alarms); subtle
  digital text edits are mainly caught by the networks and by template matching.
* Heavy downscaling or re-photographing a document destroys compression and noise traces.
* The networks are only as good as their training data. Models trained on the synthetic set
  alone will generalise less well to real forgeries than models trained with CASIA v2 and
  DocTamper - check `docs/EVALUATION.md` and the model sidecar `trained_on` field.
* A verdict is forensic evidence, not proof: confirm critical cases with the issuing authority.
