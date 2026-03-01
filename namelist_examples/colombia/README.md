# Colombia — Full Country Domain

27 km resolution domain covering the full extent of Colombia, from La Guajira in the north to the Amazon basin in the south, and from the Pacific coast to the Llanos Orientales. Suitable for national-scale weather forecasting and climatological studies.

## Domain specs

| Parameter | Value |
|---|---|
| Resolution | 27 km |
| Grid | 120 × 160 cells |
| Center | 3.5°N, 73.5°W |
| Coverage | ~12°N–4°S, ~83°W–64°W |
| Projection | Mercator |
| Time step | 162 s |
| Cumulus scheme | Tiedtke (`cu_physics = 6`) |

## Coverage

- North: La Guajira Peninsula + Caribbean Sea
- South: Amazon basin (Amazonas, Vaupés, Guainía)
- West: Pacific coast + Chocó
- East: Llanos Orientales + Venezuelan border

## Files

- `namelist.wps` — WPS domain configuration
- `namelist.input` — WRF physics and run configuration

## Usage

```bash
./scripts/run_wps.sh <case> namelist_examples/colombia/namelist.wps
./scripts/run_wrf.sh <case> namelist_examples/colombia/namelist.input
```

## Before running

Update `start_date` and `end_date` in both namelists to match
the date you downloaded with `download_gfs.sh`.

The `geog_data_path = '/geog'` must remain as-is — it points
to the volume mount inside the container.
