# TIS Location Data Roadmap

## Phase 1: Global Form Usability

Status: implemented in the current working tree.

Phase 1 intentionally keeps location data attached directly to an organization
or branch. It does not create shared locality records.

Included:

- Controlled country selection from the local dataset.
- Controlled region/state/province selection when dataset coverage exists.
- Dataset-backed city/locality selection.
- `Other / manual entry` fallback for missing regions and cities.
- Optional district and neighborhood fields, stored separately from city.
- Local cached APIs; no external location API dependency at runtime.
- Existing text location fields remain compatible with legacy Saudi data.

Manual region and city values are record-level values. They are not published
to other tenants and are not added to the imported dataset.

## Deferred Architecture

The following phases are roadmap items only. They are not part of Phase 1 and
must not be inferred from the current text-based storage model.

### Locality Registry

Create stable TIS locality identifiers and canonical locality records that are
independent from vendor dataset identifiers. Organizations and branches would
eventually reference these records while retaining display-name snapshots for
audit and migration compatibility.

### Locality Aliases

Support native names, translated names, transliterations, spelling variants,
and historical names. Alias matching should be region-aware and must not merge
places solely because their normalized names match.

### GeoNames and Official Dataset Enrichment

Build an offline enrichment process using GeoNames country dumps and, where
available, official national gazetteers. Source priority, licensing,
attribution, place classification, and duplicate resolution must be defined
before combining records.

### Tenant-Private City Additions

Allow an authorized tenant user to suggest a missing locality. New records
should initially be visible only to that tenant and must be constrained to the
tenant's organization scope.

### Platform Moderation

Provide a Platform Owner moderation queue for reviewing proposed localities,
potential duplicates, coordinates, place type, aliases, and source evidence.

### City Verification and Promotion

Support explicit states such as tenant-private, pending, verified, deprecated,
and merged. Promotion to the global catalog must be an audited platform action,
never an automatic consequence of a tenant entering free text.

### Dataset Refresh and ETL Workflow

Introduce versioned, offline imports with source checksums, staging tables,
coverage metrics, diff review, attribution records, and rollback support.
Referenced localities should be deprecated or merged rather than deleted.

## Guardrails for Future Work

- Preserve tenant isolation for all tenant-created locality data.
- Keep stable internal IDs separate from external source IDs.
- Retain source and license provenance for every imported record.
- Do not call public geocoding services from normal page requests.
- Do not modify the vendor JSON to store tenant-entered values.
- Migrate existing organization and branch text values without data loss.
