import aiohttp.web_exceptions
import pygame
import asyncio
import evdev
import os
import json
from escpos import printer
import datetime
import requests
from requests.exceptions import HTTPError
from dotenv import load_dotenv
import sqlite3
import aiohttp
from aiohttp.web_exceptions import HTTPError

scanner_names = ["BF SCAN SCAN KEYBOARD"]
q = asyncio.Queue()
lock = asyncio.Lock()

class OrderDB:
    def __init__(self, path):
            self.connection = sqlite3.connect(path)
            self.connection.execute("PRAGMA foreign_keys = 1")
            cursor = self.connection.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, t TIMESTAMP DEFAULT CURRENT_TIMESTAMP, items INTEGER, total INTEGER, synced BOOLEAN DEFAULT FALSE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS order_line (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, item INTEGER, quantity INTEGER, FOREIGN KEY (order_id) REFERENCES orders (id))")
            self.connection.commit()
    def insert_order(self, order):
        cursor = self.connection.cursor()
        cursor.execute("INSERT INTO orders (items, total) VALUES (?, ?)", (order['count'], order['total']))
        id = cursor.lastrowid
        print(f"created order {id}")
        data = []
        for item in order['i']:
            data.append((id, item['v'], item['q']))
            #cursor.execute("INSERT INTO order_line (order_id, item, quantity) VALUES(?, ?, ?)", (id, item['v'], item['q']))
        #self.connection.commit()
        cursor.executemany("INSERT INTO order_line (order_id, item, quantity) VALUES(?, ?, ?)", data)
        return id
    def mark_order_synced(self, id):
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE orders SET synced=TRUE WHERE id = ?", (id,))
            self.connection.commit()
        except sqlite3.Error as err:
            print(f"error updating order: {err}")


class Inventory:
    def __init__(self):
        self.inventory = {}
        self.fetch_inventory()
    def fetch_inventory(self):
        print("syncing inventory")
        try:
            print(os.environ['INVENTORY_URL'])
            response = requests.get(os.environ['INVENTORY_URL'])
            response.raise_for_status()
            jsonResponse = response.json()
            #print(jsonResponse)
            for item in jsonResponse:
                self.inventory[item['variant_id']] = InventoryItem(item['variant_id'],
                                                              item['product_code'],
                                                              item['product_title'],
                                                              item['variant_code'],
                                                              item['variant_price'],
                                                              item['variant_stock_status'],
                                                              item['product_is_eligibility_restricted'])
            #print(self.inventory)
                
        except HTTPError as http_err:
            print(f'HTTP error: {http_err}')
        except Exception as err:
            print(f'error requesting inventory: {err}')

class PrinterManager:
    def __init__(self):
        self.connect()

    def connect(self):
        if(os.environ["PRINTER_CONN"] == "net"):
            self.connect_net(os.environ["PRINTER_IP"])
        elif(os.environ["PRINTER_CONN"] == "usb"):
            self.connect_usb(os.environ["PRINTER_VENDOR"], os.environ["PRINTER_PRODUCT"])
        else:
            print("unknown printer connection type")
            exit(-1)        

    def connect_usb(self, vendor, product):
        print("connecting to usb printer")
        print(f"printer.Usb({vendor}, {product})")
        self.printer = printer.Usb(int(vendor, base=16), int(product, base=16), in_ep=0x81, out_ep=0x01, profile=os.environ['PRINTER_PROFILE'])
        #self.printer = printer.Usb(0x0fe6, 0x811e, in_ep=0x81, out_ep=0x01)
        
    
    def connect_net(self, ip):
        print("connecting to network printer")
        self.printer = printer.Network(ip, profile=os.environ['PRINTER_PROFILE'])

    def check_connection(self):
        if self.printer.is_online():
            return True
        return False

    def print_order(self, order):
        if not self.check_connection():
            self.connect()
        self.printer.set_with_default(align="center")
        self.printer.image("/home/bj/logo.png")
        self.printer.set_with_default(align="center", custom_size=True, width=3, height=3, density=8)
        self.printer.textln(f"Order: {order['txn']}")
        self.printer.set_with_default(align="center")
        now = datetime.datetime.now()
        self.printer.textln(f"on {now.date()} at {now.time()}")
        self.printer.set(align="center")
        self.printer.textln("================================================")
        total = 0
        for item in order["items"]:
            self.printer.set_with_default(align="left", custom_size=True, width=2, height=2)
            self.printer.textln(f"{item['sku']} : {item['size']}")
            self.printer.set_with_default(custom_size=True, width=1, height=1)
            self.printer.textln(item['description'])
            self.printer.set_with_default(align="right", double_height=True, double_width=True)
            self.printer.text(f"${item['price']}")
            self.printer.textln()
            self.printer.set_with_default()
            #sku = inventory.inventory[item['v']]
            #q = int(item['q'])
            #for i in range(q):
            #    self.printer.set_with_default(align="left", custom_size=True, width=2, height=2)
            #    self.printer.text(f"#{sku.sku} : {sku.size} ")
            #    self.printer.set_with_default()
            #    self.printer.text(sku.description)
            #    self.printer.ln()
            #    self.printer.set_with_default(align="right", double_height=True, double_width=True)
            #    self.printer.text(f"${sku.price}")
            #    self.printer.textln()
            #    self.printer.set_with_default()
            #    total += sku.price
        self.printer.set(align="center")
        self.printer.textln("-----------------------------------------------")
        self.printer.set_with_default(align="right", custom_size=True, width=2, height=2)
        self.printer.textln(f"TOTAL: ${order['total']}")
        self.printer.set_with_default()
        self.printer.textln("all prices include sales tax")
        self.printer.set_with_default()
        self.printer.qr(order['qr'], size=9,center=True)
        self.printer.cut()
        self.printer.set(align="center", custom_size=True, width=3, height=3, density=8)
        self.printer.image("/home/bj/logo.png")
        self.printer.textln(f"Order: {order['txn']}")
        self.printer.textln(f"Total: ${order['total']}")
        self.printer.qr(order['qr'], size=9,center=True)
        self.printer.set_with_default()
        self.printer.textln("all prices include sales tax")
        self.printer.ln(3)
        self.printer.eject_slip()
        self.printer.cut()
        self.printer.eject_slip()
        self.printer.set_with_default()

