#!/usr/bin/env python3
"""
Pixel-based HID screen driver for the Mintaka macropad.
Sends arbitrary 128x64 monochrome images over raw HID.
Receives screen-switch requests from the device's rotary encoder.

Usage:
    Run directly for a system monitor demo, or import HIDPixelScreen
    to send any PIL Image to the display.
"""

import hid
import os
import psutil
import random
import subprocess
import threading
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageOps
from time import sleep, monotonic
from urllib.parse import urlparse, unquote
from urllib.request import urlopen
from io import BytesIO


try:
    import numpy as np
    import sounddevice as sd
    _audio_available = True
except ImportError:
    _audio_available = False

VENDOR_ID   = 0x7368
PRODUCT_ID  = 0x4F1B
USAGE_PAGE  = 0xFF60
USAGE       = 0x61

REPORT_SIZE     = 32
OLED_WIDTH      = 128
OLED_HEIGHT     = 64
FRAMEBUFFER_SIZE = OLED_WIDTH * OLED_HEIGHT // 8  # 1024
PAYLOAD_SIZE    = REPORT_SIZE - 1                  # 31 bytes per report

CMD_START      = 0x01
CMD_DATA       = 0x02
CMD_SCREEN_REQ = 0x03  # device → host: encoder changed screen


class DeviceNotConnected(Exception):
    pass


class HIDPixelScreen:
    def __init__(self, vendor_id, product_id, usage_page, usage):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.usage_page = usage_page
        self.usage = usage
        self.connected = False

    def connect(self):
        interfaces = hid.enumerate(self.vendor_id, self.product_id)
        raw_hid = [
            i for i in interfaces
            if i["usage_page"] == self.usage_page and i["usage"] == self.usage
        ]
        if not raw_hid:
            raise DeviceNotConnected()
        try:
            self.interface = hid.Device(path=raw_hid[0]["path"])
        except hid.HIDException:
            raise DeviceNotConnected()

    def __enter__(self):
        try:
            self.connect()
            self.connected = True
        except DeviceNotConnected:
            pass
        return self

    def __exit__(self, *args):
        if self.connected:
            self.interface.close()

    def send_image(self, image):
        """Send a PIL Image to the display. Resized/converted to 128x64 monochrome automatically."""
        if not self.connected:
            return

        img = image.resize((OLED_WIDTH, OLED_HEIGHT)).convert("1")
        pixel_data = img.tobytes("raw", "1")

        for i in range(0, FRAMEBUFFER_SIZE, PAYLOAD_SIZE):
            chunk = pixel_data[i:i + PAYLOAD_SIZE]

            report = bytearray(REPORT_SIZE + 1)
            report[0] = 0x00                              # HID report ID
            report[1] = CMD_START if i == 0 else CMD_DATA # command byte
            report[2:2 + len(chunk)] = chunk              # pixel data

            try:
                self.interface.write(bytes(report))
            except hid.HIDException:
                self.connected = False
                break

    def read_device_state(self, timeout_ms=0):
        """Read device state (screen index + layer) from the device.
        Blocks up to timeout_ms for the first message, then drains any
        remaining queued messages non-blocking. Returns (screen, layer)
        or None if no message arrived."""
        if not self.connected:
            return None
        latest = None
        try:
            data = self.interface.read(32, timeout=timeout_ms)
            if data and len(data) >= 3 and data[0] == CMD_SCREEN_REQ:
                latest = (data[1], data[2])
            # Drain any extra queued messages (fast encoder turns)
            while True:
                data = self.interface.read(32, timeout=0)
                if not data:
                    break
                if len(data) >= 3 and data[0] == CMD_SCREEN_REQ:
                    latest = (data[1], data[2])
        except hid.HIDException:
            self.connected = False
        return latest


# --- Demo screens ---

class AlignedDraw:
    """Wrapper around ImageDraw that corrects font-dependent vertical offset.

    Different fonts include varying amounts of internal leading (empty space
    above glyphs), causing text to render lower than the specified y coordinate.
    This wrapper measures the offset once and subtracts it from every text call,
    so the visual top of the text always lands at the y you specify.
    """
    def __init__(self, image, font):
        self._draw = ImageDraw.Draw(image)
        self._y_offset = font.getbbox("Ay")[1]

    def text(self, xy, text, **kwargs):
        self._draw.text((xy[0], xy[1] - self._y_offset), text, **kwargs)

    def __getattr__(self, name):
        return getattr(self._draw, name)


