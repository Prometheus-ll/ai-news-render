"""Synthesized music bed + scene sound effects, mixed under the voice-over.

Everything is generated in code (numpy), so there is nothing to license: no samples, no downloads.
  * music: soft pad + pluck arpeggio + sub bass + gentle kick/hat, key / tempo / chord loop picked per video
  * sfx:   whooshes on scene cuts, clicks / chimes / ticks / thumps timed to each scene's animation events
           (the formulas mirror the ones in html/engine.html)
  * mix:   the music ducks under the voice (sidechain), sfx stay clear, loudness-normalised to -14 LUFS

mix() raises on any problem; the caller falls back to the plain voice track.
"""
import os, subprocess, zlib, wave
import numpy as np

SR = 44100


def _t(d):
    return np.arange(int(SR * d)) / SR


class Track:
    def __init__(self, dur):
        self.n = int(dur * SR)
        self.L = np.zeros(self.n)
        self.R = np.zeros(self.n)

    def put(self, sig, t, g=1.0, pan=0.0):
        i = int(round(t * SR))
        if i < 0 or i >= self.n:
            return
        seg = sig[: self.n - i]
        self.L[i:i + len(seg)] += seg * g * (1 - max(0.0, pan))
        self.R[i:i + len(seg)] += seg * g * (1 + min(0.0, pan))


# ------------------------------------------------------------------ sounds
def kick():
    t = _t(.32)
    f = 46 + 95 * np.exp(-t * 34)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def hat(rng):
    t = _t(.07)
    x = np.diff(rng.standard_normal(len(t) + 1))
    return x * np.exp(-t * 75) * .5


def pluck(f):
    t = _t(.55)
    s = np.sin(2 * np.pi * f * t) + .35 * np.sin(4 * np.pi * f * t) + .12 * np.sin(6 * np.pi * f * t)
    return s * np.minimum(1, t / .004) * np.exp(-t * 8.5)


def pad(freqs, d):
    t = _t(d)
    s = np.zeros(len(t))
    for f in freqs:
        for det in (-.004, 0, .004):
            s += np.sin(2 * np.pi * f * (1 + det) * t) + .3 * np.sin(4 * np.pi * f * (1 + det) * t)
    env = np.minimum(1, t / .35) * np.minimum(1, (d - t) / .5)
    return s * env / (len(freqs) * 3)


def bass(f, d):
    t = _t(d)
    s = np.sin(2 * np.pi * f * t) + .25 * np.sin(4 * np.pi * f * t)
    return s * np.minimum(1, t / .02) * np.minimum(1, (d - t) / .08)


def whoosh(rng, d=.5, tone=0.0):
    """Filtered-noise swell; the peak sits at the middle of the sound. tone > 0 adds a rising sine."""
    t = _t(d)
    x = rng.standard_normal(len(t))
    lows = [np.convolve(x, np.ones(k) / k, 'same') for k in (70, 24, 7)]
    pos = [.3, .5, .72]
    out = np.zeros(len(t))
    for lp, p in zip(lows, pos):
        env = np.exp(-((t / d - p) / .16) ** 2)
        out += lp * env * (3.2 if lp is lows[0] else 2.0 if lp is lows[1] else 1.1)
    out *= np.sin(np.pi * np.clip(t / d, 0, 1)) ** 1.5
    if tone:
        out += tone * np.sin(2 * np.pi * np.cumsum(260 + 1700 * (t / d) ** 2) / SR) * np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2
    return out


def tick(f=2300, d=.04):
    t = _t(d)
    return np.sin(2 * np.pi * f * t) * np.exp(-t * 150) + np.diff(np.random.default_rng(int(f)).standard_normal(len(t) + 1)) * np.exp(-t * 220) * .25


def click():
    t = _t(.05)
    return np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 130) * .7 + np.sin(2 * np.pi * 420 * t) * np.exp(-t * 90) * .5


def chime(f, d=.7):
    t = _t(d)
    return (np.sin(2 * np.pi * f * t) + .3 * np.sin(2 * np.pi * f * 2.01 * t)) * np.exp(-t * 6) * np.minimum(1, t / .003)


def thump():
    t = _t(.28)
    f = 42 + 70 * np.exp(-t * 40)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)


def pop(f=620):
    t = _t(.13)
    fr = f * (1 + .6 * np.minimum(1, t / .05))
    return np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t * 32)