class InventoryItem:
    def __init__(self, id, sku, description, size, price, stock_status, restricted):
        self.sku = sku
        self.id = id
        self.description = description
        self.size = size
        self.price_long = int(price)
        self.price = int(price/100)
        self.stock_staus = stock_status
        self.restricted = restricted

    def __str__(self):
        return str(self.id)+":"+str(self.sku)+" "+self.description+"("+self.size+")"+" $"+str(self.price)

async def sync_order(orderobj, id):
    print("in sync order")
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post('https://confmgr3.junctorconf.net/conf/merch_addtxn.php', json=orderobj)
            print("sent order")
            print(resp)
            print("content")
            print(await resp.json())
            if resp.status == 200:
                odb.mark_order_synced(id)
                print("order synced")
            else:
                print("failed to sync order")
    except aiohttp.web_exceptions.HTTPError as http_err:
        print(f'HTTP error: {http_err}')
    except Exception as err:
        print(f'error sending order: {err}')

def parse_order(order):
    print(order)
    total = 0
    count = 0

    orderobj = {}
    items = []

    order_keys = order.keys()
    for k in order_keys:
        if k not in ["i", "txn"]:
            q.put_nowait({"error": "unknown item in order"})
            return False
    if "i" not in order:
        q.put_nowait({"error": "order missing items"})
        return False
    if "txn" not in order:
        q.put_nowait({"error": "order missing txnid"})
        return False
    oi = []

    if 'i' in order:
        for item in order["i"]:
            print(item)
            print(item['v'])
            if item['v'] in inventory.inventory:
                if inventory.inventory[item['v']].restricted == "Y":
                    q.put_nowait({"error": "item is restricted"})
                    print(f"item {item['v']} is restricted")
                    return False
                if inventory.inventory[item['v']].stock_staus == "OUT":
                    q.put_nowait({"error": "item out of stock"})
                    print(f"item {item['v']} is out of stock")
                    return False
                else:
                    print(inventory.inventory[item['v']])
                    quantity = int(item['q'])
                    if(quantity > 0):
                        for i in range(quantity):
                            oi.append({"id": item['v'], "sku": inventory.inventory[item['v']].sku, "price": inventory.inventory[item['v']].price, "description": inventory.inventory[item['v']].description, "size": inventory.inventory[item['v']].size})
                        items.append({"variant_id": item['v'], "quantity": item['q'], "price_each_long": inventory.inventory[item['v']].price_long})
                        print(item['q'])
                        total += quantity*inventory.inventory[item['v']].price
                        count += int(item['q'])
                    else:
                        q.put_nowait({"error": "invalid qunatity"})
                        return False
            else:
                print(f"item {item['v']} not in inventory")
                q.put_nowait({"error": "item not in inventory"})
                return False
        eo = order.copy()
        eo['count'] = count
        eo['total'] = total
        id = odb.insert_order(eo)

        sorted_items = sorted(oi, key=lambda d: d['sku'])
        o = {"txn": os.environ['STATION']+"-"+str(id),
             "total": total,
             "count": count,
             "items": sorted_items,
             "qr": order }
        
        pm.print_order(o)

        orderobj['device_id'] = os.environ['DEVICE_ID']
        orderobj['conference_id'] = os.environ['CONFERENCE_ID']
        orderobj['passcode'] = os.environ['PASSCODE']
        orderobj['timestamp'] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S-00:00")
        orderobj['txn_num'] = os.environ['STATION']+"-"+str(id)
        orderobj['items'] = items
        #orderobj['ref_txn_num'] = "A-123"

        print(orderobj)
        loop.create_task(sync_order(orderobj, id))
        inventory.fetch_inventory()
        #sync_order(orderobj)

        return True
    else:
        return False
    