LAYER_NAMES = {0: "MACRO", 1: "NUMPAD"}


def draw_header(draw, font, title, layer):
    """Draw an inverted header bar with screen title and layer name."""
    layer_name = LAYER_NAMES.get(layer, f"L{layer}")
    draw.rectangle([0, 0, 127, 12], fill=1)
    draw.text((2, 1), title, fill=0, font=font)
    # Right-align layer name
    layer_width = draw.textlength(layer_name, font=font)
    draw.text((125 - layer_width, 1), layer_name, fill=0, font=font)


def draw_progress_bar(draw, x, y, width, height, percent):
    draw.rectangle([x, y, x + width, y + height], outline=1)
    fill_width = int((width - 2) * min(percent, 100) / 100)
    if fill_width > 0:
        draw.rectangle([x + 1, y + 1, x + 1 + fill_width, y + height - 1], fill=1)


def render_system_info(font, layer=0):
    img = Image.new("1", (OLED_WIDTH, OLED_HEIGHT), 0)
    draw = AlignedDraw(img, font)

    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()

    draw_header(draw, font, "SYSTEM", layer)

    draw.text((0, 16), f"CPU  {cpu:5.1f}%", fill=1, font=font)
    draw_progress_bar(draw, 68, 16, 59, 9, cpu)

    draw.text((0, 28), f"RAM  {ram.percent:5.1f}%", fill=1, font=font)
    draw_progress_bar(draw, 68, 28, 59, 9, ram.percent)

    ram_used_gb = (ram.total - ram.available) / (1024 ** 3)
    ram_total_gb = ram.total / (1024 ** 3)
    draw.text((0, 42), f"MEM: {ram_used_gb:.1f}/{ram_total_gb:.1f} GB", fill=1, font=font)

    # CPU temp (left) + GPU temp (right)
    temp_line = ""
    temps = psutil.sensors_temperatures()
    if temps:
        first_sensor = list(temps.values())[0]
        if first_sensor:
            temp_line = f"CPU: {first_sensor[0].current:.0f}C"
    gpu = _query_gpu()
    if gpu:
        gpu_temp = f"GPU: {gpu['temp']:.0f}C"
        if temp_line:
            draw.text((0, 54), temp_line, fill=1, font=font)
            tw = draw.textlength(gpu_temp, font=font)
            draw.text((127 - tw, 54), gpu_temp, fill=1, font=font)
        else:
            draw.text((0, 54), gpu_temp, fill=1, font=font)
    elif temp_line:
        draw.text((0, 54), temp_line, fill=1, font=font)

    return img


def _format_rate(bytes_per_sec):
    """Format a byte rate into a human-readable string."""
    if bytes_per_sec >= 1024 ** 2:
        return f"{bytes_per_sec / (1024 ** 2):.1f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.0f} KB/s"
    else:
        return f"{bytes_per_sec:.0f} B/s"


_io_samples = []  # list of (timestamp, net_sent, net_recv, disk_read, disk_write)
_IO_WINDOW = 1.0  # rolling average window in seconds
_public_ip = None
_public_ip_time = 0


def _get_local_ip():
    for iface, addrs in psutil.net_if_addrs().items():
        if iface == "lo":
            continue
        for addr in addrs:
            if addr.family.name == "AF_INET":
                return addr.address
    return None


def _get_public_ip():
    global _public_ip, _public_ip_time
    now = monotonic()
    if _public_ip is not None and (now - _public_ip_time) < 300:
        return _public_ip
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '2', 'https://api.ipify.org'],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            _public_ip = result.stdout.strip()
            _public_ip_time = now
    except Exception:
        pass
    return _public_ip