# ------------------------------------------------------------------ music bed
PROGS = [[(0, 'm'), (8, 'M'), (3, 'M'), (10, 'M')],
         [(0, 'm'), (5, 'm'), (8, 'M'), (7, 'M')],
         [(0, 'm'), (3, 'M'), (10, 'M'), (8, 'M')]]
ROOTS = [110.0, 130.81, 146.83, 87.31, 98.0]
ARPS = [[0, 1, 2, 1, 2, 1, 0, 1], [0, 2, 1, 2, 0, 2, 1, 2], [2, 1, 0, 1, 2, 1, 2, 1]]


def music(dur, seed):
    rng = np.random.default_rng(seed)
    bpm = [96, 104, 112, 120][seed % 4]
    root = ROOTS[(seed // 4) % len(ROOTS)]
    prog = PROGS[(seed // 20) % len(PROGS)]
    arp = ARPS[(seed // 60) % len(ARPS)]
    spb = 60.0 / bpm
    m = Track(dur + 2)
    bars = int(dur / (spb * 4)) + 2
    for b in range(bars):
        off, kind = prog[b % 4]
        r = root * 2 ** (off / 12)
        iv = [0, 3 if kind == 'm' else 4, 7]
        tones = [r * 2 * 2 ** (i / 12) for i in iv]
        t0 = b * spb * 4
        m.put(pad(tones, spb * 4 + .6), t0, .20, pan=0)
        m.put(bass(r, spb * 4 - .05), t0, .26)
        for k in range(8):
            f = tones[arp[k % 8]] * (2 if k % 4 == 3 else 1) * 2
            m.put(pluck(f), t0 + k * spb / 2, .075, pan=(-.35 if k % 2 else .35))
        for k in range(4):
            if b >= 1 or k >= 2:
                m.put(kick(), t0 + k * spb, .30)
            m.put(hat(rng), t0 + k * spb + spb / 2, .05, pan=.25)
    # sidechain-style pump on the beat for pad/bass is baked in via the kick; now trim, fade, level
    n = int(dur * SR)
    L, R = m.L[:n].copy(), m.R[:n].copy()
    fi, fo = int(.4 * SR), int(1.0 * SR)
    env = np.ones(n)
    env[:fi] = np.linspace(0, 1, fi)
    env[-fo:] = np.linspace(1, 0, fo)
    L *= env
    R *= env
    rms = np.sqrt(np.mean(L ** 2) + 1e-9)
    g = 0.105 / rms
    return L * g, R * g


# ------------------------------------------------------------------ sfx timing (mirrors engine.html)
def _typing(fx, t0, dur, n, rng, g=.16):
    if n <= 0 or dur <= 0:
        return
    step = max(.035, dur / n)
    t = t0
    while t < t0 + dur:
        fx.put(tick(2000 + 900 * rng.random()), t, g * (.7 + .3 * rng.random()), pan=(rng.random() - .5) * .4)
        t += step * (.8 + .4 * rng.random())


def scene_sfx(fx, sc, rng, first):
    S, E = sc['start'], sc['end']
    D = max(.5, E - S)
    ty = sc.get('type')
    if not first:
        fx.put(whoosh(rng, .5, .0), S - .25, .16)          # cut: whoosh peaks on the scene start
    if ty == 'morph':
        tc = S + min(D * .2, .9); tl = tc + .05; tk = tl + max(.55, D * .2); tr = tk + max(.5, D * .17)
        fx.put(click(), tc, .5); fx.put(thump(), tc, .22); fx.put(tick(900), tl + .05, .12)
        fx.put(chime(1318.5), tk + .04, .16); fx.put(chime(1760, .8), tk + .12, .12); fx.put(pop(500), tr + .05, .14)
    elif ty == 'prompt':
        pr = len(sc.get('prompt', '')) or 1
        t1 = S + .4; du = min(D * .42, pr * .05 + .2); tw = max(t1 + du + .3, S + D * .58)
        fx.put(pop(560), S + .12, .15)
        _typing(fx, t1, du, pr, rng)
        fx.put(click(), t1 + du + .05, .35)
        fx.put(whoosh(rng, .42, .5), tw - .21, .30)         # vertical whip up
        fx.put(chime(988, .6), tw + .1, .10)
    elif ty == 'command':
        q = len(sc.get('query', '')) or 1
        t1 = S + .3; tt = min(D * .34, q * .07 + .2); te = S + D * .62
        fx.put(pop(500), S + .1, .14)
        _typing(fx, t1, tt, q, rng)
        fx.put(whoosh(rng, .3), t1 + tt - .05, .10)
        fx.put(click(), te, .45); fx.put(chime(1174.7), te + .3, .16); fx.put(chime(1568, .8), te + .38, .11)
    elif ty == 'kinetic':
        n = max(2, len(sc.get('words', [])) or 2)
        for i in range(n):
            fx.put(thump(), S + i * D / n, .34); fx.put(tick(1500), S + i * D / n, .12)
    elif ty == 'shapes':
        n = max(2, len(sc.get('items', [])) or 2)
        fx.put(pop(520), S + .08, .14)
        for i in range(1, n):
            fx.put(pop(420 + 120 * i), S + i * D / n, .15); fx.put(whoosh(rng, .28), S + i * D / n - .1, .08)
    elif ty == 'tabs':
        for k, tm in enumerate((S + D * .3, S + D * .55)):
            fx.put(whoosh(rng, .3), tm - .04, .12); fx.put(click(), tm + .16, .25)
    elif ty == 'bars':
        n = len(sc.get('series', [])) or 8
        for i in range(n):
            fx.put(pop(330 * 2 ** (i / 12 * 2)), S + .12 + i * .07, .10)
        fx.put(chime(1568, .5), S + D * .55, .16); fx.put(click(), S + D * .55, .25)
    elif ty == 'stack':
        n = len(sc.get('items', [])) or 2
        for i in range(n):
            fx.put(thump(), S + .04 + i * .13, .22); fx.put(whoosh(rng, .3), S + .04 + i * .13 - .12, .09)
    elif ty == 'orbit':
        fx.put(whoosh(rng, .6, .4), S - .05, .14); fx.put(chime(880, .6), S + D * .0 + .5, .12)
        fx.put(whoosh(rng, .5), S + D * .5 - .05, .16); fx.put(pop(700), S + D * .5 + .45, .12)
    elif ty == 'stat' or ty == 'bignumber':
        dur = min(D * .5, 1.8); n = int(dur / .06)
        for i in range(n):
            fx.put(tick(1400 + 1500 * i / max(1, n)), S + .05 + i * .06, .10)
        fx.put(chime(1568, .5), S + .05 + dur, .14)
    elif ty == 'code':
        c = len(sc.get('cmd', '')) or 8
        cps = max(8, c / max(.8, D * .6))
        fx.put(pop(480), S + .1, .14)
        _typing(fx, S + .35, c / cps, c, rng, .14)
    elif ty == 'name' or ty == 'reveal':
        fx.put(thump(), S + .08, .34); fx.put(chime(1174.7, .8), S + .12, .14)
    elif ty in ('say', 'end', 'icon'):
        fx.put(pop(600), S + .03, .14)
    else:
        fx.put(pop(560), S + .05, .12)


# ------------------------------------------------------------------ build + mix
def _write(path, L, R):
    pcm = (np.clip(np.stack([L, R], 1), -1, 1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def mix(manifest, total, voice_path, out_path):
    """Return out_path: voice + ducked music + sfx at -14 LUFS."""
    scenes = manifest['scenes']
    seed = zlib.crc32((scenes[0].get('narration', '') + str(manifest.get('theme', ''))).encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    base = os.path.splitext(out_path)[0]
    L, R = music(total, seed)
    _write(base + '_music.wav', L, R)
    fx = Track(total)
    for i, sc in enumerate(scenes):
        scene_sfx(fx, sc, rng, i == 0)
    n = int(total * SR)
    pk = max(np.abs(fx.L[:n]).max(), np.abs(fx.R[:n]).max(), 1e-6)
    sc_ = min(1.0, .85 / pk)
    _write(base + '_sfx.wav', fx.L[:n] * sc_, fx.R[:n] * sc_)
    fg = ("[0:a]aformat=sample_rates=44100:channel_layouts=stereo[mu];"
          "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[fx];"
          "[2:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[v1][v2];"
          "[mu][v1]sidechaincompress=threshold=0.02:ratio=6:attack=12:release=420:makeup=1[md];"
          "[md][fx][v2]amix=inputs=3:duration=longest:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[o]")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base + '_music.wav', "-i", base + '_sfx.wav', "-i", voice_path,
                        "-filter_complex", fg, "-map", "[o]", "-ar", "44100", "-t", f"{total:.3f}", out_path],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError("soundtrack mix failed: " + r.stderr[-400:])
    return out_path
