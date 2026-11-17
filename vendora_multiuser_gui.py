"""VENDORA | Per-user ESP32 vending dashboard.

Requirements: Python 3.9+, pip install pyserial 'qrcode[pil]'
Run: python vendora_multiuser_gui.py
The ESP32 controls user authentication, balance, stock and dispensing.
QR is a DEMONSTRATION and does not perform a real payment.
"""
from __future__ import annotations

import datetime as dt
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

try:
    import qrcode
    from PIL import ImageTk
except ImportError:
    qrcode = None
    ImageTk = None

BG = "#0a101e"
PANEL = "#151f32"
PANEL_ALT = "#1c2b43"
BORDER = "#2b3b53"
TEXT = "#f0f5ff"
MUTED = "#91a7c2"
BLUE = "#48b7ff"
GREEN = "#35d2a4"
RED = "#ff7385"
AMBER = "#ffca7a"
FONT = "Segoe UI"


def money(n: int | None) -> str:
    return "₹—" if n is None else f"₹{n:,}"


def valid_four_digits(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{4}", text))


def parse_recharge_amount(text: str) -> int | None:
    if not re.fullmatch(r"[0-9]{1,5}", text.strip()):
        return None
    number = int(text.strip())
    return number if 1 <= number <= 10000 else None


class VendoraApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("VENDORA | Smart Vending · Personal Account")
        root.geometry("1350x850")
        root.minsize(1020, 680)
        root.configure(bg=BG)

        self.port = None
        self.io_lock = threading.Lock()
        self.stop_reader = threading.Event()
        self.queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.connected = False
        self.current_user: str | None = None
        self.pending_login: str | None = None
        self.pending_action: str | None = None
        self.pending_since = 0.0
        self.lock_until: float | None = None
        self.lock_check_sent = False
        self.balance: int | None = None
        self.stock = {1: None, 2: None}
        self.price = {1: 20, 2: 30}
        self.history: list[dict] = []
        self.reading_history = False
        self.last_transaction = "No purchases yet."
        self.is_dispensing = False
        self.last_status_text = "Connect your ESP32 to begin."
        self.login_id_var = tk.StringVar()
        self.login_pin_var = tk.StringVar()
        # Read-only live mirror of the physical 4x4 keypad.
        self.keypad_id_var = tk.StringVar(value="—")
        self.keypad_pin_var = tk.StringVar(value="—")
        self.keypad_stage_var = tk.StringVar(value="Enter your User ID on the keypad, then press #.")
        self.keypad_stage = "ID"
        self.amount_var = tk.StringVar()
        self.port_var = tk.StringVar()

        self._build()
        self._refresh_ports()
        self.root.after(70, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def label(self, parent, text: str, size=11, color=TEXT, weight="normal", **kw):
        return tk.Label(parent, text=text, font=(FONT, size, weight),
                        bg=parent.cget("bg"), fg=color, **kw)

    def panel(self, parent, **kw):
        return tk.Frame(parent, bg=PANEL, highlightthickness=1,
                        highlightbackground=BORDER, **kw)

    def button(self, parent, text, command, color=BLUE, foreground=BG, **kw):
        return tk.Button(parent, text=text, command=command, cursor="hand2",
                         bg=color, fg=foreground, activebackground=color,
                         activeforeground=foreground, font=(FONT, 10, "bold"),
                         padx=14, pady=10, relief="flat", bd=0, **kw)

    def entry(self, parent, variable, *, masked=False, width=22):
        return tk.Entry(parent, textvariable=variable, width=width,
                        font=(FONT, 13), bg=PANEL_ALT, fg=TEXT,
                        insertbackground=TEXT, relief="flat", bd=0,
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=BLUE, show="•" if masked else "")

    def _build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=30, pady=(22, 12))
        self.label(header, "VENDORA", 23, TEXT, "bold").pack(side="left")
        self.label(header, "  /  PERSONAL VENDING EXPERIENCE", 10, MUTED).pack(side="left", pady=(10, 0))
        self.link_label = self.label(header, "●  DISCONNECTED", 10, RED, "bold")
        self.link_label.pack(side="right", pady=10)

        connection = self.panel(self.root)
        connection.pack(fill="x", padx=30, pady=(0, 15))
        self.label(connection, "ESP32 USB", 10, MUTED, "bold").pack(side="left", padx=(15, 12), pady=11)
        self.ports = ttk.Combobox(connection, textvariable=self.port_var,
                                  width=18, state="readonly")
        self.ports.pack(side="left", padx=4)
        self.button(connection, "Refresh ports", self._refresh_ports, PANEL_ALT, TEXT).pack(side="left", padx=5)
        self.connect_btn = self.button(connection, "Connect", self._toggle_connection)
        self.connect_btn.pack(side="left", padx=4)
        self.label(connection, "115200 baud  ·  Virtual payments only", 9, MUTED).pack(side="right", padx=18)

        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(fill="both", expand=True, padx=30, pady=(0, 10))
        self.login_view = tk.Frame(self.main, bg=BG)
        self.dashboard = tk.Frame(self.main, bg=BG)
        self._build_login()
        self._build_dashboard()
        self._show_login()

        footer = self.panel(self.root)
        footer.pack(fill="x", padx=30, pady=(0, 16))
        self.activity = self.label(footer, "Ready. Connect your ESP32 to log in.", 10, MUTED)
        self.activity.pack(anchor="w", padx=15, pady=10)

    def _build_login(self):
        center = tk.Frame(self.login_view, bg=BG)
        center.pack(expand=True)
        card = self.panel(center, width=510, height=610)
        card.pack()
        card.pack_propagate(False)
        self.label(card, "PERSONAL ACCOUNT", 10, BLUE, "bold").pack(anchor="w", padx=35, pady=(35, 8))
        self.label(card, "Welcome to Vendora", 22, TEXT, "bold").pack(anchor="w", padx=35)
        self.label(card, "Sign in here, OR use the ESP32 keypad: ID + #, PIN + #.\nYour keypad entries appear live below.",
                   10, MUTED, wraplength=440, justify="left").pack(anchor="w", padx=35, pady=(8, 18))
        self.label(card, "USER ID  ·  4 digits", 10, MUTED, "bold").pack(anchor="w", padx=35)
        id_entry = self.entry(card, self.login_id_var, width=33)
        id_entry.pack(fill="x", padx=35, ipady=10, pady=(7, 17))
        self.label(card, "PASSCODE  ·  4 digits", 10, MUTED, "bold").pack(anchor="w", padx=35)
        pin_entry = self.entry(card, self.login_pin_var, masked=True, width=33)
        pin_entry.pack(fill="x", padx=35, ipady=10, pady=(7, 8))
        pin_entry.bind("<Return>", lambda _event: self.login())
        id_entry.bind("<Return>", lambda _event: pin_entry.focus_set())
        self.login_message = self.label(card, "Both fields are required to sign in.", 10, MUTED)
        self.login_message.pack(anchor="w", padx=35, pady=(2, 13))
        self.login_btn = self.button(card, "Sign in to my account", self.login, BLUE)
        self.login_btn.pack(fill="x", padx=35, pady=(0, 12))
        self.label(card, "Demo accounts: 1001, 1002, 1003, 1004\nUse each account's matching 4-digit PIN.",
                   9, MUTED, justify="left").pack(anchor="w", padx=35)

        # Physical keypad mirror: updated only from ESP32 INPUT packets.
        # PIN length is shown as stars; PIN digits are never received.
        mirror = tk.Frame(card, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
        mirror.pack(fill="x", padx=35, pady=(16, 0))
        self.label(mirror, "LIVE PHYSICAL KEYPAD", 10, BLUE, "bold").pack(anchor="w", padx=14, pady=(10, 7))
        line = tk.Frame(mirror, bg=PANEL_ALT)
        line.pack(fill="x", padx=14)
        self.label(line, "User ID:", 11, MUTED).pack(side="left")
        self.label(line, " ", 11, MUTED).pack(side="left")
        self.label(line, "", 11, MUTED).pack(side="left")
        self.keypad_id_label = self.label(line, "—", 13, TEXT, "bold")
        self.keypad_id_label.pack(side="left", padx=8)
        line2 = tk.Frame(mirror, bg=PANEL_ALT)
        line2.pack(fill="x", padx=14, pady=(4, 5))
        self.label(line2, "Passcode:", 11, MUTED).pack(side="left")
        self.keypad_pin_label = self.label(line2, "—", 13, TEXT, "bold")
        self.keypad_pin_label.pack(side="left", padx=8)
        self.keypad_hint = self.label(mirror, "ID → # → PIN → #", 9, MUTED)
        self.keypad_hint.pack(anchor="w", padx=14, pady=(0, 10))

        self.login_id_var.trace_add("write", lambda *_: self._limit4(self.login_id_var))
        self.login_pin_var.trace_add("write", lambda *_: self._limit4(self.login_pin_var))
        self._login_controls()

    def _limit4(self, var):
        val = var.get()
        cleaned = "".join(ch for ch in val if ch in "0123456789")[:4]
        if cleaned != val:
            var.set(cleaned)

    def _stat(self, parent, column, title, color):
        card = self.panel(parent)
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
        self.label(card, title, 9, MUTED, "bold").pack(anchor="w", padx=17, pady=(12, 7))
        value = self.label(card, "—", 22, color, "bold")
        value.pack(anchor="w", padx=17, pady=(0, 12))
        return value

    def _build_dashboard(self):
        greeting = tk.Frame(self.dashboard, bg=BG)
        greeting.pack(fill="x", pady=(0, 13))
        self.user_heading = self.label(greeting, "", 19, TEXT, "bold")
        self.user_heading.pack(side="left")
        self.logout_btn = self.button(greeting, "Log out", self.logout, PANEL_ALT, TEXT)
        self.logout_btn.pack(side="right")

        stats = tk.Frame(self.dashboard, bg=BG)
        stats.pack(fill="x", pady=(0, 13))
        for i in range(3): stats.grid_columnconfigure(i, weight=1)
        self.balance_big = self._stat(stats, 0, "MY WALLET BALANCE", BLUE)
        self.stock_big = self._stat(stats, 1, "TOTAL MACHINE STOCK", GREEN)
        self.session_big = self._stat(stats, 2, "ACCOUNT STATUS", GREEN)

        body = tk.Frame(self.dashboard, bg=BG)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left_holder = tk.Frame(body, bg=BG)
        left_holder.grid(row=0, column=0, sticky="nsew", padx=(0, 13))
        canvas = tk.Canvas(left_holder, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(left_holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        left = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.label(left, "Available products", 16, TEXT, "bold").pack(anchor="w", pady=(0, 10))
        self.product_widgets = {}
        for item in (1, 2):
            card = self.panel(left)
            card.pack(fill="x", pady=(0, 10))
            top = tk.Frame(card, bg=PANEL)
            top.pack(fill="x", padx=16, pady=(13, 8))
            self.label(top, f"0{item}  /  ITEM {item}", 13, TEXT, "bold").pack(side="left")
            price_label = self.label(top, money(self.price[item]), 17, BLUE, "bold")
            price_label.pack(side="right")
            bottom = tk.Frame(card, bg=PANEL)
            bottom.pack(fill="x", padx=16, pady=(0, 13))
            availability = self.label(bottom, "Checking stock…", 10, MUTED)
            availability.pack(side="left")
            buy_button = self.button(bottom, "Purchase this item", lambda x=item: self.buy(x))
            buy_button.pack(side="right")
            self.product_widgets[item] = (price_label, availability, buy_button)

        wallet = self.panel(left)
        wallet.pack(fill="x", pady=(3, 10))
        self.label(wallet, "RECHARGE MY WALLET", 12, TEXT, "bold").pack(anchor="w", padx=16, pady=(14, 6))
        self.wallet_line = self.label(wallet, "Balance: —", 12, BLUE, "bold")
        self.wallet_line.pack(anchor="w", padx=16, pady=(0, 14))
        self.label(wallet, "Enter recharge amount (₹)", 10, MUTED, "bold").pack(anchor="w", padx=16)
        recharge_row = tk.Frame(wallet, bg=PANEL)
        recharge_row.pack(fill="x", padx=16, pady=(7, 9))
        amount_entry = self.entry(recharge_row, self.amount_var, width=14)
        amount_entry.pack(side="left", ipady=9, padx=(0, 10))
        self.recharge_btn = self.button(recharge_row, "Scan demo QR & recharge", self.recharge, GREEN)
        self.recharge_btn.pack(side="left")
        self.recharge_hint = self.label(wallet, "Choose a whole-number amount from ₹1 to ₹10,000.", 9, MUTED)
        self.recharge_hint.pack(anchor="w", padx=16, pady=(0, 13))
        self.amount_var.trace_add("write", lambda *_: self._render_recharge_hint())

        recent = self.panel(left)
        recent.pack(fill="x", pady=(0, 10))
        self.label(recent, "LAST PURCHASE", 11, MUTED, "bold").pack(anchor="w", padx=16, pady=(13, 6))
        self.last_tx_label = self.label(recent, self.last_transaction, 11, TEXT,
                                        wraplength=550, justify="left")
        self.last_tx_label.pack(anchor="w", padx=16, pady=(0, 15))

        right = self.panel(body)
        right.grid(row=0, column=1, sticky="nsew")
        history_header = tk.Frame(right, bg=PANEL)
        history_header.pack(fill="x", padx=15, pady=(15, 10))
        self.label(history_header, "MY PURCHASE HISTORY", 12, TEXT, "bold").pack(side="left")
        self.button(history_header, "Refresh", self.request_history, PANEL_ALT, TEXT).pack(side="right")
        self.history_owner = self.label(right, "Only your transactions are displayed.", 9, MUTED)
        self.history_owner.pack(anchor="w", padx=15, pady=(0, 8))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Vendora.Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, rowheight=30, borderwidth=0, font=(FONT, 10))
        style.configure("Vendora.Treeview.Heading", background=PANEL_ALT, foreground=MUTED,
                        font=(FONT, 9, "bold"), borderwidth=0)
        style.map("Vendora.Treeview", background=[("selected", "#2b5474")])
        table_wrap = tk.Frame(right, bg=PANEL)
        table_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        cols = ("item", "paid", "before", "after", "date")
        self.table = ttk.Treeview(table_wrap, columns=cols, show="headings",
                                  style="Vendora.Treeview", height=11)
        headings = [("item", "Product", 86), ("paid", "Paid", 68),
                    ("before", "Previous", 76), ("after", "New", 76),
                    ("date", "Date / time", 146)]
        for key, title, width in headings:
            self.table.heading(key, text=title)
            self.table.column(key, minwidth=55, width=width, anchor="center")
        table_scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=table_scroll.set)
        table_scroll.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self.label(right, "Purchase records are stored on the ESP32 (latest 24 machine-wide).",
                   9, MUTED, wraplength=390, justify="left").pack(anchor="w", padx=15, pady=(0, 12))
        self._render_dashboard()

    def _mirror_keypad(self, stage: str, value: str = ""):
        """Show the ESP32 physical keypad input without revealing a passcode."""
        if stage == "ID_STAGE":
            self.keypad_stage = "ID"
            self.keypad_id_var.set("")
            self.keypad_pin_var.set("")
            self.keypad_hint.configure(text="Enter 4-digit User ID on keypad, then press #.")
        elif stage == "ID":
            if re.fullmatch(r"[0-9]{0,4}", value):
                self.keypad_stage = "ID"
                self.keypad_id_var.set(value)
        elif stage == "PIN_STAGE":
            self.keypad_stage = "PIN"
            self.keypad_pin_var.set("")
            self.keypad_hint.configure(text="Enter 4-digit passcode on keypad, then press #.")
        elif stage == "PIN":
            if re.fullmatch(r"\*{0,4}", value):
                self.keypad_stage = "PIN"
                self.keypad_pin_var.set(value)
        self.keypad_id_label.configure(text=self.keypad_id_var.get() or "—")
        self.keypad_pin_label.configure(text=self.keypad_pin_var.get() or "—")

    def _enter_verified_account(self, uid: str):
        """Open dashboard only for an ESP32-verified authentication event."""
        if not valid_four_digits(uid):
            return
        if self.current_user == uid:
            return
        self.current_user = uid
        self.pending_login = None
        self.lock_until = None
        self.lock_check_sent = False
        self.balance = None
        self.stock = {1: None, 2: None}
        self.history = []
        self.last_transaction = "No purchases yet."
        self.login_pin_var.set("")
        self._show_dashboard()
        self._note(f"User {uid} authenticated by ESP32. Personal dashboard opened.")
        self.request_status()
        self.root.after(280, self.request_history)

    def _show_login(self):
        self.dashboard.pack_forget()
        self.login_view.pack(fill="both", expand=True)
        self._login_controls()

    def _show_dashboard(self):
        self.login_view.pack_forget()
        self.dashboard.pack(fill="both", expand=True)
        self._render_dashboard()

    def _note(self, message):
        self.activity.configure(text=time.strftime("%H:%M:%S") + "   " + message)

    def _login_controls(self):
        enabled = (self.connected and self.pending_login is None and self.lock_until is None
                   and self.current_user is None)
        self.login_btn.configure(state="normal" if enabled else "disabled",
                                 bg=BLUE if enabled else "#405169")

    def _refresh_ports(self):
        if list_ports is None:
            self.ports["values"] = ()
            return
        available = [p.device for p in list_ports.comports()]
        self.ports["values"] = available
        if available and self.port_var.get() not in available:
            self.port_var.set(available[0])

    def _toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        if serial is None:
            messagebox.showerror("Library missing", "Install pyserial:\n\npip install pyserial")
            return
        port = self.port_var.get()
        if not port:
            messagebox.showwarning("Select port", "Select the ESP32 COM port first.")
            return
        try:
            device = serial.Serial(port, 115200, timeout=0.2, write_timeout=1)
        except (OSError, serial.SerialException) as err:
            messagebox.showerror("Cannot connect", str(err))
            return
        self.port = device
        self.connected = True
        self.stop_reader.clear()
        self.link_label.configure(text="●  CONNECTED", fg=GREEN)
        self.connect_btn.configure(text="Disconnect", bg=RED)
        self.login_message.configure(text="Connected. Enter your user ID and PIN.", fg=GREEN)
        self._note(f"Connected to {port}. Waiting for ESP32 to start.")
        self._login_controls()
        threading.Thread(target=self._reader, args=(device,), daemon=True).start()
        self.root.after(2500, self._initialize_board)

    def _initialize_board(self):
        if self.connected:
            self._send(f"TIME,{int(time.time())}")
            self._send("STATUS")

    def disconnect(self):
        self.stop_reader.set()
        self.connected = False
        self.current_user = None
        self.pending_login = None
        self.pending_action = None
        self.is_dispensing = False
        self.lock_until = None
        self.lock_check_sent = False
        self.balance = None
        self.stock = {1: None, 2: None}
        self.history = []
        self.last_transaction = "No purchases yet."
        self._mirror_keypad("ID_STAGE")
        with self.io_lock:
            if self.port is not None:
                try:
                    self.port.close()
                except Exception:
                    pass
                self.port = None
        self.link_label.configure(text="●  DISCONNECTED", fg=RED)
        self.connect_btn.configure(text="Connect", bg=BLUE)
        self.login_message.configure(text="Connect to ESP32 to log in.", fg=MUTED)
        self._show_login()
        self._note("Disconnected from ESP32.")

    def _reader(self, device):
        while not self.stop_reader.is_set():
            try:
                line = device.readline().decode("utf-8", errors="replace").strip()
                if line:
                    self.queue.put(("line", line))
            except (OSError, serial.SerialException) as err:
                if not self.stop_reader.is_set():
                    self.queue.put(("error", str(err)))
                break

    def _send(self, command: str) -> bool:
        if not self.connected:
            return False
        with self.io_lock:
            try:
                if self.port is None:
                    return False
                self.port.write((command + "\n").encode("ascii"))
                return True
            except (OSError, serial.SerialException) as err:
                self._note(f"Serial send failed: {err}")
                return False

    def login(self):
        if not self.connected or self.current_user or self.pending_login or self.lock_until:
            return
        uid = self.login_id_var.get().strip()
        pin = self.login_pin_var.get().strip()
        if not valid_four_digits(uid) or not valid_four_digits(pin):
            self.login_message.configure(text="Enter exactly 4 digits in both fields.", fg=RED)
            return
        if self._send(f"LOGIN,{uid},{pin}"):
            self.pending_login = uid
            self.pending_since = time.monotonic()
            self.login_pin_var.set("")
            self.login_message.configure(text="Verifying account with ESP32…", fg=AMBER)
            self._login_controls()
            self._note(f"User {uid}: authentication requested.")

    def logout(self):
        if not self.connected or self.pending_action or self.is_dispensing:
            return
        if self._send("LOGOUT"):
            self._forget_session()
            self._note("Logged out. Your account information is hidden.")

    def _forget_session(self):
        self.current_user = None
        self.pending_login = None
        self.pending_action = None
        self.balance = None
        self.stock = {1: None, 2: None}
        self.history = []
        self.is_dispensing = False
        self.last_transaction = "No purchases yet."
        self.login_id_var.set("")
        self.login_pin_var.set("")
        self.amount_var.set("")
        self._mirror_keypad("ID_STAGE")
        self.login_message.configure(text="Enter your 4-digit ID and PIN.", fg=MUTED)
        self._show_login()

    def buy(self, item: int):
        if not self._actions_ready():
            return
        stock = self.stock[item]
        if stock is None or stock <= 0:
            messagebox.showwarning("Out of stock", f"Item {item} is unavailable.")
            return
        if self.balance is None or self.balance < self.price[item]:
            messagebox.showwarning("Low balance", "Recharge your wallet before purchasing.")
            return
        if not messagebox.askyesno("Confirm purchase",
                                   f"Buy Item {item} for {money(self.price[item])}?\n\n"
                                   f"Current balance: {money(self.balance)}"):
            return
        if self._send(f"BUY,{item}"):
            self.pending_action = "purchase"
            self.pending_since = time.monotonic()
            self._note(f"Item {item}: purchase sent. Waiting for stepper motor.")
            self._render_dashboard()

    def _actions_ready(self):
        return self.connected and self.current_user is not None and not self.is_dispensing and self.pending_action is None

    def recharge(self):
        if not self._actions_ready():
            return
        amount = parse_recharge_amount(self.amount_var.get())
        if amount is None:
            messagebox.showwarning("Invalid amount", "Type a whole-number amount between ₹1 and ₹10,000.")
            return
        if self.balance is None or self.balance + amount > 100000:
            messagebox.showwarning("Wallet limit", "This recharge would exceed the ₹100,000 wallet limit.")
            return
        if qrcode is None or ImageTk is None:
            messagebox.showerror("QR support missing", 'Install QR support:\n\npip install "qrcode[pil]"')
            return
        self._show_demo_qr(amount)

    def _show_demo_qr(self, amount):
        dialog = tk.Toplevel(self.root)
        dialog.title("VENDORA | Demo wallet recharge")
        dialog.configure(bg=BG)
        dialog.geometry("460x585")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        self.label(dialog, "DEMO QR WALLET RECHARGE", 15, TEXT, "bold").pack(pady=(25, 10))
        self.label(dialog, f"User {self.current_user}  •  {money(amount)}", 17, GREEN, "bold").pack(pady=7)
        self.label(dialog, f"{money(self.balance)}  +  {money(amount)}  =  {money(self.balance + amount)}",
                   11, TEXT).pack(pady=(2, 15))
        qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=7, border=2)
        qr.add_data(f"VENDORA DEMO ONLY | User {self.current_user} | INR {amount} | No real transaction")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        img = img.resize((230, 230))
        dialog.qr_photo = ImageTk.PhotoImage(img)
        tk.Label(dialog, image=dialog.qr_photo, bg=BG).pack(pady=(0, 11))
        self.label(dialog, "DEMO QR · NOT A UPI PAYMENT", 10, AMBER, "bold").pack(pady=(2, 7))
        self.label(dialog, "No money is transferred. Confirm to add virtual\n"
                   "credits to the currently logged-in ESP32 wallet.",
                   10, MUTED, justify="center").pack()

        def confirm():
            if not self._actions_ready() or self.balance is None:
                messagebox.showwarning("Session unavailable", "Please log in again.", parent=dialog)
                return
            if not messagebox.askyesno("Confirm virtual recharge",
                                       f"Credit {money(amount)} to User {self.current_user}?\n"
                                       "This is simulated and requires no payment.", parent=dialog):
                return
            if self._send(f"RECHARGE,{amount}"):
                self.pending_action = "recharge"
                self.pending_since = time.monotonic()
                self._note(f"Waiting for ESP32 to confirm {money(amount)} recharge.")
                dialog.destroy()
                self._render_dashboard()

        self.button(dialog, "Confirm DEMO recharge", confirm, GREEN).pack(fill="x", padx=34, pady=(18, 8))
        self.button(dialog, "Cancel", dialog.destroy, PANEL_ALT, TEXT).pack(fill="x", padx=34)

    def request_history(self):
        if self.connected and self.current_user and not self.is_dispensing:
            self.reading_history = False
            self._send("HISTORY")

    def request_status(self):
        if self.connected and not self.is_dispensing:
            self._send("STATUS")

    def _on_line(self, line: str):
        fields = line.split(",")
        cmd = fields[0]
        try:
            if cmd == "READY":
                self._note("ESP32 initialized. Ready for account login.")
                self.root.after(180, self._initialize_board)
            elif cmd == "INPUT" and len(fields) >= 3:
                # Non-sensitive live input emitted by physical ESP32 keypad.
                if fields[1] == "STAGE" and fields[2] == "ID":
                    self._mirror_keypad("ID_STAGE")
                elif fields[1] == "STAGE" and fields[2] == "PIN":
                    self._mirror_keypad("PIN_STAGE")
                elif fields[1] == "ID":
                    self._mirror_keypad("ID", fields[2])
                elif fields[1] == "PIN":
                    self._mirror_keypad("PIN", fields[2])
            elif cmd == "AUTH" and len(fields) >= 3:
                if fields[1] == "OK":
                    # Hardware has validated the actual ID and PIN, whether
                    # entered from the physical keypad or GUI login form.
                    self._enter_verified_account(fields[2])
                elif fields[1] == "FAIL":
                    self.pending_login = None
                    remaining = fields[2]
                    self.login_message.configure(text=f"Incorrect ID or PIN. Attempts left: {remaining}", fg=RED)
                    self._login_controls()
                    self._note("Login rejected by ESP32.")
            elif cmd == "LOCK" and len(fields) >= 2:
                if fields[1] == "ACTIVE":
                    seconds = int(fields[2]) if len(fields) > 2 else 30
                    self.lock_until = time.monotonic() + max(1, seconds)
                    self.lock_check_sent = False
                    self.pending_login = None
                    self._forget_session()
                    self.login_message.configure(text=f"Security lock active: {seconds} seconds.", fg=RED)
                    self._note("Security lock enabled after 3 wrong PIN attempts.")
                elif fields[1] == "RELEASED":
                    self.lock_until = None
                    self.lock_check_sent = False
                    self.login_message.configure(text="Lock released. You may log in.", fg=GREEN)
                    self._note("Security lock released.")
                    self._login_controls()
            elif cmd == "SESSION":
                if len(fields) >= 2 and valid_four_digits(fields[1]) and not self.lock_until:
                    # Recover an already-verified session from an ESP32 STATUS response.
                    self._enter_verified_account(fields[1])
                elif len(fields) >= 2 and fields[1] == "NONE":
                    if self.lock_until is not None:
                        self.lock_until = None
                        self.lock_check_sent = False
                        self.login_message.configure(text="ESP32 unlocked. Enter your credentials.", fg=GREEN)
                    if self.current_user is not None:
                        self._forget_session()
                        self._note("ESP32 session ended. Account hidden.")
            elif cmd == "WALLET" and len(fields) >= 3 and fields[1] == self.current_user:
                self.balance = int(fields[2])
            elif cmd == "STOCK" and len(fields) >= 5 and self.current_user:
                self.stock[1], self.stock[2] = int(fields[1]), int(fields[2])
                self.price[1], self.price[2] = int(fields[3]), int(fields[4])
            elif cmd == "PURCHASE_START" and len(fields) >= 3 and fields[1] == self.current_user:
                self.is_dispensing = True
                self.pending_action = "purchase"
                self.pending_since = time.monotonic()
                self._note(f"Motor {fields[2]} is dispensing. Please wait…")
            elif cmd == "PURCHASE_OK" and len(fields) >= 8 and fields[1] == self.current_user:
                item = int(fields[2]); paid = int(fields[3]); before = int(fields[4]); after = int(fields[5])
                self.balance = after
                self.stock[item] = int(fields[6])
                self.is_dispensing = False
                self.pending_action = None
                self.last_transaction = (f"Item {item}  ·  Paid {money(paid)}  ·  "
                                         f"Previous {money(before)} → New {money(after)}\n"
                                         f"Item {item} remaining stock: {self.stock[item]} unit(s)")
                self._note(f"Item {item} motor cycle completed. {money(paid)} deducted; balance {money(after)}.")
                messagebox.showinfo("Purchase completed",
                                    f"Item {item} dispensing cycle completed.\n\n"
                                    f"Amount deducted: {money(paid)}\n"
                                    f"Previous balance: {money(before)}\n"
                                    f"Updated balance: {money(after)}\n"
                                    f"Item {item} stock remaining: {self.stock[item]}")
                self.request_history()
            elif cmd == "RECHARGE_OK" and len(fields) >= 5 and fields[1] == self.current_user:
                added = int(fields[2]); before = int(fields[3]); after = int(fields[4])
                self.balance = after
                self.pending_action = None
                self._note(f"Recharge complete: +{money(added)}. New balance: {money(after)}.")
                messagebox.showinfo("Wallet recharged",
                                    f"User {self.current_user}\n\n"
                                    f"Amount added: {money(added)}\n"
                                    f"Previous balance: {money(before)}\n"
                                    f"New balance: {money(after)}")
            elif cmd == "HISTORY_BEGIN" and len(fields) >= 2 and fields[1] == self.current_user:
                self.reading_history = True
                self.history = []
            elif cmd == "HISTORY" and len(fields) >= 9 and self.reading_history and fields[1] == self.current_user:
                self.history.append(dict(seq=int(fields[2]), item=int(fields[3]), price=int(fields[4]),
                                         before=int(fields[5]), after=int(fields[6]),
                                         timestamp=int(fields[7]), motor_us=int(fields[8])))
            elif cmd == "HISTORY_END" and len(fields) >= 2 and fields[1] == self.current_user:
                self.reading_history = False
                self._render_history()
                if self.history and self.last_transaction == "No purchases yet.":
                    last = max(self.history, key=lambda x: x["seq"])
                    self.last_transaction = (
                        f"Item {last['item']}  ·  Paid {money(last['price'])}  ·  "
                        f"Previous {money(last['before'])} → New {money(last['after'])}"
                    )
            elif cmd == "LOGOUT" and len(fields) >= 2 and fields[1] == self.current_user:
                self._forget_session()
            elif cmd == "ERROR":
                code = fields[1] if len(fields) > 1 else "UNKNOWN"
                self.pending_action = None
                if code == "SESSION_ACTIVE" and self.pending_login:
                    self.pending_login = None
                    self.login_message.configure(text="Another session is active. Press * on keypad to log out.", fg=AMBER)
                elif code == "LOGIN_REQUIRED" and self.current_user:
                    self._forget_session()
                if code in ("OUT_OF_STOCK", "LOW_BALANCE"):
                    messagebox.showwarning("Purchase denied", code.replace("_", " ").title())
                self._note("ESP32: " + code.replace("_", " ").lower())
                self.request_status()
        except (ValueError, IndexError):
            self._note("Ignored malformed serial message from ESP32.")
        self._render_dashboard()
        self._login_controls()

    def _render_history(self):
        self.table.delete(*self.table.get_children())
        for tx in reversed(self.history):
            stamp = tx["timestamp"]
            date = dt.datetime.fromtimestamp(stamp).strftime("%d %b %H:%M") if stamp else "Not synced"
            self.table.insert("", "end", values=(
                f"Item {tx['item']}", money(tx['price']), money(tx['before']), money(tx['after']), date))

    def _render_recharge_hint(self):
        if not hasattr(self, "recharge_hint"):
            return
        amount = parse_recharge_amount(self.amount_var.get())
        if amount is None:
            preview = "Enter ₹1–₹10,000; recharge is simulated."
        elif self.balance is None:
            preview = f"Adding {money(amount)} · waiting for wallet balance"
        else:
            preview = f"{money(self.balance)} + {money(amount)} = {money(self.balance + amount)} (after confirmation)"
        self.recharge_hint.configure(text=preview)
        self._update_controls()

    def _render_dashboard(self):
        if not hasattr(self, "balance_big"):
            return
        self.user_heading.configure(text=f"Welcome, User {self.current_user or '—'}")
        self.balance_big.configure(text=money(self.balance))
        self.wallet_line.configure(text=f"Available balance: {money(self.balance)}")
        self.session_big.configure(text="Dispensing…" if self.is_dispensing else "Signed in")
        stocks = (self.stock[1], self.stock[2])
        self.stock_big.configure(text=str(sum(stocks)) if None not in stocks else "—")
        self.history_owner.configure(text=f"Only transactions of User {self.current_user or '—'} are shown")
        self.last_tx_label.configure(text=self.last_transaction)
        for item, (price_label, availability, button) in self.product_widgets.items():
            price_label.configure(text=money(self.price[item]))
            count = self.stock[item]
            if count is None:
                text, color = "Stock: waiting for ESP32", MUTED
            elif count == 0:
                text, color = "OUT OF STOCK · 0 units", RED
            else:
                text, color = f"IN STOCK · {count} unit(s)", GREEN
            availability.configure(text=text, fg=color)
        self._update_controls()
        self._render_recharge_hint_text_only()

    def _render_recharge_hint_text_only(self):
        amount = parse_recharge_amount(self.amount_var.get())
        if amount is None:
            text = "Type a recharge amount between ₹1 and ₹10,000."
        elif self.balance is None:
            text = f"Recharge of {money(amount)} · checking wallet balance"
        else:
            text = f"Expected: {money(self.balance)} + {money(amount)} = {money(self.balance + amount)}"
        self.recharge_hint.configure(text=text)

    def _update_controls(self):
        if not hasattr(self, "product_widgets"):
            return
        ready = self._actions_ready()
        for item, (_, _, button) in self.product_widgets.items():
            in_stock = self.stock[item] is not None and self.stock[item] > 0
            affordable = self.balance is not None and self.balance >= self.price[item]
            enabled = ready and in_stock and affordable
            button.configure(state="normal" if enabled else "disabled",
                             bg=BLUE if enabled else "#40516b")
        recharge_amount = parse_recharge_amount(self.amount_var.get())
        can_recharge = (ready and recharge_amount is not None and self.balance is not None
                        and self.balance + recharge_amount <= 100000)
        self.recharge_btn.configure(state="normal" if can_recharge else "disabled",
                                    bg=GREEN if can_recharge else "#40516b")
        self.logout_btn.configure(state="normal" if ready else "disabled")

    def _pump(self):
        try:
            for _ in range(200):
                kind, line = self.queue.get_nowait()
                if kind == "error":
                    if self.connected:
                        self._note(f"Connection error: {line}")
                        self.disconnect()
                elif self.connected:
                    self._on_line(line)
        except queue.Empty:
            pass
        if self.lock_until is not None:
            remaining = max(0, int(self.lock_until - time.monotonic() + 0.99))
            if remaining:
                self.login_message.configure(text=f"Security lock active · {remaining}s remaining", fg=RED)
            else:
                # The firmware must explicitly release the lock; do not
                # enable login based only on the PC's countdown.
                if not self.lock_check_sent:
                    self._send("STATUS")
                    self.lock_check_sent = True
                self.login_message.configure(text="Confirming lock release with ESP32…", fg=AMBER)
        if self.pending_login and time.monotonic() - self.pending_since > 12:
            self.pending_login = None
            self.login_message.configure(text="No login response. Check ESP32 connection.", fg=RED)
            self._login_controls()
        if self.pending_action and time.monotonic() - self.pending_since > 24:
            self.pending_action = None
            self._note("No confirmation yet. Querying ESP32 for current status.")
            self.request_status()
            self.request_history()
            self._render_dashboard()
        self.root.after(70, self._pump)

    def close(self):
        if self.connected:
            self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    VendoraApp(root)
    root.mainloop()
