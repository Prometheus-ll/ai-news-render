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
| `setSmear(el,k,sx,sy)` | directional motion blur (SVG feGaussianBlur with separate x / y deviation), so blur follows the direction of a move |
| `expo(t,t0,k)` | exponential approach: a move enters already moving and loses a fixed share of the remaining distance per second |
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
| `prompt` | prompt, reply, hi | frosted-glass prompt box springs out and types, whip-tilt up with vertical smear, the answer page scrolls in from low and blurred with one bold key phrase |
| `stack` | items [{title, tag}] (2-3) | stacked cards with giant frosted-glass titles cut off by the card edge, blur-in with stagger |
| `orbit` | icon, items (4) | four squares spin in around the product, lock into a cross, then slide into a labelled row |
| `wordmark` | name | end card: the word arrives zoom-smeared (18 scaled copies) and settles on black (manual use; not offered to Gemini) |
| `mark` | name | identity reveal: rings draw themselves, brand mark lands, wordmark tightens in (manual use; not offered to Gemini) |

Gemini can choose `morph shapes bars kinetic command tabs prompt stack orbit` in both styles (`rich`: each type once, with the kicker chip;
`focus`: at most 3 motion scenes per video). Each has a sanitizer in `pipeline/run_pipeline.py` (`_san_*`) that clamps lengths,
strips trailing full stops and pads missing items, so a sloppy script can never break a render.

## Explainer structure
The angle "problem, solution, 3 steps, proof" is available to Gemini: problem (`say`), what it does (`say`/`name`), how it works in 3 steps (`phases` or `stack`), one proof point (`stat`/`bars`), name at the end (`end`).
The channel's loop rule still applies in `focus` style: the last line echoes the first.

## Not built yet
Dot-field wave (`field`), steps/editor/pivot/branch/fanout scenes from the earlier explainer files, and anything that needs the user's own footage.

## Sound (render/soundtrack.py)
Every video gets a synthesized music bed and scene sound effects, mixed under the voice. Nothing is downloaded or sampled, so there is no licence to check.
- **Music:** soft pad, pluck arpeggio, sub bass and a gentle kick/hat. Tempo (96-120 BPM), key and chord loop are picked from the script text, so videos do not all sound the same.
- **Sound effects:** a whoosh peaking on every scene cut, plus clicks, chimes, typing ticks and thumps timed to each motion scene's own animation events (the formulas mirror `engine.html`).
- **Mix:** the music ducks under the voice (about 16-19 dB below it while speaking, rising in the pauses), effects stay clear, final loudness -14 LUFS with true peak under -1.5 dBFS.
- **Safety:** any failure falls back to the plain voice track. Set the environment variable `MUSIC=0` to turn the whole thing off. Temporary audio goes to a temp folder that is deleted after the render.
