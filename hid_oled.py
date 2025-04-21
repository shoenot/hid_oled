import hid
import GPUtil
import dbus 
import psutil
from time import sleep, time
from math import ceil
from psutil._common import bytes2human
from format import format

vendor_id       = 0x7368
product_id      = 0x4f1b

usage_page      = 0xff60
usage           = 0x61

report_length   = 32
num_screens     = 3
num_chars       = 18
num_lines       = 4

# Initialize the arrays for network and disk transfer rates
net_bytes_recv = [0, time()]
net_bytes_sent = [0, time()]

sda_bytes_read = [0, time()]
sda_bytes_write = [0, time()]

nvme_bytes_read = [0, time()]
nvme_bytes_write = [0, time()]

# Initialize dbus session for spotify
session_bus = dbus.SessionBus()

class DeviceNotConnected(Exception):
    pass

class HID_Screen():
    def __init__(self, vendor_id, product_id, usage_page, usage):
        self.vendor_id, self.product_id, self.usage_page, self.usage = vendor_id, product_id, usage_page, usage
        self.screen_buffer = [" "] * (num_lines * num_screens) # populate the screen buffer with empty screens
        self.line_number = 0
        self.connected = False
    
    def connect_to_hid_interface(self):
        device_interfaces = hid.enumerate(self.vendor_id, self.product_id)
        raw_hid_interfaces = [i for i in device_interfaces if i['usage_page'] == self.usage_page and i['usage'] == self.usage] 
        if len(raw_hid_interfaces) == 0:
            raise DeviceNotConnected()
        try: 
            self.interface = hid.Device(path=raw_hid_interfaces[0]['path'])
        except hid.HIDException:
            raise DeviceNotConnected()

    def __enter__(self):
        try:
            self.connect_to_hid_interface() 
            self.connected = True
        except DeviceNotConnected:
            pass
        return self

    def add_to_buffer(self, line_number, line):
        self.screen_buffer[line_number] = str(line)[:num_chars]

    def send_screen(self):
        if self.connected:
            for idx, line in enumerate(self.screen_buffer):
                linebytes = list(bytes(line, "utf-8"))
                request_data = [0x00] * (report_length + 1)
                request_data[1:len(linebytes)] = linebytes
                # First line starts with a 0x01
                if idx == 0:
                    request_data[0] = 0x01
                else:
                    request_data[0] = 0x02
                # Copy over the bytes and empty the screen buffer
                request_report = bytes(request_data)
                self.screen_buffer = [" "] * num_lines
                try:
                    self.interface.write(request_report)
                except hid.HIDException:
                    break

    def __exit__(self, exc_type, exc_value, traceback):
        if self.connected:
            self.interface.close()

def align_strings(name, value):
    return f"{name:<9}{value:>9}"

