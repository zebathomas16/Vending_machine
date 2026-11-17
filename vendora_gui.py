"""VENDORA V09 — static GUI design prototype (no serial communication yet)."""
import tkinter as tk
from tkinter import ttk
root=tk.Tk()
root.title("VENDORA | V09 GUI Prototype")
root.geometry("760x480")
root.configure(bg="#0b1220")
fg="#f0f5ff"; card="#142034"
tk.Label(root,text="VENDORA",font=("Segoe UI",26,"bold"),fg=fg,bg="#0b1220").pack(anchor="w",padx=30,pady=25)
tk.Label(root,text="GUI DESIGN PROTOTYPE — no ESP32 connection yet",font=("Segoe UI",11),fg="#ffca72",bg="#0b1220").pack(anchor="w",padx=30)
for item,price in ((1,20),(2,30)):
    f=tk.Frame(root,bg=card);f.pack(fill="x",padx=30,pady=12)
    tk.Label(f,text=f"Item {item}    ₹{price}",font=("Segoe UI",17,"bold"),bg=card,fg=fg).pack(side="left",padx=20,pady=22)
    tk.Button(f,text="Coming in v10",state="disabled").pack(side="right",padx=20)
tk.Label(root,text="Version 10 will connect this interface to the physical ESP32.",fg="#9aacc4",bg="#0b1220").pack(pady=14)
root.mainloop()