def render_io(font, layer=0):
    img = Image.new("1", (OLED_WIDTH, OLED_HEIGHT), 0)
    draw = AlignedDraw(img, font)
    draw_header(draw, font, "IO", layer)

    now = monotonic()
    net = psutil.net_io_counters()
    disk = psutil.disk_io_counters()

    _io_samples.append((now, net.bytes_sent, net.bytes_recv, disk.read_bytes, disk.write_bytes))
    # Trim samples older than the rolling window
    cutoff = now - _IO_WINDOW
    while _io_samples and _io_samples[0][0] < cutoff:
        _io_samples.pop(0)

    if len(_io_samples) >= 2:
        oldest = _io_samples[0]
        dt = now - oldest[0]
        if dt > 0:
            net_up = (net.bytes_sent - oldest[1]) / dt
            net_dn = (net.bytes_recv - oldest[2]) / dt
            disk_r = (disk.read_bytes - oldest[3]) / dt
            disk_w = (disk.write_bytes - oldest[4]) / dt
        else:
            net_up = net_dn = disk_r = disk_w = 0
    else:
        net_up = net_dn = disk_r = disk_w = 0

    up_str = _format_rate(net_up)
    dn_str = _format_rate(net_dn)
    draw.text((0, 16), f"UP {up_str}", fill=1, font=font)
    dw = draw.textlength(f"DN {dn_str}", font=font)
    draw.text((127 - dw, 16), f"DN {dn_str}", fill=1, font=font)

    dr_str = _format_rate(disk_r)
    dw_str = _format_rate(disk_w)
    draw.text((0, 28), f"DR {dr_str}", fill=1, font=font)
    dww = draw.textlength(f"DW {dw_str}", font=font)
    draw.text((127 - dww, 28), f"DW {dw_str}", fill=1, font=font)

    local_ip = _get_local_ip()
    if local_ip:
        draw.text((0, 42), f"LAN {local_ip}", fill=1, font=font)

    pub_ip = _get_public_ip()
    if pub_ip:
        draw.text((0, 54), f"WAN {pub_ip}", fill=1, font=font)

    return img


# --- GPU stats (NVIDIA) ---

_gpu_cache_time = 0
_gpu_cache_data = None


