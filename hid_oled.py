import sys
import hid
from time import sleep

vendor_id       = 0x7368
product_id      = 0x4f1b

usage_page      = 0xff60
usage           = 0x61
report_length   = 32
num_chars = 18
num_lines = 4

class HID_Screen():
    def __init__(self, vendor_id, product_id, usage_page, usage):
        self.vendor_id, self.product_id, self.usage_page, self.usage = vendor_id, product_id, usage_page, usage
        self.screen_buffer = [" "] * num_lines
        self.line_number = 0
    
    def get_raw_hid_interface(self):
        device_interfaces = hid.enumerate(self.vendor_id, self.product_id)
        raw_hid_interfaces = [i for i in device_interfaces if i['usage_page'] == self.usage_page and i['usage'] == self.usage] 
        if len(raw_hid_interfaces) == 0:
            return None
        return hid.Device(path=raw_hid_interfaces[0]['path'])

    def add_to_buffer(self, line_number, line):
        self.screen_buffer[line_number] = str(line)[:num_chars]

    def send_screen(self):
        interface = self.get_raw_hid_interface()
        if interface is None:
            print("No interface detected")
            return
        for line in self.screen_buffer:
            linebytes = list(bytes(line, "utf-8"))
            request_data = [0x00] * (report_length + 1)
            request_data[1:len(linebytes) + 1] = linebytes
            request_data[0] = 0x00
            request_report = bytes(request_data)
            interface.write(request_report)
            print(request_report)
        self.screen_buffer = [" "] * num_lines
        interface.close()
        
def main():
    screen = HID_Screen(vendor_id, product_id, usage_page, usage)
    screen.add_to_buffer(0, "Test line 1")
    screen.add_to_buffer(2, "Test line 2")
    screen.send_screen() 

if __name__ == "__main__":
    main()
