#!/usr/bin/env python3
"""
КАК УМИРАТЬ — Analog Horror Video Generator

A personal meditation on what it's like to be dead.
Rendered in the aesthetic of degraded VHS found footage.
"""

import os, sys, struct, wave, random, math, subprocess, shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── locate bundled ffmpeg ────────────────────────────────────────────────────
import imageio
FFMPEG = imageio.plugins.ffmpeg.get_exe()

# ── constants ────────────────────────────────────────────────────────────────
W, H   = 640, 480
FPS    = 24
OUT    = "/home/user/games-covers/analog_horror.mp4"
FDIR   = "/tmp/ah_frames"
AUDIO  = "/tmp/ah_audio.wav"
SAMPLE_RATE = 44100

FONT_MONO  = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

# ── font cache ───────────────────────────────────────────────────────────────
_font_cache = {}
def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]

# ── VHS effects ──────────────────────────────────────────────────────────────

def apply_scanlines(arr, strength=0.45):
    """Dark horizontal scanlines every 2 rows."""
    out = arr.astype(np.float32)
    out[::2] *= (1.0 - strength)
    return np.clip(out, 0, 255).astype(np.uint8)

def apply_noise(arr, sigma=18):
    """Film grain / static."""
    noise = np.random.normal(0, sigma, arr.shape)
    return np.clip(arr.astype(np.float32) + noise, 0, 255).astype(np.uint8)

def apply_rgb_shift(arr, r_shift=3, b_shift=-3):
    """Chromatic aberration: shift R and B channels horizontally."""
    out = arr.copy()
    if r_shift > 0:
        out[:, r_shift:, 0] = arr[:, :-r_shift, 0]
        out[:, :r_shift, 0] = 0
    elif r_shift < 0:
        rs = -r_shift
        out[:, :-rs, 0] = arr[:, rs:, 0]
        out[:, -rs:, 0] = 0
    if b_shift > 0:
        out[:, b_shift:, 2] = arr[:, :-b_shift, 2]
        out[:, :b_shift, 2] = 0
    elif b_shift < 0:
        bs = -b_shift
        out[:, :-bs, 2] = arr[:, bs:, 2]
        out[:, -bs:, 2] = 0
    return out

def apply_tracking_glitch(arr, n_lines=0, intensity=8):
    """VHS tracking error: shift random horizontal strips."""
    out = arr.copy()
    for _ in range(n_lines):
        y  = random.randint(0, H - 4)
        h  = random.randint(1, 4)
        dx = random.randint(-intensity, intensity)
        strip = arr[y:y+h].copy()
        if dx > 0:
            out[y:y+h, dx:] = strip[:, :-dx]
            out[y:y+h, :dx] = 0
        elif dx < 0:
            dx = -dx
            out[y:y+h, :-dx] = strip[:, dx:]
            out[y:y+h, -dx:] = 0
    return out

def apply_vignette(arr, strength=0.5):
    """Darken corners and edges."""
    ys = np.linspace(-1, 1, H)
    xs = np.linspace(-1, 1, W)
    xg, yg = np.meshgrid(xs, ys)
    dist = np.sqrt(xg**2 + yg**2)
    mask = np.clip(1.0 - strength * dist**1.5, 0.1, 1.0)
    return np.clip(arr * mask[:, :, np.newaxis], 0, 255).astype(np.uint8)

def add_phosphor_bleed(arr, amount=0.6):
    """Slight horizontal smear on bright pixels (CRT phosphor)."""
    img   = Image.fromarray(arr)
    bleed = img.filter(ImageFilter.GaussianBlur(radius=1))
    blend = Image.blend(img, bleed, amount * 0.3)
    return np.array(blend)

