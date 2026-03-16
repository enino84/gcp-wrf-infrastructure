"""
post_processor_gcs.py — gcp-wrf-infrastructure
WRF post-processor with GCS upload.

Generates:
  - 3 static maps (cartopy):  rain_accumulated, t2_max, wind10m
  - 7 animations (ffmpeg):    t2, wind, rain_hr, rh, swdown, td, cape
  - meta.json                 run metadata + city/region info
  - timeseries.json           all time series data (consumed by React)

Everything else (charts, radar, boxplots, rain probability) is rendered
by the React frontend using timeseries.json.

Usage
─────
python post_processor_gcs.py \
    --input      /data \
    --output     /output \
    --app        wrf-colombia-27km \
    --config     /postprocess/configs/colombia.json \
    --context    "WRF Colombia 27km" \
    --gcs-bucket learn-da-data
"""

import argparse, json, shutil, sys
from glob import glob
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from scipy.interpolate import RegularGridInterpolator
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--input",         required=True)
parser.add_argument("--output",        required=True)
parser.add_argument("--app",           default="wrf-colombia-27km")
parser.add_argument("--config",        default="/postprocess/configs/colombia.json")
parser.add_argument("--context",       default="WRF Simulation")
parser.add_argument("--logo",          default="/postprocess/logo.png")
parser.add_argument("--gcs-bucket",    default="learn-da-data")
parser.add_argument("--no-upload",     action="store_true")
parser.add_argument("--create-bucket", action="store_true")
parser.add_argument("--gcs-location",  default="US")
args = parser.parse_args()

INPUT_DIR  = Path(args.input)
OUTPUT_DIR = Path(args.output)
APP_ID     = args.app
CONTEXT    = args.context
LOGO_PATH  = Path(args.logo)
GCS_BUCKET = args.gcs_bucket
DO_UPLOAD  = not args.no_upload
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# LOAD CONFIG
# ─────────────────────────────────────────────
config_path = Path(args.config)
if not config_path.exists():
    print(f"ERROR: config not found: {config_path}"); sys.exit(1)

with open(config_path, encoding="utf-8") as f:
    CFG = json.load(f)

CITIES      = CFG["cities"]
REGIONS_CFG = CFG["regions"]
LABELS      = CFG["labels"]
TZ_OFFSET   = CFG.get("timezone_offset_hours", -5)
TZ_LABEL    = CFG.get("timezone_label", f"UTC{TZ_OFFSET:+d}")
REGIONS     = list(REGIONS_CFG.keys())
REGION_COLORS = {reg: v["color"] for reg, v in REGIONS_CFG.items()}
RAIN_THRESHOLDS = [0.1, 1.0, 5.0, 10.0]

# City colors from region palettes
_ridx = {r: 0 for r in REGIONS}
CITY_COLORS = {}
for city, info in CITIES.items():
    r = info["region"]
    palette = REGIONS_CFG[r]["palette"]
    CITY_COLORS[city] = palette[_ridx[r] % len(palette)]
    _ridx[r] += 1

print(f"Config: {config_path.name} ({len(CITIES)} cities, {len(REGIONS)} regions)")

# ─────────────────────────────────────────────
# GCS
# ─────────────────────────────────────────────
gcs_bucket_obj = None

def init_gcs():
    global gcs_bucket_obj
    if not DO_UPLOAD:
        print("⚠ --no-upload set"); return
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        if not bucket.exists():
            if args.create_bucket:
                bucket = client.create_bucket(GCS_BUCKET, location=args.gcs_location)
                print(f"  ✓ Bucket created: gs://{GCS_BUCKET}")
            else:
                print(f"  ✗ Bucket gs://{GCS_BUCKET} does not exist.")
                print(f"    gsutil mb -l US gs://{GCS_BUCKET}  or use --create-bucket")
                sys.exit(1)
        gcs_bucket_obj = bucket
        print(f"✓ GCS connected → gs://{GCS_BUCKET}/apps/{APP_ID}/")
    except Exception as e:
        print(f"⚠ GCS not available ({e}) — local only")

def gcs_upload(local_path, gcs_path, content_type=None):
    if gcs_bucket_obj is None: return
    try:
        gcs_bucket_obj.blob(gcs_path).upload_from_filename(
            str(local_path), content_type=content_type)
    except Exception as e:
        print(f"  ⚠ {gcs_path}: {e}")

