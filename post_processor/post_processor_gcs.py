"""
post_processor_gcs.py — gcp-wrf-infrastructure
WRF post-processor with GCS upload.

Usage
─────
python post_processor_gcs.py \
    --input   /data \
    --output  /output \
    --app     wrf-colombia-27km \
    --context "WRF Colombia 27km" \
    --gcs-bucket learn-da-data

GCS structure
─────────────
gs://{bucket}/
  apps/
    {app}/                         e.g. wrf-colombia-27km
      index/
        {run_id}.json              lightweight index entry
      runs/
        {run_id}/                  e.g. 2026-03-14T12:00:00Z
          meta.json
          timeseries.json
          images/
            rain_accumulated.png
            t2_max.png
            ...
          animations/
            animation_t2.mp4
            ...
"""

import argparse, base64, json, shutil, sys
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
from scipy.interpolate import RegularGridInterpolator

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser(description="WRF post-processor with GCS upload")
parser.add_argument("--input",       required=True,               help="Directory with wrfout_d01_* files")
parser.add_argument("--output",      required=True,               help="Local output directory")
parser.add_argument("--app",         default="wrf-colombia-27km", help="App ID (e.g. wrf-colombia-27km, wrf-caribe-9km)")
parser.add_argument("--context",     default="WRF Simulation",    help="Label for plot titles")
parser.add_argument("--logo",        default="/postprocess/logo.png")
parser.add_argument("--gcs-bucket",  default="learn-da-data",     help="GCS bucket name")
parser.add_argument("--no-upload",   action="store_true",         help="Skip GCS upload — local only")
parser.add_argument("--create-bucket", action="store_true",       help="Create bucket if it doesn't exist")
parser.add_argument("--gcs-location", default="US",               help="Bucket location if creating (default: US)")
args = parser.parse_args()

INPUT_DIR    = Path(args.input)
OUTPUT_DIR   = Path(args.output)
APP_ID       = args.app
CONTEXT      = args.context
LOGO_PATH    = Path(args.logo)
GCS_BUCKET   = args.gcs_bucket
DO_UPLOAD    = not args.no_upload
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RAIN_THRESHOLDS = [0.1, 1.0, 5.0, 10.0]
RAIN_THRESHOLD  = 1.0

# ─────────────────────────────────────────────
# GCS CLIENT
# ─────────────────────────────────────────────
gcs_client = None
gcs_bucket_obj = None

def init_gcs():
    global gcs_client, gcs_bucket_obj
    if not DO_UPLOAD:
        print("⚠ --no-upload set, skipping GCS")
        return
    try:
        from google.cloud import storage
        gcs_client = storage.Client()

        bucket = gcs_client.bucket(GCS_BUCKET)

        if not bucket.exists():
            if args.create_bucket:
                print(f"  Bucket gs://{GCS_BUCKET} not found — creating in {args.gcs_location}...")
                bucket = gcs_client.create_bucket(GCS_BUCKET, location=args.gcs_location)
                print(f"  ✓ Bucket created: gs://{GCS_BUCKET}")
            else:
                print(f"  ✗ Bucket gs://{GCS_BUCKET} does not exist.")
                print(f"    Create it manually:  gsutil mb -l US gs://{GCS_BUCKET}")
                print(f"    Or re-run with:      --create-bucket")
                sys.exit(1)

        gcs_bucket_obj = bucket
        print(f"✓ GCS connected → gs://{GCS_BUCKET}/apps/{APP_ID}/")

    except Exception as e:
        print(f"⚠ GCS not available ({e})")
        print("  Running in local-only mode.")

def gcs_upload(local_path: Path, gcs_path: str, content_type: str = None):
    if gcs_bucket_obj is None:
        return
    try:
        blob = gcs_bucket_obj.blob(gcs_path)
        if content_type:
            blob.content_type = content_type
        blob.upload_from_filename(str(local_path))
    except Exception as e:
        print(f"  ⚠ Upload failed {gcs_path}: {e}")

def gcs_upload_bytes(data: bytes, gcs_path: str, content_type: str = "application/json"):
    if gcs_bucket_obj is None:
        return
    try:
        blob = gcs_bucket_obj.blob(gcs_path)
        blob.upload_from_string(data, content_type=content_type)  # ← content_type aquí
    except Exception as e:
        print(f"  ⚠ Upload failed {gcs_path}: {e}")

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
hours_of_day   = [t.hour for t in times_col]
t_axis         = np.arange(nframes)

