# -*- coding: utf-8 -*-
"""
Hotel Pricing Assistant - Staff UI
==============================================
A one-click pricing tool for non-technical staff:
1. Click "Run Pricing Now" to run the hotel rms.py pricing engine.
2. When finished, the results table loads automatically (recommended rates,
   demand status, suggested action).
3. Click any row to see a plain-English breakdown of WHY that price was set.

Launch: double-click Start_Pricing_UI.bat
"""

import csv
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

# ==========================================
# Path setup (works no matter where the app is launched from)
# ==========================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
RMS_SCRIPT = os.path.join(APP_DIR, "hotel rms.py")

DOW_EN = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


def read_csv_rows(path):
    """Read a CSV file into a list of dicts (stdlib only, no pandas needed)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def find_latest_csv(pattern):
    """Find the newest result CSV matching the filename pattern."""
    candidates = []
    for name in os.listdir(APP_DIR):
        if re.match(pattern, name):
            full = os.path.join(APP_DIR, name)
            candidates.append((os.path.getmtime(full), full))
    if not candidates:
        return None
    return max(candidates)[1]


def load_latest_results():
    """Load the newest Manager View + Technical View CSVs and merge them
    by (Stay_Date, Room_Type) into one record list."""
    mgr_path = find_latest_csv(r".*_RMS_Manager_View_\d{4}-\d{2}-\d{2}.*\.csv")
    tech_path = find_latest_csv(r".*_Live_Dashboard_\d{4}-\d{2}-\d{2}.*\.csv")
    if not mgr_path:
        return None

    tech_map = {}
    if tech_path:
        for row in read_csv_rows(tech_path):
            tech_map[(row.get("Stay_Date", ""), row.get("Room_Type", ""))] = row

    records = []
    for row in read_csv_rows(mgr_path):
        key = (row.get("Stay_Date", ""), row.get("Room_Type", ""))
        tech = tech_map.get(key, {})
        stay = row.get("Stay_Date", "")
        try:
            d = datetime.strptime(stay, "%Y-%m-%d")
            dow = DOW_EN[d.weekday()]
        except ValueError:
            dow = ""
        try:
            days_ahead = int(tech.get("Days_to_Checkin", "") or "")
        except ValueError:
            days_ahead = ""
        try:
            pace = float(tech.get("Pace_Ratio", "") or "")
        except ValueError:
            pace = None

        records.append({
            "Stay_Date": stay,
            "DOW": dow,
            "Room_Type": row.get("Room_Type", ""),
            "Final_ADR": row.get("Final_ADR", ""),
            "Base_ADR": tech.get("Base_Room_ADR", ""),
            "Change": row.get("ADR_Change_vs_Base", ""),
            "Demand": row.get("Demand_Status", ""),
            "Action": row.get("Action", ""),
            "Occ": row.get("Current_Occupancy", ""),
            "Confidence": row.get("Confidence_Score", ""),
            "Reason": row.get("Reason", ""),
            "Event": tech.get("Event_Name", "None"),
            "Days_to_Checkin": days_ahead,
            "Pace_Ratio": pace,
            "Competitor_ADR": tech.get("Competitor_ADR", ""),
            "RevPAR": tech.get("Expected_RevPAR", ""),
        })
    records.sort(key=lambda r: (r["Stay_Date"], r["Room_Type"]))
    return records


def parse_change_pct(change_str):
    """Parse '+12.5%' / '-8.3%' into a float; return None on failure."""
    if not change_str:
        return None
    m = re.match(r"([+-]?\d+\.?\d*)%", change_str.strip())
    return float(m.group(1)) if m else None


# ==========================================
# Main application window
# ==========================================
class RMSApp:
    def __init__(self, root):
        self.root = root
        self.records = []
        self.running = False

        root.title("Hotel Pricing Assistant")
        root.geometry("1180x760")
        root.minsize(980, 620)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Run.TButton", font=("Segoe UI", 13, "bold"), padding=14)
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=26)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("Big.TLabel", font=("Segoe UI", 11, "bold"))

        self.build_top_bar()
        self.build_table()
        self.build_detail_panel()
        self.build_status_bar()

        # Check the runtime environment in the background on startup
        threading.Thread(target=self.check_environment, daemon=True).start()

    # ---------- Top bar: run button + filters ----------
    def build_top_bar(self):
        top = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        top.pack(fill="x")

        self.run_btn = ttk.Button(top, text="▶  Run Pricing Now", style="Run.TButton",
                                  command=self.run_pricing)
        self.run_btn.pack(side="left")

        ttk.Label(top, text="   Show:").pack(side="left")
        self.range_var = tk.StringVar(value="Next 14 days")
        cb = ttk.Combobox(top, textvariable=self.range_var, state="readonly",
                          width=12, values=["Next 7 days", "Next 14 days",
                                            "Next 30 days", "All 90 days"])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.populate_table())

        ttk.Label(top, text="   Room type:").pack(side="left")
        self.type_var = tk.StringVar(value="All room types")
        self.type_cb = ttk.Combobox(top, textvariable=self.type_var, state="readonly",
                                    width=14, values=["All room types"])
        self.type_cb.pack(side="left")
        self.type_cb.bind("<<ComboboxSelected>>", lambda e: self.populate_table())

        self.last_run_lbl = ttk.Label(top, text="(Not run yet - click the button to start)",
                                      foreground="#666666")
        self.last_run_lbl.pack(side="right")

    # ---------- Middle: results table ----------
    def build_table(self):
        cols = ("date", "dow", "type", "final", "change", "demand", "action",
                "occ", "conf", "reason")
        headers = ("Date", "Day", "Room Type", "Recommended Rate", "vs Base",
                   "Demand", "Suggested Action", "Occupancy", "Confidence", "Pricing Reason")
        widths = (95, 55, 85, 115, 80, 100, 120, 80, 80, 330)

        frame = ttk.Frame(self.root, padding=(12, 4))
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, headers, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("reason", "date") else "center")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Row colors by demand status
        self.tree.tag_configure("Peak", background="#fde2e2")
        self.tree.tag_configure("High", background="#fff3e0")
        self.tree.tag_configure("Low", background="#e8f5e9")
        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

    # ---------- Bottom: pricing explanation panel ----------
    def build_detail_panel(self):
        panel = ttk.LabelFrame(self.root, text=" Why this price? (click any row above) ",
                               padding=(14, 6, 14, 10))
        panel.pack(fill="x", padx=12, pady=(2, 4))
        self.detail = panel

        # Row 1: headline conclusion
        self.summary_lbl = ttk.Label(panel, text="← Click a row in the table above to see the pricing explanation",
                                     style="Big.TLabel", foreground="#555555", wraplength=1100,
                                     justify="left")
        self.summary_lbl.grid(row=0, column=0, columnspan=6, sticky="w", pady=(2, 6))

        # Row 2: base vs recommended rate comparison bars
        self.canvas = tk.Canvas(panel, width=1050, height=64, highlightthickness=0)
        self.canvas.grid(row=1, column=0, columnspan=6, sticky="w")

        # Row 3: factor cards (5)
        self.factor_vars = []
        titles = ["📅 Special Event", "🏨 Supply & Demand", "📈 Booking Pace",
                  "🥊 Competitor", "🎯 Forecast RevPAR"]
        for i, t in enumerate(titles):
            f = ttk.Frame(panel)
            f.grid(row=2, column=i, sticky="nw", padx=(0, 24), pady=(4, 2))
            ttk.Label(f, text=t, foreground="#1a6fb5",
                      font=("Segoe UI", 9, "bold")).pack(anchor="w")
            v = tk.Text(f, width=18, height=3, wrap="word", relief="flat",
                        background="#f5f7fa", font=("Segoe UI", 9))
            v.configure(state="disabled")
            v.pack(anchor="w", pady=2)
            self.factor_vars.append(v)

        # Row 4: confidence note
        self.conf_lbl = ttk.Label(panel, text="", foreground="#666666")
        self.conf_lbl.grid(row=3, column=0, columnspan=6, sticky="w", pady=(2, 0))

    # ---------- Bottom: status log ----------
    def build_status_bar(self):
        self.status = tk.Text(self.root, height=4, relief="flat", background="#20232a",
                              foreground="#9fe88d", font=("Consolas", 9),
                              state="disabled")
        self.status.pack(fill="x", padx=12, pady=(0, 10))

    def log(self, msg):
        self.status.configure(state="normal")
        self.status.insert("end", msg + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    # ---------- Environment check ----------
    def check_environment(self):
        try:
            r = subprocess.run([sys.executable, "-c", "import pandas, numpy, requests"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                self.root.after(0, lambda: self.log("✅ Environment check passed (pandas / numpy / requests ready)"))
            else:
                self.root.after(0, lambda: self.log(
                    "⚠️ Missing Python packages (pandas / numpy / requests).\n"
                    "   To fix: press Win+R, type cmd, then run\n"
                    f"   \"{sys.executable}\" -m pip install pandas numpy requests"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"⚠️ Environment check failed: {e}"))

    # ---------- Run pricing ----------
    def run_pricing(self):
        if self.running:
            return
        self.running = True
        self.run_btn.configure(state="disabled")
        self.log(f"▶ {datetime.now():%H:%M:%S}  Running pricing engine, please wait (usually 10-30 seconds)...")

        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.Popen(
                [sys.executable, RMS_SCRIPT],
                cwd=APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env)
        except Exception as e:
            self.log(f"❌ Failed to start pricing engine: {e}")
            self.running = False
            self.run_btn.configure(state="normal")
            return

        def reader():
            for line in proc.stdout:
                self.root.after(0, self.log, line.rstrip())
            code = proc.wait()
            self.root.after(0, lambda: self.on_run_finished(code))

        threading.Thread(target=reader, daemon=True).start()

    def on_run_finished(self, code):
        self.running = False
        self.run_btn.configure(state="normal")
        if code == 0:
            self.log("✅ Pricing finished, loading results...")
            self.load_results()
        else:
            self.log("❌ Pricing engine failed. Check the log above or contact your system administrator.")

    # ---------- Load / display results ----------
    def load_results(self):
        try:
            records = load_latest_results()
        except Exception as e:
            messagebox.showerror("Load Failed", f"Error reading result files:\n{e}")
            return
        if not records:
            messagebox.showwarning("No Results",
                                   "No pricing result files found.\nPlease click \"Run Pricing Now\" first.")
            return

        self.records = records
        types = ["All room types"] + sorted({r["Room_Type"] for r in records})
        self.type_cb.configure(values=types)
        self.type_var.set("All room types")
        self.populate_table()
        self.last_run_lbl.configure(
            text=f"Data generated: {datetime.now():%Y-%m-%d %H:%M}")
        self.log(f"✅ Loaded {len(records)} rate recommendations. Click any row to see why it was priced this way.")

    def filtered_records(self):
        rng = self.range_var.get()
        limit = {"Next 7 days": 7, "Next 14 days": 14, "Next 30 days": 30}.get(rng, 999)
        out = []
        for r in self.records:
            d = r["Days_to_Checkin"]
            if isinstance(d, int) and d >= limit:
                continue
            if self.type_var.get() != "All room types" and r["Room_Type"] != self.type_var.get():
                continue
            out.append(r)
        return out

    def populate_table(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.filtered_records():
            tag = {"Peak Demand": "Peak", "High Demand": "High",
                   "Low Demand": "Low"}.get(r["Demand"], "")
            self.tree.insert("", "end", values=(
                r["Stay_Date"], r["DOW"], r["Room_Type"], r["Final_ADR"],
                r["Change"], r["Demand"], r["Action"], r["Occ"],
                r["Confidence"], r["Reason"]), tags=(tag,))

    # ---------- Row click -> pricing explanation ----------
    def on_row_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        r = self.records[self.tree.index(sel[0])] if self.records else None
        if r is None:
            return
        self.show_detail(r)

    def set_factor(self, idx, text):
        box = self.factor_vars[idx]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def show_detail(self, r):
        # 1) Headline conclusion
        pct = parse_change_pct(r["Change"])
        if pct is None:
            direction = "held at base rate"
        elif pct >= 25:
            direction = f"raised sharply by {pct:+.1f}%"
        elif pct >= 10:
            direction = f"raised by {pct:+.1f}%"
        elif pct > -10:
            direction = f"roughly flat ({pct:+.1f}%)"
        else:
            direction = f"lowered by {pct:+.1f}%"
        self.summary_lbl.configure(
            text=f"{r['Stay_Date']} ({r['DOW']}) {r['Room_Type']}: recommended rate ${r['Final_ADR']}, {direction}. "
                 f"Key driver: {r['Reason']}.",
            foreground="#c0392b" if pct is not None and pct >= 10 else "#1a6fb5")

        # 2) Base vs recommended comparison bars
        self.canvas.delete("all")
        try:
            base = float(r["Base_ADR"])
            final = float(r["Final_ADR"])
        except (TypeError, ValueError):
            base = final = None
        if base and final:
            W, y = 1000, 12
            hi = max(base, final) * 1.15
            scale = W / hi
            # Base rate bar (grey)
            self.canvas.create_rectangle(10, y, 10 + base * scale, y + 16,
                                         fill="#b0bec5", outline="")
            self.canvas.create_text(10 + base * scale + 8, y + 8, anchor="w",
                                    text=f"Base rate ${base:.0f}", font=("Segoe UI", 9),
                                    fill="#555555")
            # Recommended rate bar (red if higher, green if lower)
            color = "#e74c3c" if final >= base else "#27ae60"
            self.canvas.create_rectangle(10, y + 28, 10 + final * scale, y + 44,
                                         fill=color, outline="")
            self.canvas.create_text(10 + final * scale + 8, y + 36, anchor="w",
                                    text=f"Recommended ${final:.0f}", font=("Segoe UI", 9, "bold"),
                                    fill=color)

        # 3) Factor cards
        event = r["Event"]
        self.set_factor(0, "No special event" if event in ("None", "") else
                        f"{event}\n→ Event demand uplift applied")

        occ, pace = r["Occ"], r["Pace_Ratio"]
        supply = f"Current occupancy {occ}"
        if pace is not None:
            if pace > 1.2:
                supply += f"\nBooking pace {(pace - 1) * 100:.0f}% faster than historical → hot, raise rate"
            elif pace < 0.8:
                supply += f"\nBooking pace {(1 - pace) * 100:.0f}% slower than historical → quiet, consider discount"
            else:
                supply += "\nBooking pace in line with history → hold rate"
        self.set_factor(1, supply)

        ahead = r["Days_to_Checkin"]
        self.set_factor(2,
                        f"{ahead} days until check-in" if isinstance(ahead, int) else "Lead time unknown")

        try:
            comp = float(r["Competitor_ADR"])
            base_v = float(r["Base_ADR"])
            diff = comp - base_v
            if diff > 0:
                comp_txt = (f"Competitor avg ${comp:.0f}\n"
                            f"${diff:.0f} above our base → room to raise")
            else:
                comp_txt = (f"Competitor avg ${comp:.0f}\n"
                            f"${abs(diff):.0f} below our base → stay competitive")
        except (TypeError, ValueError):
            comp_txt = "No competitor data"
        self.set_factor(3, comp_txt)

        self.set_factor(4, f"${r['RevPAR']}" if r["RevPAR"] else "N/A")

        # 4) Confidence note
        try:
            conf = int(float(r["Confidence"]))
            self.conf_lbl.configure(
                text=f"System confidence for this recommendation: {conf}/100"
                     + (" (strong data basis - safe to apply)" if conf >= 70 else
                        " (moderate data basis - use your judgement)"))
        except (TypeError, ValueError):
            self.conf_lbl.configure(text="")


def main():
    root = tk.Tk()
    app = RMSApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
