/* =============================================================================
   invite.app — renders the invite from window.INVITE
   No dependencies. Nothing here should need editing to change the invite;
   edit assets/js/content.js instead.
   ========================================================================== */
(function () {
  'use strict';

  var D = window.INVITE;
  if (!D) return;

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* --- tiny DOM helper ---------------------------------------------------- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k === 'html') node.innerHTML = v;
        else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? '' : v);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  /* Hosts are emptied on mount. The page ships pre-rendered (see
     scripts/prerender.mjs) so it reads instantly and works without JS; this
     then replaces that snapshot with the live version from content.js. */
  function mount(id) {
    var node = document.getElementById(id);
    if (node) node.replaceChildren();
    return node;
  }

  /* =========================================================================
     Dates
     Events are shown in the timezone written into content.js, NOT the
     viewer's. A guest opening this from London must still read "7:00 pm"
     for a 7pm Jaipur ceremony. We do that by shifting the instant by the
     offset in the string and then formatting everything as UTC.
     ====================================================================== */
  function offsetMinutes(iso) {
    var m = /([+-])(\d{2}):?(\d{2})$/.exec(iso);
    if (!m) return 0;                              // 'Z' or naive → treat as UTC
    var mins = (+m[2]) * 60 + (+m[3]);
    return m[1] === '-' ? -mins : mins;
  }

  function localised(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return null;
    return new Date(d.getTime() + offsetMinutes(iso) * 60000);
  }

  function fmt(date, opts) {
    if (!date) return '';
    opts = Object.assign({ timeZone: 'UTC' }, opts);
    try { return new Intl.DateTimeFormat('en-GB', opts).format(date); }
    catch (e) { return date.toUTCString(); }
  }

  var fmtDayFull  = function (d) { return fmt(d, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }); };
  var fmtDayShort = function (d) { return fmt(d, { weekday: 'short', day: 'numeric', month: 'short' }); };
  var fmtTime     = function (d) { return fmt(d, { hour: 'numeric', minute: '2-digit', hour12: true }).replace(/\s?([ap])m/i, ' $1m'); };

  function whenLine(ev) {
    var s = localised(ev.start);
    if (!s) return '';
    var line = fmtDayShort(s) + ' · ' + fmtTime(s);
    if (ev.end) {
      var e = localised(ev.end);
      if (e) {
        var sameDay = fmt(s, { day: 'numeric', month: 'short' }) === fmt(e, { day: 'numeric', month: 'short' });
        line += ' – ' + fmtTime(e) + (sameDay ? '' : ' (' + fmtDayShort(e) + ')');
      }
    }
    return line;
  }

  /* =========================================================================
     Theme
     ====================================================================== */
  (function theme() {
    if (!D.theme) return;
    var root = document.documentElement;
    Object.keys(D.theme).forEach(function (k) { root.style.setProperty('--' + k, D.theme[k]); });
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta && D.theme.paper) meta.setAttribute('content', D.theme.paper);
  })();

  /* =========================================================================
     Inline SVG bits (no icon font, no requests)
     ====================================================================== */
  function icon(path, extra) {
    return '<svg class="btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
           'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
           path + (extra || '') + '</svg>';
  }
  var ICON = {
    calendar: icon('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>'),
    pin:      icon('<path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Z"/><circle cx="12" cy="10" r="2.6"/>'),
    share:    icon('<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M12 16V3M8 7l4-4 4 4"/>'),
    whatsapp: icon('<path d="M20 12a8 8 0 0 1-11.9 7L4 20l1.1-3.9A8 8 0 1 1 20 12Z"/><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5"/>'),
  };

  var ORNAMENT =
    '<svg class="ornament ornament--center" viewBox="0 0 100 14" fill="none" stroke="currentColor" ' +
    'stroke-width="1.1" stroke-linecap="round" aria-hidden="true">' +
    '<path d="M2 7h30M68 7h30"/><path d="M44 7c0-3 2-5 6-5s6 2 6 5-2 5-6 5-6-2-6-5Z"/>' +
    '<path d="M50 2v10"/></svg>';

  /* =========================================================================
     Hero
     ====================================================================== */
  (function hero() {
    var host = mount('hero');
    if (!host) return;
    var h = D.hero || {};
    var c = D.couple || {};

    host.appendChild(el('div', { class: 'wrap hero' }, [
      h.art ? el('img', {
        class: 'hero__art', src: h.art, alt: h.artAlt || '',
        width: '640', height: '640', fetchpriority: 'high', decoding: 'async',
      }) : null,

      el('div', {}, [
        h.eyebrow ? el('p', { class: 'eyebrow', text: h.eyebrow }) : null,
        el('h1', { class: 'hero__names' }, [
          (c.one && c.one.name) || '',
          el('span', { class: 'hero__amp', text: '&' }),
          (c.two && c.two.name) || '',
        ]),
      ]),

      el('p', { class: 'hero__meta' }, [
        h.dateLine ? el('strong', { text: h.dateLine }) : null,
        h.placeLine ? el('span', { text: h.placeLine }) : null,
      ]),

      h.note ? el('p', { class: 'scroll-cue', text: h.note }) : null,
    ]));
  })();

  /* =========================================================================
     Invitation
     ====================================================================== */
  (function invitation() {
    var host = mount('invitation');
    var v = D.invitation;
    if (!host || !v) return;

    host.appendChild(el('div', { class: 'wrap' }, [
      el('div', { html: ORNAMENT }),
      v.heading ? el('h2', { class: 'section-title', text: v.heading }) : null,
      el('div', { class: 'lede' }, (v.body || []).map(function (p) { return el('p', { text: p }); })),
      v.signoff ? el('p', { class: 'eyebrow', style: 'margin-top:1.6rem', text: v.signoff }) : null,
    ]));
  })();

  /* =========================================================================
     Countdown
     ====================================================================== */
  (function countdown() {
    var host = mount('countdown');
    if (!host || !D.countdownTo) return;

    var target = (D.events || []).filter(function (e) { return e.id === D.countdownTo; })[0];
    if (!target) return;

    var when = new Date(target.start);
    if (isNaN(when)) return;

    var box = el('div', { class: 'countdown' });
    var wrap = el('div', { class: 'wrap' }, [
      el('p', { class: 'eyebrow', style: 'text-align:center', text: 'Counting down to ' + target.name }),
      el('div', { style: 'height:1.2rem' }),
      box,
    ]);
    host.appendChild(wrap);

    var units = [['days', 86400000], ['hours', 3600000], ['minutes', 60000], ['seconds', 1000]];
    var timer;

    function tick() {
      var left = when.getTime() - Date.now();

      if (left <= 0) {
        box.replaceChildren(el('p', { class: 'countdown__done', text: 'Today’s the day.' }));
        if (timer) clearInterval(timer);
        return;
      }

      var rest = left;
      box.replaceChildren.apply(box, units.map(function (u) {
        var n = Math.floor(rest / u[1]);
        rest -= n * u[1];
        return el('div', { class: 'countdown__unit' }, [
          el('span', { class: 'countdown__n', text: String(n) }),
          el('span', { class: 'countdown__l', text: u[0] }),
        ]);
      }));
    }

    tick();
    timer = setInterval(tick, 1000);
    // Don't burn battery in a background tab.
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { clearInterval(timer); }
      else { tick(); timer = setInterval(tick, 1000); }
    });
  })();

  /* =========================================================================
     Events + add to calendar
     ====================================================================== */
  function icsStamp(d) {
    return d.getUTCFullYear() +
      String(d.getUTCMonth() + 1).padStart(2, '0') +
      String(d.getUTCDate()).padStart(2, '0') + 'T' +
      String(d.getUTCHours()).padStart(2, '0') +
      String(d.getUTCMinutes()).padStart(2, '0') + '00Z';
  }

  function icsEscape(s) {
    return String(s || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
  }

  function downloadIcs(ev) {
    var start = new Date(ev.start);
    var end = ev.end ? new Date(ev.end) : new Date(start.getTime() + 3 * 3600000);
    var title = ev.name + ' — ' + ((D.couple && D.couple.joined) || '');
    var where = [ev.venue, ev.address].filter(Boolean).join(', ');

    var lines = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//invite//EN', 'CALSCALE:GREGORIAN',
      'BEGIN:VEVENT',
      'UID:' + ev.id + '-' + icsStamp(start) + '@invite',
      'DTSTAMP:' + icsStamp(new Date()),
      'DTSTART:' + icsStamp(start),
      'DTEND:' + icsStamp(end),
      'SUMMARY:' + icsEscape(title),
      where ? 'LOCATION:' + icsEscape(where) : null,
      ev.note ? 'DESCRIPTION:' + icsEscape(ev.note) : null,
      D.share && D.share.url ? 'URL:' + D.share.url : null,
      'END:VEVENT', 'END:VCALENDAR',
    ].filter(Boolean);

    // RFC 5545 wants CRLF line endings; some calendar apps are fussy about it.
    var blob = new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/calendar;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = el('a', { href: url, download: ev.id + '.ics' });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  (function events() {
    var host = mount('events');
    if (!host || !(D.events || []).length) return;

    var list = el('div', { class: 'events' }, D.events.map(function (ev) {
      var rows = [];
      if (ev.venue || ev.address) {
        rows.push(el('div', { class: 'event__row' }, [
          el('dt', { text: 'Where' }),
          el('dd', {}, [
            ev.venue ? el('strong', { text: ev.venue }) : null,
            ev.venue && ev.address ? el('br') : null,
            ev.address ? el('span', { text: ev.address }) : null,
          ]),
        ]));
      }
      if (ev.dress) {
        rows.push(el('div', { class: 'event__row' }, [
          el('dt', { text: 'Wear' }), el('dd', { text: ev.dress }),
        ]));
      }
      if (ev.note) {
        rows.push(el('div', { class: 'event__row' }, [
          el('dt', { text: 'Note' }), el('dd', { text: ev.note }),
        ]));
      }

      var start = localised(ev.start);

      return el('article', { class: 'event' + (ev.primary ? ' event--primary' : '') }, [
        el('div', { class: 'event__head' }, [
          el('h3', { class: 'event__name', text: ev.name }),
          el('p', { class: 'event__when', text: whenLine(ev) }),
        ]),
        start ? el('p', { class: 'visually-hidden', text: fmtDayFull(start) }) : null,
        rows.length ? el('dl', { class: 'event__rows' }, rows) : null,
        el('div', { class: 'event__actions' }, [
          el('button', {
            class: 'btn', type: 'button',
            html: ICON.calendar + '<span>Add to calendar</span>',
            'aria-label': 'Add ' + ev.name + ' to your calendar',
            onclick: function () { downloadIcs(ev); },
          }),
          ev.map ? el('a', {
            class: 'btn', href: ev.map, target: '_blank', rel: 'noopener noreferrer',
            html: ICON.pin + '<span>Directions</span>',
            'aria-label': 'Directions to ' + (ev.venue || ev.name) + ' (opens in a new tab)',
          }) : null,
        ]),
      ]);
    }));

    host.appendChild(el('div', { class: 'wrap' }, [
      el('p', { class: 'eyebrow', text: 'The days' }),
      el('h2', { class: 'section-title', text: D.events.length > 1 ? 'Three days, in order' : 'When and where' }),
      list,
    ]));
  })();

  /* =========================================================================
     Gallery
     ====================================================================== */
  (function gallery() {
    var host = mount('gallery');
    var g = D.gallery;
    if (!host || !g || !(g.items || []).length) return;

    host.appendChild(el('div', { class: 'wrap' }, [
      g.heading ? el('h2', { class: 'section-title', text: g.heading }) : null,
      g.caption ? el('p', { class: 'lede', style: 'margin-bottom:2rem', text: g.caption }) : null,
      el('div', { class: 'gallery' }, g.items.map(function (item) {
        return el('figure', { class: 'gallery__item' }, [
          el('div', { class: 'gallery__frame' }, [
            el('img', {
              src: item.src, alt: item.alt || '',
              loading: 'lazy', decoding: 'async', width: '480', height: '600',
            }),
          ]),
          item.label ? el('figcaption', { class: 'gallery__label', text: item.label }) : null,
        ]);
      })),
    ]));
  })();

  /* =========================================================================
     RSVP
     ====================================================================== */
  (function rsvp() {
    var host = mount('rsvp');
    var r = D.rsvp;
    if (!host || !r || r.mode === 'off') return;

    var eventsById = {};
    (D.events || []).forEach(function (e) { eventsById[e.id] = e; });
    var choices = (r.attendingOptions || []).map(function (id) { return eventsById[id]; }).filter(Boolean);

    var status = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite', hidden: true });

    var nameInput = el('input', { type: 'text', id: 'rsvp-name', name: 'name', required: true, autocomplete: 'name' });
    var countInput = el('input', { type: 'number', id: 'rsvp-count', name: 'guests', min: '1', max: '20', value: '1', inputmode: 'numeric' });
    var comingSelect = el('select', { id: 'rsvp-coming', name: 'attending' }, [
      el('option', { value: 'yes', text: 'Yes, wouldn’t miss it' }),
      el('option', { value: 'no', text: 'Sadly can’t make it' }),
    ]);
    var noteInput = el('textarea', { id: 'rsvp-note', name: 'message', rows: '3', placeholder: 'Anything we should know — food, travel, a song request' });

    var checks = choices.map(function (ev) {
      var box = el('input', { type: 'checkbox', name: 'events', value: ev.id, checked: true });
      return { ev: ev, box: box, node: el('label', { class: 'check' }, [box, el('span', { text: ev.name + ' · ' + whenLine(ev) })]) };
    });

    var submit = el('button', { class: 'btn btn--primary', type: 'submit' }, []);
    submit.innerHTML = (r.mode === 'whatsapp' ? ICON.whatsapp : ICON.share) +
      '<span>' + (r.mode === 'whatsapp' ? 'Send our reply on WhatsApp' : 'Send our reply') + '</span>';

    function collect() {
      return {
        name: nameInput.value.trim(),
        guests: countInput.value,
        attending: comingSelect.value,
        events: checks.filter(function (c) { return c.box.checked; }).map(function (c) { return c.ev.name; }),
        message: noteInput.value.trim(),
      };
    }

    function say(text, tone) {
      status.textContent = text;
      status.setAttribute('data-tone', tone);
      status.hidden = false;
    }

    var form = el('form', { class: 'form', novalidate: true, onsubmit: function (e) {
      e.preventDefault();
      var data = collect();

      if (!data.name) {
        say('We need a name — otherwise we won’t know who replied.', 'err');
        nameInput.focus();
        return;
      }

      if (r.mode === 'whatsapp') {
        var text = [
          'RSVP for ' + ((D.couple && D.couple.joined) || 'the invite'),
          'Name: ' + data.name,
          'Coming: ' + (data.attending === 'yes' ? 'Yes' : 'No'),
          data.attending === 'yes' ? 'Guests: ' + data.guests : null,
          data.attending === 'yes' && data.events.length ? 'For: ' + data.events.join(', ') : null,
          data.message ? 'Note: ' + data.message : null,
        ].filter(Boolean).join('\n');

        var num = String(r.whatsappNumber || '').replace(/\D/g, '');
        window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(text), '_blank', 'noopener');
        say('WhatsApp should have opened — press send there and you’re done.', 'ok');
        return;
      }

      if (!r.endpoint) {
        say('RSVP isn’t switched on yet. Please message us directly.', 'err');
        return;
      }

      submit.disabled = true;
      fetch(r.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
        .then(function (res) {
          if (!res.ok) throw new Error(res.status);
          form.replaceChildren(el('p', { class: 'form__status', 'data-tone': 'ok', text: r.successMessage || 'Thank you.' }));
        })
        .catch(function () {
          submit.disabled = false;
          say('That didn’t send. Please try again, or message us directly.', 'err');
        });
    } }, [
      el('div', { class: 'field' }, [
        el('label', { for: 'rsvp-name', text: 'Your name' }), nameInput,
      ]),
      el('div', { class: 'field' }, [
        el('label', { for: 'rsvp-coming', text: 'Can you come?' }), comingSelect,
      ]),
      el('div', { class: 'field' }, [
        el('label', { for: 'rsvp-count', text: 'How many of you' }), countInput,
      ]),
      checks.length ? el('fieldset', { class: 'fieldset' }, [
        el('legend', { text: 'Which days' }),
      ].concat(checks.map(function (c) { return c.node; }))) : null,
      el('div', { class: 'field' }, [
        el('label', { for: 'rsvp-note', text: 'Anything else' }), noteInput,
      ]),
      status,
      el('div', {}, [submit]),
    ]);

    var deadline = r.deadline ? localised(r.deadline) : null;

    host.appendChild(el('div', { class: 'wrap' }, [
      el('p', { class: 'eyebrow', text: 'RSVP' }),
      r.heading ? el('h2', { class: 'section-title', text: r.heading }) : null,
      el('div', { class: 'lede', style: 'margin-bottom:2rem' }, [
        r.body ? el('p', { text: r.body }) : null,
        deadline ? el('p', { text: 'Replies by ' + fmtDayFull(deadline) + '.' }) : null,
      ]),
      form,
      el('p', {
        class: 'privacy-note',
        text: r.mode === 'whatsapp'
          ? 'Your reply opens in your own WhatsApp and goes straight to us. Nothing is stored on this website.'
          : 'We keep your reply only to plan the events, and delete it afterwards. It isn’t shared with anyone else.',
      }),
    ]));
  })();

  /* =========================================================================
     FAQ + contacts
     ====================================================================== */
  (function faq() {
    var host = mount('faq');
    if (!host) return;
    var items = D.faq || [];
    var contacts = D.contacts || [];
    if (!items.length && !contacts.length) return;

    host.appendChild(el('div', { class: 'wrap' }, [
      el('p', { class: 'eyebrow', text: 'Practicalities' }),
      el('h2', { class: 'section-title', text: 'Things people have asked' }),

      items.length ? el('div', { class: 'faq' }, items.map(function (f) {
        return el('details', { class: 'faq__item' }, [
          el('summary', { text: f.q }),
          el('p', { text: f.a }),
        ]);
      })) : null,

      contacts.length ? el('div', { class: 'contacts' }, contacts.map(function (c) {
        return el('div', { class: 'contact' }, [
          el('span', { class: 'contact__role', text: c.role || 'Call' }),
          el('span', { class: 'contact__name', text: c.name }),
          c.phone ? el('a', { href: 'tel:' + String(c.phone).replace(/\s/g, ''), text: c.phone }) : null,
        ]);
      })) : null,
    ]));
  })();

  /* =========================================================================
     Footer + sharing
     ====================================================================== */
  (function footer() {
    var host = mount('footer');
    if (!host) return;

    var s = D.share || {};
    var c = D.couple || {};
    var url = s.url || window.location.href;
    var message = s.message || s.title || '';

    var copyBtn = el('button', { class: 'btn', type: 'button', html: ICON.share + '<span>Share this invite</span>' });
    copyBtn.addEventListener('click', function () {
      var label = copyBtn.querySelector('span');
      if (navigator.share) {
        navigator.share({ title: s.title || '', text: message, url: url }).catch(function () {});
        return;
      }
      var done = function () {
        label.textContent = 'Link copied';
        setTimeout(function () { label.textContent = 'Share this invite'; }, 2200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, function () {});
      } else {
        var t = el('textarea', { style: 'position:fixed;opacity:0' });
        t.value = url;
        document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); done(); } catch (e) {}
        t.remove();
      }
    });

    host.appendChild(el('div', { class: 'wrap footer' }, [
      el('p', {
        class: 'footer__monogram',
        text: ((c.one && c.one.initial) || '') + ' & ' + ((c.two && c.two.initial) || ''),
      }),
      el('div', { class: 'footer__share' }, [
        copyBtn,
        el('a', {
          class: 'btn',
          href: 'https://wa.me/?text=' + encodeURIComponent(message + ' ' + url),
          target: '_blank', rel: 'noopener noreferrer',
          html: ICON.whatsapp + '<span>Send on WhatsApp</span>',
        }),
      ]),
      D.footer && D.footer.line ? el('p', { class: 'footer__line', text: D.footer.line }) : null,
    ]));
  })();

  /* =========================================================================
     Reveal on scroll
     Applied only when we can actually observe — a page that never reveals is
     worse than a page with no animation.
     ====================================================================== */
  (function reveals() {
    if (reduceMotion || !('IntersectionObserver' in window)) return;

    var targets = document.querySelectorAll('#invitation .wrap, #countdown .wrap, #events .event, #gallery .gallery__item, #rsvp .wrap, #faq .wrap');
    if (!targets.length) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });

    Array.prototype.forEach.call(targets, function (t, i) {
      t.classList.add('reveal');
      t.style.transitionDelay = Math.min(i % 4, 3) * 70 + 'ms';
      io.observe(t);
    });
  })();

  /* =========================================================================
     Envelope intro — once per session, never for reduced-motion
     ====================================================================== */
  (function envelope() {
    var box = document.getElementById('envelope');
    var root = document.documentElement;
    if (!box) return;

    // The head script already decided this, before first paint.
    if (!root.classList.contains('intro-on')) { box.remove(); return; }

    var c = D.couple || {};
    var seal = box.querySelector('.envelope__seal');
    if (seal) seal.textContent = ((c.one && c.one.initial) || '') + ((c.two && c.two.initial) || '');

    function open() {
      if (box.classList.contains('is-open')) return;
      box.classList.add('is-open');
      try { sessionStorage.setItem('invite-opened', '1'); } catch (e) {}
      setTimeout(function () {
        box.remove();
        root.classList.remove('intro-on');   // restores scrolling
      }, 800);
    }

    box.addEventListener('click', open);
    box.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    if (seal) seal.focus();
    // Never trap someone behind it.
    setTimeout(open, 6000);
  })();
})();