# Run ID = simulation start time in UTC
RUN_ID     = times_utc[0].strftime("%Y-%m-%dT%H:%M:%SZ")
GCS_PREFIX = f"apps/{APP_ID}/runs/{RUN_ID}"

print(f"App:     {APP_ID}")
print(f"Run ID:  {RUN_ID}")
print(f"Domain:  {dx_km:.0f} km | {date_start_col} → {date_end_col} | {nframes} frames")
print(f"GCS:     gs://{GCS_BUCKET}/{GCS_PREFIX}/")

# Init GCS after we know the run ID
init_gcs()

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

def dewpoint(q_gkg, psfc_hpa):
    q  = q_gkg / 1000
    e  = q * psfc_hpa / (0.622 + q)
    td = (243.5 * np.log(e/6.112)) / (17.67 - np.log(e/6.112))
    return td

TD_all = dewpoint(Q2_all, PSFC_all)

print("Extracting city time series...")
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
# WRITE meta.json
# ─────────────────────────────────────────────
print("\nWriting meta.json...")
ext = "mp4" if shutil.which("ffmpeg") else "gif"
meta = {
    "run_id":       RUN_ID,
    "app":          APP_ID,
    "context":      CONTEXT,
    "dx_km":        round(dx_km, 1),
    "nframes":      nframes,
    "start_utc":    times_utc[0].isoformat(),
    "end_utc":      times_utc[-1].isoformat(),
    "start_col":    times_col[0].isoformat(),
    "end_col":      times_col[-1].isoformat(),
    "timestamps_utc": [t.isoformat() for t in times_utc],
    "timestamps_col": [t.isoformat() for t in times_col],
    "domain": {
        "lat_min": float(lats_g.min()),
        "lat_max": float(lats_g.max()),
        "lon_min": float(lons_g.min()),
        "lon_max": float(lons_g.max()),
    },
    "cities": {
        city: {
            "lat":    info["lat"],
            "lon":    info["lon"],
            "region": info["region"],
            "dept":   info["dept"],
            "color":  CITY_COLORS[city],
        }
        for city, info in CITIES.items()
    },
    "regions": {reg: {"color": REGION_COLORS[reg]} for reg in REGIONS},
    "rain_thresholds": RAIN_THRESHOLDS,
    "images": {
        "rain_accumulated": "images/rain_accumulated.png",
        "t2_max":           "images/t2_max.png",
        "wind10m":          "images/wind10m.png",
    },
    "animations": {k: f"animations/animation_{k}.{ext}"
                   for k in ["t2","wind","rain_hr","rh","swdown","td","cape"]},
    "generated_at": pd.Timestamp.utcnow().isoformat(),
}

# ─────────────────────────────────────────────
# WRITE timeseries.json
# ─────────────────────────────────────────────
print("Writing timeseries.json...")

def arr(a): return [round(float(x), 3) for x in a]