def apply_white_flash(arr, alpha):
    """Sudden white flicker (tape damage)."""
    white = np.full_like(arr, 255)
    return np.clip(arr.astype(np.float32) * (1 - alpha) +
                   white.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

def make_static(density=1.0):
    """Pure TV static frame."""
    base = np.random.randint(0, 50, (H, W, 3), dtype=np.uint8)
    if density > 0.3:
        bright = np.random.random((H, W)) < (0.15 * density)
        base[bright] = np.random.randint(180, 255, (bright.sum(), 3))
    return base

def vhs_process(arr, glitch_lines=0, glitch_intensity=8,
                noise_sigma=18, rgb_r=3, rgb_b=-3,
                scanline_strength=0.45, flash_alpha=0.0):
    """Full VHS pipeline."""
    arr = apply_rgb_shift(arr, rgb_r, rgb_b)
    arr = apply_tracking_glitch(arr, glitch_lines, glitch_intensity)
    arr = apply_noise(arr, noise_sigma)
    arr = apply_scanlines(arr, scanline_strength)
    arr = apply_vignette(arr)
    arr = add_phosphor_bleed(arr)
    if flash_alpha > 0:
        arr = apply_white_flash(arr, flash_alpha)
    return arr

# ── text rendering helpers ───────────────────────────────────────────────────

def wrap_text(text, fnt, max_width, draw):
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines, line = [], ""
    for word in words:
        test = (line + " " + word).strip()
        if draw.textlength(test, font=fnt) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines

def draw_centered_text(draw, lines, fnt, y_start, color, line_spacing=1.4):
    """Draw wrapped lines centred horizontally."""
    _, _, _, lh = draw.textbbox((0, 0), "Ag", font=fnt)
    step = int(lh * line_spacing)
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=fnt)
        x  = (W - tw) // 2
        y  = y_start + i * step
        draw.text((x, y), line, font=fnt, fill=color)
    return y_start + len(lines) * step