def gcs_upload_bytes(data, gcs_path, content_type="application/json"):
    if gcs_bucket_obj is None: return
    try:
        gcs_bucket_obj.blob(gcs_path).upload_from_string(
            data, content_type=content_type)
    except Exception as e:
        print(f"  ⚠ {gcs_path}: {e}")

# ─────────────────────────────────────────────
# LOAD WRF DATA
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

print(f"\nFound {len(files_orig)} wrfout files...")
probe = []
for f in files_orig:
    try:
        d = open_one(f); nt = int(d.sizes.get("Time",0)); d.close()
        probe.append((f,nt))
    except:
        probe.append((f,-1))

kept = [f for f,nt in probe if nt>=2] or [f for f,nt in probe if nt>=1]
ds   = xr.concat([open_one(f) for f in safe_copy(kept, OUTPUT_DIR)], dim="Time")

lats_g = ds["XLAT"].isel(Time=0).values
lons_g = ds["XLONG"].isel(Time=0).values
ny, nx = lats_g.shape

raw_times = ["".join(t.astype(str)) for t in ds["Times"].values]
times_utc = pd.to_datetime(raw_times, format="%Y-%m-%d_%H:%M:%S", errors="coerce")
good = ~times_utc.isna()
if not good.all():
    ds = ds.isel(Time=np.where(good.values)[0])
    times_utc = pd.to_datetime(
        ["".join(t.astype(str)) for t in ds["Times"].values],
        format="%Y-%m-%d_%H:%M:%S")

times_local  = times_utc + pd.Timedelta(hours=TZ_OFFSET)
nframes      = len(times_local)
dx_km        = float(ds.attrs.get("DX",0))/1000
date_start   = times_local[0].strftime(f"%Y-%m-%d %H:%M {TZ_LABEL}")
date_end     = times_local[-1].strftime(f"%Y-%m-%d %H:%M {TZ_LABEL}")
hours_of_day = [t.hour for t in times_local]
t_axis       = np.arange(nframes)
RUN_ID       = times_utc[0].strftime("%Y-%m-%dT%H:%M:%SZ")
GCS_PREFIX   = f"apps/{APP_ID}/runs/{RUN_ID}"

print(f"App:    {APP_ID}  |  Run ID: {RUN_ID}")
print(f"Domain: {dx_km:.0f} km | {date_start} → {date_end} | {nframes} frames")
init_gcs()

