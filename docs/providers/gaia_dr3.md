# Gaia DR3 — reference catalog

Status: **query builder and row → `CatalogSource` mapping implemented and tested offline (hand-constructed rows); network query not implemented; no live request made.** Epoch propagation and cross-matching (`skyshift/science/catalog.py`) are implemented and exercised with the simulated catalog.

- References: [Gaia DR3 documentation](https://gea.esac.esa.int/archive/documentation/GDR3/), [Astroquery Gaia TAP](https://docs.astropy.org/projects/astroquery/en/stable/gaia/gaia.html), [MAST Gaia resources](https://archive.stsci.edu/missions-and-data/gaia).
- Table pinned explicitly: `gaiadr3.gaia_source` (never a changing default; not EDR3). `build_cone_query` selects explicit columns with `TOP`.
- Reference epoch `ref_epoch` (J2016.0) is kept as `jyear` in **TCB**; converted to TDB with astropy, never relabelled UTC.
- `astrometric_params_solved`: 3 → 2-parameter (no parallax/pm; not propagated, uncertainty inflated), 31 → 5-parameter, 95 → 6-parameter. Correlations use Gaia column names. Missing radial velocity stays `None`.
- Matching: catalog positions propagated (space motion + observer parallax at each epoch) before matching; a padded search radius includes sources that move into the field; ambiguous/blended matches are kept; an unmatched source is not evidence of a new object; weak or negative parallaxes are never inverted.
- Planned live checks: one bounded DR3 cone query (row count, schema, units), propagation of a known high-proper-motion star, and recorded attribution. Acknowledgement to use once Gaia data are shown: "This work has made use of data from the European Space Agency (ESA) mission Gaia, processed by the Gaia Data Processing and Analysis Consortium (DPAC)."
