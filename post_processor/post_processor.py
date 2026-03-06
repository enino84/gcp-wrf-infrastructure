"""
post_processor.py  —  gcp-wrf-infrastructure
WRF post-processor for Colombia domain.

Products
────────
Maps (3×1):        accumulated rain · max T2 · wind10m
City time series:  one figure per variable (6), bilinear interp, hora Colombia on X
Region time series: one figure per variable (6)
Boxplots:          T2 daily cycle per region (cities as boxes)
Radar charts:      climate fingerprint per region
Rain probability:  bar chart per city · per region · per department
Animations (5):    T2 · wind · rain_hr · RH · CAPE
HTML report:       tabbed, embedded, Learn-DA branding + www.learn-da.com
"""

import argparse, base64, shutil, sys
from glob import glob
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.interpolate import RegularGridInterpolator

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--input",   required=True)
parser.add_argument("--output",  required=True)
parser.add_argument("--context", default="WRF Simulation")
parser.add_argument("--logo",    default="/postprocess/logo.png")
args = parser.parse_args()

INPUT_DIR  = Path(args.input)
OUTPUT_DIR = Path(args.output)
CONTEXT    = args.context
LOGO_PATH  = Path(args.logo)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RAIN_THRESHOLDS = [0.1, 1.0, 5.0, 10.0]   # mm/h ranges: llovizna, leve, moderada, fuerte
RAIN_THRESHOLD  = 1.0                      # default for dept/region charts

# ─────────────────────────────────────────────
# CITIES & REGIONS
# ─────────────────────────────────────────────
CITIES = {
    "Barranquilla": {"lat":10.96,"lon":-74.80,"region":"Caribe",    "dept":"Atlántico"},
    "Cartagena":    {"lat":10.39,"lon":-75.51,"region":"Caribe",    "dept":"Bolívar"},
    "Santa Marta":  {"lat":11.24,"lon":-74.20,"region":"Caribe",    "dept":"Magdalena"},
    "Riohacha":     {"lat":11.54,"lon":-72.91,"region":"Caribe",    "dept":"La Guajira"},
    "Valledupar":   {"lat":10.48,"lon":-73.25,"region":"Caribe",    "dept":"Cesar"},
    "Bogotá":       {"lat": 4.71,"lon":-74.07,"region":"Andina",    "dept":"Cundinamarca"},
    "Medellín":     {"lat": 6.25,"lon":-75.56,"region":"Andina",    "dept":"Antioquia"},
    "Manizales":    {"lat": 5.07,"lon":-75.52,"region":"Andina",    "dept":"Caldas"},
    "Pereira":      {"lat": 4.81,"lon":-75.69,"region":"Andina",    "dept":"Risaralda"},
    "Bucaramanga":  {"lat": 7.13,"lon":-73.13,"region":"Andina",    "dept":"Santander"},
    "Cali":         {"lat": 3.44,"lon":-76.52,"region":"Pacífico",  "dept":"Valle del Cauca"},
    "Buenaventura": {"lat": 3.88,"lon":-77.02,"region":"Pacífico",  "dept":"Valle del Cauca"},
    "Quibdó":       {"lat": 5.69,"lon":-76.66,"region":"Pacífico",  "dept":"Chocó"},
    "Tumaco":       {"lat": 1.80,"lon":-78.76,"region":"Pacífico",  "dept":"Nariño"},
    "Villavicencio":{"lat": 4.14,"lon":-73.63,"region":"Orinoquía","dept":"Meta"},
    "Yopal":        {"lat": 5.34,"lon":-72.40,"region":"Orinoquía","dept":"Casanare"},
    "Florencia":    {"lat": 1.61,"lon":-75.61,"region":"Amazonía",  "dept":"Caquetá"},
    "Leticia":      {"lat":-4.21,"lon":-69.94,"region":"Amazonía",  "dept":"Amazonas"},
}

REGIONS = ["Caribe","Andina","Pacífico","Orinoquía","Amazonía"]
REGION_COLORS = {"Caribe":"#00d4ff","Andina":"#ff6b35","Pacífico":"#7fff7f",
                 "Orinoquía":"#ffcc00","Amazonía":"#cc88ff"}
_rpal = {
    "Caribe":    ["#00d4ff","#0099cc","#006699","#003366","#00e5ff"],
    "Andina":    ["#ff6b35","#ff9966","#ffcc99","#cc4400","#ff3300"],
    "Pacífico":  ["#7fff7f","#44cc44","#228822","#99ff99"],
    "Orinoquía": ["#ffcc00","#ffaa00"],
    "Amazonía":  ["#cc88ff","#9944ff"],
}
_ridx = {r:0 for r in REGIONS}
CITY_COLORS = {}
for city, info in CITIES.items():
    r = info["region"]
    CITY_COLORS[city] = _rpal[r][_ridx[r] % len(_rpal[r])]
    _ridx[r] += 1

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
files_orig = sorted(glob(str(INPUT_DIR/"wrfout_d01_*")))
if not files_orig:
    print(f"ERROR: no wrfout_d01_* in {INPUT_DIR}"); sys.exit(1)

def open_one(p):
    return xr.open_dataset(p, engine="netcdf4", decode_times=False)

def safe_copy(src_files, out_dir):
    tmp = out_dir/"tmp_nc"; tmp.mkdir(parents=True, exist_ok=True)
    dst = []
    for s in src_files:
        p = Path(s); safe = p.name.replace(":","_")
        d = tmp/safe
        if not d.exists() or d.stat().st_size != p.stat().st_size:
            shutil.copy2(p, d)
        dst.append(str(d))
    return dst

print(f"Found {len(files_orig)} wrfout files...")
probe = []
for f in files_orig:
    try:
        d = open_one(f); nt = int(d.sizes.get("Time",0)); d.close()
        probe.append((f,nt))
    except:
        probe.append((f,-1))

kept = [f for f,nt in probe if nt>=2] or [f for f,nt in probe if nt>=1]
files_to_open = safe_copy(kept, OUTPUT_DIR)
ds = xr.concat([open_one(f) for f in files_to_open], dim="Time")

lats_g = ds["XLAT"].isel(Time=0).values
lons_g = ds["XLONG"].isel(Time=0).values

