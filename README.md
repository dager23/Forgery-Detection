# DocAuth v2 - multi-feature document forgery detection

DocAuth checks certificates, IDs, scans and photos for manipulation. It runs eight independent
forensic tests, fuses their evidence into a single **Accepted / Suspicious / Rejected** verdict
with a 0-100 authenticity score, and shows *where* the document was edited with heatmaps and
region boxes, plus a downloadable PDF report.

Originally built for **Smart India Hackathon 2023**. v2 is a complete rebuild: the v1 repository
contained only a React + Express login shell, and none of the analysis described in its README.

## What it detects

| # | Module | What it looks for |
|---|---|---|
| 1 | **Metadata analysis** | Editing software, capture vs. modification time, ISO/camera fields, EXIF-thumbnail mismatch; for PDFs: incremental revisions, whiteout boxes, text over scans, mixed fonts in a line |
| 2 | **Error level analysis** | Regions that re-compress differently from similar content |
| 3 | **Noise consistency** | Content whose sensor/scanner noise differs from the page (pastes, typed text, whiteout) |
| 4 | **JPEG compression traces** | JPEG ghosts, misaligned 8x8 grids, double compression |
| 5 | **Copy-move detection** | Cloned stamps, signatures or digits (noise-verified, so repeated print isn't flagged) |
| 6 | **Template matching (SSIM)** | Added / missing content compared with a verified original, ignoring variable fields |
| 7 | **SRM-CNN classifier** | CNN whose first layer starts from the 30 SRM high-pass filters; real vs. fake |
| 8 | **Pixel manipulation analyzer** | Two-stream RGB + DCT network producing a per-pixel heatmap |

Modules 1, 2 (SRM-CNN), 3 (pixel analyzer) and 4 (SSIM) implement the four features in the
original README; 2-5 add classical forensics that need no training. Details and limitations are
in [docs/FORENSICS.md](docs/FORENSICS.md); measured accuracy is in
[docs/EVALUATION.md](docs/EVALUATION.md).

## v1 vs v2

| | v1 (2023) | v2 |
|---|---|---|
| Analysis | none in code | 8 modules, fusion, heatmaps, PDF report |
| Backend | Express + MongoDB auth only | FastAPI: auth, uploads, background jobs, templates, admin |
| Auth | token readable by anyone via `/get-token?email=`, hard-coded secret | httpOnly JWT cookie, bcrypt, throttling, roles |
| Frontend | CRA, fixed-pixel layouts, 4 copy-paste error pages, did not compile | React 19 + Vite + TypeScript, responsive, dark mode |
| Inputs | - | JPEG, PNG, TIFF, BMP, WebP, multi-page PDF |
| Quality | no tests | 34 backend + frontend tests, CI, lint |

## Quick start (development)

Requires Python 3.11+ and Node 20+.

```bash
python -m venv .venv
.venv/Scripts/pip install -e "backend[dev]"      # Windows; on Linux/macOS use .venv/bin/pip
cp .env.example .env                              # set DOCAUTH_ADMIN_PASSWORD
.venv/Scripts/docauth seed-demo                   # demo templates + sample files in data/samples
cd frontend && npm install && cd ..
```

Run the API and the web app (or use `scripts/dev.ps1` / `scripts/dev.sh`):

```bash
.venv/Scripts/python -m uvicorn docauth.main:app --reload --reload-dir backend --port 8000
npm --prefix frontend run dev
```

Open <http://localhost:5173> and sign in with the admin account from `.env`, or register a new
user. API docs live at <http://127.0.0.1:8000/docs>.

### Production

```bash
npm --prefix frontend run build          # the API serves frontend/dist itself
DOCAUTH_ENV=production DOCAUTH_SECRET_KEY=... docauth serve --host 0.0.0.0
```

or with Docker:

```bash
DOCAUTH_SECRET_KEY=$(openssl rand -hex 32) DOCAUTH_ADMIN_PASSWORD=... docker compose up --build
```

Data (database, uploads, results) is kept in `DOCAUTH_DATA_DIR` (`/data` in the container).

## Command line

```bash
docauth analyze certificate.jpg                         # verdict + module table
docauth analyze scan.pdf --template original.png --out results/   # with heatmaps
docauth analyze photo.jpg --json                        # full JSON report
docauth create-admin --email you@example.com
```

## Models

The two networks ship as ONNX files in `backend/docauth/forensics/deep/weights/` and run on
CPU with ONNX Runtime. To retrain them on CASIA v2, DocTamper and the synthetic forgery set,
export, and recalibrate the engine, follow [docs/TRAINING.md](docs/TRAINING.md). If the weight
files are missing, those two modules are reported as "not installed" and everything else
still works.

## Project layout

```
backend/   FastAPI service + forensic engine (Python package `docauth`) + tests
frontend/  React + Vite + TypeScript web app
ml/        datasets, models, training, ONNX export, evaluation & calibration
docs/      architecture, forensic methods, training, evaluation
scripts/   dev launchers
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the request flow and security model.

## Tests

```bash
cd backend && ../.venv/Scripts/pytest -q        # API, permissions, forensic modules, CLI
cd frontend && npm test && npm run typecheck
```

## Disclaimer

DocAuth produces forensic indicators, not legal determinations. Confirm decisions that matter
with the issuing authority.