ts_data = {
    "timestamps_col": [t.isoformat() for t in times_col],
    "variables": {
        "t2":     {"label": "Temperatura 2m",        "unit": "°C"},
        "ws10":   {"label": "Viento 10m",            "unit": "m/s"},
        "rain_hr":{"label": "Precipitación horaria", "unit": "mm/h"},
        "q2":     {"label": "Humedad específica",    "unit": "g/kg"},
        "psfc":   {"label": "Presión superficial",   "unit": "hPa"},
        "swdown": {"label": "Radiación solar",       "unit": "W/m²"},
        "rh":     {"label": "Humedad relativa",      "unit": "%"},
        "cape":   {"label": "CAPE",                  "unit": "J/kg"},
        "td":     {"label": "Punto de rocío",        "unit": "°C"},
    },
    "cities": {
        city: {v: arr(city_data[city][v])
               for v in ["t2","ws10","rain_hr","q2","psfc","swdown","rh","cape","td"]}
        for city in CITIES
    },
    "regions": {
        reg: {v: arr(region_data[reg][v])
              for v in ["t2","ws10","rain_hr","q2","psfc","swdown","rh","cape","td"]}
        for reg in region_data
    },
    "rain_probability": {
        "thresholds": RAIN_THRESHOLDS,
        "cities": {
            city: [round(float(np.mean(city_data[city]["rain_hr"] >= thr)*100), 1)
                   for thr in RAIN_THRESHOLDS]
            for city in CITIES
        },
        "regions": {
            reg: [round(float(np.mean(region_data[reg]["rain_hr"] >= thr)*100), 1)
                  for thr in RAIN_THRESHOLDS]
            for reg in region_data
        },
    }
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

def save_fig(fig, name, subdir="images"):
    (OUTPUT_DIR/subdir).mkdir(exist_ok=True)
    p = OUTPUT_DIR/subdir/name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close(fig)
    ct = "image/gif" if name.endswith(".gif") else "image/png"
    gcs_upload(p, f"{GCS_PREFIX}/{subdir}/{name}", ct)
    print(f"  → {subdir}/{name}")
    return f"{subdir}/{name}"

def styled_ax(ax):
    ax.set_facecolor(CARD)
    ax.grid(True, alpha=0.3, linewidth=0.5)
    ax.tick_params(colors=MUTED, labelsize=7)
    for sp in ax.spines.values(): sp.set_edgecolor(BORDER)

def set_time_xticks(ax, max_ticks=10):
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

sk = max(2, lats_g.shape[0]//12)

# ─── MAPS ─────────────────────────────────────────────────────
print("\n[1/5] Maps...")

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
generated.append({"type":"image","file":save_fig(fig,"rain_accumulated.png"),"title":"Precipitación Acumulada","tab":"maps"})

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
generated.append({"type":"image","file":save_fig(fig,"t2_max.png"),"title":"Temperatura Máxima 2m","tab":"maps"})

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
fig.text(0.5,0.97,"Viento 10m",ha="center",fontsize=14,fontweight="bold",color=TEXT)
fig.text(0.5,0.945,f"{dx_km:.0f} km  |  {CONTEXT}",ha="center",fontsize=8,color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"wind10m.png"),"title":"Viento 10m","tab":"maps"})