def timestring(microseconds):
    seconds = ceil(microseconds/1000000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
    else:
        return "{:02}:{:02}".format(int(minutes), int(seconds))

def net_rates():
    global net_bytes_recv, net_bytes_sent
    io_counters = psutil.net_io_counters()

    diff_recv = io_counters.bytes_recv - net_bytes_recv[0]
    rate_recv = diff_recv / (time() - net_bytes_recv[1])
    diff_sent = io_counters.bytes_sent - net_bytes_sent[0]
    rate_sent = diff_sent / (time() - net_bytes_sent[1])

    net_bytes_recv = [io_counters.bytes_recv, time()]
    net_bytes_sent = [io_counters.bytes_sent, time()]

    return (format(rate_recv), format(rate_sent))

def disk_rates():
    global sda_bytes_read, sda_bytes_write, nvme_bytes_read, nvme_bytes_write
    io_counters = psutil.disk_io_counters(perdisk=True)

    sda = psutil.disk_io_counters(perdisk=True)["sda"]
    nvme = psutil.disk_io_counters(perdisk=True)["nvme0n1"]

    diff_sda_read = sda.read_bytes - sda_bytes_read[0]
    diff_sda_write = sda.write_bytes - sda_bytes_write[0]
    rate_sda_read = diff_sda_read / (time() - sda_bytes_read[1])
    rate_sda_write = diff_sda_write / (time() - sda_bytes_write[1])

    diff_nvme_read = nvme.read_bytes - nvme_bytes_read[0]
    diff_nvme_write = nvme.write_bytes - nvme_bytes_write[0]
    rate_nvme_read = diff_nvme_read / (time() - nvme_bytes_read[1])
    rate_nvme_write = diff_nvme_write / (time() - nvme_bytes_write[1])

    sda_bytes_read = [sda.read_bytes, time()]
    sda_bytes_write = [sda.write_bytes, time()]
    nvme_bytes_read = [nvme.read_bytes, time()]
    nvme_bytes_write = [nvme.write_bytes, time()]

    return (format(rate_nvme_read), format(rate_nvme_write), 
            format(rate_sda_read), format(rate_sda_write))

def spotify_infostrings(spotify_properties):
    if spotify_properties:
        info = dict()
        metadata = spotify_properties.Get("org.mpris.MediaPlayer2.Player", "Metadata")
        info['status'] = str(spotify_properties.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus")) + ":"
        info['position'] = timestring(spotify_properties.Get("org.mpris.MediaPlayer2.Player", "Position"))
        info['length'] = timestring(metadata['mpris:length'])
        info['title'] = str(metadata['xesam:title'])
        info['album'] = str(metadata['xesam:album'])
        info['artist'] = str(metadata['xesam:artist'][0])
        info['progress'] = info['position'] + '/' + info['length']
        for k, v in info.items():
            info[k] = v.upper()
        return info
    else:
        return None

def coreinfo():
    info = dict()
    CPU = format(psutil.cpu_percent(interval=0.1), True)
    RAM = format(psutil.virtual_memory().total - psutil.virtual_memory().available)
    GPU = format(GPUtil.getGPUs()[0].load * 100, True)
    CPU_T = format(psutil.sensors_temperatures()['k10temp'][1].current, True)
    VRAM = format(GPUtil.getGPUs()[0].memoryUsed * 1024 * 1024)
    GPU_T = format(GPUtil.getGPUs()[0].temperature, True)
    lines = [f"{"CPU":<6}{" RAM".center(6)}{"GPU":>6}"]
    lines.append(f"{CPU}  {RAM.center(6)}  {GPU}")
    lines.append(f"{"CPU_T":<6}{"VRAM".center(6)}{"GPU_T":>6}")
    lines.append(f"{CPU_T}  {VRAM.center(6)}  {GPU_T}")
    return lines

def rateinfo():
    info = dict()
    DOWN, UP = net_rates()
    NVME_R, NVME_W, SDA_R, SDA_W = disk_rates()

    lines = [f"{"READ":<6} {" READ".center(6)}{"UP":>5}"]
    lines.append(f"{NVME_R}  {SDA_R.center(6)}{UP}")
    lines.append(f"{"WRITE":<6} {"WRITE".center(6)}{"DOWN":>5}")
    lines.append(f"{NVME_W}  {SDA_W.center(6)}{DOWN}")

    return lines

title_i = 0
error_printed = False
init_printed = False

def main():
    global error_printed, init_printed
    while True:
        with HID_Screen(vendor_id, product_id, usage_page, usage) as screen:
            if screen.connected:
                if error_printed:
                    print("Device connected")
                    error_printed = False

                if not init_printed:
                    print("Device connected")
                    init_printed = True

                try:
                    spotify_bus = session_bus.get_object("org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2")
                    spotify_properties = dbus.Interface(spotify_bus, "org.freedesktop.DBus.Properties")
                except: 
                    spotify_bus = None 
                    spotify_properties = None

                page_1 = coreinfo()
                page_2 = rateinfo()
                spotify = spotify_infostrings(spotify_properties)

                screen.add_to_buffer(0, page_1[0])
                screen.add_to_buffer(1, page_1[1])
                screen.add_to_buffer(2, page_1[2])
                screen.add_to_buffer(3, page_1[3])

                screen.add_to_buffer(4, page_2[0])
                screen.add_to_buffer(5, page_2[1])
                screen.add_to_buffer(6, page_2[2])
                screen.add_to_buffer(7, page_2[3])
                
                global title_i
                if spotify:
                    if len(spotify['title']) > 18:
                        title = spotify['title'][title_i:]
                        title_i += 1
                        if title_i > (len(spotify['title']) - 18):
                            title_i = 0
                    else:
                        title = spotify['title']

                    screen.add_to_buffer(8, spotify['status'].center(18))
                    screen.add_to_buffer(9, title.center(18))
                    screen.add_to_buffer(10, spotify['artist'].center(18))
                    screen.add_to_buffer(11, spotify['progress'].center(18))
                else:
                    screen.add_to_buffer(8, "Spotify".center(18))
                    screen.add_to_buffer(9, "not".center(18))
                    screen.add_to_buffer(10, "running".center(18))
                    screen.add_to_buffer(11, " ".center(18))

                screen.send_screen() 
            else:
                if not error_printed:
                    print("Device not connected")
                    error_printed = True
        sleep(1)

if __name__ == "__main__":
    main()
