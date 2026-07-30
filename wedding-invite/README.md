# The invite

A wedding / engagement invite as a website. Static, fast, and built so that
changing the venue at 11pm the night before takes one line and thirty seconds.

Built to the method in Shashwat Agarwal's *AI Wedding Invite Playbook* — the
invite-website leg of it, plus the four failure modes it warns about that are
solvable in code: the WhatsApp preview, load speed, RSVP data, and late changes.
The build order and the list of traps are his; the code here is not, and none of
his prompts or project files were used.

```
npm install         # optional — only needed for the build scripts
npm run dev         # preview at http://localhost:4321
npm run build       # sync meta + regenerate the preview image + prerender
npm run check       # build, then screenshot at phone sizes and check weight
```

Everything you edit lives in **one file**: `assets/js/content.js`.

---

## What's here

| Path | What it is |
|---|---|
| `assets/js/content.js` | **The only file you need to edit.** Names, events, venues, RSVP, colours. |
| `assets/js/app.js` | Renders the invite from that file. You shouldn't need to touch it. |
| `assets/css/style.css` | All the styling. Colours come from `content.js`. |
| `assets/img/` | Caricatures, favicon, and the generated link-preview image. |
| `scripts/` | The build and test commands below. |
| `index.html` | Shell + generated meta tags + prerendered markup. Generated — don't hand-edit. |
| `vercel.json` | Hosting config: cache rules and security headers. |

### Commands

| Command | What it does |
|---|---|
| `npm run dev` | Serves the site. Also listens on your local network so you can open it on your phone. |
| `npm run sync` | Rewrites the `<head>` meta tags and the favicon from `content.js`. |
| `npm run og` | Regenerates `assets/img/og.png`, the 1200×630 link preview card. |
| `npm run prerender` | Bakes the rendered invite into `index.html`. |
| `npm run build` | All three. **Run this before every deploy.** |
| `npm run shots` | Screenshots at four device sizes into `screenshots/`, reports page weight, fails on JS errors. |
| `npm run check` | `build` then `shots`. This is the one to run before you send the link to anyone. |

---

## Build order

The order matters more than the tools. Out of order, you rebuild things.

**1. Write the story down first.** Open `content.js` and fill in `feeling`,
`couple`, `hero` and `events` before you think about a single colour. If you
skip this the invite comes out generic, and no amount of styling fixes that.

**2. Make the caricatures before you style anything.** The illustration sets the
palette, not the other way round. See `docs/ART-DIRECTION.md`. Drop the finished
files into `assets/img/`, point `hero.art` and `gallery.items` at them, then pull
the colours out of the artwork into `theme` in `content.js`. The whole site
re-tints from those six values.

**3. Fill in the rest of `content.js`.** Events, RSVP, FAQ, contacts.

**4. Test on a phone. Now, and after every change.** `npm run dev`, then open
`http://<your-computer's-ip>:4321` on your actual phone on the same wifi.
`npm run shots` catches the obvious breakage between times, but it is not a
substitute — it does not know what your thumb can reach.

**5. Put it on a real link.** See Deploying, below. Then do the grey box test.

**6. Make the video last.** Once the site exists and the style is settled. See
`docs/ART-DIRECTION.md`.

---

## The five things that actually break

The playbook names five. Here is what this project does about each, and what is
still on you.

### 1. Caricature consistency

Two portraits that don't look like the same artist drew them will sink the whole
thing. **Handled by you**, with a method in `docs/ART-DIRECTION.md`: nail one
face, then generate every other image using that image as the reference. Never
start a second one from a blank prompt.

The placeholder SVGs in `assets/img/` are deliberately simple line art in the
project palette — good enough to build against, obviously meant to be replaced.

### 2. The WhatsApp preview

Your invite is judged as a grey box in a family group chat before anyone taps it.

**Handled.** `npm run sync` writes the Open Graph tags into `index.html` from
`content.js`, and `npm run og` renders a matching 1200×630 card from the same
source, so the preview can't drift from the invite.

Two things you must do:

- Set `share.url` in `content.js` to the **real, final, absolute URL** before you
  build. The sync script warns you if it's still the placeholder. Relative image
  paths do not work in link previews — the script makes them absolute for you,
  but only if `share.url` is right.
- **The grey box test.** After deploying, send the link to yourself on WhatsApp
  and look at it. If it's wrong, fix it, redeploy, and test again *with a
  cache-buster* (`?v=2` on the end) — WhatsApp caches previews aggressively and
  you will otherwise spend an hour debugging a fixed problem.

### 3. Load speed at the venue

Heavy invites feel great on wifi and fail on 3G in a banquet hall.

