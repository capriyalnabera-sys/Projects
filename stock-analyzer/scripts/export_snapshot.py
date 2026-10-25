"""Export the website as ONE self-contained HTML file.

Renders the main pages from the current cached data (no server needed),
stitches them into a single file with working in-page navigation, and
disables anything that needs the live server (refresh buttons, forms,
stock-detail links). Open the result in any browser, on any device, or
share it — it's a frozen snapshot.

Run from the stock-analyzer folder:
    python scripts/export_snapshot.py                 # -> snapshot_<date>.html
    python scripts/export_snapshot.py --out my.html --note "Sample data"
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# (path, nav href it stands in for, label)
PAGES = [
    ("/", "/", "Recommendations"),
    ("/opportunities", "/opportunities", "Opportunities"),
    ("/fno/NIFTY", "/fno", "F&O · NIFTY"),
    ("/fno/BANKNIFTY", "/fno/BANKNIFTY", "F&O · BANK NIFTY"),
    ("/market", "/market", "Market Pulse"),
]

MAIN_RE = re.compile(r'<main class="wrap" id="main-content">(.*?)</main>', re.S)

SNAPSHOT_JS = r"""
<script>
(function () {
  var MAP = %(map)s;   // server path -> section id
  var sections = Array.prototype.slice.call(document.querySelectorAll('.snap-page'));

  function show() {
    var id = (location.hash || '').slice(1);
    if (!document.getElementById(id)) id = sections[0].id;
    sections.forEach(function (s) { s.hidden = s.id !== id; });
    document.querySelectorAll('.nav-link').forEach(function (a) {
      var on = a.getAttribute('href') === '#' + id;
      a.classList.toggle('active', on);
    });
    // The browser jumps to the #section anchor (under the sticky header)
    // after this runs on load — defer so the page always opens at the top.
    setTimeout(function () { window.scrollTo(0, 0); }, 0);
  }
  window.addEventListener('load', function () { setTimeout(function () { window.scrollTo(0, 0); }, 0); });

  // Internal links: in-page jump if the page is in the snapshot, else inert.
  document.querySelectorAll('a[href^="/"]').forEach(function (a) {
    var path = a.getAttribute('href').split('?')[0].split('#')[0];
    var target = MAP[path] || (path.indexOf('/fno') === 0 ? MAP['/fno'] : null);
    if (target) { a.setAttribute('href', '#' + target); }
    else {
      if (a.classList.contains('nav-link')) { a.style.display = 'none'; return; }
      a.removeAttribute('href');
      a.title = 'Available in the live app';
      a.style.cursor = 'default';
    }
  });
  // Anything that needs the server is disabled in a static file.
  document.querySelectorAll('button[onclick]').forEach(function (b) {
    b.disabled = true; b.title = 'Available in the live app'; b.style.opacity = '0.5';
  });
  document.querySelectorAll('select[onchange]').forEach(function (s) {
    s.removeAttribute('onchange'); s.disabled = true;
  });
  document.querySelectorAll('form').forEach(function (f) {
    f.addEventListener('submit', function (e) { e.preventDefault(); });
  });

  window.addEventListener('hashchange', show);
  show();
})();
</script>
"""

BANNER = """
<div style="background:var(--accent-soft);color:var(--text-soft);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:9px 14px;margin-bottom:18px;font-size:12px;
            display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
  <i data-lucide="camera" aria-hidden="true"></i>
  <b style="color:var(--text);">Snapshot</b> generated {when} · static copy — refresh buttons
  and stock-detail links work only in the live app.{note}
</div>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None, help="output file (default snapshot_<date>.html)")
    ap.add_argument("--note", default="", help="extra text for the snapshot banner")
    args = ap.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    from src.web import app

    client = app.test_client()
    shell, sections, path_map = None, [], {}
    for i, (path, nav_href, label) in enumerate(PAGES):
        print(f"  rendering {label} ({path}) …", flush=True)
        r = client.get(path)
        if r.status_code != 200:
            print(f"    skipped: HTTP {r.status_code}")
            continue
        page = r.data.decode("utf-8")
        m = MAIN_RE.search(page)
        if not m:
            print("    skipped: no main content found")
            continue
        sid = f"page-{i}"
        path_map[nav_href] = sid
        path_map.setdefault(path, sid)
        if shell is None:
            shell = page
        sections.append(f'<section class="snap-page" id="{sid}" aria-label="{html.escape(label)}">'
                        f'{m.group(1)}</section>')

    if shell is None:
        sys.exit("Nothing rendered — is the analysis cache empty? Run a refresh first.")

    when = datetime.now().strftime("%d %b %Y, %H:%M")
    note = f" <b>{html.escape(args.note)}</b>" if args.note else ""
    body = BANNER.format(when=when, note=note) + "\n".join(sections)
    out_html = MAIN_RE.sub(lambda _m: f'<main class="wrap" id="main-content">{body}</main>',
                           shell, count=1)
    out_html = re.sub(r"<title>.*?</title>",
                      f"<title>Stock Analyzer 2.0 — Snapshot {when}</title>", out_html, count=1, flags=re.S)
    import json
    # Static file: no server to call. Neutralize fetch before any page script
    # runs (e.g. the home page's refresh-progress poller) so nothing errors.
    out_html = out_html.replace(
        "<head>", "<head>\n<script>window.fetch = function () { return new Promise(function () {}); };</script>", 1)
    out_html = out_html.replace("</body>", SNAPSHOT_JS % {"map": json.dumps(path_map)} + "</body>", 1)

    out = Path(args.out or f"snapshot_{datetime.now().strftime('%Y-%m-%d_%H%M')}.html")
    out.write_text(out_html, encoding="utf-8")
    print(f"\n  Saved {out.resolve()}  ({out.stat().st_size / 1024:,.0f} KB, {len(sections)} pages)")
    print("  Open it in any browser — or send it to your phone.")
    os._exit(0)  # background tracker/prewarm threads don't need a graceful shutdown


if __name__ == "__main__":
    main()