# ─────────────────────────────────────────────
# EXTRACT VARIABLES
# ─────────────────────────────────────────────
def bilinear(field2d, lat, lon):
    interp = RegularGridInterpolator(
        (lats_g[:,nx//2], lons_g[ny//2,:]), field2d,
        method="linear", bounds_error=False, fill_value=None)
    return float(interp([[lat, lon]])[0])

def city_ts(var3d, city):
    lat, lon = CITIES[city]["lat"], CITIES[city]["lon"]
    return np.array([bilinear(var3d[t], lat, lon) for t in range(nframes)])

print("\nExtracting variables...")
T2   = ds["T2"].values - 273.15
U10  = ds["U10"].values
V10  = ds["V10"].values
WS10 = np.sqrt(U10**2 + V10**2)
RAIN = ds["RAINC"].values + ds["RAINNC"].values
RAIN_HR = np.maximum(0, np.diff(RAIN, axis=0, prepend=RAIN[[0]]))
Q2   = ds["Q2"].values * 1000
PSFC = ds["PSFC"].values / 100
SW   = ds["SWDOWN"].values if "SWDOWN" in ds else np.zeros_like(T2)

def rh_calc(q, t2c, psfc):
    T  = t2c + 273.15
    es = 6.112 * np.exp(17.67*(T-273.15)/(T-29.65))
    e  = (q/1000)*psfc/(0.622+q/1000)
    return np.clip(e/es*100, 0, 100)

RH   = rh_calc(Q2, T2, PSFC)
CAPE = ds["CAPE"].values if "CAPE" in ds else np.zeros_like(T2)

def dewpoint(q_gkg, psfc_hpa):
    q = q_gkg / 1000
    e = q * psfc_hpa / (0.622 + q)
    return (243.5 * np.log(e/6.112)) / (17.67 - np.log(e/6.112))

TD = dewpoint(Q2, PSFC)

print("Extracting city time series...")
city_data = {}
for city in CITIES:
    city_data[city] = {
        "t2":     city_ts(T2,    city),
        "ws10":   city_ts(WS10,  city),
        "rain_hr":city_ts(RAIN_HR,city),
        "q2":     city_ts(Q2,    city),
        "psfc":   city_ts(PSFC,  city),
        "swdown": city_ts(SW,    city),
        "rh":     city_ts(RH,    city),
        "cape":   city_ts(CAPE,  city),
        "td":     city_ts(TD,    city),
        "region": CITIES[city]["region"],
        "dept":   CITIES[city].get("dept",""),
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
    "run_id":    RUN_ID,
    "app":       APP_ID,
    "config":    config_path.name,
    "context":   CONTEXT,
    "dx_km":     round(dx_km, 1),
    "nframes":   nframes,
    "start_utc": times_utc[0].isoformat(),
    "end_utc":   times_utc[-1].isoformat(),
    "start_local": times_local[0].isoformat(),
    "end_local":   times_local[-1].isoformat(),
    "timestamps_utc":   [t.isoformat() for t in times_utc],
    "timestamps_local": [t.isoformat() for t in times_local],
    "timezone_offset_hours": TZ_OFFSET,
    "timezone_label":        TZ_LABEL,
    "domain": {
        "lat_min": float(lats_g.min()), "lat_max": float(lats_g.max()),
        "lon_min": float(lons_g.min()), "lon_max": float(lons_g.max()),
    },
    "cities":  {city: {**CITIES[city], "color": CITY_COLORS[city]} for city in CITIES},
    "regions": {reg: {"color": REGION_COLORS[reg]} for reg in REGIONS},
    "rain_thresholds": RAIN_THRESHOLDS,
    "labels": LABELS,
    "images": {
        "rain_accumulated": "images/rain_accumulated.png",
        "t2_max":           "images/t2_max.png",
        "wind10m":          "images/wind10m.png",
    },
    "animations": {k: f"animations/animation_{k}.{ext}"
                   for k in ["t2","wind","rain_hr","rh","swdown","td","cape"]},
    "generated_at": pd.Timestamp.now("UTC").isoformat(),
}

# ─────────────────────────────────────────────
# WRITE timeseries.json
# ─────────────────────────────────────────────
print("Writing timeseries.json...")

def arr(a): return [round(float(x), 3) for x in a]

ts_data = {
    "timestamps_local": [t.isoformat() for t in times_local],
    "variables": {
        "t2":     {"label": LABELS["t2_series"],      "unit": "°C"},
        "ws10":   {"label": LABELS["ws10_series"],    "unit": "m/s"},
        "rain_hr":{"label": LABELS["rain_hr_series"], "unit": "mm/h"},
        "q2":     {"label": LABELS["q2_series"],      "unit": "g/kg"},
        "psfc":   {"label": LABELS["psfc_series"],    "unit": "hPa"},
        "swdown": {"label": LABELS["swdown_series"],  "unit": "W/m²"},
        "rh":     {"label": LABELS["anim_rh"],        "unit": "%"},
        "cape":   {"label": "CAPE",                   "unit": "J/kg"},
        "td":     {"label": LABELS["anim_td"],        "unit": "°C"},
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
            city: [round(float(np.mean(city_data[city]["rain_hr"]>=thr)*100),1)
                   for thr in RAIN_THRESHOLDS]
            for city in CITIES
        },
        "regions": {
            reg: [round(float(np.mean(region_data[reg]["rain_hr"]>=thr)*100),1)
                  for thr in RAIN_THRESHOLDS]
            for reg in region_data
        },
    },
    # Pre-computed daily cycle for boxplots (React uses this directly)
    "daily_cycle": {
        city: {
            str(h): arr([city_data[city]["t2"][i]
                         for i,hh in enumerate(hours_of_day) if hh==h])
            for h in range(24)
            if any(hh==h for hh in hours_of_day)
        }
        for city in CITIES
    },
}

# ─────────────────────────────────────────────
# STYLE
# ─────────────────────────────────────────────
DARK="#07090f"; CARD="#111827"; BORDER="#1a2540"; TEXT="#e8f4f8"; MUTED="#5a7a94"
plt.rcParams.update({
    "figure.facecolor":DARK, "axes.facecolor":CARD, "axes.edgecolor":BORDER,
    "axes.labelcolor":TEXT,  "xtick.color":MUTED,   "ytick.color":MUTED,
    "text.color":TEXT,       "grid.color":BORDER,   "grid.alpha":0.4,
})

generated = []
proj = ccrs.PlateCarree()
sk   = max(2, ny//12)

def add_logo(fig, y=0.07, h=0.055):
    if LOGO_PATH.exists():
        from PIL import Image as PILImage
        try:
            logo = PILImage.open(LOGO_PATH)
            wf,hf = fig.get_size_inches()
            w = h*(logo.width/logo.height)*(hf/wf)
            ax = fig.add_axes([0.5-w/2, y, w, h])
            ax.imshow(np.array(logo)); ax.axis("off")
        except: pass
    fig.text(0.5, y-0.018, LABELS.get("website","www.learn-da.com"),
             ha="center", va="top", fontsize=7, color=MUTED, fontstyle="italic")

def save_fig(fig, name, subdir="images"):
    (OUTPUT_DIR/subdir).mkdir(exist_ok=True)
    p = OUTPUT_DIR/subdir/name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close(fig)
    ct = "image/gif" if name.endswith(".gif") else "image/png"
    gcs_upload(p, f"{GCS_PREFIX}/{subdir}/{name}", ct)
    print(f"  → {subdir}/{name}")
    return f"{subdir}/{name}"

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
    for city,info in CITIES.items():
        ax.plot(info["lon"], info["lat"], "o",
                color=CITY_COLORS[city], markersize=4, transform=proj, zorder=10)
        ax.text(info["lon"]+0.25, info["lat"], city, fontsize=6,
                color=CITY_COLORS[city], transform=proj, zorder=11,
                path_effects=[pe.withStroke(linewidth=2, foreground=DARK)])

# ─── MAPS ─────────────────────────────────────────────────────
print("\n[1/2] Maps...")

rain_acc = RAIN[-1]-RAIN[0] if nframes>=2 else np.zeros_like(lats_g)
fig,ax = make_map()
cs = ax.contourf(lons_g, lats_g, rain_acc, levels=np.arange(0,205,5),
                 cmap="YlGnBu", transform=proj, extend="max")
city_markers(ax)
cbar = plt.colorbar(cs, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
cbar.set_label(LABELS["rain_accumulated_unit"], color=TEXT, fontsize=9)
cbar.ax.tick_params(colors=MUTED, labelsize=8)
fig.text(0.5,0.97, LABELS["rain_accumulated"], ha="center", fontsize=14, fontweight="bold", color=TEXT)
fig.text(0.5,0.945, f"{date_start} → {date_end}  |  {dx_km:.0f} km  |  {CONTEXT}", ha="center", fontsize=8, color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"rain_accumulated.png"),
                   "title":LABELS["rain_accumulated"],"tab":"maps"})

fig,ax = make_map()
cs = ax.contourf(lons_g, lats_g, T2.max(axis=0), levels=np.arange(15,42,1),
                 cmap="RdYlBu_r", transform=proj, extend="both")
city_markers(ax)
cbar = plt.colorbar(cs, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
cbar.set_label(LABELS["t2_max_unit"], color=TEXT, fontsize=9)
cbar.ax.tick_params(colors=MUTED, labelsize=8)
fig.text(0.5,0.97, LABELS["t2_max"], ha="center", fontsize=14, fontweight="bold", color=TEXT)
fig.text(0.5,0.945, f"{date_start} → {date_end}  |  {dx_km:.0f} km  |  {CONTEXT}", ha="center", fontsize=8, color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"t2_max.png"),
                   "title":LABELS["t2_max"],"tab":"maps"})

