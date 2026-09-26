"""Minimal GIF89a encoder with exact control over frame count and timing.

PIL's writer silently merges byte-identical consecutive frames and sums their
durations, which destroys the reference contract (414 discrete full-canvas
composites with a specific delay histogram). This encoder never merges: it emits
one graphic-control extension + one full-canvas image descriptor per frame.

Emits: GIF89a, 256-entry global colour table, disposal=1 on every frame, and
deliberately NO NETSCAPE2.0 application extension so the file plays once.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# GIF packs sub-blocks at up to 255 bytes each.
_MAX_SUBBLOCK = 255
# LZW dictionary ceiling; GIF must reset before exceeding 12-bit codes.
_LZW_MAX = 4096


class _BitWriter:
    """LSB-first bit packer, as GIF's LZW stream requires."""

    def __init__(self) -> None:
        self._out = bytearray()
        self._cur = 0
        self._nbits = 0

    def write(self, code: int, width: int) -> None:
        self._cur |= code << self._nbits
        self._nbits += width
        while self._nbits >= 8:
            self._out.append(self._cur & 0xFF)
            self._cur >>= 8
            self._nbits -= 8

    def flush(self) -> bytes:
        if self._nbits:
            self._out.append(self._cur & 0xFF)
            self._cur = 0
            self._nbits = 0
        return bytes(self._out)


def _lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    """GIF variable-width LZW. Returns the raw code stream (no sub-blocks)."""
    clear_code = 1 << min_code_size
    eoi_code = clear_code + 1
    code_width = min_code_size + 1
    next_code = eoi_code + 1

    # dict maps (prefix, suffix) -> code
    table: dict[tuple[int, int], int] = {}
    bw = _BitWriter()
    bw.write(clear_code, code_width)

    prefix = indices[0]
    for i in range(1, len(indices)):
        suffix = indices[i]
        key = (prefix, suffix)
        found = table.get(key)
        if found is not None:
            prefix = found
            continue
        bw.write(prefix, code_width)
        if next_code < _LZW_MAX:
            table[key] = next_code
            next_code += 1
            # width grows when the next code to be assigned needs one more bit
            if next_code > (1 << code_width) and code_width < 12:
                code_width += 1
        else:
            # table full: reset the dictionary
            bw.write(clear_code, code_width)
            table.clear()
            code_width = min_code_size + 1
            next_code = eoi_code + 1
        prefix = suffix

    bw.write(prefix, code_width)
    bw.write(eoi_code, code_width)
    return bw.flush()


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), _MAX_SUBBLOCK):
        chunk = data[i:i + _MAX_SUBBLOCK]
        out.append(len(chunk))
        out += chunk
    out.append(0)  # block terminator
    return bytes(out)


