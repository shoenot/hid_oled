from math import ceil, floor 
from decimal import Decimal

def format(value, percent=False):
    fmt_string = ""
    if percent:
        if value >= 100:
            fmt_string = str(Decimal(value).quantize(Decimal('100'))) + '.'
        if value >= 10:
            fmt_string = str(Decimal(value).quantize(Decimal('10.0')))
        if value <= 10:
            fmt_string = str(Decimal(value).quantize(Decimal('1.00')))
        return fmt_string
    if not percent:
        smalls = ("B", "K", "M")
        for unit in ("B", "K", "M", "G", "T", "P", "E", "Z"):
            if abs(value) < 1000.0:
                if unit in smalls:
                    fmt_string = str(Decimal(value).quantize(Decimal('1000'))) + unit
                    break
                else:
                    if value > 100.0:
                        fmt_string = str(Decimal(value).quantize(Decimal('100'))) + unit
                    else:
                        fmt_string = str(Decimal(value).quantize(Decimal('10.0'))) + unit
                    break
            value /= 1024.0
        if len(fmt_string) < 5:
            spaces = 5 - len(fmt_string)
            return spaces * ' ' + fmt_string
        else:
            return fmt_string
