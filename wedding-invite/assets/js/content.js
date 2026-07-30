/* ============================================================================
   invite.content — THE ONLY FILE YOU NEED TO EDIT
   ----------------------------------------------------------------------------
   Every word, date, venue and link on the invite comes from this file.
   Change something here, save, refresh. Nothing else to rebuild.

   Dates use ISO 8601 with an offset:  2026-12-05T19:00:00+05:30
                                       ^date    ^time    ^timezone
   Keep the offset — the countdown and the calendar files depend on it.
   ========================================================================== */

window.INVITE = {

  /* -- 1. THE STORY ---------------------------------------------------------
     The playbook's step one. Decide this before you touch anything visual.
     `feeling` is a note to yourself; it never renders. Keep it honest, and
     judge every later change against it.                                     */
  feeling: 'Warm, unhurried, a little hand-made. Not a corporate landing page.',

  /* -- 2. WHO ------------------------------------------------------------- */
  couple: {
    one:  { name: 'Aanya',  initial: 'A' },
    two:  { name: 'Vikram', initial: 'V' },
    // Shown in the browser tab and the WhatsApp preview.
    joined: 'Aanya & Vikram',
  },

  /* -- 3. THE HEADLINE ---------------------------------------------------- */
  hero: {
    eyebrow: 'We’re getting engaged',
    // Rendered on two lines with the ampersand between them.
    dateLine: 'Friday, 5 December 2026',
    placeLine: 'Jaipur',
    // Small line under the scroll cue. Keep it to a handful of words.
    note: 'Scroll for the details',
    // Optional: a caricature for the hero. Swap for your own file, or leave
    // the placeholder — see docs/ART-DIRECTION.md.
    art: 'assets/img/caricature-couple.svg',
    artAlt: 'Illustrated caricature of Aanya and Vikram',
  },

  /* -- 4. THE INVITATION LINE --------------------------------------------- */
  invitation: {
    heading: 'You’re invited',
    // Two or three short paragraphs. More than that and nobody reads it.
    body: [
      'Six years ago we met in a queue for bad coffee and neither of us left.',
      'We would love you there when we make it official — close family and the friends who feel like it.',
    ],
    signoff: 'With love, from both our families',
  },

  /* -- 5. THE COUNTDOWN ---------------------------------------------------
     Which event to count down to, by its `id` below. Set to null to hide.  */
  countdownTo: 'ceremony',

  /* -- 6. EVENTS ----------------------------------------------------------
     Add, remove or reorder freely. Every field except `id`, `name` and
     `start` is optional — leave a field out and that row simply won't show.
     `end` is used by Add-to-calendar; if omitted we assume 3 hours.        */
  events: [
    {
      id: 'mehendi',
      name: 'Mehendi',
      start: '2026-12-04T16:00:00+05:30',
      end:   '2026-12-04T21:00:00+05:30',
      venue: 'The Courtyard, Narain Niwas',
      address: 'Kanota Bagh, Narain Singh Road, Jaipur 302004',
      // Any maps link. Right-click a pin in Google Maps → "Copy link".
      map: 'https://maps.google.com/?q=Narain+Niwas+Palace+Jaipur',
      dress: 'Something you can sit cross-legged in',
      note: 'Lunch will be served. Come hungry.',
    },
    {
      id: 'sangeet',
      name: 'Sangeet',
      start: '2026-12-04T20:00:00+05:30',
      end:   '2026-12-05T01:00:00+05:30',
      venue: 'Lawn, Narain Niwas',
      address: 'Kanota Bagh, Narain Singh Road, Jaipur 302004',
      map: 'https://maps.google.com/?q=Narain+Niwas+Palace+Jaipur',
      dress: 'Dress to dance',
      note: 'If you want to perform, tell us by 20 November.',
    },
    {
      id: 'ceremony',
      name: 'The Engagement',
      start: '2026-12-05T19:00:00+05:30',
      end:   '2026-12-05T23:30:00+05:30',
      venue: 'Rambagh Terrace',
      address: 'Bhawani Singh Road, Jaipur 302005',
      map: 'https://maps.google.com/?q=Rambagh+Palace+Jaipur',
      dress: 'Indian formal',
      note: 'Rings at 8, dinner at 9.',
      // Marks the main event — gets the emphasis treatment.
      primary: true,
    },
  ],

  /* -- 7. CARICATURES / GALLERY -------------------------------------------
     The playbook is right: make these first, then match the site to them.
     Drop your files in assets/img/ and point at them here.
     Set to [] to hide the section entirely.                                */
  gallery: {
    heading: 'Us, roughly',
    caption: 'Drawn, not photographed. It seemed more us.',
    items: [
      { src: 'assets/img/caricature-one.svg',    alt: 'Caricature of Aanya',  label: 'Aanya' },
      { src: 'assets/img/caricature-two.svg',    alt: 'Caricature of Vikram', label: 'Vikram' },
      { src: 'assets/img/caricature-couple.svg', alt: 'Caricature of the two of them together', label: 'The pair of us' },
    ],
  },

  /* -- 8. RSVP -------------------------------------------------------------
     Read the RSVP section of README.md before switching this on. The moment
     you collect names and numbers you are storing other people's personal
     data on the internet.

     mode: 'whatsapp'  → opens WhatsApp with the reply pre-written.
                         Nothing is stored anywhere. Safest default.
           'endpoint'  → POSTs JSON to `endpoint`. You own that data.
           'off'       → hides the section.                                 */
  rsvp: {
    mode: 'whatsapp',
    heading: 'Will you be there?',
    // Don't repeat the date here — the deadline line below prints it for you.
    body: 'Let us know either way. It helps more than you’d think.',
    // For mode:'whatsapp' — international format, no + and no spaces.
    whatsappNumber: '919999999999',
    // For mode:'endpoint'
    endpoint: '',
    deadline: '2026-11-15T23:59:00+05:30',
    // Which events guests choose from. Uses the ids above.
    attendingOptions: ['mehendi', 'sangeet', 'ceremony'],
    successMessage: 'Thank you — we’ve got it. See you in December.',
  },

  /* -- 9. THINGS PEOPLE ASK ------------------------------------------------
     Cut this to three. Nobody reads ten.                                   */
  faq: [
    {
      q: 'Where should we stay?',
      a: 'We’ve held rooms at Narain Niwas under “Aanya & Vikram” until 1 November. Call them directly and mention it.',
    },
    {
      q: 'Are children invited?',
      a: 'Yes, all three days. There’s a quiet room at the ceremony if you need it.',
    },
    {
      q: 'What about gifts?',
      a: 'Your being there is genuinely the whole thing. If you’d still like to, we’re putting anything given towards the honeymoon.',
    },
  ],

  /* -- 10. WHO TO CALL ---------------------------------------------------- */
  contacts: [
    { name: 'Rhea (Aanya’s sister)', role: 'Anything about the events', phone: '+919999999999' },
    { name: 'Arjun (Vikram’s brother)', role: 'Travel and stay', phone: '+919888888888' },
  ],

  /* -- 11. THE LINK ITSELF -------------------------------------------------
     This is what a family WhatsApp group sees before anyone taps. Get it
     wrong and your invite looks like spam. See README → "The grey box test".
     `url` must be the final public URL, absolute, no trailing slash.       */
  share: {
    url: 'https://aanya-and-vikram.example.com',
    title: 'Aanya & Vikram — 5 December 2026, Jaipur',
    description: 'We’re getting engaged, and we’d love you there. Dates, venues and RSVP inside.',
    image: 'assets/img/og.png',            // 1200×630. Run `npm run og` to regenerate.
    // Text used by the share button and the WhatsApp share link.
    message: 'We’re getting engaged — here are the details 🧡',
  },

  /* -- 12. LOOK -----------------------------------------------------------
     Set these to match your caricatures, not the other way round.          */
  theme: {
    ink:      '#211A16',   // text
    paper:    '#FAF4EA',   // background
    accent:   '#C2452D',   // headings, primary buttons  (vermilion)
    accent2:  '#D9922F',   // secondary marks            (marigold)
    muted:    '#6F6257',   // secondary text
    rule:     '#E2D6C4',   // hairlines
  },

  /* -- 13. FOOTER --------------------------------------------------------- */
  footer: {
    line: 'Made at home, at the kitchen table.',
  },
};