def _query_gpu():
    """Query nvidia-smi for GPU stats. Cached for 0.5s to avoid subprocess overhead."""
    global _gpu_cache_time, _gpu_cache_data
    now = monotonic()
    if _gpu_cache_data is not None and (now - _gpu_cache_time) < 0.5:
        return _gpu_cache_data
    try:
        result = subprocess.run(
            ['nvidia-smi',
             '--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,'
             'memory.used,memory.total,power.draw,power.limit',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return None
        parts = [p.strip() for p in result.stdout.strip().split(',')]
        if len(parts) < 8:
            return None
        _gpu_cache_data = {
            'name': parts[0],
            'temp': float(parts[1]),
            'gpu_util': float(parts[2]),
            'mem_util': float(parts[3]),
            'mem_used': float(parts[4]),
            'mem_total': float(parts[5]),
            'power_draw': float(parts[6]),
            'power_limit': float(parts[7]),
        }
        _gpu_cache_time = now
        return _gpu_cache_data
    except Exception:
        return None


def render_gpu_info(font, layer=0):
    img = Image.new("1", (OLED_WIDTH, OLED_HEIGHT), 0)
    draw = AlignedDraw(img, font)
    draw_header(draw, font, "GPU", layer)

    gpu = _query_gpu()
    if not gpu:
        draw.text((20, 32), "NO NVIDIA GPU", fill=1, font=font)
        return img

    name = gpu['name'].replace('NVIDIA ', '').replace('GeForce ', '')
    draw.text((0, 16), name, fill=1, font=font)

    draw.text((0, 28), f"UTIL {gpu['gpu_util']:4.0f}%", fill=1, font=font)
    draw_progress_bar(draw, 68, 28, 59, 9, gpu['gpu_util'])

    draw.text((0, 40), f"VRAM {gpu['mem_util']:4.0f}%", fill=1, font=font)
    draw_progress_bar(draw, 68, 40, 59, 9, gpu['mem_util'])

    power_pct = (gpu['power_draw'] / gpu['power_limit'] * 100) if gpu['power_limit'] > 0 else 0
    draw.text((0, 52), f"PWR  {power_pct:4.0f}%", fill=1, font=font)
    draw_progress_bar(draw, 68, 52, 59, 9, power_pct)

    return img


# --- Audio capture for visualizer ---

_AUDIO_RATE = 48000  # Match PipeWire default
_AUDIO_CHUNK = 2048
_audio_bands = [0.0] * 16
_audio_peak = 0.001
_audio_thread = None

if _audio_available:
    _band_edges = np.logspace(np.log10(30), np.log10(_AUDIO_RATE / 2), 17)

    def _find_monitor_source():
        """Get the monitor source name for the default audio output via pactl."""
        try:
            result = subprocess.run(['pactl', 'get-default-sink'],
                                    capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip() + ".monitor"
            # Fallback: parse pactl info
            result = subprocess.run(['pactl', 'info'],
                                    capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if 'Default Sink:' in line:
                    return line.split(':', 1)[1].strip() + ".monitor"
        except Exception:
            pass
        return None

    def _audio_callback(indata, frames, time_info, status):
        global _audio_bands, _audio_peak
        if status:
            return
        mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
        windowed = mono * np.hanning(len(mono))
        fft_mag = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(windowed), 1.0 / _AUDIO_RATE)

        raw = []
        for i in range(16):
            mask = (freqs >= _band_edges[i]) & (freqs < _band_edges[i + 1])
            raw.append(float(np.mean(fft_mag[mask])) if mask.any() else 0.0)

        # Auto-level: fast attack, slow decay on peak
        peak = max(raw) if raw else 0.0
        _audio_peak = peak if peak > _audio_peak else _audio_peak * 0.995
        _audio_peak = max(_audio_peak, 0.001)

        # Normalize and smooth: instant rise, gradual fall
        for i in range(16):
            level = min(1.0, raw[i] / _audio_peak)
            if level > _audio_bands[i]:
                _audio_bands[i] = level
            else:
                _audio_bands[i] = _audio_bands[i] * 0.75 + level * 0.25

    def _start_audio_capture():
        global _audio_thread
        if _audio_thread is not None and _audio_thread.is_alive():
            return
        monitor = _find_monitor_source()
        if monitor:
            os.environ['PULSE_SOURCE'] = monitor
        def run():
            try:
                with sd.InputStream(channels=1, samplerate=_AUDIO_RATE,
                                    blocksize=_AUDIO_CHUNK, callback=_audio_callback):
                    while True:
                        sd.sleep(1000)
            except Exception:
                pass
        _audio_thread = threading.Thread(target=run, daemon=True)
        _audio_thread.start()


# --- Spotify screen (animated) ---

_viz_bars = [0.0] * 16
_title_offset = 0
_last_title = ""
_art_cache = {}


def _format_time(microseconds):
    s = max(0, int(microseconds / 1_000_000))
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}"


def _get_spotify_info():
    try:
        result = subprocess.run(
            ['playerctl', '-p', 'spotify', 'metadata', '--format',
             '{{status}}|{{title}}|{{artist}}|{{mpris:length}}|{{position}}|{{mpris:artUrl}}'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        parts = result.stdout.strip().split('|', 5)
        if len(parts) < 6:
            return None
        status, title, artist, length, position, art_url = parts
        length = int(length) if length else 0
        position = int(position) if position else 0
        return {
            'status': status,
            'title': title.upper(),
            'artist': artist.upper(),
            'position': position,
            'length': length,
            'progress': (position / length * 100) if length > 0 else 0,
            'art_url': art_url,
        }
    except Exception:
        return None


def _load_album_art(url, size):
    if not url:
        return None
    if url in _art_cache:
        return _art_cache[url]
    try:
        if url.startswith('file://'):
            raw = Image.open(unquote(urlparse(url).path))
        elif url.startswith('http'):
            raw = Image.open(BytesIO(urlopen(url, timeout=2).read()))
        else:
            return None

        art = raw.convert("L")                                         # grayscale
        art = art.resize((size * 2, size * 2), Image.LANCZOS)          # oversample to 2x
        art = ImageOps.autocontrast(art, cutoff=2)                     # stretch histogram
        art = ImageEnhance.Contrast(art).enhance(1.5)                  # push darks/lights apart
        art = art.filter(ImageFilter.GaussianBlur(1.5))                # smooth out noise
        art = art.resize((size, size), Image.LANCZOS)                  # downsample to target
        art = art.convert("1")                                         # dither with clean input

        _art_cache.clear()
        _art_cache[url] = art
        return art
    except Exception:
        return None


def render_spotify(font, layer=0):
    global _viz_bars, _title_offset, _last_title

    img = Image.new("1", (OLED_WIDTH, OLED_HEIGHT), 0)
    draw = AlignedDraw(img, font)

    draw_header(draw, font, "SPOTIFY", layer)

    info = _get_spotify_info()
    if not info:
        draw.text((24, 32), "NOT PLAYING", fill=1, font=font)
        _viz_bars = [0.0] * 16
        return img

    # Album art (32x32, dithered to mono)
    ART_SIZE = 32
    art = _load_album_art(info['art_url'], ART_SIZE)
    if art:
        img.paste(art, (0, 14))
    else:
        draw.rectangle([0, 14, ART_SIZE - 1, 14 + ART_SIZE - 1], outline=1)

    # Song info (right of album art)
    tx = ART_SIZE + 4
    max_ch = (OLED_WIDTH - tx) // 7

    # Scrolling title
    title = info['title']
    if title != _last_title:
        _title_offset = 0
        _last_title = title
    if len(title) > max_ch:
        padded = title + "   " + title
        display_title = padded[_title_offset:_title_offset + max_ch]
        _title_offset = (_title_offset + 1) % (len(title) + 3)
    else:
        display_title = title

    draw.text((tx, 16), display_title, fill=1, font=font)
    draw.text((tx, 27), info['artist'][:max_ch], fill=1, font=font)
    draw.text((tx, 38), f"{_format_time(info['position'])}/{_format_time(info['length'])}", fill=1, font=font)

    # Progress bar (full width, thin)
    draw.rectangle([0, 48, 127, 49], outline=1)
    fill_w = int(126 * info['progress'] / 100)
    if fill_w > 0:
        draw.rectangle([1, 48, fill_w, 49], fill=1)

    # Visualizer bars driven by real audio (falls back to random if unavailable)
    VIZ_TOP = 52
    VIZ_H = 12
    BAR_W = 6
    NUM_BARS = 16  # 16 * (6 + 2) = 128

    if _audio_available:
        _start_audio_capture()
        bands = list(_audio_bands)
    else:
        bands = None

    for i in range(NUM_BARS):
        if bands is not None:
            h = max(1, int(bands[i] * VIZ_H))
        else:
            if info['status'] == 'Playing':
                target = random.uniform(2, VIZ_H)
                _viz_bars[i] += (target - _viz_bars[i]) * 0.5
            else:
                _viz_bars[i] = max(1, _viz_bars[i] * 0.8)
            h = max(1, int(_viz_bars[i]))
        x = i * (BAR_W + 2)
        draw.rectangle(
            [x, VIZ_TOP + VIZ_H - h, x + BAR_W - 1, VIZ_TOP + VIZ_H - 1],
            fill=1
        )

    return img


# Add/remove/reorder render functions here. Keep NUM_SCREENS in the firmware
# (pixel_screen.c) in sync with the length of this list.
SCREENS = [render_system_info, render_gpu_info, render_io, render_spotify]


def main():
    current_screen = 0
    current_layer = 0
    error_printed = False
    init_printed = False

    font_path = "/home/shurjo/projects/hid_oled/fonts/route159_110/Route159-Light.otf"
    font_size = 11
    font = ImageFont.truetype(font_path, font_size)

    while True:
        with HIDPixelScreen(VENDOR_ID, PRODUCT_ID, USAGE_PAGE, USAGE) as screen:
            if screen.connected:
                if error_printed:
                    print("Device connected")
                    error_printed = False
                if not init_printed:
                    print("Device connected")
                    init_printed = True

                while screen.connected:
                    # 500ms timeout: fast enough for ~2fps visualizer animation
                    # while still being efficient for static screens.
                    # Returns immediately on encoder/layer events.
                    state = screen.read_device_state(timeout_ms=250)
                    if state is not None:
                        idx, layer = state
                        if 0 <= idx < len(SCREENS):
                            current_screen = idx
                        current_layer = layer

                    img = SCREENS[current_screen](font, current_layer)
                    screen.send_image(img)

                print("Device disconnected")
                error_printed = True
            else:
                if not error_printed:
                    print("Device not connected")
                    error_printed = True
        sleep(1)


if __name__ == "__main__":
    main()
