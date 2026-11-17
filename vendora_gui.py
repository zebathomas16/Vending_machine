"""VENDORA V10 | USB serial GUI. Run: python vendora_gui.py; pip install pyserial"""
import tkinter as tk
from tkinter import messagebox, ttk
import threading, queue, re
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial=None
    list_ports=None
BG="#0b1220"; PANEL="#142034"; TEXT="#f0f5ff"; MUTED="#9aacc4"
root=tk.Tk()
root.title("VENDORA | Version 10")
root.geometry("900x720")
root.configure(bg=BG)
port_var=tk.StringVar()
status_var=tk.StringVar(value="Disconnected")
auth_var=tk.StringVar(value="PIN required")
wallet_var=tk.StringVar(value="Wallet: pending")
stock_var=tk.StringVar(value="Stock: pending")
activity=tk.StringVar(value="Connect ESP32 at 115200 baud")
pin_var=tk.StringVar()
recharge_var=tk.StringVar(value="100")
history_rows=[]
serial_port=None
reader_stop=threading.Event()
inbox=queue.Queue()
state={"authenticated":False,"wallet":None,"prices":[20,30],"stock":[None,None]}

def label(parent,text,**kwargs):
    opts={"font":("Segoe UI",11)};opts.update(kwargs)
    return tk.Label(parent,text=text,bg=parent.cget("bg"),fg=TEXT,**opts)

def send(cmd):
    if not serial_port: return False
    try:
        serial_port.write((cmd+"\n").encode("ascii")); return True
    except Exception as error:
        activity.set(str(error)); return False

def login():
    pin=pin_var.get().strip()
    if not re.fullmatch(r"[0-9]{4}",pin):
        messagebox.showwarning("PIN","Enter exactly 4 digits");return
    send("LOGIN,"+pin)
    pin_var.set("")

def buy(item):
    if not state["authenticated"]:messagebox.showwarning("Login","Sign in first");return
    if False and state["wallet"] is not None and state["wallet"]<state["prices"][item-1]:
        messagebox.showwarning("Wallet","Insufficient virtual balance");return
    if False and state["stock"][item-1] is not None and state["stock"][item-1]<=0:
        messagebox.showwarning("Stock","Item out of stock");return
    if messagebox.askyesno("Purchase",f"Dispense Item {item}?"):
        send(f"BUY,{item}")

def recharge():
    val=recharge_var.get().strip()
    if not re.fullmatch(r"[0-9]{1,5}",val) or not 1<=int(val)<=10000:
        messagebox.showwarning("Amount","Enter ₹1–₹10000");return
    if state["authenticated"]: send("RECHARGE,"+val)
    else: messagebox.showwarning("Login","Authenticate before recharging")

def on_line(line):
    if line=="AUTH,OK": state["authenticated"]=True;auth_var.set("Access granted")
    elif line.startswith("AUTH,FAIL"): state["authenticated"]=False;auth_var.set("Incorrect PIN")
    elif line.startswith("STATUS,AUTH,"):
        state["authenticated"]=line.endswith("1");auth_var.set("Access granted" if state["authenticated"] else "PIN required")
    elif line.startswith("LOCK,ACTIVE"):state["authenticated"]=False;auth_var.set("Locked for 30 seconds")
    elif line=="LOCK,RELEASED":auth_var.set("Lock released; enter PIN")
    elif line.startswith("WALLET,"):
        state["wallet"]=int(line.split(",")[1]);wallet_var.set(f"My wallet: ₹{state['wallet']}")
    elif line.startswith("PRICES,"):
        state["prices"]=[int(x) for x in line.split(",")[1:3]]
        for i in (0,1):item_prices[i].set(f"₹{state['prices'][i]}")
    elif line.startswith("STOCK,"):
        state["stock"]=[int(x) for x in line.split(",")[1:3]]
        stock_var.set("Item 1: {} units  |  Item 2: {} units".format(*state["stock"]))
        for i in (0,1):stock_indicators[i].set("OUT OF STOCK" if state["stock"][i]==0 else f"{state['stock'][i]} available")
    elif line.startswith("RECHARGE_OK,"):
        amount,balance=(int(x) for x in line.split(",")[1:3]);state["wallet"]=balance;wallet_var.set(f"My wallet: ₹{balance}")
        messagebox.showinfo("Wallet",f"Virtual recharge: ₹{amount} added. New balance ₹{balance}")
    elif line.startswith("HISTORY,") and len(line.split(","))==6:
        _,sequence,item,paid,balance,uptime=line.split(",")
        history_rows.append((sequence,item,paid,balance,uptime))
    elif line=="HISTORY_BEGIN":
        history_rows.clear()
    elif line=="HISTORY_END":
        for row in tree.get_children():tree.delete(row)
        for seq,item,paid,balance,uptime in reversed(history_rows):tree.insert("","end",values=(seq,item,"₹"+paid,"₹"+balance,uptime+" s"))
    elif line.startswith("PURCHASE,"):
        activity.set("Purchase complete; wallet and stock refreshed")
        send("STATUS")
        if False:send("HISTORY")
    elif line.startswith("ERROR,"):activity.set(line.replace(","," · "))
    elif line.startswith("MOTOR_START,"):activity.set("Dispensing item " +line.split(",")[1])
    elif line.startswith("MOTOR_DONE,"):activity.set("Motor cycle completed")
    refresh_buttons()