def _global_color_table(pal: Image.Image) -> bytes:
    # force exactly 256 entries
    flat = [0] * (256 * 3)
    src = pal.convert("P").getpalette() or []
    for i in range(min(256, len(src) // 3)):
        flat[i * 3:i * 3 + 3] = src[i * 3:i * 3 + 3]
    return bytes(flat)


def write_gif(
    out_path: Path,
    frames: list[Image.Image],
    durations_ms: list[int],
    disposal: int = 1,
) -> dict:
    """Write a single-play GIF. `frames` must all be P-mode, same size."""
    if len(frames) != len(durations_ms):
        raise ValueError(f"{len(frames)} frames vs {len(durations_ms)} durations")

    w, h = frames[0].size
    first = frames[0]
    buf = bytearray()

    # --- header + logical screen descriptor
    buf += b"GIF89a"
    buf += bytes([w & 0xFF, (w >> 8) & 0xFF, h & 0xFF, (h >> 8) & 0xFF])
    # 0xF7: GCT present, colour resolution 8-bit, unsorted, 256-entry table
    buf += bytes([0xF7, 0x00, 0x00])
    buf += _global_color_table(first)

    # no NETSCAPE2.0 extension -> plays once

    min_code_size = 8
    for i, (frame, dur) in enumerate(zip(frames, durations_ms)):
        delay_cs = max(1, round(dur / 10))

        # --- graphic control extension: disposal, no transparency, delay
        buf += bytes([0x21, 0xF9, 0x04])
        packed = ((disposal & 0x07) << 2)  # transparency flag 0, input 0
        buf += bytes([packed, delay_cs & 0xFF, (delay_cs >> 8) & 0xFF, 0x00, 0x00])

        # --- image descriptor: full canvas, no local table, not interlaced
        buf += bytes([0x2C])
        buf += bytes([0x00, 0x00, 0x00, 0x00, w & 0xFF, (w >> 8) & 0xFF,
                      h & 0xFF, (h >> 8) & 0xFF, 0x00])

        buf += bytes([min_code_size])
        buf += _sub_blocks(_lzw_encode(frame.tobytes(), min_code_size))

    buf += b"\x3B"  # trailer
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(buf))
    return {"frames": len(frames), "bytes": len(buf)}


def parse_structure(path: Path) -> dict:
    """Walk the byte stream. PIL does not surface the GCE disposal field, so the
    only trustworthy check is a raw block walk."""
    raw = path.read_bytes()
    i = 13 + 768  # header + logical screen descriptor + 256-entry GCT
    frames = 0
    disposals: list[int] = []
    rects: list[tuple[int, int, int, int]] = []
    loop = False
    gce = 0
    while i < len(raw):
        b = raw[i]
        if b == 0x21:  # extension
            label = raw[i + 1]
            if label == 0xF9:  # graphic control
                size = raw[i + 2]
                blk = raw[i + 3:i + 3 + size]
                disposals.append((blk[0] >> 2) & 0x07)
                gce += 1
                i += 3 + size + 1
            elif label == 0xFF:  # application (NETSCAPE loop)
                loop = True
                i += 2
                while raw[i] != 0:
                    i += 1 + raw[i]
                i += 1
            else:
                i += 2
                while raw[i] != 0:
                    i += 1 + raw[i]
                i += 1
        elif b == 0x2C:  # image descriptor
            rects.append((raw[i + 1] | (raw[i + 2] << 8),
                          raw[i + 3] | (raw[i + 4] << 8),
                          raw[i + 5] | (raw[i + 6] << 8),
                          raw[i + 7] | (raw[i + 8] << 8)))
            i += 10
            i += 1  # LZW min code size
            while raw[i] != 0:
                i += 1 + raw[i]
            i += 1
            frames += 1
        elif b == 0x3B:
            break
        else:
            i += 1
    return {
        "image_frames": frames,
        "gce_count": gce,
        "disposals": sorted(set(disposals)),
        "disposal_count": len(disposals),
        "rects": sorted(set(rects)),
        "full_canvas": set(rects) == {(0, 0, 1552, 992)},
        "all_disposal_1": set(disposals) == {1} and gce == frames,
        "loop_extension": loop,
    }


def validate_gif(path: Path) -> dict:
    """Decode and measure, rather than trusting the encoder."""
    raw = path.read_bytes()
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)

    hist: dict[int, int] = {}
    for i in range(n):
        im.seek(i)
        d = int(im.info.get("duration", 0))
        hist[d] = hist.get(d, 0) + 1

    total = sum(k * v for k, v in hist.items())
    st = parse_structure(path)
    return {
        "frames": n,
        "size": list(im.size),
        "delay_histogram": dict(sorted(hist.items())),
        "total_ms": total,
        "disposals": st["disposals"],
        "all_disposal_1": st["all_disposal_1"],
        "full_canvas": st["full_canvas"],
        "loops": st["loop_extension"],
        "gif89a": raw[:6] == b"GIF89a",
        "bytes": len(raw),
        "mb": round(len(raw) / 1e6, 2),
    }
