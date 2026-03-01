# Región Caribe Colombia

9 km resolution domain covering the full Colombian Caribbean coast, the Guajira Peninsula, the Sierra Nevada de Santa Marta, the islands of San Andrés and Providencia, and the adjacent Caribbean Sea.

## Domain specs

| Parameter | Value |
|---|---|
| Resolution | 9 km |
| Grid | 141 × 111 cells |
| Center | 9.5°N, 74.5°W |
| Coverage | ~4°N–15°N, ~85°W–64°W |
| Projection | Mercator |
| Time step | 54 s |
| Cumulus scheme | Tiedtke (`cu_physics = 6`) |

## Coverage

- North: Caribbean Sea + San Andrés and Providencia islands
- South: Northern Antioquia and Córdoba departments
- West: Gulf of Urabá + Panama border
- East: La Guajira + Venezuelan border

## Files

- `namelist.wps` — WPS domain configuration
- `namelist.input` — WRF physics and run configuration

## Usage

```bash
./scripts/run_wps.sh <case> namelist_examples/caribe-colombia/namelist.wps
./scripts/run_wrf.sh <case> namelist_examples/caribe-colombia/namelist.input
```

## Before running

Update `start_date` and `end_date` in both namelists to match
the date you downloaded with `download_gfs.sh`.

The `geog_data_path = '/geog'` must remain as-is — it points
to the volume mount inside the container.