fig,ax = make_map()
cs = ax.contourf(lons_g, lats_g, WS10[-1], levels=np.arange(0,22,1),
                 cmap="plasma", transform=proj, extend="max")
ax.quiver(lons_g[::sk,::sk], lats_g[::sk,::sk],
          U10[-1][::sk,::sk], V10[-1][::sk,::sk],
          transform=proj, scale=400, width=0.003, color="white", alpha=0.7)
city_markers(ax)
cbar = plt.colorbar(cs, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
cbar.set_label(LABELS["wind10m_unit"], color=TEXT, fontsize=9)
cbar.ax.tick_params(colors=MUTED, labelsize=8)
fig.text(0.5,0.97, f"{LABELS['wind10m']} ({LABELS['wind10m_last']})",
         ha="center", fontsize=14, fontweight="bold", color=TEXT)
fig.text(0.5,0.945, f"{dx_km:.0f} km  |  {CONTEXT}", ha="center", fontsize=8, color=MUTED)
add_logo(fig)
generated.append({"type":"image","file":save_fig(fig,"wind10m.png"),
                   "title":LABELS["wind10m"],"tab":"maps"})

# ─── ANIMATIONS ───────────────────────────────────────────────
print("[2/2] Animations...")
ANIM_VARS = [
    ("t2",      T2,      np.arange(15,40,1),    "RdYlBu_r", LABELS["anim_t2"]),
    ("wind",    WS10,    np.arange(0,20.5,.5),  "plasma",   LABELS["anim_wind"]),
    ("rain_hr", RAIN_HR, np.arange(0,20,.5),    "YlGnBu",   LABELS["anim_rain_hr"]),
    ("rh",      RH,      np.arange(40,101,2),   "BuPu",     LABELS["anim_rh"]),
    ("swdown",  SW,      np.arange(0,1001,25),  "hot",      LABELS["anim_swdown"]),
    ("td",      TD,      np.arange(5,32,1),     "YlGn",     LABELS["anim_td"]),
    ("cape",    CAPE,    np.arange(0,3001,100), "YlOrRd",   LABELS["anim_cape"]),
]

if nframes >= 2:
    for vname,data3d,levels,cmap,label in ANIM_VARS:
        fig,ax = make_map()
        title_h = ax.set_title("", fontsize=11, color=TEXT, pad=8)
        state = {"art":[]}
        before = set(ax.get_children())
        cf0 = ax.contourf(lons_g, lats_g, data3d[0], levels=levels,
                          cmap=cmap, extend="both", transform=proj)
        if vname=="wind":
            ax.quiver(lons_g[::sk,::sk], lats_g[::sk,::sk],
                      U10[0][::sk,::sk], V10[0][::sk,::sk],
                      transform=proj, scale=400, width=0.003, color="white", alpha=0.6)
        state["art"] = list(set(ax.get_children())-before)
        cbar = plt.colorbar(cf0, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=30)
        cbar.set_label(label, color=TEXT, fontsize=9)
        cbar.ax.tick_params(colors=MUTED, labelsize=8)
        city_markers(ax); add_logo(fig)

        def make_upd(vn, d3, lv, cm, lbl, st, th):
            def upd(t):
                for a in st["art"]:
                    try: a.remove()
                    except: pass
                before_ = set(ax.get_children())
                ax.contourf(lons_g, lats_g, d3[t], levels=lv, cmap=cm, extend="both", transform=proj)
                if vn=="wind":
                    ax.quiver(lons_g[::sk,::sk], lats_g[::sk,::sk],
                              U10[t][::sk,::sk], V10[t][::sk,::sk],
                              transform=proj, scale=400, width=0.003, color="white", alpha=0.6)
                st["art"] = list(set(ax.get_children())-before_)
                ts_str = times_local[t].strftime(f"%Y-%m-%d %H:%M {TZ_LABEL}")
                th.set_text(f"{CONTEXT}  ·  {lbl}  ·  {ts_str}")
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
        generated.append({"type":"animation","file":f"animations/{afile}",
                           "title":label,"tab":"animations"})

# ─── UPLOAD JSON ──────────────────────────────────────────────
print("\nUploading JSON files...")
meta["products"] = generated
meta["products_count"] = len(generated)

meta_bytes = json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8")
(OUTPUT_DIR/"meta.json").write_bytes(meta_bytes)
gcs_upload_bytes(meta_bytes, f"{GCS_PREFIX}/meta.json")

ts_bytes = json.dumps(ts_data, ensure_ascii=False).encode("utf-8")
(OUTPUT_DIR/"timeseries.json").write_bytes(ts_bytes)
gcs_upload_bytes(ts_bytes, f"{GCS_PREFIX}/timeseries.json")

index_entry = {
    "run_id":      RUN_ID,
    "app":         APP_ID,
    "config":      config_path.name,
    "dx_km":       round(dx_km, 1),
    "start_local": times_local[0].isoformat(),
    "end_local":   times_local[-1].isoformat(),
    "nframes":     nframes,
    "context":     CONTEXT,
    "meta_path":   f"{GCS_PREFIX}/meta.json",
}
gcs_upload_bytes(
    json.dumps(index_entry, indent=2).encode(),
    f"apps/{APP_ID}/index/{RUN_ID}.json")

print(f"\n✓ {len(generated)} products (3 maps + {len(generated)-3} animations)")
print(f"✓ Local: {OUTPUT_DIR}/")
if gcs_bucket_obj:
    print(f"✓ GCS:   gs://{GCS_BUCKET}/{GCS_PREFIX}/")
print("\nNote: charts, radar, boxplots and rain probability are rendered by React")
print(f"      using timeseries.json ({len(ts_bytes)//1024} KB)")