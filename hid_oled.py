import hid
import GPUtil
import dbus 
import psutil
from time import sleep, time
from math import ceil
from psutil._common import bytes2human

vendor_id       = 0x7368
product_id      = 0x4f1b

usage_page      = 0xff60
usage           = 0x61
report_length   = 32
num_screens     = 3
num_chars       = 18
num_lines       = 4

net_bytes_recv = [0, time()]
net_bytes_sent = [0, time()]

session_bus = dbus.SessionBus()

class DeviceNotConnected(Exception):
    pass

class HID_Screen():
    def __init__(self, vendor_id, product_id, usage_page, usage):
        self.vendor_id, self.product_id, self.usage_page, self.usage = vendor_id, product_id, usage_page, usage
        self.screen_buffer = [" "] * (num_lines * num_screens)
        self.line_number = 0
        self.connected = False
    
    def connect_to_hid_interface(self):
        device_interfaces = hid.enumerate(self.vendor_id, self.product_id)
        raw_hid_interfaces = [i for i in device_interfaces if i['usage_page'] == self.usage_page and i['usage'] == self.usage] 
        if len(raw_hid_interfaces) == 0:
            raise DeviceNotConnected()
        self.interface = hid.Device(path=raw_hid_interfaces[0]['path'])

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
                if idx == 0:
                    request_data[0] = 0x01
                else:
                    request_data[0] = 0x02
                request_report = bytes(request_data)
                self.screen_buffer = [" "] * num_lines
                try:
                    self.interface.write(request_report)
                except hid.HIDException:
                    break
                print(request_report)

    def __exit__(self, exc_type, exc_value, traceback):
        if self.connected:
            self.interface.close()

def cpu_line():
    cpu = str(round(psutil.cpu_percent(), 1))
    cpu_string = f"{'CPU':<9}{cpu:>9}" 
    return cpu_string        

def ram_line():
    ram = bytes2human(psutil.virtual_memory().total - psutil.virtual_memory().available)
    ram_string = f"{'RAM':<9}{ram:>9}"
    return ram_string

def gpu_line():
    gpu = str(round(GPUtil.getGPUs()[0].load * 100, 1))
    gpu_string = f"{'GPU':<9}{gpu:>9}"
    return gpu_string

def vram_line():
    vram = bytes2human(GPUtil.getGPUs()[0].memoryUsed * 1024 * 1024)
    vram_string = f"{'VRAM':<9}{vram:>9}"
    return vram_string

def ctemp_line():
    temp = str(int(psutil.sensors_temperatures()['k10temp'][1].current)) + "C"
    temp_string = f"{'CPU_T':<9}{temp:>9}"
    return temp_string

def gtemp_line():
    temp = str(int(GPUtil.getGPUs()[0].temperature)) + "C" 
    temp_string = f"{'GPU_T':<9}{temp:>9}"
    return temp_string

def net_rate_lines():
    global net_bytes_recv, net_bytes_sent
    io_counters = psutil.net_io_counters()

    diff_recv = io_counters.bytes_recv - net_bytes_recv[0]
    rate_recv = diff_recv / (time() - net_bytes_recv[1])
    diff_sent = io_counters.bytes_sent - net_bytes_sent[0]
    rate_sent = diff_sent / (time() - net_bytes_sent[1])

    net_bytes_recv = [io_counters.bytes_recv, time()]
    net_bytes_sent = [io_counters.bytes_sent, time()]

    recv_str = f"{'DOWN':<9}{bytes2human(rate_recv):>9}"
    sent_str = f"{'UP':<9}{bytes2human(rate_sent):>9}"

    return [recv_str, sent_str]

def timestring(microseconds):
    seconds = ceil(microseconds/1000000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
    else:
        return "{:02}:{:02}".format(int(minutes), int(seconds))

def trackinfo(spotify_properties):
    if spotify_properties:
        info = dict()
        metadata = spotify_properties.Get("org.mpris.MediaPlayer2.Player", "Metadata")
        info['position'] = timestring(spotify_properties.Get("org.mpris.MediaPlayer2.Player", "Position"))
        info['length'] = timestring(metadata['mpris:length'])
        info['title'] = str(metadata['xesam:title'])
        info['album'] = str(metadata['xesam:album'])
        info['artist'] = str(metadata['xesam:artist'][0])
        info['progress'] = info['position'] + '/' + info['length']
        return info
    else:
        return None


def main():
    while True:
        with HID_Screen(vendor_id, product_id, usage_page, usage) as screen:
            if screen.connected:
                try:
                    spotify_bus = session_bus.get_object("org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2")
                    spotify_properties = dbus.Interface(spotify_bus, "org.freedesktop.DBus.Properties")
                except: 
                    spotify_bus = None 
                    spotify_properties = None

                net_rates = net_rate_lines()
                spotify = trackinfo(spotify_properties)

                screen.add_to_buffer(0, cpu_line())
                screen.add_to_buffer(1, ram_line())
                screen.add_to_buffer(2, gpu_line())
                screen.add_to_buffer(3, vram_line())

                screen.add_to_buffer(4, ctemp_line())
                screen.add_to_buffer(5, gtemp_line())
                screen.add_to_buffer(6, net_rates[0])
                screen.add_to_buffer(7, net_rates[1])

                if spotify:
                    screen.add_to_buffer(8, spotify['title'].center(18))
                    screen.add_to_buffer(9, spotify['album'].center(18))
                    screen.add_to_buffer(10, spotify['artist'].center(18))
                    screen.add_to_buffer(11, spotify['progress'].center(18))
                else:
                    screen.add_to_buffer(8, "Spotify is".center(18))
                    screen.add_to_buffer(9, "not running".center(18))
                    screen.add_to_buffer(10, " ".center(18))
                    screen.add_to_buffer(11, " ".center(18))

                screen.send_screen() 
            else:
                print("Device not connected")
        sleep(1)

if __name__ == "__main__":
    main()
