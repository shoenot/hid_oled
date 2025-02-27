import hid
from time import sleep
import psutil
from psutil._common import bytes2human
from datetime import datetime

vendor_id       = 0x7368
product_id      = 0x4f1b

usage_page      = 0xff60
usage           = 0x61
report_length   = 32
num_screens     = 4
num_chars       = 18
num_lines       = 4

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

def main():
    while True:
        with HID_Screen(vendor_id, product_id, usage_page, usage) as screen:
            if screen.connected:
                screen.add_to_buffer(0, cpu_line())
                screen.add_to_buffer(1, ram_line())
                screen.add_to_buffer(2, datetime.now().strftime("%M:%S"))
                screen.add_to_buffer(3, "fourth test line")
                screen.add_to_buffer(4, "fifth test line")
                screen.add_to_buffer(5, "sixth test line")
                screen.add_to_buffer(6, "seventh test line")
                screen.add_to_buffer(7, "eighth test line")
                screen.add_to_buffer(8, "9 test line")
                screen.add_to_buffer(9, "10 test line")
                screen.add_to_buffer(10, "11 test line")
                screen.add_to_buffer(11, "12 test line")
                screen.add_to_buffer(12, "13 test line")
                screen.add_to_buffer(13, "14 test line")
                screen.add_to_buffer(14, "15 test line")
                screen.add_to_buffer(15, "16 test line")
                screen.send_screen() 
            else:
                print("Device not connected")
        sleep(1)

if __name__ == "__main__":
    main()
