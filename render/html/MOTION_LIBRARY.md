# Motion library

Scene types and primitives for the HTML engine (`engine.html`). Everything is a pure function of time `t`
(no CSS transitions, no timers, no state between frames), so renders are deterministic.

## Style rules (from the channel's reference prompts)
- One idea per shot, lots of empty space, one accent colour (the theme's `--acc2`), one clean sans, tight tracking.
- Springs, never bouncy easing: a tiny overshoot at most. Use `spr()` / `trk()`.
- A cursor drives every UI change (real click, press-scale), content swaps with a short blur (`blurTo`).
- **Banned:** shockwave / ripple rings, particle bursts, RGB split, camera shake, lens flares, neon glows, grid floors,
  flashing backgrounds, bouncy easing, placeholder cards.
- **No full stops in on-screen text** (`nofs()` in the engine, `_nofs()` in the sanitizers).
- Real footage only: never fake clips. (The wall-of-clips / 3D carousel / phone-mockup ideas need your own vertical clips, so they are not built.)

## Primitives
| name | what |
|---|---|
| `spr(t,t0,z,w)` | closed-form damped-spring step response started at `t0` (z < 1) |
| `trk(t,keys,z,w)` | value that changes target many times = sum of one spring per change |
| `blurTo(el,a)` | opacity + blur swap for content that changes inside a morphing container |
| `slotAl(t,a,b)` | fade in at `a`, out at `b` for a content slot |
| `shapePath(s,R)` | radius-lerp morph between circle, squircle, triangle, star (`s` = 0..3) |
| transition `panel` | accent panel sweeps across the frame; the scene hard-cuts under it |

## Scene types
| type | fields | what it shows |
|---|---|---|
| `morph` | label, result | ONE pill: button -> loader -> check -> result, a cursor clicks it |
| `shapes` | items (2-4) | ONE shape morphs through the concepts, with a motion trail and a label that blur-swaps |
| `bars` | value, label, series (5-8) | counter + bars that grow on springs, a trend line that draws itself, a tooltip |
| `kinetic` | words (2-4) | each word lands on its own beat, hard cuts between light / dark / accent frames |
| `command` | query, results (3), toast | command palette: types, list filters, Enter, a toast confirms |
| `tabs` | items (3), pick, detail | liquid indicator: the leading edge rides a faster spring than the trailing edge |
| `mark` | name | identity reveal: rings draw themselves, brand mark lands, wordmark tightens in (manual use; not offered to Gemini) |

Gemini can choose `morph shapes bars kinetic command tabs` in both styles (`rich`: each type once, with the kicker chip;
`focus`: at most 3 motion scenes per video). Each has a sanitizer in `pipeline/run_pipeline.py` (`_san_*`) that clamps lengths,
strips trailing full stops and pads missing items, so a sloppy script can never break a render.

## Not built yet
Dot-field wave (`field`), steps/editor/pivot/branch/fanout scenes from the earlier explainer files, and anything that needs the user's own footage.
