"""
post_processor.py
WRF output post-processor for the gcp-wrf-infrastructure pipeline.

Generates:
  - Static images: accumulated rain, max T2, wind speed + vectors
  - Animations:    T2 time series, wind speed + vectors time series
  - HTML report:   all products embedded, with Learn-DA logo

Usage (called by run_postprocess.sh):
  python post_processor.py --input /data --context "Colombia" --output /data/plots
"""

import argparse
import os
import sys
import shutil
import base64
from glob import glob
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr


# ============================================================
# CLI
# ============================================================
parser = argparse.ArgumentParser()
parser.add_argument("--input",   required=True, help="Directory containing wrfout_d01_* files")
parser.add_argument("--output",  required=True, help="Directory to write plots and report")
parser.add_argument("--context", default="WRF Simulation", help="Simulation context label, e.g. 'Colombia'")
parser.add_argument("--logo",    default="/postprocess/logo.png", help="Path to logo image")
args = parser.parse_args()

INPUT_DIR  = Path(args.input)
OUTPUT_DIR = Path(args.output)
CONTEXT    = args.context
LOGO_PATH  = Path(args.logo)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# LOAD DATA
# ============================================================
pattern = str(INPUT_DIR / "wrfout_d01_*")
files = sorted(glob(pattern))
if not files:
    print(f"ERROR: No wrfout_d01_* files found in {INPUT_DIR}")
    sys.exit(1)

print(f"Found {len(files)} wrfout file(s). Loading...")
try:
    ds = xr.open_mfdataset(files, concat_dim="Time", combine="nested", engine="scipy")
except Exception:
    ds = xr.open_mfdataset(files, concat_dim="Time", combine="nested", engine="h5netcdf")

lats = ds["XLAT"].isel(Time=0).values
lons = ds["XLONG"].isel(Time=0).values

# Parse simulation times
raw_times = ["".join(t.astype(str)) for t in ds["Times"].values]
times_utc   = pd.to_datetime(raw_times, format="%Y-%m-%d_%H:%M:%S")
times_local = times_utc + pd.Timedelta(hours=-5)  # Colombia UTC-5
nframes     = len(times_local)

# Extract metadata from wrfout
dx_m  = float(ds.attrs.get("DX", 0))
dx_km = dx_m / 1000.0
date_start = times_utc[0].strftime("%Y-%m-%d %H:%M UTC")
date_end   = times_utc[-1].strftime("%Y-%m-%d %H:%M UTC")

print(f"Domain: {dx_km:.0f} km | {date_start} → {date_end}")
print(f"Context: {CONTEXT}")

# ============================================================
# HELPERS
# ============================================================
LOGO_B64 = ""
if LOGO_PATH.exists():
    with open(LOGO_PATH, "rb") as f:
        LOGO_B64 = base64.b64encode(f.read()).decode()

def add_logo(fig, logo_path=LOGO_PATH, x=0.01, y=0.01, w=0.10, h=0.07):
    """Add Learn-DA logo to figure."""
    if not logo_path.exists():
        return
    from PIL import Image as PILImage
    try:
        logo = PILImage.open(logo_path)
        logo_ax = fig.add_axes([x, y, w, h])
        logo_ax.imshow(np.array(logo))
        logo_ax.axis("off")
    except Exception as e:
        print(f"  Warning: could not add logo: {e}")

def make_title(fig, variable_title):
    """Standard title block: variable name + context + dates."""
    fig.text(0.5, 0.965, variable_title,
             ha="center", va="top", fontsize=14, fontweight="bold")
    fig.text(0.5, 0.938, CONTEXT,
             ha="center", va="top", fontsize=11)
    fig.text(0.5, 0.915, f"{date_start}  →  {date_end}  |  {dx_km:.0f} km resolution",
             ha="center", va="top", fontsize=9, color="#555555")

def make_footnote(fig, note="WRF model output. Results represent model guidance, not deterministic truth."):
    fig.text(0.5, 0.01, note, ha="center", va="bottom", fontsize=8, color="#777777")