raw_times = ["".join(t.astype(str)) for t in ds["Times"].values]
times_utc = pd.to_datetime(raw_times, format="%Y-%m-%d_%H:%M:%S", errors="coerce")
good = ~times_utc.isna()
if not good.all():
    ds = ds.isel(Time=np.where(good.values)[0])
    raw_times = ["".join(t.astype(str)) for t in ds["Times"].values]
    times_utc = pd.to_datetime(raw_times, format="%Y-%m-%d_%H:%M:%S", errors="raise")

times_col  = times_utc + pd.Timedelta(hours=-5)
nframes    = len(times_col)
dx_km      = float(ds.attrs.get("DX",0))/1000
date_start_col = times_col[0].strftime("%Y-%m-%d %H:%M hora Colombia")
date_end_col   = times_col[-1].strftime("%Y-%m-%d %H:%M hora Colombia")
hours_col  = [t.strftime("%H:%M") for t in times_col]
hours_of_day = [t.hour for t in times_col]
t_axis     = np.arange(nframes)

print(f"{dx_km:.0f} km | {date_start_col} → {date_end_col} | {nframes} frames")

# ─────────────────────────────────────────────
# BILINEAR INTERPOLATION
# ─────────────────────────────────────────────
ny, nx = lats_g.shape

def bilinear_extract(field2d, lat, lon):
    lat_1d = lats_g[:, nx//2]
    lon_1d = lons_g[ny//2, :]
    interp = RegularGridInterpolator(
        (lat_1d, lon_1d), field2d,
        method="linear", bounds_error=False, fill_value=None)
    return float(interp([[lat, lon]])[0])

def extract_city_ts(var_3d, city):
    lat = CITIES[city]["lat"]; lon = CITIES[city]["lon"]
    return np.array([bilinear_extract(var_3d[t], lat, lon) for t in range(nframes)])

# ─────────────────────────────────────────────
# EXTRACT VARIABLES
# ─────────────────────────────────────────────
print("\nExtracting variables...")
T2_all   = ds["T2"].values - 273.15
U10_all  = ds["U10"].values
V10_all  = ds["V10"].values
WS10_all = np.sqrt(U10_all**2 + V10_all**2)
RAIN_all = ds["RAINC"].values + ds["RAINNC"].values
RAIN_HR  = np.maximum(0, np.diff(RAIN_all, axis=0, prepend=RAIN_all[[0]]))
Q2_all   = ds["Q2"].values * 1000
PSFC_all = ds["PSFC"].values / 100
SW_all   = ds["SWDOWN"].values if "SWDOWN" in ds else np.zeros_like(T2_all)

def rh_approx(q, t2c, psfc):
    T  = t2c + 273.15
    es = 6.112 * np.exp(17.67*(T-273.15)/(T-29.65))
    e  = (q/1000) * psfc / (0.622 + q/1000)
    return np.clip(e/es*100, 0, 100)

RH_all   = rh_approx(Q2_all, T2_all, PSFC_all)
CAPE_all = ds["CAPE"].values if "CAPE" in ds else np.zeros_like(T2_all)

# Dewpoint from Q2 and PSFC
def dewpoint(q_gkg, psfc_hpa):
    q  = q_gkg / 1000
    e  = q * psfc_hpa / (0.622 + q)
    td = (243.5 * np.log(e/6.112)) / (17.67 - np.log(e/6.112))
    return td
TD_all = dewpoint(Q2_all, PSFC_all)

print("Extracting city time series (bilinear interpolation)...")
city_data = {}
for city in CITIES:
    city_data[city] = {
        "t2":     extract_city_ts(T2_all,   city),
        "ws10":   extract_city_ts(WS10_all, city),
        "rain_hr":extract_city_ts(RAIN_HR,  city),
        "q2":     extract_city_ts(Q2_all,   city),
        "psfc":   extract_city_ts(PSFC_all, city),
        "swdown": extract_city_ts(SW_all,   city),
        "rh":     extract_city_ts(RH_all,   city),
        "cape":   extract_city_ts(CAPE_all, city),
        "td":     extract_city_ts(TD_all,   city),
        "region": CITIES[city]["region"],
        "dept":   CITIES[city]["dept"],
    }
    d = city_data[city]
    print(f"  {city}: T2={d['t2'].mean():.1f}°C  WS={d['ws10'].mean():.1f}m/s  RH={d['rh'].mean():.0f}%")

region_data = {}
for reg in REGIONS:
    members = [c for c,d in city_data.items() if d["region"]==reg]
    if not members: continue
    region_data[reg] = {
        v: np.mean([city_data[c][v] for c in members], axis=0)
        for v in ["t2","ws10","rain_hr","q2","psfc","swdown","rh","cape","td"]
    }

# ─────────────────────────────────────────────
# STYLE
# ─────────────────────────────────────────────
DARK="#07090f"; CARD="#111827"; BORDER="#1a2540"
TEXT="#e8f4f8"; MUTED="#5a7a94"; ACCENT="#00d4ff"

plt.rcParams.update({
    "figure.facecolor":DARK,"axes.facecolor":CARD,"axes.edgecolor":BORDER,
    "axes.labelcolor":TEXT,"xtick.color":MUTED,"ytick.color":MUTED,
    "text.color":TEXT,"grid.color":BORDER,"grid.alpha":0.4,
})

LOGO_B64 = ""
if LOGO_PATH.exists():
    LOGO_B64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()

generated = []
proj = ccrs.PlateCarree()

def add_logo(fig, y=0.07, h=0.055):
    if LOGO_PATH.exists():
        from PIL import Image as PILImage
        try:
            logo = PILImage.open(LOGO_PATH)
            wf, hf = fig.get_size_inches()
            aspect = logo.width/logo.height
            w = h * aspect * hf/wf
            ax = fig.add_axes([0.5-w/2, y, w, h])
            ax.imshow(np.array(logo)); ax.axis("off")
        except: pass
    fig.text(0.5, y-0.018, "www.learn-da.com", ha="center", va="top",
             fontsize=7, color=MUTED, fontstyle="italic")

def save_fig(fig, name):
    p = OUTPUT_DIR/name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close(fig); print(f"  → {name}"); return name

def styled_ax(ax):
    ax.set_facecolor(CARD)
    ax.grid(True, alpha=0.3, linewidth=0.5)
    ax.tick_params(colors=MUTED, labelsize=7)
    for sp in ax.spines.values(): sp.set_edgecolor(BORDER)

def set_time_xticks(ax, max_ticks=10):
    """Smart X ticks: show HH:MM in Colombia time, add date label when day changes."""
    step = max(1, nframes // max_ticks)
    tick_pos = t_axis[::step]
    labels = []
    prev_day = None
    for i in tick_pos:
        t = times_col[i]
        day_str = t.strftime("%d %b")
        if prev_day is None or day_str != prev_day:
            labels.append(t.strftime("%H:%M\n") + day_str)
            prev_day = day_str
        else:
            labels.append(t.strftime("%H:%M"))
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(labels, rotation=0, ha="center", fontsize=6.5, color=MUTED)

def make_map():
    fig = plt.figure(figsize=(9,9), facecolor=DARK)
    ax  = plt.axes(projection=proj, facecolor=DARK)
    ax.add_feature(cfeature.OCEAN,     facecolor="#0d1b2a", zorder=0)
    ax.add_feature(cfeature.LAND,      facecolor="#0f1f14", zorder=1)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.9, edgecolor="#2a5a3a", zorder=2)
    ax.add_feature(cfeature.BORDERS,   linewidth=0.6, edgecolor="#1e3a2a", zorder=2)
    ax.add_feature(cfeature.RIVERS,    linewidth=0.4, edgecolor="#0d2a3a", zorder=2)
    return fig, ax

def city_markers(ax):
    for city, info in CITIES.items():
        ax.plot(info["lon"], info["lat"], "o",
                color=CITY_COLORS[city], markersize=4, transform=proj, zorder=10)
        ax.text(info["lon"]+0.25, info["lat"], city, fontsize=6,
                color=CITY_COLORS[city], transform=proj, zorder=11,
                path_effects=[pe.withStroke(linewidth=2, foreground=DARK)])

VAR_CFG = [
    ("t2",      "Temperatura 2m (°C)"),
    ("ws10",    "Viento 10m (m/s)"),
    ("rain_hr", "Precipitación horaria (mm/h)"),
    ("q2",      "Humedad específica (g/kg)"),
    ("psfc",    "Presión superficial (hPa)"),
    ("swdown",  "Radiación solar (W/m²)"),
]

VAR_DESC = {
    "t2":      "Temperatura del aire a 2 m. Extraída con interpolación bilineal al punto de cada ciudad.",
    "ws10":    "Rapidez del viento a 10 m (magnitud del vector horizontal U10, V10).",
    "rain_hr": f"Precipitación horaria acumulada. Umbral de lluvia: {RAIN_THRESHOLD} mm/h.",
    "q2":      "Humedad específica a 2 m en g/kg (gramos de vapor por kg de aire).",
    "psfc":    "Presión atmosférica en la superficie en hPa.",
    "swdown":  "Radiación solar de onda corta descendente en W/m².",
    "rh":      "Humedad relativa calculada a partir de Q2, T2 y presión superficial.",
    "cape":    "Energía potencial convectiva disponible (CAPE) en J/kg — indicador de convección severa.",
}

sk = max(2, lats_g.shape[0]//12)   # quiver skip

# ─── 1. MAP RAIN ───────────────────────────────────────────
print("\n[1/14] Rain map...")
rain_acc = RAIN_all[-1]-RAIN_all[0] if nframes>=2 else np.zeros_like(lats_g)
fig, ax = make_map()
cs = ax.contourf(lons_g, lats_g, rain_acc, levels=np.arange(0,205,5),
                 cmap="YlGnBu", transform=proj, extend="max")
city_markers(ax)
cbar = plt.colorbar(cs, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
cbar.set_label("Precipitación acumulada (mm)", color=TEXT, fontsize=9)
cbar.ax.tick_params(colors=MUTED, labelsize=8)
fig.text(0.5,0.97,"Precipitación Acumulada",ha="center",fontsize=14,fontweight="bold",color=TEXT)
fig.text(0.5,0.945,f"{date_start_col} → {date_end_col}  |  {dx_km:.0f} km  |  {CONTEXT}",ha="center",fontsize=8,color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"rain_accumulated.png"),
    "title":"Precipitación Acumulada","tab":"maps",
    "desc":"Precipitación total acumulada durante la simulación (RAINC + RAINNC). Incluye lluvia convectiva y estratiforme."})

# ─── 2. MAP T2 MAX ──────────────────────────────────────────
print("[2/14] T2 max map...")
fig, ax = make_map()
cs = ax.contourf(lons_g, lats_g, T2_all.max(axis=0), levels=np.arange(15,42,1),
                 cmap="RdYlBu_r", transform=proj, extend="both")
city_markers(ax)
cbar = plt.colorbar(cs, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
cbar.set_label("T2 máxima (°C)", color=TEXT, fontsize=9)
cbar.ax.tick_params(colors=MUTED, labelsize=8)
fig.text(0.5,0.97,"Temperatura Máxima 2m",ha="center",fontsize=14,fontweight="bold",color=TEXT)
fig.text(0.5,0.945,f"{date_start_col} → {date_end_col}  |  {dx_km:.0f} km  |  {CONTEXT}",ha="center",fontsize=8,color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"t2_max.png"),
    "title":"Temperatura Máxima 2m","tab":"maps",
    "desc":"Temperatura máxima del aire a 2 m durante todo el período simulado."})

# ─── 3. MAP WIND ────────────────────────────────────────────
print("[3/14] Wind map...")
fig, ax = make_map()
cs = ax.contourf(lons_g, lats_g, WS10_all[-1], levels=np.arange(0,22,1),
                 cmap="plasma", transform=proj, extend="max")
ax.quiver(lons_g[::sk,::sk], lats_g[::sk,::sk],
          U10_all[-1][::sk,::sk], V10_all[-1][::sk,::sk],
          transform=proj, scale=400, width=0.003, color="white", alpha=0.7)
city_markers(ax)
cbar = plt.colorbar(cs, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
cbar.set_label("Viento 10m (m/s)", color=TEXT, fontsize=9)
cbar.ax.tick_params(colors=MUTED, labelsize=8)
ts_lbl = times_col[-1].strftime("%Y-%m-%d %H:%M hora Colombia") if nframes else ""
fig.text(0.5,0.97,"Viento 10m",ha="center",fontsize=14,fontweight="bold",color=TEXT)
fig.text(0.5,0.945,f"{ts_lbl}  |  {dx_km:.0f} km",ha="center",fontsize=8,color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"wind10m.png"),
    "title":"Viento 10m (último paso)","tab":"maps",
    "desc":"Rapidez y dirección del viento a 10 m en el último paso de tiempo. Las flechas muestran la dirección."})

