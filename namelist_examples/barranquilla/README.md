# Barranquilla — City Domain

3 km convection-permitting domain centered on Barranquilla, covering the city and approximately 225 km in all directions. At this resolution, convective storms are resolved explicitly — no cumulus parameterization is applied.

## Domain specs

| Parameter | Value |
|---|---|
| Resolution | 3 km |
| Grid | 151 × 151 cells |
| Center | 10.97°N, 74.78°W |
| Coverage | ~8.9°N–13.0°N, ~77.6°W–71.9°W |
| Projection | Mercator |
| Time step | 18 s |
| Cumulus scheme | None (`cu_physics = 0`) — convection-permitting |

## Coverage

- Barranquilla metropolitan area
- Ciénaga Grande de Santa Marta
- Gulf of Morrosquillo
- Northern Bolívar and Magdalena departments
- Adjacent Caribbean Sea

## Files

- `namelist.wps` — WPS domain configuration
- `namelist.input` — WRF physics and run configuration

## Usage

```bash
./scripts/run_wps.sh <case> namelist_examples/barranquilla/namelist.wps
./scripts/run_wrf.sh <case> namelist_examples/barranquilla/namelist.input
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