**Handled, and enforced.** No webfonts, no frameworks, no external requests at
all — nothing to block on a bad connection. The page is prerendered into
`index.html` so it shows finished content on first paint rather than waiting for
JavaScript. `npm run shots` fails the build if the page goes over **400 KB**.

Where it currently sits: about 70 KB total. The budget exists because the moment
you swap in real caricatures, photos are what will blow it. Export illustrations
as SVG where you can; where you can't, resize to no more than 1200px on the long
edge and save as WebP.

### 4. RSVP data

The moment you collect names and numbers you are holding your guests' personal
data on the internet. Decide where it goes *before* you turn the form on.

**Handled by defaulting to the safe option.** `rsvp.mode` in `content.js`:

- **`'whatsapp'` (default)** — the form composes the reply and opens the guest's
  own WhatsApp with it pre-written. They press send. Nothing is stored on the
  website, there is no database, there is nothing to leak, and the replies land
  where you'll actually read them. For a few hundred guests this is genuinely
  the better product, not just the safer one.
- **`'endpoint'`** — POSTs JSON to a URL you control. Use this only if you have
  somewhere to put the data. A Google Apps Script bound to a private Sheet is
  the usual answer; a Vercel or Cloudflare function writing to a private store is
  the tidier one. Whatever you pick, check three things before you announce the
  link: the destination is **not publicly readable**, only you and your partner
  can see it, and you know when you're going to delete it.
- **`'off'`** — hides the section.

The visible privacy note under the form changes to match the mode. If you switch
to `'endpoint'`, make sure that sentence is still true.

Do not collect anything you won't use. Name, headcount, which days, one free-text
field. You do not need addresses, and you certainly don't need dates of birth.

### 5. Late changes

The venue moves. An event gets added. An aunt spots a misspelling.

**Handled.** Every word, date, venue, phone number and colour is in
`content.js`. Change it, run `npm run build`, redeploy. Nothing else knows any of
those values — not the meta tags, not the preview image, not the calendar files.

`vercel.json` sets `must-revalidate` on the HTML, CSS and JS so a corrected time
is live for everyone on their next open rather than sitting behind a cache for a
day. That is a deliberate trade of a little speed for correctness.

---

## Deploying

Hosting is free at this size. The build needs a browser (for the preview image
and the prerender), so build locally and deploy the result.

```bash
npm run check                    # build + phone screenshots + weight check
npx vercel --prod                # first run walks you through linking a project
```

There is no build step on Vercel's side — it serves the folder as-is. If you'd
rather use Netlify, Cloudflare Pages or GitHub Pages, all of them work the same
way; only `vercel.json` is Vercel-specific, and its cache rules have equivalents
elsewhere.

**A custom domain is worth the money.** The link *is* the invite — it's the thing
people see in the group chat. `aanya-and-vikram.com` reads like an invitation;
`invite-final-v9.vercel.app` reads like a phishing attempt. Buy it, point it at
the project in Vercel's dashboard, then update `share.url` in `content.js` and
run `npm run build` again so the preview tags match the new domain.

### Before you send the link to anyone

- [ ] `share.url` is the real domain, and `npm run build` has been run since
- [ ] `npm run check` passes — no JS errors, under budget
- [ ] Opened on a real phone, in portrait, and scrolled all the way down
- [ ] Sent the link to yourself on WhatsApp and the preview looks right
- [ ] Every "Add to calendar" button produces the correct time
- [ ] Every "Directions" link opens the right pin, not a similarly-named venue
- [ ] Submitted the RSVP form yourself and the reply arrived where you expect
- [ ] Read every name out loud, slowly. This is the one that gets people.

---

## Notes on how it works

A few decisions worth knowing about if you go into the code.

**Times are shown in the venue's timezone, not the viewer's.** A cousin opening
this in London must still read "7:00 pm" for a 7pm Jaipur ceremony. `app.js`
parses the UTC offset out of each ISO date in `content.js` and formats against
that. Keep the `+05:30` on the end of your dates, or this breaks. Calendar files
convert to real UTC, so they're correct wherever the guest's phone is.

**The page is prerendered but JavaScript still owns it.** `npm run prerender`
snapshots the rendered DOM into `index.html`; on load, `app.js` empties each
section and re-renders it from `content.js`. So the two can never disagree at
runtime — the worst case is that a visitor with JavaScript disabled sees a
version that's one build old.

**The envelope intro can't trap anyone.** It shows once per browser tab, never
for people who've asked for reduced motion, never without JavaScript, and it
opens itself after six seconds whether or not anyone taps it.

**Nothing is loaded from another domain.** No fonts, no analytics, no icon
library, no CDN. Partly it's speed, partly it's that a wedding invite has no
business sending your guest list to anyone's servers.