async def handle_barcode_scan(device):
    print(device.name)
    scancodes = {
        # Scancode: ASCIICode
        0: None, 1: u'ESC', 2: u'1', 3: u'2', 4: u'3', 5: u'4', 6: u'5', 7: u'6', 8: u'7', 9: u'8',
        10: u'9', 11: u'0', 12: u'-', 13: u'=', 14: u'BKSP', 15: u'TAB', 16: u'q', 17: u'w', 18: u'e', 19: u'r',
        20: u't', 21: u'y', 22: u'u', 23: u'i', 24: u'o', 25: u'p', 26: u'[', 27: u']', 28: u'CRLF', 29: u'LCTRL',
        30: u'a', 31: u's', 32: u'd', 33: u'f', 34: u'g', 35: u'h', 36: u'j', 37: u'k', 38: u'l', 39: u';',
        40: u'\'', 41: u'`', 42: u'LSHFT', 43: u'\\', 44: u'z', 45: u'x', 46: u'c', 47: u'v', 48: u'b', 49: u'n',
        50: u'm', 51: u',', 52: u'.', 53: u'/', 54: u'RSHFT', 56: u'LALT', 57: u' ', 71: u'7', 72: u'8', 73: u'9',
        75: u'4', 76: u'5', 77: u'6', 79: u'1', 80: u'2', 81: u'3', 82: u'0', 100: u'RALT'
    }

    capscodes = {
        0: None, 1: u'ESC', 2: u'!', 3: u'@', 4: u'#', 5: u'$', 6: u'%', 7: u'^', 8: u'&', 9: u'*',
        10: u'(', 11: u')', 12: u'_', 13: u'+', 14: u'BKSP', 15: u'TAB', 16: u'Q', 17: u'W', 18: u'E', 19: u'R',
        20: u'T', 21: u'Y', 22: u'U', 23: u'I', 24: u'O', 25: u'P', 26: u'{', 27: u'}', 28: u'CRLF', 29: u'LCTRL',
        30: u'A', 31: u'S', 32: u'D', 33: u'F', 34: u'G', 35: u'H', 36: u'J', 37: u'K', 38: u'L', 39: u':',
        40: u'"', 41: u'~', 42: u'LSHFT', 43: u'|', 44: u'Z', 45: u'X', 46: u'C', 47: u'V', 48: u'B', 49: u'N',
        50: u'M', 51: u'<', 52: u'>', 53: u'?', 54: u'RSHFT', 56: u'LALT', 57: u' ', 71: u'7', 72: u'8', 73: u'9',
        75: u'4', 76: u'5', 77: u'6', 79: u'1', 80: u'2', 81: u'3', 82: u'0', 100: u'RALT'
    }

    LEFT_SHIFT = 42
    KEY_STATE_PRESSED = 1
    KEY_STATE_RELEASED = 0
    RETURN = 28

    caps = False
    pending_string = ''

    async for event in device.async_read_loop():
        if event.type == evdev.ecodes.EV_KEY:
            data = evdev.categorize(event)
            if data.scancode == LEFT_SHIFT:
                if data.keystate == KEY_STATE_PRESSED:
                    caps = True
                if data.keystate == KEY_STATE_RELEASED:
                    caps = False

            if data.keystate == 1: # Down events only
                if caps:
                    key_lookup = capscodes.get(data.scancode) or None
                else:
                    key_lookup = scancodes.get(data.scancode) or None

                if (data.scancode == RETURN):
                    print(pending_string)
                    try:
                        data = json.loads(pending_string)
                        await q.put(data)
                        print("put a scan on the queue")
                    except json.JSONDecodeError:
                        print("unable to parse json")
                        data = {"error": "unable to parse qr code json"}
                        await q.put(data)                    
                    pending_string = ''
                elif (data.scancode != LEFT_SHIFT) and (key_lookup != None):
                    pending_string += key_lookup

