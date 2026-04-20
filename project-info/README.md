# Handwriting Studio v2.1

Convert typed text into realistic handwritten notes on various paper templates including MJCET Assignment Sheets, ruled paper, grid paper, and plain paper.

## Features

- **Realistic handwriting** using the Caveat font family with per-glyph noise transforms
- **Paper templates**: Plain, Ruled, Grid, MJCET Answer Sheet, MJCET Assignment Sheet
- **Scanner effect**: Adds paper grain, vignette, and warmth shift for authentic scanned look
- **Export**: PNG (per-page) and PDF output
- **Live preview**: Fast low-res preview with full-res export
- **Performance optimized**: ~22ms scanner effect via uint16 fixed-point math, cached grain/LUTs
- **Celery-ready**: Background export processing with graceful thread fallback

## Project Structure

```
handwriting-studio/
├── backend/
│   ├── main.py              # FastAPI app (uvicorn entry point)
│   ├── renderer.py          # Core rendering engine (scanner, noise, templates)
│   ├── noise.py             # Per-glyph human variability engine
│   ├── models.py            # Pydantic request/response models
│   ├── document_parser.py   # Plain text -> DocumentNode tree
│   ├── tasks.py             # Celery background tasks
│   ├── requirements.txt     # Python dependencies
│   └── fonts/               # Download Caveat fonts here (see below)
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Main app component
│   │   ├── App.css          # Styles
│   │   ├── main.tsx         # React entry point
│   │   ├── lib/
│   │   │   └── types.ts     # Shared TypeScript types
│   │   └── components/
│   │       └── SettingsPanel.tsx  # Settings sidebar
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── README.md
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Caveat font files (see below)

### 1. Download Fonts

```bash
# Create fonts directory
mkdir backend/fonts

# Download Caveat font family (OFL licensed, free for use)
# Option A: From Google Fonts
wget https://fonts.google.com/download?family=Caveat -O caveat.zip
unzip caveat.zip -d backend/fonts/

# Option B: Manual download
# Visit https://fonts.google.com/specimen/Caveat and download
# Place Caveat-Regular.ttf, Caveat-SemiBold.ttf, Caveat-Bold.ttf in backend/fonts/
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Activate (Linux/Mac)
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev

# Or build for production
npm run build
```

### 4. Access the App

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/preview` | Render low-res preview (JPEG) |
| POST | `/api/export` | Start export job (PNG/PDF) |
| GET | `/api/export/{job_id}` | Check export status |
| GET | `/api/download/{job_id}` | Download completed file |

## Template Options

| Template | Description |
|----------|-------------|
| `plain` | No guidelines |
| `ruled` | Blue horizontal lines |
| `grid` | Green grid lines |
| `mjcet` | MJCET Answer Sheet with Name/Roll No/Subject/Date fields |
| `mjcet_assignment` | MJCET Assignment Sheet with header bar and ruled body |

## Backend Patches (v2.0 -> v2.1)

### v2.1 - New MJCET Assignment Sheet Template
- Added `mjcet_assignment` paper template matching real MJCET Assignment/Tutorial Sheets
- Three-section header bar: MJCET | Assignment/Tutorial Sheet | Page No.
- Red margin line + ruled body area
- Margin auto-clamp prevents text overlapping the 85px header

### v2.0 - Five Performance & Bug Fixes

| # | Fix | Improvement |
|---|-----|-------------|
| 1 | **Scanner cache** | Rebuilt grain/LUTs/vignette once per canvas size, not per page. Hot path: **~22ms** (was 102ms) |
| 2 | **Page slant** | Correct `page_slant_deg` applied via `rotate()` with background fill |
| 3 | **MJCET header layout** | Fixed field ordering: Name \| Roll No (top), Subject \| Date (bottom). Proportional underline guides |
| 4 | **RGBA->PDF** | img2pdf now receives pre-converted RGB, fixing "RGBA cannot be saved as PDF" error |
| 5 | **Celery ping** | `celery_app.control.ping()` checks broker reachability; falls back to threads if Redis down |

## License

MIT License - Font files remain under their respective licenses (Caveat: SIL OFL 1.1).