def save(fig, name):
    path = OUTPUT_DIR / name
    fig.savefig(path, dpi=180, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print(f"  Saved → {path.name}")
    return path.name

proj = ccrs.PlateCarree()

generated = []   # list of dicts: {type, file, title}

# ============================================================
# 1. ACCUMULATED PRECIPITATION
# ============================================================
print("\n[1/5] Accumulated precipitation...")
rain = (ds["RAINC"] + ds["RAINNC"])
rain_acc = (rain.isel(Time=-1) - rain.isel(Time=0)).values

fig = plt.figure(figsize=(9, 9))
ax  = plt.axes(projection=proj)
levels = np.arange(0, 205, 5)
cs = ax.contourf(lons, lats, rain_acc, levels=levels,
                 cmap="turbo", transform=proj, extend="max")
ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
ax.add_feature(cfeature.BORDERS,   linewidth=0.6)
cbar = plt.colorbar(cs, orientation="horizontal", pad=0.06, shrink=0.9)
cbar.set_label("Accumulated precipitation (mm)")
make_title(fig, "Accumulated Precipitation")
make_footnote(fig)
add_logo(fig)
fname = save(fig, "rain_accumulated.png")
generated.append({"type": "image", "file": fname, "title": "Accumulated Precipitation"})

# ============================================================
# 2. MAXIMUM 2-m TEMPERATURE
# ============================================================
print("[2/5] Maximum 2-m temperature...")
t2_max = (ds["T2"] - 273.15).max(dim="Time").values

fig = plt.figure(figsize=(9, 9))
ax  = plt.axes(projection=proj)
levels = np.arange(15, 42, 1)
cs = ax.contourf(lons, lats, t2_max, levels=levels,
                 cmap="turbo", transform=proj, extend="both")
ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
ax.add_feature(cfeature.BORDERS,   linewidth=0.6)
cbar = plt.colorbar(cs, orientation="horizontal", pad=0.06, shrink=0.9)
cbar.set_label("Maximum temperature at 2 m (°C)")
make_title(fig, "Daily Maximum Temperature at 2 m")
make_footnote(fig)
add_logo(fig)
fname = save(fig, "t2_max.png")
generated.append({"type": "image", "file": fname, "title": "Max 2-m Temperature"})

# ============================================================
# 3. 10-m WIND SPEED + VECTORS (last time step)
# ============================================================
print("[3/5] 10-m wind speed and direction...")
u10  = ds["U10"].isel(Time=-1).values
v10  = ds["V10"].isel(Time=-1).values
wspd = np.sqrt(u10**2 + v10**2)

fig = plt.figure(figsize=(9, 9))
ax  = plt.axes(projection=proj)
levels = np.arange(0, 22, 1)
cs = ax.contourf(lons, lats, wspd, levels=levels,
                 cmap="turbo", transform=proj, extend="max")
skip = 8
ax.quiver(lons[::skip, ::skip], lats[::skip, ::skip],
          u10[::skip, ::skip],  v10[::skip, ::skip],
          transform=proj, scale=600, width=0.002)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
ax.add_feature(cfeature.BORDERS,   linewidth=0.6)
cbar = plt.colorbar(cs, orientation="horizontal", pad=0.06, shrink=0.9)
cbar.set_label("10 m wind speed (m s⁻¹)")
ts_label = times_local[-1].strftime("%Y-%m-%d %H:%M local")
make_title(fig, f"10 m Wind Speed and Direction  |  {ts_label}")
make_footnote(fig, "Wind vectors shown every ~8 grid points for clarity.")
add_logo(fig)
fname = save(fig, "wind10m.png")
generated.append({"type": "image", "file": fname, "title": "10 m Wind Speed & Direction"})

# ============================================================
# 4. ANIMATION — 2-m TEMPERATURE
# ============================================================
print("[4/5] Animation: 2-m temperature...")
T2 = (ds["T2"] - 273.15).values
LEVELS_T = np.arange(15, 40, 1)

fig = plt.figure(figsize=(9, 9))
ax  = plt.axes(projection=proj)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
ax.add_feature(cfeature.BORDERS,   linewidth=0.6)
title_anim = ax.set_title("", fontsize=13)

children_before = set(ax.get_children())
cf0 = ax.contourf(lons, lats, T2[0], levels=LEVELS_T,
                  cmap="turbo", extend="both", transform=proj)
children_after = set(ax.get_children())
current_cf = list(children_after - children_before)
cbar = plt.colorbar(cf0, orientation="horizontal", pad=0.05, shrink=0.9)
cbar.set_label("2-m Temperature (°C)")
add_logo(fig)

def update_t2(t):
    global current_cf
    for a in current_cf:
        try: a.remove()
        except Exception: pass
    before = set(ax.get_children())
    ax.contourf(lons, lats, T2[t], levels=LEVELS_T,
                cmap="turbo", extend="both", transform=proj)
    after = set(ax.get_children())
    current_cf = list(after - before)
    ts = times_local[t].strftime("%Y-%m-%d %H:%M")
    title_anim.set_text(f"{CONTEXT}  |  2 m Temperature\n{ts} local time")
    return current_cf

ani_t2 = animation.FuncAnimation(fig, update_t2, frames=nframes,
                                  interval=300, blit=False)
if shutil.which("ffmpeg"):
    anim_t2_file = "animation_t2.mp4"
    ani_t2.save(OUTPUT_DIR / anim_t2_file, dpi=130, writer="ffmpeg")
else:
    anim_t2_file = "animation_t2.gif"
    ani_t2.save(OUTPUT_DIR / anim_t2_file, dpi=100, writer="pillow")
plt.close(fig)
print(f"  Saved → {anim_t2_file}")
generated.append({"type": "animation", "file": anim_t2_file, "title": "2-m Temperature Animation"})

# ============================================================
# 5. ANIMATION — 10-m WIND
# ============================================================
print("[5/5] Animation: 10-m wind...")
U10_all = ds["U10"].values
V10_all = ds["V10"].values
WS10    = np.sqrt(U10_all**2 + V10_all**2)
LEVELS_W = np.arange(0, 20.5, 0.5)

fig = plt.figure(figsize=(9, 9))
ax  = plt.axes(projection=proj)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
ax.add_feature(cfeature.BORDERS,   linewidth=0.6)
title_wind = ax.set_title("", fontsize=13)

children_before = set(ax.get_children())
cf_w0 = ax.contourf(lons, lats, WS10[0], levels=LEVELS_W,
                    cmap="turbo", extend="max", transform=proj)
q0 = ax.quiver(lons[::skip, ::skip], lats[::skip, ::skip],
               U10_all[0][::skip, ::skip], V10_all[0][::skip, ::skip],
               transform=proj, scale=450, width=0.0022)
children_after = set(ax.get_children())
current_wind = list(children_after - children_before)
cbar_w = plt.colorbar(cf_w0, orientation="horizontal", pad=0.05, shrink=0.9)
cbar_w.set_label("10-m Wind Speed (m/s)")
add_logo(fig)

def update_wind(t):
    global current_wind
    for a in current_wind:
        try: a.remove()
        except Exception: pass
    before = set(ax.get_children())
    ax.contourf(lons, lats, WS10[t], levels=LEVELS_W,
                cmap="turbo", extend="max", transform=proj)
    ax.quiver(lons[::skip, ::skip], lats[::skip, ::skip],
              U10_all[t][::skip, ::skip], V10_all[t][::skip, ::skip],
              transform=proj, scale=450, width=0.0022)
    after = set(ax.get_children())
    current_wind = list(after - before)
    ts = times_local[t].strftime("%Y-%m-%d %H:%M")
    title_wind.set_text(f"{CONTEXT}  |  10 m Wind Speed + Vectors\n{ts} local time")
    return current_wind

ani_wind = animation.FuncAnimation(fig, update_wind, frames=nframes,
                                   interval=300, blit=False)
if shutil.which("ffmpeg"):
    anim_wind_file = "animation_wind10m.mp4"
    ani_wind.save(OUTPUT_DIR / anim_wind_file, dpi=130, writer="ffmpeg")
else:
    anim_wind_file = "animation_wind10m.gif"
    ani_wind.save(OUTPUT_DIR / anim_wind_file, dpi=100, writer="pillow")
plt.close(fig)
print(f"  Saved → {anim_wind_file}")
generated.append({"type": "animation", "file": anim_wind_file, "title": "10-m Wind Animation"})

# ============================================================
# HTML REPORT
# ============================================================
print("\nGenerating HTML report...")

def img_tag(filename, alt=""):
    """Embed image as base64 in HTML."""
    path = OUTPUT_DIR / filename
    if not path.exists():
        return f'<p style="color:red">Missing: {filename}</p>'
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    ext = filename.split(".")[-1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif"}.get(ext, "image/png")
    return f'<img src="data:{mime};base64,{b64}" alt="{alt}" style="max-width:100%;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.18);">'

def video_tag(filename):
    """Embed mp4 video in HTML."""
    path = OUTPUT_DIR / filename
    if not path.exists():
        return f'<p style="color:red">Missing: {filename}</p>'
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return (f'<video controls loop autoplay muted '
            f'style="max-width:100%;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.18);">'
            f'<source src="data:video/mp4;base64,{b64}" type="video/mp4">'
            f'Your browser does not support the video tag.</video>')

def media_block(item):
    fname = item["file"]
    title = item["title"]
    ext   = fname.split(".")[-1].lower()
    if ext == "mp4":
        media = video_tag(fname)
    else:
        media = img_tag(fname, alt=title)
    return f"""
    <div class="card">
      <h2>{title}</h2>
      {media}
    </div>"""

logo_tag = ""
if LOGO_B64:
    logo_tag = f'<img src="data:image/png;base64,{LOGO_B64}" alt="Learn-DA" style="height:70px;">'

images    = [g for g in generated if g["type"] == "image"]
anims     = [g for g in generated if g["type"] == "animation"]

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WRF Report — {CONTEXT}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #0d1117;
    color: #e6edf3;
    min-height: 100vh;
  }}
  header {{
    background: linear-gradient(135deg, #161b22 0%, #1c2333 100%);
    border-bottom: 1px solid #30363d;
    padding: 28px 40px;
    display: flex;
    align-items: center;
    gap: 28px;
  }}
  header .header-text h1 {{
    font-size: 1.8rem;
    font-weight: 700;
    color: #58a6ff;
    letter-spacing: 0.5px;
  }}
  header .header-text p {{
    color: #8b949e;
    font-size: 0.95rem;
    margin-top: 4px;
  }}
  .meta-bar {{
    background: #161b22;
    border-bottom: 1px solid #21262d;
    padding: 12px 40px;
    display: flex;
    gap: 32px;
    font-size: 0.88rem;
    color: #8b949e;
  }}
  .meta-bar span strong {{ color: #e6edf3; }}
  main {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 40px 24px;
  }}
  section {{ margin-bottom: 52px; }}
  section h2.section-title {{
    font-size: 1.1rem;
    font-weight: 600;
    color: #58a6ff;
    border-bottom: 1px solid #21262d;
    padding-bottom: 10px;
    margin-bottom: 28px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(440px, 1fr));
    gap: 28px;
  }}
  .card {{
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 20px;
  }}
  .card h2 {{
    font-size: 0.95rem;
    font-weight: 600;
    color: #c9d1d9;
    margin-bottom: 14px;
  }}
  .card-full {{
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 28px;
  }}
  .card-full h2 {{
    font-size: 0.95rem;
    font-weight: 600;
    color: #c9d1d9;
    margin-bottom: 14px;
  }}
  footer {{
    text-align: center;
    padding: 32px;
    color: #484f58;
    font-size: 0.82rem;
    border-top: 1px solid #21262d;
  }}
</style>
</head>
<body>

<header>
  <div>{logo_tag}</div>
  <div class="header-text">
    <h1>WRF Simulation Report</h1>
    <p>{CONTEXT}</p>
  </div>
</header>

<div class="meta-bar">
  <span><strong>Start:</strong> {date_start}</span>
  <span><strong>End:</strong> {date_end}</span>
  <span><strong>Resolution:</strong> {dx_km:.0f} km</span>
  <span><strong>Time steps:</strong> {nframes}</span>
</div>

<main>

  <section>
    <h2 class="section-title">Static Products</h2>
    <div class="grid">
      {''.join(media_block(g) for g in images)}
    </div>
  </section>

  <section>
    <h2 class="section-title">Animations</h2>
    {''.join(f'<div class="card-full">{media_block(g)}</div>' for g in anims)}
  </section>

</main>

<footer>
  Generated by <strong>gcp-wrf-infrastructure</strong> post-processor &mdash;
  WRF model output. Results represent model guidance, not deterministic truth.
</footer>

</body>
</html>"""

report_path = OUTPUT_DIR / "report.html"
with open(report_path, "w") as f:
    f.write(html)
print(f"  Saved → report.html")

print(f"\n✓ Post-processing complete. {len(generated)} products + report in:\n  {OUTPUT_DIR}")