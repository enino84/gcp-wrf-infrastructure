# WRF-Docker Pipeline

**Automated Weather Research and Forecasting (WRF) System Infrastructure for containerized HPC environments.**

This repository provides a fully reproducible Docker-based pipeline to compile and run [WRF v4.5.2](https://github.com/wrf-model/WRF) and [WPS v4.5](https://github.com/wrf-model/WPS) on any Linux host. It handles complex library dependencies (Jasper, NetCDF), automatic GFS boundary data download, and a clean step-by-step execution pipeline — so that any researcher worldwide can run numerical weather prediction without manual compilation headaches.

---

## Pipeline

![WRF-Docker Pipeline](pipeline.svg)

---

## Repository Structure

```
wrf-docker-pipeline/
├── Dockerfile.libs          # Stage 1: base libraries (Jasper, NetCDF, compilers)
├── Dockerfile.wrf           # Stage 2: WRF v4.5.2 compilation
├── Dockerfile.wps           # Stage 3: WPS v4.5 compilation
├── scripts/
│   ├── setup_folders.sh     # Creates the host directory skeleton
│   ├── download_gfs.sh      # Downloads GFS boundary data from NOAA NOMADS
│   ├── run_wps.sh           # Runs WPS pipeline (geogrid → ungrib → metgrid)
│   └── run_wrf.sh           # Runs real.exe + wrf.exe simulation
└── README.md
```

---

## Architecture: 3-Layer Docker Build

The system uses a staged build to isolate and resolve conflicting dependencies:

| Image | Base | Role |
|---|---|---|
| `wrf-libs-base` | `ubuntu:22.04` | Compilers + Jasper 1.900.1 (source build) + NetCDF |
| `wrf-compiled` | `wrf-libs-base` | WRF v4.5.2 compiled (`em_real` configuration) |
| `wps-compiled` | `wrf-compiled` | WPS v4.5 compiled (geogrid, ungrib, metgrid) |

**Why compile Jasper from source?** Ubuntu 22.04's packaged Jasper is incompatible with WPS's `ungrib.exe`. The fix is to compile Jasper 1.900.1 from source with a `const char*` patch applied before configuration.

**Why `-fno-lto`?** Ubuntu 22.04's `gcc`/`gfortran` enables Link-Time Optimization by default, which causes linker errors (`ld: error`) during WRF compilation. Disabling it in `configure.wrf` and `configure.wps` resolves this.

**Why `-lnetcdff` before `-lnetcdf`?** WPS's configure script on Ubuntu omits the Fortran NetCDF library flag. The fix patches `configure.wps` to explicitly link `-lnetcdff -lnetcdf` in the correct order.

---

## Prerequisites

### Host Requirements

- Linux server (tested on Ubuntu 22.04)
- Docker installed and running
- At least **50 GB** free disk space (WRF source + compiled binaries + GFS data)
- At least **4 CPU cores** recommended for compilation

### Required External Data (must exist before running)

| Data | Description | Default Host Path |
|---|---|---|
| **WPS_GEOG** | Static geographical/terrain data | `/mnt/data/WPS_GEOG/WPS_GEOG_FULL` |
| **namelist.wps** | WPS domain configuration | `/mnt/data/cases/<your_case>/namelist.wps` |
| **namelist.input** | WRF run configuration | `/mnt/data/cases/<your_case>/namelist.input` |
| **Vtable** | GRIB variable table (e.g., `Vtable.GFS`) | `/mnt/data/cases/<your_case>/Vtable` |
| **GFS GRIB2 files** | Boundary/initial conditions | `/mnt/data/cases/<your_case>/gfs_data/` |

Download WPS_GEOG from [UCAR's WRF Users Page](https://www2.mmm.ucar.edu/wrf/users/download/get_sources_wps_geog.html).

GFS data can be downloaded automatically with the provided script (see Step 2).

---

## Host Filesystem Permissions

On most Linux servers `/mnt` is owned by `root`. Before running any script, ensure your user has write access:

```bash
# Option A — give your user ownership of the working directory
sudo mkdir -p /mnt/data
sudo chown -R $USER:$USER /mnt/data

# Option B — use sudo for the setup script and then fix ownership
sudo ./scripts/setup_folders.sh <your_case_name>
sudo chown -R $USER:$USER /mnt/data
```

You can verify access with:

```bash
ls -ld /mnt/data
```

The output should show your username as owner. Without this step, the setup and download scripts will fail with `Permission denied`.

---

## Step 0 — Set Up Host Directory Structure

Run once to create the required folder skeleton on the host. **All scripts must be run from the repository root** (the folder that contains `Dockerfile.libs`, `Dockerfile.wrf`, etc.), not from inside the `scripts/` directory.

```bash
# Make sure you are at the repo root first
cd /path/to/wrf-docker-pipeline

chmod +x scripts/setup_folders.sh
sudo ./scripts/setup_folders.sh <your_case_name>
# Example: sudo ./scripts/setup_folders.sh my_experiment
```

**What it creates:**

```
/mnt/data/
├── WPS_GEOG/              # Place WPS_GEOG_FULL here manually
└── cases/
    └── <your_case_name>/
        ├── gfs_data/      # GFS GRIB2 files go here
        ├── output/        # Pipeline outputs land here
        ├── namelist.wps   # You must provide this
        ├── namelist.input # You must provide this
        └── Vtable         # You must provide this
```

---

## Step 1 — Build Docker Images

Build the three images in order. Each stage depends on the previous one.

> 💡 **Why `nohup`?** Stage 2 (WRF) can take 60–120 minutes. Without `nohup`, losing your SSH connection would kill the build and you would have to start over. Use `nohup` for any stage that may outlast your session, and monitor progress with `tail -f`.

```bash
# Stage 1: Base libraries (~10–15 min)
nohup docker build -f Dockerfile.libs -t wrf-libs-base:latest . > build_libs.log 2>&1 &
tail -f build_libs.log

# Stage 2: WRF compilation (~60–120 min) — nohup strongly recommended
nohup docker build -f Dockerfile.wrf -t wrf-compiled:latest . > build_wrf.log 2>&1 &
tail -f build_wrf.log

# Stage 3: WPS compilation (~10–20 min)
nohup docker build -f Dockerfile.wps -t wps-compiled:latest . > build_wps.log 2>&1 &
tail -f build_wps.log
```

Each `nohup` command returns immediately and runs the build in the background. The `tail -f` lets you watch progress live — you can safely close it with `Ctrl+C` and reconnect later with `tail -f build_wrf.log`.

**Validation:** After each stage, the Dockerfile validates that required executables exist. If any binary is missing, the build will fail with a clear error message.

Expected executables after Stage 2 (`wrf-compiled`):
- `main/wrf.exe`
- `main/real.exe`
- `main/ndown.exe`
- `main/tc.exe`

Expected executables after Stage 3 (`wps-compiled`):
- `geogrid.exe`
- `ungrib.exe`
- `metgrid.exe`

---

## Step 2 — Download GFS Boundary Data

```bash
chmod +x scripts/download_gfs.sh
./scripts/download_gfs.sh YYYYMMDD <your_case_name>
# Example: ./scripts/download_gfs.sh 20240815 my_experiment
```

**What it downloads:** GFS 0.25° GRIB2 files from NOAA NOMADS for the 12Z cycle, at 3-hourly intervals from f000 to f024.

**Required:** The NOMADS server (`nomads.ncep.noaa.gov`) must be accessible. Files older than ~10 days may not be available on the real-time server; use the NOAA archive instead.

**Outputs written to:** `/mnt/data/cases/<your_case_name>/gfs_data/`

---

## Step 3 — Run WPS Pre-processing

WPS processes the geographical domain and interpolates GFS meteorological data onto it.

```bash
chmod +x scripts/run_wps.sh
./scripts/run_wps.sh <your_case_name>
# Example: ./scripts/run_wps.sh my_experiment
```

**Inputs required (must exist before running):**

| File/Directory | Mount Point Inside Container | Purpose |
|---|---|---|
| `/mnt/data/WPS_GEOG/WPS_GEOG_FULL` | `/geog` | Static terrain/land-use data |
| `/mnt/data/cases/<case>/namelist.wps` | read from `/experimento` | Domain definition |
| `/mnt/data/cases/<case>/Vtable` | read from `/experimento` | GFS variable mapping |
| `/mnt/data/cases/<case>/gfs_data/*.grib2` | read from `/experimento/gfs_data` | Meteorological boundary data |

**Sub-steps executed inside the container:**

1. `geogrid.exe` — Defines the model grid and interpolates static geographical fields
2. `link_grib.csh` — Symlinks GRIB2 files for ungrib
3. `ungrib.exe` — Extracts and decodes meteorological fields from GRIB2
4. `metgrid.exe` — Horizontally interpolates met fields onto the model grid

**Outputs written to** `/mnt/data/cases/<your_case_name>/output/`:

| File | Description |
|---|---|
| `geo_em.d01.nc` | Geographical grid for domain 1 |
| `met_em.d01.YYYY-MM-DD_HH:mm:ss.nc` | Interpolated met fields (one per GFS time step) |

---

## Step 4 — Run WRF Simulation

Runs `real.exe` (initial/boundary condition preparation) followed by `wrf.exe` (the model itself). Launched with `nohup` in the background so the simulation survives terminal disconnects and SSH session drops.

> 💡 **Why `nohup`?** WRF simulations can take hours. Without `nohup`, closing your terminal or losing your SSH connection would kill the process. With `nohup`, the simulation keeps running and all output is captured in `simulation.log`.

```bash
chmod +x scripts/run_wrf.sh
./scripts/run_wrf.sh <your_case_name>
# Example: ./scripts/run_wrf.sh my_experiment
```

**Inputs required (must exist before running):**

| File | Source | Purpose |
|---|---|---|
| `met_em.d01.*.nc` | Output from Step 3 | Meteorological initial/boundary conditions |
| `namelist.input` | User-provided | WRF run configuration (time, physics, domain) |

**Sub-steps executed inside the container:**

1. `real.exe` — Creates WRF initial and boundary condition files
2. `wrf.exe` — Runs the numerical simulation

**Outputs written to** `/mnt/data/cases/<your_case_name>/output/`:

| File | Description |
|---|---|
| `wrfinput_d01` | Initial conditions for domain 1 |
| `wrfbdy_d01` | Boundary conditions for domain 1 |
| `wrfout_d01_YYYY-MM-DD_HH:00:00` | NetCDF forecast output (temperature, wind, precipitation, etc.) |

**Monitor progress:**

```bash
tail -f /mnt/data/cases/<your_case_name>/simulation.log
```

`wrf.exe` also writes detailed timing logs to `rsl.out.0000` and `rsl.error.0000` inside the container's working directory. These are not persisted to the host by default; add a volume mount if needed.

---

## Volume Mapping Summary

All containers are stateless. Data persists on the host via Docker volume mounts (`-v`):

| Host Path | Container Path | Used In |
|---|---|---|
| `/mnt/data/WPS_GEOG/WPS_GEOG_FULL` | `/geog` | WPS (Step 3) |
| `/mnt/data/cases/<case>` | `/experimento` | WPS (Step 3) + WRF (Step 4) |

---

## Customizing for Your Domain

To run for a different region or time period:

1. Edit `namelist.wps` — define your domain center, resolution, and date range
2. Edit `namelist.input` — match the domain and set your simulation start/end times
3. Download GFS data for your dates using `download_gfs.sh`
4. Use the appropriate `Vtable` for your input data source (`Vtable.GFS` for GFS)

The Dockerfiles and scripts require no modification for different domains.

---

## Tested Environment

- Host OS: Ubuntu 22.04 LTS
- Docker: 24.x
- WRF: v4.5.2 (serial, `em_real`)
- WPS: v4.5
- Compiler: gfortran/gcc 11 (Ubuntu default)
- NetCDF: system package (`libnetcdf-dev`, `libnetcdff-dev`)
- Jasper: 1.900.1 (compiled from source)

---

## License

This pipeline infrastructure is released under the MIT License. WRF and WPS are subject to their own licenses; see the [WRF GitHub repository](https://github.com/wrf-model/WRF) for details.

---

*Developed for reproducible numerical weather prediction research.*