# ─── 4-9. CITY TIME SERIES (one per variable) ────────────────
print("[4-9/14] City time series...")
for var, ylabel in VAR_CFG:
    fig, ax = plt.subplots(figsize=(14,5), facecolor=DARK)
    fig.subplots_adjust(top=0.82, bottom=0.22, left=0.07, right=0.82)
    styled_ax(ax)
    ax.set_ylabel(ylabel, fontsize=9, color=TEXT)
    for city, data in city_data.items():
        ax.plot(t_axis, data[var], color=CITY_COLORS[city],
                linewidth=1.3, alpha=0.88, label=city)
    set_time_xticks(ax)
    ax.set_xlabel("Hora Colombia (UTC-5)", fontsize=8, color=MUTED)
    handles = [Line2D([0],[0],color=CITY_COLORS[c],linewidth=2,label=c) for c in city_data]
    fig.legend(handles=handles, loc="center right", bbox_to_anchor=(1.0,0.5),
               frameon=True, facecolor=CARD, edgecolor=BORDER,
               labelcolor=TEXT, fontsize=7, title="Ciudad", title_fontsize=7.5)
    fig.text(0.5,0.95,f"Ciudades — {ylabel}",ha="center",fontsize=13,fontweight="bold",color=TEXT)
    fig.text(0.5,0.927,f"{CONTEXT}  |  {date_start_col} → {date_end_col}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.03, h=0.045)
    generated.append({"type":"image","file":save_fig(fig,f"city_ts_{var}.png"),
        "title":f"Ciudades — {ylabel}","tab":"cities","desc":VAR_DESC.get(var,"")})

# ─── 10. REGION TIME SERIES (one per variable) ───────────────
print("[10/14] Region time series...")
for var, ylabel in VAR_CFG:
    fig, ax = plt.subplots(figsize=(14,5), facecolor=DARK)
    fig.subplots_adjust(top=0.82, bottom=0.22, left=0.07, right=0.84)
    styled_ax(ax)
    ax.set_ylabel(ylabel, fontsize=9, color=TEXT)
    for reg, data in region_data.items():
        c = REGION_COLORS[reg]
        ax.plot(t_axis, data[var], color=c, linewidth=2.2, alpha=0.92, label=reg)
        ax.fill_between(t_axis, data[var], alpha=0.07, color=c)
    set_time_xticks(ax)
    ax.set_xlabel("Hora Colombia (UTC-5)", fontsize=8, color=MUTED)
    handles = [Line2D([0],[0],color=REGION_COLORS[r],linewidth=2.5,label=r) for r in region_data]
    fig.legend(handles=handles, loc="center right", bbox_to_anchor=(1.0,0.5),
               frameon=True, facecolor=CARD, edgecolor=BORDER,
               labelcolor=TEXT, fontsize=8, title="Región", title_fontsize=8.5)
    fig.text(0.5,0.95,f"Regiones — {ylabel}",ha="center",fontsize=13,fontweight="bold",color=TEXT)
    fig.text(0.5,0.927,f"{CONTEXT}  |  {date_start_col} → {date_end_col}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.03, h=0.045)
    generated.append({"type":"image","file":save_fig(fig,f"region_ts_{var}.png"),
        "title":f"Regiones — {ylabel}","tab":"regions","desc":VAR_DESC.get(var,"")})

# ─── 11. BOXPLOTS ────────────────────────────────────────────
print("[11/14] Boxplots...")
for reg in REGIONS:
    cities_reg = [c for c,d in city_data.items() if d["region"]==reg]
    if not cities_reg: continue
    n = len(cities_reg)
    fig, axes = plt.subplots(1, n, figsize=(max(10,n*3.5),6), facecolor=DARK)
    if n==1: axes=[axes]
    fig.subplots_adjust(wspace=0.3, top=0.80, bottom=0.18, left=0.07, right=0.97)
    for ax, city in zip(axes, cities_reg):
        styled_ax(ax)
        color = CITY_COLORS[city]
        t2h = [[] for _ in range(24)]
        for i,h in enumerate(hours_of_day): t2h[h].append(city_data[city]["t2"][i])
        present = [h for h in range(24) if t2h[h]]
        ax.boxplot([t2h[h] for h in present], positions=present, widths=0.7,
                   patch_artist=True, showfliers=False,
                   medianprops=dict(color="white",linewidth=1.5),
                   whiskerprops=dict(color=MUTED,linewidth=1),
                   capprops=dict(color=MUTED,linewidth=1),
                   boxprops=dict(facecolor=color+"33",edgecolor=color,linewidth=1.2))
        ax.set_xlabel("Hora local", fontsize=8, color=MUTED)
        ax.set_ylabel("T2 (°C)", fontsize=8, color=TEXT)
        ax.set_title(city, fontsize=9, color=color, fontweight="bold")
        if present: ax.set_xlim(min(present)-1, max(present)+1)
    rc = REGION_COLORS[reg]
    fig.text(0.5,0.95,f"Ciclo Diario T2 — {reg}",ha="center",fontsize=13,fontweight="bold",color=rc)
    fig.text(0.5,0.922,f"Distribución por hora local  |  {CONTEXT}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.01, h=0.045)
    sr = reg.replace("í","i").replace("ó","o").replace(" ","_").lower()
    generated.append({"type":"image","file":save_fig(fig,f"boxplot_{sr}.png"),
        "title":f"Ciclo Diario T2 — {reg}","tab":"regions",
        "desc":f"Distribución de T2 por hora del día para las ciudades de la región {reg}. Mediana, Q1–Q3 y bigotes."})

# ─── 11b. RADAR CHARTS — climate fingerprint per region ──────
print("[11b] Radar charts...")

labels_r = ["Temperatura", "Viento", "Lluvia", "Humedad", "Radiación"]
N_r = len(labels_r)
angles_r = np.linspace(0, 2*np.pi, N_r, endpoint=False).tolist()
angles_r += angles_r[:1]

city_vals_raw = {}
for city, data in city_data.items():
    city_vals_raw[city] = np.array([
        data["t2"].mean(), data["ws10"].mean(),
        data["rain_hr"].sum(), data["q2"].mean(), data["swdown"].mean()
    ])
all_raw = np.array(list(city_vals_raw.values()))

def norm_col(col):
    mn, mx = col.min(), col.max()
    return (col - mn)/(mx - mn) if mx > mn else np.zeros_like(col)

norm_matrix = np.column_stack([norm_col(all_raw[:,j]) for j in range(N_r)])
city_list_r  = list(city_vals_raw.keys())

for reg in REGIONS:
    c_in_reg = [c for c in city_list_r if city_data[c]["region"]==reg]
    if not c_in_reg: continue
    nc = len(c_in_reg)
    cols = min(nc, 3); rows = (nc + cols - 1) // cols
    fig = plt.figure(figsize=(cols*4.5, rows*4.5+1.4), facecolor=DARK)
    fig.subplots_adjust(top=0.84, bottom=0.10, hspace=0.5, wspace=0.4)
    for idx, city in enumerate(c_in_reg):
        ax = fig.add_subplot(rows, cols, idx+1, polar=True, facecolor=CARD)
        ci = city_list_r.index(city)
        vals = norm_matrix[ci].tolist() + [norm_matrix[ci][0]]
        color = CITY_COLORS[city]
        ax.plot(angles_r, vals, color=color, linewidth=2)
        ax.fill(angles_r, vals, color=color, alpha=0.2)
        ax.set_xticks(angles_r[:-1])
        ax.set_xticklabels(labels_r, fontsize=7, color=MUTED)
        ax.set_yticks([0.25,0.5,0.75,1.0])
        ax.set_yticklabels(["","","",""], fontsize=0)
        ax.set_ylim(0,1)
        ax.spines["polar"].set_edgecolor(BORDER)
        ax.grid(color=BORDER, linewidth=0.5)
        ax.set_title(city, fontsize=9, color=color, fontweight="bold", pad=14)
    rc = REGION_COLORS[reg]
    fig.text(0.5,0.95,f"Perfil Climático — {reg}",ha="center",fontsize=13,fontweight="bold",color=rc)
    fig.text(0.5,0.925,f"Variables normalizadas  |  {CONTEXT}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.01, h=0.045)
    sr = reg.replace("í","i").replace("ó","o").replace(" ","_").lower()
    generated.append({"type":"image","file":save_fig(fig,f"radar_{sr}.png"),
        "title":f"Perfil Climático — {reg}","tab":"regions",
        "desc":f"Gráfico de radar para las ciudades de {reg}. Cada eje muestra una variable normalizada de 0 a 1 respecto al resto del país: temperatura media, velocidad del viento, lluvia total, humedad y radiación solar."})

# ─── 12. RAIN PROBABILITY (multi-range) ─────────────────────
print("[12/14] Rain probability (multi-range)...")

RANGE_LABELS  = ["Llovizna\n≥0.1 mm/h", "Leve\n≥1 mm/h", "Moderada\n≥5 mm/h", "Fuerte\n≥10 mm/h"]
RANGE_COLORS  = ["#00aaff", "#00dd88", "#ffcc00", "#ff4444"]

def rain_probs_multi(rain_hr_ts):
    return [float(np.mean(rain_hr_ts >= thr)*100) for thr in RAIN_THRESHOLDS]

# 12a — city stacked grouped bar
cities_list = list(city_data.keys())
n_cities = len(cities_list)
n_ranges = len(RAIN_THRESHOLDS)
x = np.arange(n_cities)
width = 0.18

fig, ax = plt.subplots(figsize=(16, 7), facecolor=DARK)
fig.subplots_adjust(top=0.82, bottom=0.22, left=0.06, right=0.97)
styled_ax(ax)
for ri, (thr, lbl, rc) in enumerate(zip(RAIN_THRESHOLDS, RANGE_LABELS, RANGE_COLORS)):
    probs = [float(np.mean(city_data[c]["rain_hr"] >= thr)*100) for c in cities_list]
    offset = (ri - n_ranges/2 + 0.5) * width
    bars = ax.bar(x + offset, probs, width, label=lbl.replace("\n"," "),
                  color=rc, alpha=0.85, edgecolor=BORDER, linewidth=0.4)
ax.set_xticks(x)
ax.set_xticklabels(cities_list, rotation=40, ha="right", fontsize=7.5, color=TEXT)
ax.set_ylabel("Probabilidad (%)", fontsize=9, color=TEXT)
ax.set_ylim(0, 105)
ax.legend(frameon=True, facecolor=CARD, edgecolor=BORDER, labelcolor=TEXT,
          fontsize=8, loc="upper right")
fig.text(0.5,0.95,"Probabilidad de Lluvia por Intensidad — Ciudades",
         ha="center",fontsize=13,fontweight="bold",color=TEXT)
fig.text(0.5,0.925,f"Fracción de horas por rango de intensidad  |  {CONTEXT}",
         ha="center",fontsize=8,color=MUTED)
add_logo(fig, y=0.01, h=0.045)
generated.append({"type":"image","file":save_fig(fig,"rain_prob_city.png"),
    "title":"Prob. de Lluvia por Intensidad — Ciudades","tab":"rain",
    "desc":"Porcentaje de horas de simulación con precipitación en cada rango de intensidad: llovizna (≥0.1), leve (≥1), moderada (≥5) y fuerte (≥10 mm/h)."})

# 12b — region grouped bar
regs_list = list(region_data.keys())
x2 = np.arange(len(regs_list))
fig, ax = plt.subplots(figsize=(11, 6), facecolor=DARK)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.08, right=0.97)
styled_ax(ax)
for ri, (thr, lbl, rc) in enumerate(zip(RAIN_THRESHOLDS, RANGE_LABELS, RANGE_COLORS)):
    probs = [float(np.mean(region_data[r]["rain_hr"] >= thr)*100) for r in regs_list]
    offset = (ri - n_ranges/2 + 0.5) * 0.18
    ax.bar(x2 + offset, probs, 0.18, label=lbl.replace("\n"," "),
           color=rc, alpha=0.85, edgecolor=BORDER, linewidth=0.4)
ax.set_xticks(x2)
ax.set_xticklabels(regs_list, fontsize=9, color=TEXT)
ax.set_ylabel("Probabilidad (%)", fontsize=9, color=TEXT)
ax.set_ylim(0, 105)
ax.legend(frameon=True, facecolor=CARD, edgecolor=BORDER, labelcolor=TEXT, fontsize=8)
fig.text(0.5,0.95,"Probabilidad de Lluvia por Intensidad — Regiones",
         ha="center",fontsize=13,fontweight="bold",color=TEXT)
fig.text(0.5,0.925,f"{CONTEXT}  |  {date_start_col} → {date_end_col}",ha="center",fontsize=8,color=MUTED)
add_logo(fig, y=0.01, h=0.05)
generated.append({"type":"image","file":save_fig(fig,"rain_prob_region.png"),
    "title":"Prob. de Lluvia por Intensidad — Regiones","tab":"rain",
    "desc":"Comparación regional de la probabilidad de lluvia por rango de intensidad."})

# 12c — department horizontal stacked bars
depts = {}
for city, d in city_data.items():
    dept = d["dept"]
    if dept not in depts: depts[dept] = {"rain_hr": d["rain_hr"], "region": d["region"]}
dept_region = {dept: v["region"] for dept,v in depts.items()}
# Sort by P(≥1mm/h)
depts_sorted = sorted(depts, key=lambda d: np.mean(depts[d]["rain_hr"]>=1.0), reverse=True)

fig, ax = plt.subplots(figsize=(12, max(5, len(depts_sorted)*0.65)), facecolor=DARK)
fig.subplots_adjust(top=0.88, bottom=0.08, left=0.28, right=0.88)
styled_ax(ax)
y_pos = np.arange(len(depts_sorted))
for ri, (thr, lbl, rc) in enumerate(zip(RAIN_THRESHOLDS, RANGE_LABELS, RANGE_COLORS)):
    probs = [float(np.mean(depts[d]["rain_hr"] >= thr)*100) for d in depts_sorted]
    offset = (ri - n_ranges/2 + 0.5) * 0.18
    ax.barh(y_pos + offset, probs, 0.18, label=lbl.replace("\n"," "),
            color=rc, alpha=0.85, edgecolor=BORDER, linewidth=0.4)
ax.set_yticks(y_pos)
ax.set_yticklabels(depts_sorted, fontsize=7.5, color=TEXT)
ax.set_xlabel("Probabilidad (%)", fontsize=9, color=TEXT)
ax.set_xlim(0, 115)
ax.legend(frameon=True, facecolor=CARD, edgecolor=BORDER, labelcolor=TEXT,
          fontsize=7.5, loc="lower right")
# Region color dots
for yi, dept in enumerate(depts_sorted):
    ax.plot(112, yi, "o", color=REGION_COLORS[dept_region[dept]], markersize=6, clip_on=False)
fig.text(0.5,0.95,"Probabilidad de Lluvia por Departamento",ha="center",fontsize=13,fontweight="bold",color=TEXT)
fig.text(0.5,0.928,f"Punto = región  |  {CONTEXT}",ha="center",fontsize=8,color=MUTED)
add_logo(fig, y=0.01, h=0.04)
generated.append({"type":"image","file":save_fig(fig,"rain_prob_dept.png"),
    "title":"Prob. de Lluvia — Departamentos","tab":"rain",
    "desc":"Probabilidad de lluvia por departamento para 4 rangos de intensidad. El punto de color indica la región natural de Colombia."})

# ─── 13. ANIMATIONS (5) ──────────────────────────────────────
print("[13/14] Animations (7)...")
ANIM_VARS = [
    ("t2",      T2_all,   np.arange(15,40,1),    "RdYlBu_r","Temperatura 2m (°C)"),
    ("wind",    WS10_all, np.arange(0,20.5,.5),  "plasma",   "Viento 10m (m/s)"),
    ("rain_hr", RAIN_HR,  np.arange(0,20,.5),    "YlGnBu",   "Precipitación horaria (mm/h)"),
    ("rh",      RH_all,   np.arange(40,101,2),   "BuPu",     "Humedad relativa (%)"),
    ("swdown",  SW_all,   np.arange(0,1001,25),  "hot",      "Radiación solar (W/m²)"),
    ("td",      TD_all,   np.arange(5,32,1),     "YlGn",     "Temperatura de punto de rocío (°C)"),
    ("cape",    CAPE_all, np.arange(0,3001,100), "YlOrRd",   "CAPE (J/kg)"),
]

if nframes >= 2:
    for vname, data3d, levels, cmap, label in ANIM_VARS:
        fig, ax = make_map()
        title_h = ax.set_title("", fontsize=11, color=TEXT, pad=8)
        state = {"art":[]}
        before = set(ax.get_children())
        cf0 = ax.contourf(lons_g, lats_g, data3d[0], levels=levels,
                          cmap=cmap, extend="both", transform=proj)
        if vname=="wind":
            ax.quiver(lons_g[::sk,::sk], lats_g[::sk,::sk],
                      U10_all[0][::sk,::sk], V10_all[0][::sk,::sk],
                      transform=proj, scale=400, width=0.003, color="white", alpha=0.6)
        state["art"] = list(set(ax.get_children())-before)
        cbar = plt.colorbar(cf0, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
        cbar.set_label(label, color=TEXT, fontsize=9)
        cbar.ax.tick_params(colors=MUTED, labelsize=8)
        city_markers(ax)
        add_logo(fig)

        # Capture loop variables
        _vname=vname; _data3d=data3d; _levels=levels; _cmap=cmap; _label=label
        _state=state; _title_h=title_h

        def make_upd(vn, d3, lv, cm, lbl, st, th):
            def upd(t):
                for a in st["art"]:
                    try: a.remove()
                    except: pass
                before_ = set(ax.get_children())
                ax.contourf(lons_g, lats_g, d3[t], levels=lv, cmap=cm, extend="both", transform=proj)
                if vn=="wind":
                    ax.quiver(lons_g[::sk,::sk], lats_g[::sk,::sk],
                              U10_all[t][::sk,::sk], V10_all[t][::sk,::sk],
                              transform=proj, scale=400, width=0.003, color="white", alpha=0.6)
                st["art"] = list(set(ax.get_children())-before_)
                ts = times_col[t].strftime("%Y-%m-%d %H:%M hora Colombia")
                th.set_text(f"{CONTEXT}  ·  {lbl}  ·  {ts}")
                return st["art"]
            return upd

        ani = animation.FuncAnimation(fig, make_upd(_vname,_data3d,_levels,_cmap,_label,_state,_title_h),
                                      frames=nframes, interval=350, blit=False)
        ext = "mp4" if shutil.which("ffmpeg") else "gif"
        afile = f"animation_{vname}.{ext}"
        ani.save(OUTPUT_DIR/afile, dpi=110, writer="ffmpeg" if ext=="mp4" else "pillow")
        plt.close(fig)
        print(f"  → {afile}")
        generated.append({"type":"animation","file":afile,
            "title":f"Animación — {label}","tab":"animations",
            "desc":VAR_DESC.get(vname,label)})

# ─── 14. HTML REPORT ─────────────────────────────────────────
print("[14/14] HTML report...")

def embed_img(fn):
    p = OUTPUT_DIR/fn
    if not p.exists(): return f'<p class="missing">Missing: {fn}</p>'
    b64 = base64.b64encode(p.read_bytes()).decode()
    ext = fn.split(".")[-1].lower()
    mime = {"png":"image/png","gif":"image/gif"}.get(ext,"image/png")
    return f'<img src="data:{mime};base64,{b64}" alt="{fn}" loading="lazy">'

def embed_video(fn):
    p = OUTPUT_DIR/fn
    if not p.exists(): return f'<p class="missing">Missing: {fn}</p>'
    b64 = base64.b64encode(p.read_bytes()).decode()
    return (f'<video controls loop autoplay muted playsinline>'
            f'<source src="data:video/mp4;base64,{b64}" type="video/mp4"></video>')

def card(item, full=False):
    fn=item["file"]; title=item["title"]; desc=item.get("desc","")
    media = embed_video(fn) if fn.endswith((".mp4",".gif")) else embed_img(fn)
    cls = "card card-full" if full else "card"
    desc_html = f'<p class="card-desc">{desc}</p>' if desc else ""
    return f'<div class="{cls}"><div class="card-title">{title}</div>{media}{desc_html}</div>'

logo_tag = (f'<img src="data:image/png;base64,{LOGO_B64}" alt="Learn-DA">'
            if LOGO_B64 else '<span class="logo-text">Learn-DA</span>')

TABS = [
    ("maps",       "🗺 Mapas"),
    ("cities",     "🏙 Ciudades"),
    ("regions",    "🌎 Regiones"),
    ("rain",       "🌧 Lluvia"),
    ("animations", "🎬 Animaciones"),
]

TAB_INTROS = {
    "maps": (
        "🗺 Mapas del Dominio",
        "Estos mapas muestran el estado de las principales variables meteorológicas sobre todo el dominio de simulación. "
        "La <strong>precipitación acumulada</strong> es la lluvia total que cayó durante todo el período. "
        "La <strong>temperatura máxima</strong> es el valor más alto que alcanzó el termómetro a 2 metros sobre el suelo en cada punto. "
        "El <strong>viento</strong> muestra la velocidad y dirección del viento a 10 metros, en el último momento de la simulación."
    ),
    "cities": (
        "🏙 Series de Tiempo por Ciudad",
        "Estas gráficas muestran cómo evolucionó cada variable a lo largo del tiempo en 18 ciudades colombianas. "
        "Los valores se extraen con interpolación bilineal — es decir, no se toma el punto de grilla más cercano sino que se interpola suavemente entre los puntos vecinos, "
        "lo que mejora la precisión especialmente en ciudades de montaña. "
        "El eje horizontal es la <strong>hora local de Colombia (UTC−5)</strong>. "
        "Cuando la simulación cruza la medianoche, aparece la fecha del nuevo día."
    ),
    "regions": (
        "🌎 Análisis por Región Natural",
        "Colombia se divide en cinco grandes regiones naturales con climas muy diferentes. "
        "Las series de tiempo muestran el promedio de las ciudades representativas de cada región. "
        "Los <strong>diagramas de caja</strong> (boxplots) muestran el ciclo diario de temperatura: la línea central es la mediana, "
        "la caja cubre el 50% central de los datos, y los bigotes muestran el rango general. "
        "Los <strong>gráficos de radar</strong> o 'perfil climático' comparan cada ciudad en cinco dimensiones normalizadas — "
        "una ciudad con área grande es relativamente más cálida, ventosa, lluviosa, húmeda o soleada que las demás."
    ),
    "rain": (
        "🌧 Probabilidad de Lluvia",
        "La probabilidad de lluvia se calcula como la fracción de horas de simulación en que la precipitación superó un umbral determinado. "
        "Se muestran cuatro intensidades: <strong>llovizna</strong> (≥0.1 mm/h, gotas finas), <strong>leve</strong> (≥1 mm/h, lluvia ligera), "
        "<strong>moderada</strong> (≥5 mm/h, lluvia regular) y <strong>fuerte</strong> (≥10 mm/h, aguacero). "
        "Un valor de 30% significa que en 3 de cada 10 horas simuladas llovió con esa intensidad. "
        "Nota: esta es la probabilidad que el modelo estimó para <em>este período específico</em>, no un promedio climático."
    ),
    "animations": (
        "🎬 Animaciones Temporales",
        "Estas animaciones muestran la evolución hora a hora de cada variable sobre todo el dominio. "
        "Son útiles para ver el ciclo diurno (calentamiento de día, enfriamiento de noche), "
        "el avance de sistemas de lluvia, y los cambios en humedad y viento. "
        "El título de cada cuadro indica la hora exacta en Colombia."
    ),
}

def tab_content(tab):
    items = [g for g in generated if g.get("tab")==tab]
    title, intro = TAB_INTROS.get(tab, ("",""))
    intro_html = (f'<div class="section-intro"><h2>{title}</h2><p>{intro}</p></div>' if intro else "")
    if tab=="maps":
        content = f'<div class="grid grid-maps">{"".join(card(i) for i in items)}</div>'
    else:
        content = "\n".join(card(i, full=True) for i in items)
    return intro_html + content

tabs_html = "\n".join(
    f'<button class="tab-btn{" active" if i==0 else ""}" onclick="switchTab(\'{t}\')" id="btn-{t}">{lbl}</button>'
    for i,(t,lbl) in enumerate(TABS))
panels_html = "\n".join(
    f'<div class="tab-panel{" active" if i==0 else ""}" id="panel-{t}">{tab_content(t)}</div>'
    for i,(t,_) in enumerate(TABS))

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WRF Report — {CONTEXT}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');
:root{{--bg:#07090f;--surface:#0d1117;--card:#111827;--border:#1a2540;--accent:#00d4ff;--text:#e8f4f8;--muted:#5a7a94;--mono:'Space Mono',monospace;--sans:'DM Sans',sans-serif;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:var(--sans);background:var(--bg);color:var(--text);min-height:100vh;}}
header{{background:linear-gradient(135deg,#050810,#0a1628,#060e1a);border-bottom:1px solid var(--border);padding:0 48px;height:78px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;}}
header .brand{{display:flex;align-items:center;gap:14px;}}
header .brand img{{height:42px;}}
header .brand .logo-text{{font-family:var(--mono);font-size:1.2rem;color:var(--accent);letter-spacing:2px;}}
header .title-block h1{{font-size:1.05rem;font-weight:600;color:var(--text);}}
header .title-block p{{font-size:.75rem;color:var(--muted);font-family:var(--mono);margin-top:2px;}}
.meta-bar{{background:#080b12;border-bottom:1px solid var(--border);padding:10px 48px;display:flex;gap:36px;overflow-x:auto;}}
.meta-item{{display:flex;flex-direction:column;gap:2px;white-space:nowrap;}}
.meta-item .label{{font-family:var(--mono);font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;}}
.meta-item .value{{font-family:var(--mono);font-size:.8rem;color:var(--accent);}}
.tab-bar{{background:var(--surface);border-bottom:1px solid var(--border);padding:0 48px;display:flex;gap:2px;overflow-x:auto;}}
.tab-btn{{background:none;border:none;border-bottom:3px solid transparent;padding:15px 22px;color:var(--muted);font-family:var(--sans);font-size:.86rem;font-weight:500;cursor:pointer;transition:all .2s;white-space:nowrap;}}
.tab-btn:hover{{color:var(--text);}}
.tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent);}}
.tab-panel{{display:none;padding:36px 48px;max-width:1440px;margin:0 auto;}}
.tab-panel.active{{display:block;}}
.grid{{display:grid;grid-template-columns:1fr;gap:22px;}}
.grid-maps{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;}}
@media(max-width:1100px){{.grid-maps{{grid-template-columns:1fr;}}}}
.section-intro{{background:#0a0f1e;border:1px solid var(--border);border-radius:12px;padding:22px 28px;margin-bottom:28px;}}
.section-intro h2{{font-size:1rem;font-weight:600;color:var(--accent);margin-bottom:8px;}}
.section-intro p{{font-size:.85rem;color:#8aabb8;line-height:1.65;}}
.section-intro strong{{color:var(--text);}}
.section-intro em{{color:#aaccdd;font-style:italic;}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;transition:border-color .2s,transform .2s;}}
.card:hover{{border-color:var(--accent);transform:translateY(-2px);}}
.card-full{{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:22px;}}
.card-title{{padding:10px 16px;font-size:.75rem;font-weight:600;color:var(--muted);font-family:var(--mono);text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--border);background:#0d1117;}}
.card-desc{{padding:10px 16px 14px;font-size:.78rem;color:var(--muted);line-height:1.55;border-top:1px solid var(--border);background:#090d16;}}
.card img,.card-full img,.card video,.card-full video{{width:100%;display:block;}}
footer{{border-top:1px solid var(--border);padding:36px 48px;display:flex;flex-direction:column;align-items:center;gap:10px;background:var(--surface);}}
footer .footer-logo img{{height:38px;opacity:.85;}}
footer .footer-logo .logo-text{{font-family:var(--mono);font-size:1rem;color:var(--accent);opacity:.85;}}
footer a.footer-url{{font-family:var(--mono);font-size:.85rem;color:var(--accent);text-decoration:none;opacity:.75;letter-spacing:1.5px;transition:opacity .2s;}}
footer a.footer-url:hover{{opacity:1;}}
footer .footer-note{{font-size:.72rem;color:var(--muted);text-align:center;max-width:620px;}}
.missing{{color:#ff4444;padding:16px;font-family:var(--mono);font-size:.8rem;}}
::-webkit-scrollbar{{width:5px;height:5px;}}
::-webkit-scrollbar-track{{background:var(--bg);}}
::-webkit-scrollbar-thumb{{background:var(--border);border-radius:3px;}}
</style>
</head>
<body>
<header>
  <div class="brand">{logo_tag}</div>
  <div class="title-block"><h1>WRF Simulation Report</h1><p>{CONTEXT.upper()}</p></div>
</header>
<div class="meta-bar">
  <div class="meta-item"><span class="label">Inicio</span><span class="value">{date_start_col}</span></div>
  <div class="meta-item"><span class="label">Fin</span><span class="value">{date_end_col}</span></div>
  <div class="meta-item"><span class="label">Resolución</span><span class="value">{dx_km:.0f} km</span></div>
  <div class="meta-item"><span class="label">Pasos</span><span class="value">{nframes}</span></div>
  <div class="meta-item"><span class="label">Productos</span><span class="value">{len(generated)}</span></div>
  <div class="meta-item"><span class="label">Ciudades</span><span class="value">{len(CITIES)}</span></div>
  <div class="meta-item"><span class="label">Umbral lluvia</span><span class="value">≥{RAIN_THRESHOLD} mm/h</span></div>
</div>
<div class="tab-bar">{tabs_html}</div>
{panels_html}
<footer>
  <div class="footer-logo">{logo_tag}</div>
  <a class="footer-url" href="https://www.learn-da.com" target="_blank">www.learn-da.com</a>
  <p class="footer-note">Generado por gcp-wrf-infrastructure · Salida del modelo WRF · Los resultados representan orientación del modelo, no verdad determinística.</p>
</footer>
<script>
function switchTab(id){{
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  document.getElementById('btn-'+id).classList.add('active');
}}
</script>
</body>
</html>"""

(OUTPUT_DIR/"report.html").write_text(html, encoding="utf-8")
print("  → report.html")
print(f"\n✓ {len(generated)} productos en {OUTPUT_DIR}")