class DisplayUI:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Merch")
        self.screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN | pygame.NOFRAME)

        self.WHITE = (255, 255, 255)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)
        self.RED = (255, 0, 0)
        self.BLACK = (0,0,0)

        ws = pygame.display.get_window_size()

        self.font = pygame.font.Font('freesansbold.ttf', 64)
        self.header = self.font.render('DEF CON 32 Merch', True, self.GREEN, self.BLUE)
        self.header_rect = self.header.get_rect()
        self.header_rect.centerx = ws[0]/2
        self.header_rect.centery = 40

        self.scan_instruction = self.font.render("Please scan your barcode", True, self.GREEN, self.BLUE)
        self.scan_instruction_rect = self.scan_instruction.get_rect()
        self.scan_instruction_rect.centerx = ws[0]/2
        self.scan_instruction_rect.centery = ws[1]/2

        self.error_instruction = self.font.render("Unable to process order", True, self.BLACK, self.RED)
        self.error_instruction_rect = self.error_instruction.get_rect()
        self.error_instruction_rect.centerx = ws[0]/2
        self.error_instruction_rect.centery = ws[1]/2

        self.goodorder = self.font.render("Please take your receipt", True, self.GREEN, self.BLUE)
        self.goodorder_rect = self.goodorder.get_rect()
        self.goodorder_rect.centerx = ws[0]/2
        self.goodorder_rect.centery = ws[1]/2

        self.badorder = self.font.render("There was an issue with your order, see a Goon", True, self.BLACK, self.RED)
        self.badorder_rect = self.goodorder.get_rect()
        self.badorder_rect.centerx = ws[0]/2
        self.badorder_rect.centery = ws[1]/2

        

        self.DEBOUNCE = pygame.USEREVENT+1
        self.SCANERROR = pygame.USEREVENT+2
        self.GOODORDER = pygame.USEREVENT+3
        self.BADORDER = pygame.USEREVENT+4

        self.running = True

    async def run(self):
        message = self.scan_instruction
        message_rect = self.scan_instruction_rect
        while self.running:
            try:
                event = q.get_nowait()
                q.task_done()
                print("got an event")
                print(event)
                if "error" in event:
                    pygame.event.post(pygame.event.Event(self.SCANERROR))
                else:
                    if parse_order(event):
                        pygame.event.post(pygame.event.Event(self.GOODORDER))
                    else:
                        pygame.event.post(pygame.event.Event(self.BADORDER))

                self.screen.fill(self.BLUE)
            except asyncio.QueueEmpty:
                pass

            self.screen.blit(self.header, self.header_rect)
            self.screen.blit(message, message_rect)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    for task in asyncio.all_tasks():
                        task.cancel()
                if event.type == self.SCANERROR:
                    self.screen.fill(self.RED)
                    message = self.error_instruction
                    message_rect = self.error_instruction_rect
                    pygame.time.set_timer(self.DEBOUNCE, 5000, loops=1)
                if event.type == self.DEBOUNCE:
                    self.screen.fill(self.BLACK)
                    message = self.scan_instruction
                    message_rect = self.scan_instruction_rect
                if event.type == self.GOODORDER:
                    self.screen.fill(self.GREEN)
                    message = self.goodorder
                    message_rect = self.goodorder_rect
                    pygame.time.set_timer(self.DEBOUNCE, 5000, loops=1)
                if event.type == self.BADORDER:
                    self.screen.fill(self.RED)
                    message = self.badorder
                    message_rect = self.badorder_rect
                    pygame.time.set_timer(self.DEBOUNCE, 5000, loops=1)
                    
                    #self.screen.blit(self.error_instruction, self.error_instruction_rect)
            pygame.display.update()
            await asyncio.sleep(0.1)
            

async def main():
    load_dotenv()
    global background_tasks
    background_tasks = []
    global loop
    loop = asyncio.get_event_loop()

    global pm
    pm = PrinterManager()
    #printer = Network("192.168.42.40",  profile="TM-T88V")

    global inventory
    inventory = Inventory()

    global odb
    odb = OrderDB(os.environ['DB_PATH'])

    
    devices = []
    for filename in os.listdir("/dev/input/by-path"):
        devices.append(evdev.InputDevice("/dev/input/by-path/"+filename))
    print(devices)
    
    for idx, device in enumerate(devices):
       if device.name in scanner_names:
           print(f"found scanner at index {idx}, {device.path}")
           device.grab() #grab for exclusive access
           task = handle_barcode_scan(device)
           background_tasks.append(task)


    display_ui = DisplayUI()
    background_tasks.append(display_ui.run())

    await asyncio.gather(*background_tasks)


if __name__ == "__main__":
    asyncio.run(main())