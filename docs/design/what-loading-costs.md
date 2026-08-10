# What loading costs, measured 2026-08-10

Everything written during one session, opened one after another through the
viewer's own server, **a fresh browser for each row** so none is warmed by the one
before. The disk is warm for all of them equally — they were written the same
evening — so these are a floor rather than what a cold machine pays.

| what | sources | first pixel | loaded | requests | frames/5s |
| --- | --- | --- | --- | --- | --- |
| 4096 tiles, merged canvas | 2 | 1.1 s | 1.3 s | 301 | 302 |
| 4096 tiles, raw composed | 2 | 0.8 s | 0.9 s | 301 | 301 |
| 1024 positions, continuous, clipped | 1 | 0.7 s | 0.7 s | 128 | 302 |
| 1024 positions, continuous, raw | 1 | 0.7 s | 0.7 s | 128 | 302 |
| 64 tiles, chessboard, clipped | 2 | 0.7 s | 0.7 s | 301 | 302 |
| 64 tiles, chessboard, raw | 2 | 0.7 s | 0.7 s | 301 | 302 |
| 64 tiles, drifting, clipped | 1 | 0.6 s | 0.6 s | 128 | 302 |
| **16 positions, linked view + pyramid** | 1 | 0.7 s | **2.5 s** | **925** | 302 |
| **200 positions, container of stores** | **200** | 1.9 s | 1.9 s | **1053** | 302 |

`first pixel` is until specimen is on screen; `loaded` until every visible piece
is in hand; `requests` is pieces the browser asked for while opening.

## What it says

**The `sources` column is the whole story.** Every merged picture is one or two
sources however much is behind it — 4,096 tiles and 1,024 positions both open in
about a second. The container of separate stores is 200 sources for 200 tiles and
pays 1,053 requests for it.

**Frame rate never moved.** 301–302 in every row, including 200 sources. The older
claim that a thousand positions draw 24 frames in five seconds did not reproduce
on this machine at any size measured.

**The linked view is the row that does not fit.** One source, and still 925
requests and 2.5 s to settle for only 16 positions — where the same specimen
written as one canvas takes 128–301 requests and under a second. That is the open
question. The likeliest cause is that a pointer map hands out pieces one at a time
where a written pyramid gives the engine runs of neighbouring chunks, **but that
is a guess and has not been measured.**

## How a container of separate stores scales

Measured separately, in the mesoSPIM organisation (bare container group, one
`z y x` OME-Zarr per tile, no `omero`, blosc/zstd bitshuffle):

```
tiles      1     5    10    50   100   200
sources    1     5    10    50   100   200
requests  27    78   103   303   553  1053
opening  0.7   0.7   0.7   0.8   1.3   2.0  s
frames   301   302   302   302   302   302
```

**Linear, 5.2 requests a tile, no sign of turning over.** Flat to about fifty
tiles, then cold start climbs. Fine for a 3×2 mosaic many times over; wrong for a
survey.

## How the cold start divides

At 4,096 tiles, timed on Playwright's request events (the page's own
`performance` API is blind to worker requests and reported 4 requests and 0 bytes
where Playwright saw 301):

```
first pixel          0.86 s
  waiting for bytes  0.33 s   (39%)   301 requests
  everything after   0.53 s   (61%)
```

So most of the wait is not disk or server. Sharding could only attack the 39%.

## Traps that produced confident wrong numbers

- `performance.getEntriesByType('resource')` cannot see worker requests, and the
  engine fetches every chunk in a worker.
- Reading the canvas back with `drawImage` returns black; the drawing buffer is
  not preserved. Photograph with `page.screenshot`.
- `int()` on a translation of 95.99999 truncates to 95 and silently compares
  strips shifted by a voxel. Always round.
- The clipped canvas's joins sit at `96k + 15`, not `96k` — the trim moves them by
  half the overlap. Measuring at the wrong column produced a confident claim that
  clipping cleans seams from stage error. **It does not:** raw joins stepped
  78–177, clipped 93–196.
