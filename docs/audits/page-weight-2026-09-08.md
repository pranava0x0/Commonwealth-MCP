# Page weight, before and after the split into four pages

GitHub issues [#46](https://github.com/pranava0x0/Commonwealth-MCP/issues/46)
and [#52](https://github.com/pranava0x0/Commonwealth-MCP/issues/52). Measured
2026-09-08 with `gzip -9` for the transfer column, and in a 1280×720 viewport
served by `python -m http.server -d docs`.

## What the one page weighed

`docs/index.html` held everything: the CSS, the script, two copies of the
seal as a base64 data URI, and three JSON blobs inlined so the file would
work opened straight off disk.

| | Raw | Transfer (gzip) |
|---|---|---|
| `index.html` | 1,333,013 | 404,617 |

Of that raw figure, 898 KB was the three inlined JSON blocks, 354 KB was the
seal (the same 133 KB image, base64-encoded, twice), and 9 KB the favicon.
Nothing was cached between visits, because it was all one file.

## What the four pages weigh

| File | Raw | Transfer (gzip) | Loaded by |
|---|---|---|---|
| `index.html` | 63,823 | 18,566 | the landing page |
| `tools.html` | 54,548 | 15,997 | the tool reference |
| `sources.html` | 55,170 | 16,128 | the source registry |
| `examples.html` | 55,084 | 16,178 | the recorded trail |
| `assets/site.css` | 27,443 | 7,990 | every page, cached after the first |
| `assets/site.js` | 46,479 | 14,962 | every page, cached after the first |
| `assets/seal.webp` | 132,764 | — | every page, cached after the first |
| `data/core.json` | 55,526 | 14,660 | committed; embedded in all four pages |
| `data/coverage.json` | 460,031 | 28,927 | fetched by the landing page's coverage table |
| `data/audit-demo.json` | 439,676 | 55,562 | fetched by `examples.html` |
| `data/resolver-demo.json` | 308,965 | 22,512 | fetched on the first keystroke in the resolver |

A first visit to the landing page transfers about 42 KB of HTML, CSS and
script plus the 133 KB seal, then fetches `coverage.json` after the page has
already painted. The trail's 55 KB reaches only a reader who opens
`examples.html`. The resolver's 22 KB reaches only a reader who types into
it.

## What this cost

The page no longer works opened as a file. `fetch()` rejects `file://` URLs,
so a page opened from disk paints and then shows a one-line note naming the
fix (`python -m http.server -d docs`) where the fetched section would be.
That was a deliberate trade: the property was worth 898 KB on every visit,
and it served the maintainer more than any reader arriving from a link.

The seal now loads from `assets/seal.webp`, which was already committed and
byte-identical to what the data URI encoded. It is the one asset with no
gzip win, being already compressed.

## Shape of the page

Measured with the sections closed, at 1280×720.

| | Before | After the split | After the second pass |
|---|---|---|---|
| Landing page height | 21,144 px (29 screens) | 6,537 px (9.1) | 3,600 px (5.0) |
| Landing page words | 6,101 | 1,430 | 991 |
| Quick start starts at | ~19,000 px | 1,299 px | 1,104 px |
| Tools section | 3,409 px | 1,062 px (1.5 screens), on its own page | unchanged |
| Sources section | 8,208 px | 1,262 px (1.8 screens), on its own page | unchanged |

The split alone left nine screens, which is still further than a reader
should travel to reach an install command. The second pass was three
changes, each a different way of not stacking things:

- **Constrain the prose, not the container.** The column was 820 px
  because that is about as wide as a line of prose stays readable, so a
  grid of cards got two columns on a 27-inch screen. The container is
  1,120 px now and the 74-character limit moved onto paragraphs, so cards,
  tables and steppers use the width and sentences do not.
- **One step of the quick start at a time.** Four stacked steps were
  1,568 px, most of it below a reader who had not finished step one. As a
  tabbed stepper they are 379 px, and the step you are on is marked.
- **Fold the reference under the answer.** The coverage table is eleven
  rows and 1,239 px, and it answers a question a reader has once. A
  derived one-line summary answers it for most people and the table opens
  on request; the section is 358 px. The same treatment holds the
  workflows list to three cards and a button.

At 375 px the landing page is 7.6 screens and no page overflows
horizontally.