# ─── CITY TIME SERIES ─────────────────────────────────────────
print("[2/5] City time series...")
for var, ylabel in VAR_CFG:
    fig, ax = plt.subplots(figsize=(14,5), facecolor=DARK)
    fig.subplots_adjust(top=0.82, bottom=0.22, left=0.07, right=0.82)
    styled_ax(ax)
    ax.set_ylabel(ylabel, fontsize=9, color=TEXT)
    for city, data in city_data.items():
        ax.plot(t_axis, data[var], color=CITY_COLORS[city], linewidth=1.3, alpha=0.88)
    set_time_xticks(ax)
    ax.set_xlabel("Hora Colombia (UTC-5)", fontsize=8, color=MUTED)
    handles = [Line2D([0],[0],color=CITY_COLORS[c],linewidth=2,label=c) for c in city_data]
    fig.legend(handles=handles, loc="center right", bbox_to_anchor=(1.0,0.5),
               frameon=True, facecolor=CARD, edgecolor=BORDER,
               labelcolor=TEXT, fontsize=7, title="Ciudad", title_fontsize=7.5)
    fig.text(0.5,0.95,f"Ciudades — {ylabel}",ha="center",fontsize=13,fontweight="bold",color=TEXT)
    fig.text(0.5,0.927,f"{CONTEXT}  |  {date_start_col} → {date_end_col}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.03, h=0.045)
    generated.append({"type":"image","file":save_fig(fig,f"city_ts_{var}.png"),"title":f"Ciudades — {ylabel}","tab":"cities"})

# ─── REGION TIME SERIES ───────────────────────────────────────
print("[3/5] Region time series...")
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
    generated.append({"type":"image","file":save_fig(fig,f"region_ts_{var}.png"),"title":f"Regiones — {ylabel}","tab":"regions"})

# ─── BOXPLOTS & RADAR ─────────────────────────────────────────
print("[4/5] Boxplots & radar...")
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
    fig.text(0.5,0.922,f"{CONTEXT}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.01, h=0.045)
    sr = reg.replace("í","i").replace("ó","o").replace(" ","_").lower()
    generated.append({"type":"image","file":save_fig(fig,f"boxplot_{sr}.png"),"title":f"Ciclo Diario — {reg}","tab":"regions"})

# Radar charts
labels_r = ["Temperatura","Viento","Lluvia","Humedad","Radiación"]
N_r = len(labels_r)
angles_r = np.linspace(0, 2*np.pi, N_r, endpoint=False).tolist() + [0]
city_vals_raw = {}
for city, data in city_data.items():
    city_vals_raw[city] = np.array([
        data["t2"].mean(), data["ws10"].mean(),
        data["rain_hr"].sum(), data["q2"].mean(), data["swdown"].mean()
    ])
all_raw = np.array(list(city_vals_raw.values()))
def norm_col(col):
    mn, mx = col.min(), col.max()
    return (col-mn)/(mx-mn) if mx>mn else np.zeros_like(col)
norm_matrix = np.column_stack([norm_col(all_raw[:,j]) for j in range(N_r)])
city_list_r  = list(city_vals_raw.keys())

for reg in REGIONS:
    c_in_reg = [c for c in city_list_r if city_data[c]["region"]==reg]
    if not c_in_reg: continue
    nc = len(c_in_reg)
    cols = min(nc,3); rows = (nc+cols-1)//cols
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
        ax.set_yticks([0.25,0.5,0.75,1.0]); ax.set_yticklabels([""]*4)
        ax.set_ylim(0,1)
        ax.spines["polar"].set_edgecolor(BORDER)
        ax.grid(color=BORDER, linewidth=0.5)
        ax.set_title(city, fontsize=9, color=color, fontweight="bold", pad=14)
    rc = REGION_COLORS[reg]
    fig.text(0.5,0.95,f"Perfil Climático — {reg}",ha="center",fontsize=13,fontweight="bold",color=rc)
    fig.text(0.5,0.925,f"{CONTEXT}",ha="center",fontsize=8,color=MUTED)
    add_logo(fig, y=0.01, h=0.045)
    sr = reg.replace("í","i").replace("ó","o").replace(" ","_").lower()
    generated.append({"type":"image","file":save_fig(fig,f"radar_{sr}.png"),"title":f"Perfil Climático — {reg}","tab":"regions"})

# ─── RAIN PROBABILITY ─────────────────────────────────────────
RANGE_LABELS = ["Llovizna\n≥0.1","Leve\n≥1","Moderada\n≥5","Fuerte\n≥10"]
RANGE_COLORS = ["#00aaff","#00dd88","#ffcc00","#ff4444"]
n_ranges = len(RAIN_THRESHOLDS)

cities_list = list(city_data.keys())
x = np.arange(len(cities_list))
fig, ax = plt.subplots(figsize=(16,7), facecolor=DARK)
fig.subplots_adjust(top=0.82, bottom=0.22, left=0.06, right=0.97)
styled_ax(ax)
for ri,(thr,lbl,rc) in enumerate(zip(RAIN_THRESHOLDS,RANGE_LABELS,RANGE_COLORS)):
    probs = [float(np.mean(city_data[c]["rain_hr"]>=thr)*100) for c in cities_list]
    ax.bar(x+(ri-n_ranges/2+0.5)*0.18, probs, 0.18,
           label=lbl.replace("\n"," "), color=rc, alpha=0.85, edgecolor=BORDER, linewidth=0.4)
ax.set_xticks(x); ax.set_xticklabels(cities_list, rotation=40, ha="right", fontsize=7.5, color=TEXT)
ax.set_ylabel("Probabilidad (%)", fontsize=9, color=TEXT); ax.set_ylim(0,105)
ax.legend(frameon=True, facecolor=CARD, edgecolor=BORDER, labelcolor=TEXT, fontsize=8, loc="upper right")
fig.text(0.5,0.95,"Probabilidad de Lluvia — Ciudades",ha="center",fontsize=13,fontweight="bold",color=TEXT)
fig.text(0.5,0.925,f"{CONTEXT}",ha="center",fontsize=8,color=MUTED)
add_logo(fig, y=0.01, h=0.045)
generated.append({"type":"image","file":save_fig(fig,"rain_prob_city.png"),"title":"Prob. Lluvia — Ciudades","tab":"rain"})

regs_list = list(region_data.keys())
x2 = np.arange(len(regs_list))
fig, ax = plt.subplots(figsize=(11,6), facecolor=DARK)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.08, right=0.97)
styled_ax(ax)
for ri,(thr,lbl,rc) in enumerate(zip(RAIN_THRESHOLDS,RANGE_LABELS,RANGE_COLORS)):
    probs = [float(np.mean(region_data[r]["rain_hr"]>=thr)*100) for r in regs_list]
    ax.bar(x2+(ri-n_ranges/2+0.5)*0.18, probs, 0.18,
           label=lbl.replace("\n"," "), color=rc, alpha=0.85, edgecolor=BORDER, linewidth=0.4)
ax.set_xticks(x2); ax.set_xticklabels(regs_list, fontsize=9, color=TEXT)
ax.set_ylabel("Probabilidad (%)", fontsize=9, color=TEXT); ax.set_ylim(0,105)
ax.legend(frameon=True, facecolor=CARD, edgecolor=BORDER, labelcolor=TEXT, fontsize=8)
fig.text(0.5,0.95,"Probabilidad de Lluvia — Regiones",ha="center",fontsize=13,fontweight="bold",color=TEXT)
fig.text(0.5,0.925,f"{CONTEXT}",ha="center",fontsize=8,color=MUTED)
add_logo(fig, y=0.01, h=0.05)
generated.append({"type":"image","file":save_fig(fig,"rain_prob_region.png"),"title":"Prob. Lluvia — Regiones","tab":"rain"})

# ─── ANIMATIONS ───────────────────────────────────────────────
print("[5/5] Animations...")
ANIM_VARS = [
    ("t2",      T2_all,   np.arange(15,40,1),   "RdYlBu_r","Temperatura 2m (°C)"),
    ("wind",    WS10_all, np.arange(0,20.5,.5), "plasma",   "Viento 10m (m/s)"),
    ("rain_hr", RAIN_HR,  np.arange(0,20,.5),   "YlGnBu",   "Precipitación horaria (mm/h)"),
    ("rh",      RH_all,   np.arange(40,101,2),  "BuPu",     "Humedad relativa (%)"),
    ("swdown",  SW_all,   np.arange(0,1001,25), "hot",      "Radiación solar (W/m²)"),
    ("td",      TD_all,   np.arange(5,32,1),    "YlGn",     "Punto de rocío (°C)"),
    ("cape",    CAPE_all, np.arange(0,3001,100),"YlOrRd",   "CAPE (J/kg)"),
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
                th.set_text(f"{CONTEXT}  ·  {lbl}  ·  {times_col[t].strftime('%Y-%m-%d %H:%M hora Colombia')}")
                return st["art"]
            return upd

        ani = animation.FuncAnimation(
            fig, make_upd(vname,data3d,levels,cmap,label,state,title_h),
            frames=nframes, interval=350, blit=False)

        afile = f"animation_{vname}.{ext}"
        (OUTPUT_DIR/"animations").mkdir(exist_ok=True)
        anim_local = OUTPUT_DIR/"animations"/afile
        ani.save(anim_local, dpi=110, writer="ffmpeg" if ext=="mp4" else "pillow")
        plt.close(fig)
        ct = "video/mp4" if ext=="mp4" else "image/gif"
        gcs_upload(anim_local, f"{GCS_PREFIX}/animations/{afile}", ct)
        print(f"  → animations/{afile}")
        generated.append({"type":"animation","file":f"animations/{afile}","title":f"Animación — {label}","tab":"animations"})

# ─── UPLOAD JSON FILES ────────────────────────────────────────
print("\nUploading JSON files...")
meta["products"]       = generated
meta["products_count"] = len(generated)

meta_bytes = json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8")
(OUTPUT_DIR/"meta.json").write_bytes(meta_bytes)
gcs_upload_bytes(meta_bytes, f"{GCS_PREFIX}/meta.json", "application/json")

ts_bytes = json.dumps(ts_data, ensure_ascii=False).encode("utf-8")
(OUTPUT_DIR/"timeseries.json").write_bytes(ts_bytes)
gcs_upload_bytes(ts_bytes, f"{GCS_PREFIX}/timeseries.json", "application/json")

# Index entry for run listing
index_entry = {
    "run_id":    RUN_ID,
    "app":       APP_ID,
    "dx_km":     round(dx_km, 1),
    "start_col": times_col[0].isoformat(),
    "end_col":   times_col[-1].isoformat(),
    "nframes":   nframes,
    "context":   CONTEXT,
    "meta_path": f"{GCS_PREFIX}/meta.json",
}
gcs_upload_bytes(
    json.dumps(index_entry, indent=2).encode(),
    f"apps/{APP_ID}/index/{RUN_ID}.json",
    "application/json"
)

print(f"\n✓ {len(generated)} productos generados")
print(f"✓ Local:  {OUTPUT_DIR}/")
if gcs_bucket_obj:
    print(f"✓ GCS:    gs://{GCS_BUCKET}/{GCS_PREFIX}/")
