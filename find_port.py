"""List serial ports so you know what to pass to --port.  python find_port.py"""
import sys
try:
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial not installed.  Run:  pip install pyserial")

ports = list(list_ports.comports())
if not ports:
    print("No serial ports found.")
    print("  - is the Arduino plugged in?")
    print("  - on Windows, check Device Manager for a CH340/CH341 driver")
    print("  - on Linux you may need:  sudo usermod -a -G dialout $USER  (then log out/in)")
    sys.exit(1)

print(f"{len(ports)} serial port(s):\n")
board = None
for p in ports:
    blob   = ((p.description or '') + ' ' + (p.manufacturer or '')).lower()
    likely = any(k in blob for k in ('arduino', 'ch340', 'ch341',
                                     'usb-serial', 'wch', 'ftdi'))
    print(f"  {p.device:<22}{p.description or '-'}")
    if p.manufacturer: print(f"  {'':<22}manufacturer: {p.manufacturer}")
    if likely:
        print(f"  {'':<22}>>> this looks like your Arduino <<<")
        if board is None: board = p
    elif 'bluetooth' in blob:
        # The trap: a Bluetooth COM port OPENS without error and throws every
        # byte away.  The run looks perfect -- bands scroll, audio plays --
        # and the LCD never lights.  Nothing in the program can detect it.
        print(f"  {'':<22}(Bluetooth -- opens fine and silently eats every")
        print(f"  {'':<22} frame.  Point --port here and the LCD stays blank")
        print(f"  {'':<22} with no error at all.)")
    print()

print("Use it like:")
if board is None:
    print(f"  python -m snsled.main --port {ports[0].device} --mode spectrum")
    print()
    print("  ...but none of these looks like a board.  Check the USB cable is a")
    print("  data cable and not charge-only, and on Windows check Device Manager")
    print("  for a CH340/CH341 driver.")
else:
    print(f"  python -m snsled.main --port {board.device} --mode spectrum")
    if board.device != ports[0].device:
        print()
        print(f"  Note: {board.device}, NOT {ports[0].device}.  Windows hands out COM numbers in")
        print(f"  plug-in order, so the board moves when you replug it or reboot --")
        print(f"  re-run this whenever the display goes blank for no reason.")
