# Montería — City Domain

3 km convection-permitting domain centered on Montería, covering the city and approximately 180 km in all directions. Designed for high-resolution studies of the Sinú River valley, the Paramillo massif, and the Córdoba lowlands.

## Domain specs

| Parameter | Value |
|---|---|
| Resolution | 3 km |
| Grid | 121 × 121 cells |
| Center | 8.75°N, 75.88°W |
| Coverage | ~7.0°N–10.5°N, ~78.6°W–73.1°W |
| Projection | Mercator |
| Time step | 18 s |
| Cumulus scheme | None (`cu_physics = 0`) — convection-permitting |

## Coverage

- Montería and the Sinú River valley
- Paramillo National Park and Sierra Abibe
- Gulf of Urabá (western edge)
- Northern Antioquia and southern Córdoba
- Portions of Sucre and Bolívar departments

## Files

- `namelist.wps` — WPS domain configuration
- `namelist.input` — WRF physics and run configuration

## Usage

```bash
./scripts/run_wps.sh <case> namelist_examples/monteria/namelist.wps
./scripts/run_wrf.sh <case> namelist_examples/monteria/namelist.input
```

## Before running

Update `start_date` and `end_date` in both namelists to match
the date you downloaded with `download_gfs.sh`.

The `geog_data_path = '/geog'` must remain as-is — it points
to the volume mount inside the container.

## Note on convection-permitting resolution

At 3 km, cumulus parameterization is turned off (`cu_physics = 0`).
The model resolves convective cells explicitly. This requires
higher-quality boundary conditions and is more computationally
demanding than coarser domains.