def refresh_buttons():
    for i,button in enumerate(buy_buttons):
        permitted=state["authenticated"]
        if False and state["stock"][i] is not None and state["stock"][i]<=0:permitted=False
        button.configure(state="normal" if permitted else "disabled")
    if False:recharge_btn.configure(state="normal" if state["authenticated"] else "disabled")

def reader():
    while not reader_stop.is_set():
        try:
            line=serial_port.readline().decode("utf8","replace").strip()
            if line:inbox.put(("line",line))
        except Exception as e:
            inbox.put(("error",str(e)));break

def connect():
    global serial_port
    if serial is None:messagebox.showerror("Dependency","pip install pyserial");return
    try:serial_port=serial.Serial(port_var.get(),115200,timeout=.2)
    except Exception as e:messagebox.showerror("Port",str(e));return
    reader_stop.clear();threading.Thread(target=reader,daemon=True).start()
    status_var.set("Connected: "+port_var.get())
    root.after(3000,lambda:send("STATUS"))

def disconnect():
    global serial_port
    reader_stop.set()
    if serial_port:
        try:serial_port.close()
        except Exception:pass
    serial_port=None
    state["authenticated"]=False
    status_var.set("Disconnected")
    refresh_buttons()

def pump():
    try:
        for _ in range(80):
            kind,text=inbox.get_nowait()
            if kind=="line":on_line(text)
            else:activity.set("Serial error: "+text);disconnect()
    except queue.Empty:pass
    root.after(70,pump)

def on_close():
    disconnect();root.destroy()

header=tk.Frame(root,bg=BG);header.pack(fill="x",padx=24,pady=20)
label(header,"VENDORA  /  VERSION 10",font=("Segoe UI",19,"bold")).pack(side="left")
label(header,"USB serial · 115200 baud").pack(side="right")
bar=tk.Frame(root,bg=PANEL);bar.pack(fill="x",padx=24,pady=8)
ports=[p.device for p in list_ports.comports()] if list_ports else []
if ports:port_var.set(ports[0])
ttk.Combobox(bar,values=ports,textvariable=port_var,width=19).pack(side="left",padx=10,pady=12)
tk.Button(bar,text="Connect",command=connect).pack(side="left",padx=5)
tk.Button(bar,text="Disconnect",command=disconnect).pack(side="left",padx=5)
label(bar,"Status:").pack(side="left",padx=8)
label(bar,"",textvariable=status_var).pack(side="left")
loginframe=tk.Frame(root,bg=PANEL);loginframe.pack(fill="x",padx=24,pady=8)
label(loginframe,"Four-digit PIN (keypad also works):").pack(side="left",padx=10,pady=12)
tk.Entry(loginframe,textvariable=pin_var,show="*",width=12).pack(side="left")
tk.Button(loginframe,text="Sign in",command=login).pack(side="left",padx=8)
tk.Button(loginframe,text="Log out",command=lambda:send("LOGOUT")).pack(side="left")
label(loginframe,"",textvariable=auth_var).pack(side="right",padx=16)
prod=tk.Frame(root,bg=BG);prod.pack(fill="x",padx=24,pady=10)
buy_buttons=[];item_prices=[];stock_indicators=[]
for i in (1,2):
    panel=tk.Frame(prod,bg=PANEL);panel.pack(fill="x",pady=5)
    label(panel,f"ITEM {i}",font=("Segoe UI",14,"bold")).pack(side="left",padx=14,pady=12)
    p=tk.StringVar(value="₹20" if i==1 else "₹30");item_prices.append(p)
    label(panel,"",textvariable=p).pack(side="left",padx=14)
    s=tk.StringVar(value="Stock arrives in v12" if True else "Stock pending");stock_indicators.append(s)
    label(panel,"",textvariable=s).pack(side="left",padx=14)
    btn=tk.Button(panel,text="Dispense",command=lambda item=i:buy(item));btn.pack(side="right",padx=16)
    buy_buttons.append(btn)
if False:
    wallet=tk.Frame(root,bg=PANEL);wallet.pack(fill="x",padx=24,pady=8)
    label(wallet,"",textvariable=wallet_var).pack(side="left",padx=15,pady=14)
    label(wallet,"Recharge amount ₹:").pack(side="left",padx=12)
    tk.Entry(wallet,textvariable=recharge_var,width=10).pack(side="left",padx=4)
    recharge_btn=tk.Button(wallet,text="Recharge (virtual)",command=recharge);recharge_btn.pack(side="left",padx=12)
else:
    recharge_btn=tk.Button(root)
if False:
    label(root,"",textvariable=stock_var).pack(anchor="w",padx=26)
if False:
    panel=tk.Frame(root,bg=PANEL);panel.pack(fill="both",expand=True,padx=24,pady=10)
    label(panel,"PURCHASE HISTORY (last 10, RAM)").pack(anchor="w",padx=14,pady=8)
    tk.Button(panel,text="Sync history",command=lambda:send("HISTORY")).pack(anchor="e",padx=15)
    tree=ttk.Treeview(panel,columns=("id","item","paid","wallet","uptime"),show="headings",height=7)
    for key,title in (("id","No."),("item","Item"),("paid","Paid"),("wallet","Balance"),("uptime","ESP32 uptime")):
        tree.heading(key,text=title)
    tree.pack(fill="both",expand=True,padx=12,pady=8)
else:
    tree=None
foot=tk.Frame(root,bg=PANEL);foot.pack(fill="x",padx=24,pady=10)
label(foot,"",textvariable=activity).pack(anchor="w",padx=12,pady=12)
refresh_buttons()
root.after(70,pump)
root.protocol("WM_DELETE_WINDOW",on_close)
root.mainloop()
