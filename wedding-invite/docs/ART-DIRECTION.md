# The caricatures, and the video

The website is the easy part. These two are where the weekend actually goes.

Do them in this order: **one face → the other face → the pair → the video.** Each
step uses the previous image as its reference. Never start a second image from a
blank prompt — that is the single mistake that produces two portraits which
obviously came from different artists.

---

## Part 1 — The caricatures

Any image model with an image-input and a decent illustration range will do this.
The method matters more than the tool.

### Step 1: pick a style, in words, once

Before generating anything, write down the style as a short fixed phrase you will
paste into every single prompt, unchanged. Something like:

> flat vector portrait illustration, clean uniform 3px black line weight, no
> shading or gradients, warm cream background, limited palette of terracotta,
> marigold and olive, calm friendly expression, plain background, no text

Be specific about the things that give consistency away between images:

- **Line weight** — "uniform 3px black outline". Models drift here more than
  anywhere else.
- **Shading** — say "flat colour, no gradients, no shadows" explicitly. Otherwise
  one portrait comes back with soft rendering and the other doesn't.
- **Palette** — name three or four colours and no more. This is what you will
  later copy into `theme` in `content.js`.
- **Crop** — "head and shoulders, centred, facing forward" for both.
- **Background** — "plain warm cream, no scenery".

Save this paragraph in a note. It is the actual asset; the images are downstream
of it.

### Step 2: nail one face

Upload one clear, well-lit, front-facing photo. Ask for the caricature in your
style phrase.

Then iterate on *that one image only*, one change per message: "same image, make
the hair a little longer", "same image, warmer skin tone", "same image, thinner
outline". Do not ask for two changes at once — you lose the ability to tell which
one caused the drift.

Expect somewhere between five and fifteen rounds. This is normal, and it is the
whole job. When it's right, **save the file and don't touch it again.** It is now
your reference.

### Step 3: generate the second face *from* the first

Upload both the first caricature **and** the second person's photo, and ask for
the second portrait *in the style of the attached illustration* — same line
weight, same palette, same crop, same background.

Then hold the two side by side, at phone size, and check specifically:

- line weight — identical?
- eye and mouth treatment — same drawing language?
- head size relative to the frame — same crop?
- background colour — the same cream, or nearly-but-not-quite?

"Nearly but not quite" is worse than obviously different. Fix it or regenerate.

### Step 4: the pair

Upload both finished portraits and ask for the two of them together, same style,
standing side by side. This is the hardest one — models routinely re-draw faces
when combining. Judge it only on whether the faces still look like the two
approved portraits. If they don't, ask for it again rather than accepting a
likeness you'll notice every time you open the site.

### Step 5: get them into the invite

Export as **SVG** if the tool offers it. Flat vector illustration is exactly the
case SVG is best at, and it stays sharp on every screen at a fraction of the
weight.

If you only get PNGs: resize to 1200px on the long edge, convert to WebP, and
check `npm run shots` still passes the weight budget. Three unoptimised portrait
PNGs will put you over it on their own.

Then in `content.js`:

```js
hero:    { art: 'assets/img/couple.svg', artAlt: 'Illustration of the two of us' },
gallery: { items: [
  { src: 'assets/img/her.svg',    alt: '…', label: 'Aanya' },
  { src: 'assets/img/him.svg',    alt: '…', label: 'Vikram' },
  { src: 'assets/img/couple.svg', alt: '…', label: 'The pair of us' },
]},
```

Write real `alt` text. Someone in your family uses a screen reader, or has the
images blocked, or is on a connection where they never load.

### Step 6: pull the palette out of the artwork

Sample the actual colours from your finished caricatures and put them in `theme`:

```js
theme: {
  ink: '#211A16', paper: '#FAF4EA', accent: '#C2452D',
  accent2: '#D9922F', muted: '#6F6257', rule: '#E2D6C4',
},
```

The whole site re-tints from these six values. This is the step that makes the
site look designed rather than assembled — and it only works in this direction.
Matching illustrations to an existing website means redrawing the illustrations.

Two checks before you move on: `accent` needs to stay readable on `paper`
(4.5:1 contrast or better — it's used for body-adjacent text), and `rule` should
be barely visible rather than a hard line.

---

## Part 2 — The video

Thirty minutes, once the site exists and the style is locked. Not before — build
it from the *approved* caricatures so the two match.

**What it's for:** the video is the thing you post to Instagram and drop in the
group chat. The website is where people land and get the details. Don't try to
put the details in the video; it's a knock on the door, not the invitation.

**Length:** 10–20 seconds. It will be watched on mute, at speed, once.

**A shape that works:**

1. Both caricatures animate in — a gentle draw-on or fade, nothing frantic
2. Names appear
3. Date and city
4. The URL, held on screen long enough to actually read

**Practical notes**

- **Export 9:16 first** (1080×1920). That's Stories, Reels and a WhatsApp status.
  A 1:1 crop second if you want a feed post. Landscape is useless here.
- **Burn the text in.** It's watched on mute.
- **Keep it under about 10 MB** so it sends over WhatsApp without being crushed.
- **Put the URL in the last frame and hold it** for two full seconds. People
  screenshot that frame.
- **Watch it on a phone at arm's length** before you post it. Text that's
  comfortable on a laptop is unreadable at that size.

Save the final file outside this repo, or add it to `assets/` — but if you add it,
re-run `npm run shots`. A video in the page will not fit the weight budget, so
link to it rather than embedding it.