def render_text_frame(text, fnt_size=28, color=(200, 200, 200),
                       bg=(0, 0, 0), subtitle=None, sub_color=(120, 120, 120),
                       label=None, blink_cursor=False):
    """Render a clean frame with centred text."""
    img  = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    fnt  = font(FONT_SERIF, fnt_size)

    lines = wrap_text(text, fnt, W - 80, draw)
    _, _, _, lh = draw.textbbox((0, 0), "Ag", font=fnt)
    step    = int(lh * 1.4)
    total_h = len(lines) * step
    y_start = (H - total_h) // 2

    draw_centered_text(draw, lines, fnt, y_start, color)

    if subtitle:
        sfnt  = font(FONT_MONO, 14)
        sw    = draw.textlength(subtitle, font=sfnt)
        draw.text(((W - sw)//2, H - 60), subtitle, font=sfnt, fill=sub_color)

    if label:
        lfnt = font(FONT_MONO, 12)
        draw.text((20, 20), label, font=lfnt, fill=(80, 80, 80))

    if blink_cursor:
        cx = W//2 + 4
        cy = y_start + total_h + 8
        draw.rectangle([cx, cy, cx+12, cy+22], fill=color)

    return np.array(img)

def render_mono_frame(lines_list, sizes, colors, y_positions,
                       bg=(0, 0, 0), label=None):
    """Free-form monospace text layout."""
    img  = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    for text, sz, col, y in zip(lines_list, sizes, colors, y_positions):
        fnt = font(FONT_MONO, sz)
        tw  = draw.textlength(text, font=fnt)
        draw.text(((W - tw)//2, y), text, font=fnt, fill=col)

    if label:
        lfnt = font(FONT_MONO, 11)
        draw.text((20, 20), label, font=lfnt, fill=(60, 60, 60))

    return np.array(img)

# ── audio generation ─────────────────────────────────────────────────────────

def generate_audio(duration_secs):
    """Generate eerie low drone + static audio."""
    n  = duration_secs * SAMPLE_RATE
    t  = np.linspace(0, duration_secs, n, endpoint=False)

    # Sub-bass drone: 38Hz fundamental with detuned harmonics
    drone  = 0.28 * np.sin(2 * math.pi * 38.0 * t)
    drone += 0.12 * np.sin(2 * math.pi * 76.3 * t)   # slightly detuned 2nd
    drone += 0.06 * np.sin(2 * math.pi * 114.1 * t)  # 3rd harmonic
    drone += 0.04 * np.sin(2 * math.pi * 19.1 * t)   # subsub

    # Slow amplitude modulation — like a dying pulse
    mod_freq = 0.18
    mod      = 0.65 + 0.35 * np.sin(2 * math.pi * mod_freq * t)
    drone   *= mod

    # High whine (VHS motor) — very quiet
    whine  = 0.015 * np.sin(2 * math.pi * 3420 * t)
    whine += 0.008 * np.sin(2 * math.pi * 6840 * t)

    # White noise (tape hiss)
    hiss = 0.06 * np.random.standard_normal(n)

    # Occasional pop / crackle
    pops = np.zeros(n)
    for _ in range(int(duration_secs * 1.5)):
        pos = random.randint(0, n - 200)
        amp = random.uniform(0.15, 0.5) * random.choice([-1, 1])
        pops[pos:pos+3] = amp

    signal = drone + whine + hiss + pops

    # Soft clamp
    signal = np.tanh(signal * 1.6) * 0.85

    # Fade in/out
    fade = 400
    signal[:fade]  *= np.linspace(0, 1, fade)
    signal[-fade:] *= np.linspace(1, 0, fade)

    # Convert to 16-bit PCM
    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16)

    with wave.open(AUDIO, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())

    print(f"  Audio: {duration_secs}s written to {AUDIO}")

# ── scene definitions ────────────────────────────────────────────────────────
#
#  Each scene is (duration_secs, renderer_fn)
#  renderer_fn(frame_index, total_frames) → np.ndarray (H, W, 3) raw
#  then vhs_process is applied on top.

rng = random.Random(0xDEAD)  # deterministic but eerie

def scene_static(seconds, density=1.0, fade_in=False, fade_out=False):
    def render(fi, total):
        arr = make_static(density)
        if fade_in:
            alpha = 1.0 - fi / total
            arr = (arr.astype(float) * alpha).astype(np.uint8)
        if fade_out:
            alpha = fi / total
            arr = (arr.astype(float) * (1 - alpha)).astype(np.uint8)
        return vhs_process(arr, glitch_lines=rng.randint(2, 6),
                           glitch_intensity=12, noise_sigma=10)
    return (seconds, render)

def scene_text(seconds, text, fnt_size=30, color=(200, 200, 200),
               bg=(0, 0, 0), subtitle=None, sub_color=(100, 100, 100),
               label=None, fade_in_frames=8, fade_out_frames=8,
               glitch_lines=1, noise_sigma=14, rgb_shift=3,
               static_mix=0.0):
    def render(fi, total):
        arr = render_text_frame(
            text, fnt_size=fnt_size, color=color, bg=bg,
            subtitle=subtitle, sub_color=sub_color, label=label)

        if static_mix > 0:
            st  = make_static(0.4)
            arr = np.clip(
                arr.astype(float) * (1 - static_mix) +
                st.astype(float) * static_mix, 0, 255).astype(np.uint8)

        alpha = 1.0
        if fi < fade_in_frames:
            alpha = fi / fade_in_frames
        elif fi > total - fade_out_frames:
            alpha = (total - fi) / fade_out_frames

        if alpha < 1.0:
            arr = (arr.astype(float) * alpha).astype(np.uint8)

        gl = glitch_lines + (rng.randint(0, 3) if rng.random() < 0.15 else 0)
        flash = 0.0
        if rng.random() < 0.03:
            flash = rng.uniform(0.1, 0.4)
        return vhs_process(arr, glitch_lines=gl, noise_sigma=noise_sigma,
                           rgb_r=rgb_shift, rgb_b=-rgb_shift, flash_alpha=flash)
    return (seconds, render)

def scene_multiline(seconds, lines, fnt_size=26, color=(180, 180, 180),
                     stagger_frames=12, glitch_lines=1, noise_sigma=14,
                     label=None):
    """Lines appear one by one with a stagger, then hold."""
    def render(fi, total):
        n_visible = min(len(lines), 1 + fi // stagger_frames)
        img  = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        fnt  = font(FONT_SERIF, fnt_size)
        _, _, _, lh = draw.textbbox((0, 0), "Ag", font=fnt)
        step    = int(lh * 1.5)
        total_h = len(lines) * step
        y0      = (H - total_h) // 2
        for i, line in enumerate(lines[:n_visible]):
            tw   = draw.textlength(line, font=fnt)
            fade = 1.0
            if i == n_visible - 1 and fi % stagger_frames < 4:
                fade = (fi % stagger_frames) / 4
            col = tuple(int(c * fade) for c in color)
            draw.text(((W - tw)//2, y0 + i * step), line, font=fnt, fill=col)
        if label:
            lfnt = font(FONT_MONO, 11)
            draw.text((20, 20), label, font=lfnt, fill=(60, 60, 60))
        arr = np.array(img)
        return vhs_process(arr, glitch_lines=glitch_lines,
                           noise_sigma=noise_sigma)
    return (seconds, render)

def scene_title_card(seconds):
    """Glitchy main title with horizontal scan corruption."""
    def render(fi, total):
        img  = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # big Cyrillic title
        tf   = font(FONT_SERIF, 52)
        text = "КАК УМИРАТЬ"
        tw   = draw.textlength(text, font=tf)
        draw.text(((W - tw)//2, H//2 - 50), text, font=tf,
                  fill=(220, 220, 220))

        # subtitle
        sf   = font(FONT_MONO, 14)
        sub  = "personal account  ·  VHS-C"
        sw   = draw.textlength(sub, font=sf)
        draw.text(((W - sw)//2, H//2 + 30), sub, font=sf, fill=(80, 80, 80))

        arr = np.array(img)

        # heavy RGB shift on title card
        shift = 5 + rng.randint(0, 8)
        arr = apply_rgb_shift(arr, shift, -shift)

        # random horizontal band corrupt
        if rng.random() < 0.5:
            y  = rng.randint(H//2 - 60, H//2 + 60)
            h2 = rng.randint(2, 10)
            dx = rng.randint(-20, 20)
            strip = arr[y:y+h2].copy()
            if dx > 0:
                arr[y:y+h2, dx:] = strip[:, :-dx] if dx < W else 0
            elif dx < 0:
                dx = -dx
                arr[y:y+h2, :-dx] = strip[:, dx:]

        # scanlines & noise
        arr = apply_noise(arr, 20)
        arr = apply_scanlines(arr, 0.5)
        arr = apply_vignette(arr, 0.7)

        # fade in
        if fi < 12:
            arr = (arr.astype(float) * fi / 12).astype(np.uint8)

        return arr
    return (seconds, render)

def scene_found_footage_header(seconds):
    """VHS timestamp / record counter header."""
    lines_data = [
        ("ЗАПИСЬ НАЙДЕНА", FONT_MONO, 18, (80, 80, 80)),
        ("ДАТА: █████ / ██ / ██  ██:██:██", FONT_MONO, 14, (60, 60, 60)),
        ("REC ●  CH 02  SP  [NO SIGNAL]", FONT_MONO, 13, (60, 60, 60)),
        ("ВОСПРОИЗВЕДЕНИЕ...", FONT_MONO, 16, (100, 100, 100)),
    ]
    def render(fi, total):
        img  = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        y    = 120
        for text, fp, sz, col in lines_data:
            fnt = font(fp, sz)
            tw  = draw.textlength(text, font=fnt)
            draw.text(((W - tw)//2, y), text, font=fnt, fill=col)
            y  += sz + 14

        # glitchy box
        draw.rectangle([W//2 - 100, H//2 - 10, W//2 + 100, H//2 + 10],
                       outline=(40, 40, 40))

        arr = np.array(img)
        st  = make_static(0.25)
        arr = np.clip(arr.astype(float) * 0.85 + st.astype(float) * 0.15,
                      0, 255).astype(np.uint8)

        arr = apply_tracking_glitch(arr, n_lines=rng.randint(1, 4),
                                    intensity=6)
        arr = apply_noise(arr, 16)
        arr = apply_scanlines(arr, 0.4)
        arr = apply_vignette(arr)
        return arr
    return (seconds, render)

def scene_dissolve_to_black(seconds):
    """Text 'НИЧЕГО' burns in then fades with heavy corruption."""
    def render(fi, total):
        t    = fi / total
        img  = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # text fades in then back out
        if t < 0.4:
            alpha = t / 0.4
        elif t < 0.7:
            alpha = 1.0
        else:
            alpha = 1.0 - (t - 0.7) / 0.3

        col  = tuple(int(c * alpha) for c in (230, 230, 230))
        fnt  = font(FONT_SERIF, 68)
        text = "НИЧЕГО"
        tw   = draw.textlength(text, font=fnt)
        draw.text(((W - tw)//2, H//2 - 42), text, font=fnt, fill=col)

        arr = np.array(img)

        glitch = int(3 + t * 20)
        sigma  = int(12 + t * 40)
        arr = apply_rgb_shift(arr, int(4 + t * 12), -int(4 + t * 12))
        arr = apply_tracking_glitch(arr, n_lines=glitch, intensity=glitch*2)
        arr = apply_noise(arr, sigma)
        arr = apply_scanlines(arr, 0.5)
        arr = apply_vignette(arr, 0.6 + t * 0.4)

        # final fade to black
        if t > 0.75:
            fade = (t - 0.75) / 0.25
            arr  = (arr.astype(float) * (1 - fade)).astype(np.uint8)

        return arr
    return (seconds, render)

def scene_corruption_burst(seconds, glitch_intensity=30):
    """Maximal corruption — the tape is breaking."""
    def render(fi, total):
        t   = fi / total
        arr = make_static(0.6 + t * 0.4)

        # horizontal bars of near-white
        for _ in range(rng.randint(1, 5)):
            y  = rng.randint(0, H - 4)
            h2 = rng.randint(1, 6)
            arr[y:y+h2] = rng.randint(100, 255)

        arr = apply_tracking_glitch(arr, n_lines=rng.randint(8, 18),
                                    intensity=glitch_intensity)
        arr = apply_rgb_shift(arr, rng.randint(8, 20), -rng.randint(8, 20))
        arr = apply_noise(arr, 25)
        arr = apply_scanlines(arr, 0.3)
        return arr
    return (seconds, render)

def scene_final_message(seconds):
    """
    The dead narrator speaks directly to camera.
    Slowly typed, slightly wrong colour temperature — warmer, more personal.
    """
    msg1 = "Я уже давно пытаюсь тебе сказать."
    msg2 = "Но мёртвых не слышат."
    def render(fi, total):
        t   = fi / total
        img = Image.new("RGB", (W, H), (0, 0, 0))
        d   = ImageDraw.Draw(img)

        f1 = font(FONT_SERIF, 26)
        f2 = font(FONT_SERIF, 26)

        # msg1 types itself in the first half
        chars1 = max(1, int(len(msg1) * min(1.0, t * 2.5)))
        partial1 = msg1[:chars1]
        tw1 = d.textlength(partial1, font=f1)
        d.text(((W - d.textlength(msg1, font=f1))//2, H//2 - 40),
               partial1, font=f1, fill=(210, 200, 180))

        # msg2 appears after msg1 is done
        if t > 0.5:
            chars2 = max(1, int(len(msg2) * min(1.0, (t - 0.5) * 3.0)))
            partial2 = msg2[:chars2]
            tw2 = d.textlength(partial2, font=f2)
            d.text(((W - d.textlength(msg2, font=f2))//2, H//2 + 10),
                   partial2, font=f2, fill=(160, 140, 110))

        # cursor blink
        cursor_phase = int(fi * 2 / FPS) % 2
        if cursor_phase == 0:
            if t <= 0.5:
                cw = d.textlength(partial1, font=f1)
                cx = (W - d.textlength(msg1, font=f1))//2 + cw + 2
                cy = H//2 - 40
            else:
                if t > 0.5:
                    cw = d.textlength(msg2[:max(1, int(len(msg2) * min(1.0, (t - 0.5) * 3.0)))], font=f2)
                    cx = (W - d.textlength(msg2, font=f2))//2 + cw + 2
                    cy = H//2 + 10
                else:
                    cx, cy = W//2, H//2
            d.rectangle([cx, cy + 4, cx + 10, cy + 22], fill=(180, 160, 130))

        arr = np.array(img)
        arr = apply_rgb_shift(arr, 2, -2)
        arr = apply_noise(arr, 13)
        arr = apply_scanlines(arr, 0.42)
        arr = apply_vignette(arr, 0.55)
        return arr
    return (seconds, render)

def scene_text_glitch(seconds, text, fnt_size=30, base_color=(200, 200, 200)):
    """Text that occasionally corrupts individual characters."""
    CORRUPT_CHARS = "█▓▒░▌▐│┼╬░▒▓█╳╱╲╫"

    def corrupt_line(line, intensity):
        out = []
        for c in line:
            if c != ' ' and random.random() < intensity:
                out.append(random.choice(CORRUPT_CHARS))
            else:
                out.append(c)
        return ''.join(out)

    def render(fi, total):
        t         = fi / total
        intensity = 0.0 if t < 0.1 else (t - 0.1) * 0.3
        img  = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        fnt  = font(FONT_SERIF, fnt_size)
        display = corrupt_line(text, intensity)
        lines   = wrap_text(display, fnt, W - 80, draw)
        _, _, _, lh = draw.textbbox((0, 0), "Ag", font=fnt)
        step    = int(lh * 1.4)
        total_h = len(lines) * step
        y0 = (H - total_h) // 2
        for i, line in enumerate(lines):
            col = base_color if random.random() > intensity else (
                random.randint(150, 230),
                random.randint(100, 180),
                random.randint(80, 150))
            tw = draw.textlength(line, font=fnt)
            draw.text(((W - tw)//2, y0 + i * step), line, font=fnt, fill=col)
        arr = np.array(img)
        shift = 3 + int(intensity * 15)
        arr   = apply_rgb_shift(arr, shift, -shift)
        arr   = apply_tracking_glitch(arr, n_lines=int(intensity * 10),
                                      intensity=int(8 + intensity * 20))
        arr   = apply_noise(arr, int(14 + intensity * 30))
        arr   = apply_scanlines(arr, 0.45)
        arr   = apply_vignette(arr)
        return arr
    return (seconds, render)

# ── scene list ───────────────────────────────────────────────────────────────
#
#  This is the film.  Read it top-to-bottom.

SCENES = [
    # ── cold open ──────────────────────────────────────────────────────────
    scene_static(2.5, density=1.0),
    scene_found_footage_header(3.0),
    scene_static(1.0, density=0.8),

    # ── title ──────────────────────────────────────────────────────────────
    scene_title_card(3.0),
    scene_static(0.5, density=0.9),

    # ── 1. the silence ─────────────────────────────────────────────────────
    scene_text(3.5,
        "Сначала всё становится очень тихим.",
        fnt_size=28, color=(190, 190, 190),
        label="01 / 09"),

    scene_text(3.0,
        "Ты слышишь своё сердце.",
        fnt_size=26, color=(170, 170, 170),
        label="01 / 09"),

    scene_corruption_burst(0.8),

    scene_text(3.5,
        "Потом не слышишь.",
        fnt_size=32, color=(210, 210, 210),
        noise_sigma=22,
        label="01 / 09"),

    scene_static(1.5, density=0.7),

    # ── 2. the unfinished ──────────────────────────────────────────────────
    scene_text(3.0,
        "Странно,",
        fnt_size=28, color=(180, 180, 180),
        label="02 / 09"),

    scene_text(3.5,
        "но ты совсем не боишься.",
        fnt_size=28, color=(180, 180, 180),
        label="02 / 09"),

    scene_static(1.0, density=0.6),

    scene_multiline(5.0,
        ["Ты пытаешься вспомнить", "что-то важное."],
        fnt_size=26, stagger_frames=20, label="02 / 09",
        glitch_lines=2),

    scene_corruption_burst(1.0),

    scene_multiline(5.0,
        ["Что-то,", "что нужно было", "сказать."],
        fnt_size=26, stagger_frames=18, glitch_lines=1),

    scene_static(2.0, density=0.65),

    # ── 3. the void ────────────────────────────────────────────────────────
    scene_text(3.5,
        "Темнота — неправильное слово.",
        fnt_size=26, color=(160, 160, 160),
        label="03 / 09"),

    scene_text(3.0,
        "Темнота — это всё ещё что-то.",
        fnt_size=26, color=(150, 150, 150),
        label="03 / 09"),

    scene_text(3.0,
        "Это...",
        fnt_size=36, color=(200, 200, 200),
        noise_sigma=18,
        label="03 / 09"),

    scene_dissolve_to_black(5.0),   # НИЧЕГО

    scene_static(2.0, density=0.5),

    # ── 4. catalogue of absences ───────────────────────────────────────────
    scene_multiline(6.0,
        ["Нет туннеля.", "Нет света.", "Нет бога.", "Нет тебя."],
        fnt_size=24, color=(140, 140, 140),
        stagger_frames=24, glitch_lines=1),

    scene_static(1.5, density=0.75),

    # ── 5. the personal note ───────────────────────────────────────────────
    scene_text(3.0,
        "Я узнал одну вещь о смерти.",
        fnt_size=26, color=(200, 195, 180),
        label="05 / 09"),

    scene_text(4.0,
        "Самое страшное — не боль и не тьма.",
        fnt_size=24, color=(190, 185, 170),
        label="05 / 09"),

    scene_text(4.0,
        "Самое страшное — что тебя просто нет.",
        fnt_size=24, color=(190, 185, 170),
        label="05 / 09", noise_sigma=20),

    scene_text(3.5,
        "Нет даже осознания отсутствия.",
        fnt_size=24, color=(170, 165, 150),
        label="05 / 09"),

    scene_static(2.0, density=0.8),

    # ── 6. tape damage ─────────────────────────────────────────────────────
    scene_text_glitch(5.0,
        "Всё что ты считал собой — привычки, страхи, голос — исчезает.",
        fnt_size=22, base_color=(180, 180, 180)),

    scene_corruption_burst(1.5, glitch_intensity=40),

    scene_text_glitch(4.0,
        "Не медленно. Не постепенно. Просто — уже нет.",
        fnt_size=24, base_color=(200, 195, 185)),

    scene_static(2.5, density=0.9),

    # ── 7. the message ─────────────────────────────────────────────────────
    scene_final_message(7.0),

    scene_corruption_burst(2.0, glitch_intensity=50),

    # ── 8. coda ────────────────────────────────────────────────────────────
    scene_text(4.0,
        "Продолжай жить.",
        fnt_size=30, color=(210, 205, 190),
        subtitle="пока можешь",
        sub_color=(100, 95, 80),
        noise_sigma=12),

    scene_static(3.0, density=1.0, fade_out=True),
]

# ── render loop ──────────────────────────────────────────────────────────────

def render_all():
    os.makedirs(FDIR, exist_ok=True)
    # wipe old frames
    for f in os.listdir(FDIR):
        if f.endswith('.png'):
            os.remove(os.path.join(FDIR, f))

    total_frames = sum(int(s[0] * FPS) for s in SCENES)
    print(f"  Rendering {total_frames} frames across {len(SCENES)} scenes …")

    frame_idx = 0
    for si, (duration, render_fn) in enumerate(SCENES):
        n = max(1, int(duration * FPS))
        for fi in range(n):
            arr = render_fn(fi, n)
            img = Image.fromarray(arr.astype(np.uint8), 'RGB')
            img.save(os.path.join(FDIR, f"frame_{frame_idx:05d}.png"))
            frame_idx += 1
        pct = frame_idx / total_frames * 100
        print(f"  Scene {si+1:02d}/{len(SCENES)}  ({pct:.0f}%)", end='\r')

    print(f"\n  Done — {frame_idx} frames written to {FDIR}")
    return frame_idx

# ── assemble with ffmpeg ──────────────────────────────────────────────────────

def assemble(n_frames):
    total_secs = n_frames / FPS
    print(f"  Generating {total_secs:.1f}s of audio …")
    generate_audio(int(math.ceil(total_secs)) + 1)

    cmd = [
        FFMPEG, "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(FDIR, "frame_%05d.png"),
        "-i", AUDIO,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        OUT,
    ]
    print(f"  Running FFmpeg …")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFmpeg stderr:", result.stderr[-2000:])
        sys.exit(1)
    size_mb = os.path.getsize(OUT) / 1_048_576
    print(f"  Output: {OUT}  ({size_mb:.1f} MB)")

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== КАК УМИРАТЬ  ·  Analog Horror Generator ===\n")
    n = render_all()
    assemble(n)
    print("\nFinished. ✓\n")
