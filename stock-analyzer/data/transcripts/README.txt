Drop transcript files in this folder. The tool will index them and show ticker
mentions on the relevant stock detail pages (informational only — does NOT
feed verdict scoring, same policy as the Telegram research feed).

Supported formats:
  .txt  - plain text (paste from Otter, Notion, your own notes)
  .md   - markdown notes
  .vtt  - WebVTT subtitles (Zoom / Google Meet exports)
  .json - Fireflies / Otter JSON exports (auto-detects 'sentences' / 'transcript' shapes)

Filenames become the displayed title (underscores/hyphens converted to spaces).

If you add new files, click "Recompute" or call:
  curl -X POST http://127.0.0.1:5000/api/transcripts/invalidate

…to drop the cache so the next stock-detail visit re-scans.
