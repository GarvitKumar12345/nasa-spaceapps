/* Generated from backend/skyshift/contracts.py (scripts/export_contracts.py + json2ts). Do not edit; run npm run gen:contracts. */

/**
 * Generated from backend/skyshift/contracts.py (skyshift.contracts/1). Do not edit.
 */
export interface SkyShiftContracts {
  ApiError?: ApiError;
  AssociationCandidate?: AssociationCandidate;
  AstrometricCalibration?: AstrometricCalibration;
  BackgroundInfo?: BackgroundInfo;
  Band?: Band;
  CatalogAssociation?: CatalogAssociation;
  CatalogOverlay?: CatalogOverlay;
  CatalogSource?: CatalogSource;
  ChangeIndicator?: ChangeIndicator;
  Coverage?: Coverage;
  CurveComponent?: CurveComponent;
  Dataset?: Dataset;
  DatasetReference?: DatasetReference;
  DatasetSummary?: DatasetSummary;
  DerivedQuantity?: DerivedQuantity;
  DetectedSource?: DetectedSource;
  DifferenceInfo?: DifferenceInfo;
  Epoch?: Epoch;
  EvidenceRecord?: EvidenceRecord;
  EvidenceSelection?: EvidenceSelection;
  EvidenceValidation?: EvidenceValidation;
  FieldDescription?: FieldDescription;
  FitInputs?: FitInputs;
  FitParameter?: FitParameter;
  FitRequest?: FitRequest;
  FitResidual?: FitResidual;
  FrameProduct?: FrameProduct;
  FrameTruth?: FrameTruth;
  HealthStatus?: HealthStatus;
  IdentifiabilityReport?: IdentifiabilityReport;
  InstrumentDescription?: InstrumentDescription;
  MaskBit?: MaskBit;
  MeasurementSet?: MeasurementSet;
  ModelComparison?: ModelComparison;
  ModelFit?: ModelFit;
  Observation?: Observation;
  ObservationTiming?: ObservationTiming;
  ObserverModel?: ObserverModel;
  PSFReference?: PSFReference;
  PredictionCurve?: PredictionCurve;
  PropagatedPosition?: PropagatedPosition;
  Provenance?: Provenance;
  ProviderCapability?: ProviderCapability;
  ProviderStatus?: ProviderStatus;
  Quality?: Quality;
  RegistrationSummary?: RegistrationSummary;
  ReproductionCheck?: ReproductionCheck;
  ReproductionReport?: ReproductionReport;
  ResolveResult?: ResolveResult;
  SimulationSection?: SimulationSection;
  SimulationTruth?: SimulationTruth;
  SkyPosition?: SkyPosition;
  SourceIdentity?: SourceIdentity;
  SourceMeasurement?: SourceMeasurement;
  SuiteRun?: SuiteRun;
  TestResult?: TestResult;
  TrackPoint?: TrackPoint;
  TruthPosition?: TruthPosition;
  TruthSource?: TruthSource;
  ValidationReport?: ValidationReport;
  ViewState?: ViewState;
  WCSDescription?: WCSDescription;
  WavelengthInfo?: WavelengthInfo;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ApiError".
 */
export interface ApiError {
  code:
    | "not_found"
    | "provider_unavailable"
    | "incompatible_frames"
    | "invalid_request"
    | "invalid_record"
    | "not_synthetic"
    | "not_available"
    | "internal_error";
  details: {
    [k: string]: unknown;
  };
  message: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "AssociationCandidate".
 */
export interface AssociationCandidate {
  catalog_source_id: string;
  /**
   * Mahalanobis distance using combined covariance
   */
  normalized_separation: number | null;
  propagated: PropagatedPosition;
  separation_arcsec: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "PropagatedPosition".
 */
export interface PropagatedPosition {
  catalog_source_id: string;
  corr_ra_dec: number | null;
  dec_deg: number;
  epoch: Epoch;
  includes_observer_parallax: boolean;
  includes_space_motion: boolean;
  method: string;
  notes: string[];
  origin: "model_prediction";
  ra_deg: number;
  sigma_dec_mas: number | null;
  sigma_ra_cosdec_mas: number | null;
}
/**
 * An instant with an explicit time scale.
 *
 * `value`/`format`/`scale` preserve the original convention (e.g. Gaia DR3
 * reference epoch 2016.0, jyear, TCB). `mjd_tdb` is derived by the backend
 * with astropy for model computations; `iso_utc` is a derived display value.
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Epoch".
 */
export interface Epoch {
  format: "isot" | "mjd" | "jd" | "jyear";
  /**
   * Derived display value (UTC ISO-8601)
   */
  iso_utc: string | null;
  /**
   * Derived: same instant as MJD in TDB
   */
  mjd_tdb: number;
  scale: "utc" | "tai" | "tt" | "tdb" | "tcb";
  value: number | string;
}
/**
 * Absolute zero point of the registered frame set against a reference catalog.
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "AstrometricCalibration".
 */
export interface AstrometricCalibration {
  /**
   * Catalog used, or None if the zero point is uncalibrated
   */
  catalog: string | null;
  catalog_origin: ("catalog" | "simulated") | null;
  method: string;
  method_version: string;
  n_used: number;
  notes: string[];
  offset_east_mas: number | null;
  offset_north_mas: number | null;
  quality: Quality;
  reference_frame_id: string;
  rms_residual_mas: number | null;
  rotation_deg: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Quality".
 */
export interface Quality {
  /**
   * Machine-readable flags, e.g. MASKED_PIXELS_IN_FIT
   */
  flags: string[];
  /**
   * Human-readable explanations
   */
  messages: string[];
  status: "ok" | "warning" | "pending" | "rejected" | "unavailable";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "BackgroundInfo".
 */
export interface BackgroundInfo {
  included_in_image: boolean;
  model_available: boolean;
  model_kind: string | null;
  notes: string[];
  /**
   * Whether SkyShift removes background; measurement fits a local constant term instead
   */
  subtracted_by_skyshift: boolean;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Band".
 */
export interface Band {
  center_um: number | null;
  /**
   * Set when a 'band' is a local-wavelength group of observed frames
   */
  compatibility: CompatibilityGroup | null;
  id: string;
  label: string;
  notes: string[];
  wavelength_model: "fixed_filter" | "position_dependent" | "unknown";
  width_um: number | null;
}
/**
 * Observations that may be compared or blinked at one sky position (observed SPHEREx data).
 *
 * Membership requires the same detector AND local wavelengths, evaluated at the
 * reference position, within the stated fraction of the local bandwidth.
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "CompatibilityGroup".
 */
export interface CompatibilityGroup {
  blinkable: boolean;
  detector: number | null;
  lambda_max_um: number | null;
  lambda_min_um: number | null;
  max_delta_fraction: number;
  member_observation_ids: string[];
  min_bandwidth_um: number | null;
  reason: string;
  reference_position: SkyPosition;
  rule: string;
  wavelength_determination: "position_lookup_visualization" | "calibration_product";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SkyPosition".
 */
export interface SkyPosition {
  dec_deg: number;
  /**
   * Epoch of this position, required for moving sources
   */
  epoch: Epoch | null;
  frame: "icrs";
  ra_deg: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "CatalogAssociation".
 */
export interface CatalogAssociation {
  candidates: AssociationCandidate[];
  criteria: string;
  epoch: Epoch;
  image_source_id: string;
  match_radius_arcsec: number;
  measurement_id: string | null;
  notes: string[];
  status: "matched" | "ambiguous" | "unmatched" | "not_evaluated";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "CatalogOverlay".
 */
export interface CatalogOverlay {
  catalog: string;
  catalog_origin: "catalog" | "simulated";
  dataset_id: string;
  epoch: Epoch;
  frame_id: string;
  notes: string[];
  padding_note: string;
  propagated: PropagatedPosition[];
  search_center: SkyPosition;
  search_radius_deg: number;
  sources: CatalogSource[];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "CatalogSource".
 */
export interface CatalogSource {
  astrometric_params_solved: number | null;
  astrometric_solution: "2-parameter" | "5-parameter" | "6-parameter" | "unknown";
  /**
   * Exact table, e.g. 'gaiadr3.gaia_source'
   */
  catalog: string;
  catalog_release: string;
  /**
   * Gaia-style e.g. ra_dec_corr
   */
  correlations: {
    [k: string]: number;
  };
  dec_deg: number;
  dec_error_mas: number | null;
  /**
   * e.g. 'gaiadr3:<source_id>' or 'simcat:<n>'
   */
  id: string;
  origin: "catalog" | "simulated";
  parallax_error_mas: number | null;
  parallax_mas: number | null;
  photometry: {
    [k: string]: number | null;
  };
  pmdec_error_mas_yr: number | null;
  pmdec_mas_yr: number | null;
  pmra_error_mas_yr: number | null;
  /**
   * dRA/dt * cos(Dec)
   */
  pmra_mas_yr: number | null;
  provenance: Provenance;
  quality: Quality;
  quality_indicators: {
    [k: string]: number | null;
  };
  ra_deg: number;
  /**
   * sigma of RA*cos(Dec) in mas (Gaia ra_error convention)
   */
  ra_error_mas: number | null;
  radial_velocity_error_km_s: number | null;
  radial_velocity_km_s: number | null;
  reference_epoch: Epoch;
  uncertainty_status: "estimated" | "propagated" | "catalog_reported" | "not_available" | "not_applicable";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Provenance".
 */
export interface Provenance {
  dataset_id: string | null;
  /**
   * Dotted SkyShift function or archive process that produced this
   */
  method: string | null;
  method_version: string | null;
  notes: string[];
  origin: "observed" | "simulated" | "simulation_truth" | "derived_measurement" | "model_prediction" | "catalog";
  /**
   * IDs of the inputs this product was derived from
   */
  parents: string[];
  processing_version: string | null;
  provider: ("synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat") | "skyshift";
  /**
   * Data release / collection label exactly as the provider names it
   */
  release: string | null;
  retrieved_utc: string | null;
  software: SoftwareVersion[];
  source_url: string | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SoftwareVersion".
 */
export interface SoftwareVersion {
  name: string;
  version: string;
}
/**
 * Derived statistics from measured positions/fluxes. Not a classification.
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ChangeIndicator".
 */
export interface ChangeIndicator {
  description: string;
  kind: "displacement" | "flux_variation";
  n_epochs: number;
  /**
   * True if statistic exceeds the stated threshold
   */
  significant: boolean | null;
  statistic: number | null;
  threshold: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Coverage".
 */
export interface Coverage {
  /**
   * Corner (ra_deg, dec_deg) of the valid region, in order
   */
  footprint_icrs: [number, number][];
  mask_plane: "mask" | null;
  nan_marks_no_coverage: boolean;
  valid_fraction: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "CurveComponent".
 */
export interface CurveComponent {
  dec_offset_mas: number[];
  ra_cosdec_offset_mas: number[];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Dataset".
 */
export interface Dataset {
  archive_query: ArchiveQuerySummary | null;
  astrometric_calibration: AstrometricCalibration | null;
  bands: Band[];
  /**
   * Empty = all analyses available
   */
  capabilities: AnalysisCapability[];
  common_grid: WCSDescription;
  description: string;
  field: FieldDescription;
  frames: FrameProduct[];
  generator: string | null;
  generator_version: string | null;
  id: string;
  instrument: InstrumentDescription;
  limitations: string[];
  observations: Observation[];
  origin: "observed" | "simulated";
  provenance: Provenance;
  provider: "synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat";
  quality: Quality;
  /**
   * band_id -> frame_id used as registration reference
   */
  reference_frame_ids: {
    [k: string]: string;
  };
  release: string;
  scenario_parameters: {
    [k: string]: unknown;
  } | null;
  seed: number | null;
  title: string;
}
/**
 * How an observed dataset was assembled from an archive (see its retrieval manifest).
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ArchiveQuerySummary".
 */
export interface ArchiveQuerySummary {
  collection: string;
  manifest_path: string;
  n_downloaded: number;
  n_failed: number;
  n_rows: number;
  n_screen_failed: number;
  n_screened: number;
  n_selected: number;
  n_superseded: number;
  notes: string[];
  provider: "synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat";
  query_url: string;
  retrieved_utc: string;
  selection_rule: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "AnalysisCapability".
 */
export interface AnalysisCapability {
  id:
    | "source_detection"
    | "source_measurement"
    | "astrometric_fit"
    | "difference_imaging"
    | "catalog_overlay"
    | "evidence_record"
    | "registration";
  reason: string | null;
  /**
   * What must be implemented and validated first
   */
  requirements: string[];
  status: "available" | "unavailable";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "WCSDescription".
 */
export interface WCSDescription {
  distortion: "none" | "sip" | "tpv" | "other";
  /**
   * FITS WCS keywords (CRPIX is FITS 1-based)
   */
  header: {
    [k: string]: number | string;
  };
  kind: "native_header" | "registered" | "common_grid" | "simulation_truth";
  pixel_convention: "0-based-centers";
  /**
   * (ny, nx) of the pixel grid this WCS describes
   *
   * @minItems 2
   * @maxItems 2
   */
  shape: [number, number];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FieldDescription".
 */
export interface FieldDescription {
  center: SkyPosition;
  ecliptic_lat_deg: number | null;
  fov_arcsec: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FrameProduct".
 */
export interface FrameProduct {
  background: BackgroundInfo;
  band_id: string;
  coverage: Coverage;
  dataset_id: string;
  derived_covariance_note: string | null;
  /**
   * True for reprojected products: never a measurement input
   */
  display_only: boolean;
  id: string;
  /**
   * native: original arrays; registered: SkyShift-registered display product; archive_wcs_reprojection: display product aligned only by the archive's header WCS (not registered by SkyShift)
   */
  kind: "native" | "registered" | "archive_wcs_reprojection";
  mask_bits: MaskBit[];
  observation_id: string;
  planes: ("image" | "variance" | "mask")[];
  provenance: Provenance;
  psf: PSFReference;
  quality: Quality;
  registration: RegistrationSummary | null;
  /**
   * (ny, nx)
   *
   * @minItems 2
   * @maxItems 2
   */
  shape: [number, number];
  /**
   * astropy unit string of the image plane, e.g. 'electron' or 'MJy / sr'
   */
  unit: string;
  unit_kind: "counts" | "surface_brightness" | "flux_density" | "dimensionless";
  variance_unit: string | null;
  wavelength: WavelengthInfo;
  wcs: WCSDescription;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "MaskBit".
 */
export interface MaskBit {
  bit: number;
  description: string;
  name: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "PSFReference".
 */
export interface PSFReference {
  fwhm_arcsec: number | null;
  /**
   * True if evaluating the model already integrates over the pixel response
   */
  includes_pixel_response: boolean;
  model: "gaussian_pixel_integrated" | "effective_psf_product" | "unknown";
  oversampling: number | null;
  product_format_version: string | null;
  /**
   * Archive product / extension name for an ePSF
   */
  product_ref: string | null;
  source: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "RegistrationSummary".
 */
export interface RegistrationSummary {
  chi2_per_dof: number | null;
  /**
   * Sources rejected as non-stationary/outliers
   */
  excluded_source_ids: string[];
  median_abs_residual_mas: number | null;
  method: string;
  method_version: string;
  n_matched: number;
  n_rejected: number;
  n_used: number;
  quality: Quality;
  /**
   * 'frame:<frame_id>' or 'catalog:<catalog>'
   */
  reference: string;
  rms_residual_mas: number | null;
  /**
   * dx_px, dy_px, rotation_deg, scale (native -> reference)
   */
  transform: {
    [k: string]: number;
  };
  transform_uncertainty: {
    [k: string]: number;
  };
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "WavelengthInfo".
 */
export interface WavelengthInfo {
  band_id: string;
  /**
   * e.g. CWAVE/CBAND product reference for SPHEREx
   */
  calibration_ref: string | null;
  center_um: number | null;
  determination: "band_definition" | "position_lookup_visualization" | "calibration_product" | "unknown";
  notes: string[];
  position_dependent: boolean;
  width_um: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "InstrumentDescription".
 */
export interface InstrumentDescription {
  /**
   * (ny, nx)
   *
   * @minItems 2
   * @maxItems 2
   */
  detector_shape: [number, number];
  full_well_e: number | null;
  gain_e_per_adu: number | null;
  kind: "generic_synthetic" | "spherex" | "wise" | "neossat";
  name: string;
  notes: string[];
  pixel_scale_arcsec: number;
  psf_by_band: {
    [k: string]: PSFReference;
  };
  read_noise_e: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Observation".
 */
export interface Observation {
  archive: ArchiveObservationInfo | null;
  band_id: string;
  dataset_id: string;
  detector: string | null;
  /**
   * Native and registered product IDs
   */
  frame_ids: string[];
  id: string;
  instrument: string;
  observer: ObserverModel;
  /**
   * Nominal pointing centre from the header
   */
  pointing: SkyPosition | null;
  provenance: Provenance;
  provider: "synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat";
  quality: Quality;
  status: "available" | "missing" | "failed" | "pending";
  status_reason: string | null;
  timing: ObservationTiming;
}
/**
 * Archive identity, local wavelength and file checks of one observed product.
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ArchiveObservationInfo".
 */
export interface ArchiveObservationInfo {
  access_url: string;
  bandpass_name: string;
  bytes: number | null;
  /**
   * HISTORY [CALIB] product -> identifier
   */
  calibration_refs: {
    [k: string]: string;
  };
  collection: string;
  cutout_url: string | null;
  detector: number;
  edge_margin_px: number | null;
  file_name: string;
  /**
   * Flag names set within the documented 2.5 px radius
   */
  flags_near_query: string[];
  header_quality: {
    [k: string]: number | string | boolean;
  };
  local_bandwidth_um: number | null;
  local_wavelength_um: number | null;
  obs_id: string;
  obs_publisher_did: string | null;
  pipeline_version: string | null;
  processing_tag: string;
  /**
   * 0-based cutout pixel of the query position
   */
  query_pixel_cutout: [number, number] | null;
  /**
   * 0-based detector pixel of the query position
   */
  query_pixel_detector: [number, number] | null;
  release: string;
  retrieved_utc: string | null;
  sha256: string | null;
  validation: FileCheck[];
  /**
   * |astropy -TAB - independent bilinear| at the query pixel
   */
  wavelength_crosscheck_um: number | null;
  wavelength_method: string;
}
/**
 * One executed check of an archive file against its documented format.
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FileCheck".
 */
export interface FileCheck {
  detail: string;
  id: string;
  reference: string | null;
  status: "pass" | "warn" | "fail";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ObserverModel".
 */
export interface ObserverModel {
  approximation_note: string | null;
  /**
   * e.g. 'astropy builtin (ERFA epv00)'
   */
  ephemeris: string | null;
  kind: "geocenter" | "spacecraft_ephemeris" | "solar_system_barycenter" | "circular_1au_approximation";
  /**
   * Quantified bound on the observer-position error of this approximation
   */
  max_position_error_km: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ObservationTiming".
 */
export interface ObservationTiming {
  exposure_s: number;
  mid: Epoch;
  mid_derivation: string;
  /**
   * Raw timing keywords as recorded
   */
  raw: {
    [k: string]: number | string;
  };
  start: Epoch;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "DatasetReference".
 */
export interface DatasetReference {
  dataset_id: string;
  generator: string | null;
  generator_version: string | null;
  origin: "observed" | "simulated";
  provider: "synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat";
  release: string;
  scenario_parameters: {
    [k: string]: unknown;
  } | null;
  seed: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "DatasetSummary".
 */
export interface DatasetSummary {
  availability: "ready" | "partial" | "not_fetched";
  availability_note: string | null;
  bands: string[];
  description: string;
  id: string;
  n_available_frames: number;
  n_observations: number;
  origin: "observed" | "simulated";
  provider: "synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat";
  release: string;
  time_range_utc: [string, string] | null;
  title: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "DerivedQuantity".
 */
export interface DerivedQuantity {
  name: string;
  reason: string;
  status: "derived" | "not_derived";
  uncertainty: number | null;
  unit: string;
  value: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "DetectedSource".
 */
export interface DetectedSource {
  band_id: string;
  change_indicators: ChangeIndicator[];
  dataset_id: string;
  detected_in_frame_id: string;
  flux: number | null;
  flux_err: number | null;
  flux_unit: string;
  id: string;
  label: string;
  origin: "derived_measurement";
  position: SkyPosition;
  quality: Quality;
  sigma_dec_mas: number | null;
  sigma_ra_cosdec_mas: number | null;
  snr: number | null;
  /**
   * Per-frame linked positions (derived)
   */
  track: TrackPoint[];
  x_px: number;
  y_px: number;
}
/**
 * Per-frame linked position of a detected source (derived; for selection/overlay).
 *
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "TrackPoint".
 */
export interface TrackPoint {
  dec_deg: number | null;
  frame_id: string;
  ra_deg: number | null;
  status: "measured" | "not_detected" | "ambiguous" | "outside_coverage" | "missing_frame" | "rejected";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "DifferenceInfo".
 */
export interface DifferenceInfo {
  checks: {
    [k: string]: boolean | number | string;
  };
  compatible: boolean;
  frame_a: string;
  frame_b: string;
  label: string;
  origin: "derived_measurement";
  reasons: string[];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "EvidenceRecord".
 */
export interface EvidenceRecord {
  assumptions: string[];
  contracts_version: string;
  created_utc: string;
  dataset: DatasetReference;
  fit: ModelFit | null;
  fit_status: "current" | "stale" | "none";
  id: string;
  included_measurement_ids: string[];
  measurements: SourceMeasurement[];
  notes: string;
  provenance: Provenance;
  quality_flags: string[];
  record_label: "synthetic training record" | "candidate for review";
  schema_version: "skyshift.evidence/1";
  selection: EvidenceSelection;
  simulation: SimulationSection | null;
  source: SourceIdentity;
  title: string;
  updated_utc: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ModelFit".
 */
export interface ModelFit {
  assumptions: string[];
  band_ids: string[];
  chi2: number | null;
  comparisons: ModelComparison[];
  covariance: number[][] | null;
  covariance_parameters: string[];
  dataset_id: string;
  derived: DerivedQuantity[];
  dof: number;
  id: string;
  identifiability: IdentifiabilityReport;
  /**
   * sha256 of canonical FitInputs + included measurement values
   */
  input_hash: string;
  inputs: FitInputs;
  method: string;
  method_version: string;
  model: "static" | "proper_motion" | "proper_motion_parallax";
  model_description: string;
  origin: "derived_measurement";
  p_value: number | null;
  parameters: FitParameter[];
  prediction: PredictionCurve | null;
  provenance: Provenance;
  reduced_chi2: number | null;
  reference_epoch: Epoch;
  residuals: FitResidual[];
  source_id: string;
  status: "ok" | "warning" | "pending" | "rejected" | "unavailable";
  warnings: string[];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ModelComparison".
 */
export interface ModelComparison {
  bic: number | null;
  chi2: number | null;
  dof: number;
  model: "static" | "proper_motion" | "proper_motion_parallax";
  status: "fit" | "underconstrained" | "insufficient_data";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "IdentifiabilityReport".
 */
export interface IdentifiabilityReport {
  /**
   * Of the column-normalised weighted design matrix
   */
  condition_number: number | null;
  dof: number;
  max_abs_correlation: number | null;
  messages: string[];
  n_epochs: number;
  n_measurements: number;
  n_parameters: number;
  /**
   * (span of RA* factor, span of Dec factor), dimensionless
   */
  parallax_factor_span: [number, number] | null;
  status: "constrained" | "weakly_constrained" | "underconstrained" | "insufficient_data";
  thresholds: {
    [k: string]: number;
  };
  time_baseline_yr: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FitInputs".
 */
export interface FitInputs {
  excluded_measurement_ids: string[];
  /**
   * Measurements included in the fit, in order
   */
  measurement_ids: string[];
  model: "static" | "proper_motion" | "proper_motion_parallax";
  observer: ObserverModel;
  reference_epoch_mjd_tdb: number;
  reference_position: SkyPosition;
  settings: {
    [k: string]: number | string | boolean;
  };
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FitParameter".
 */
export interface FitParameter {
  label: string;
  /**
   * offset_ra_cosdec | offset_dec | pmra | pmdec | parallax
   */
  name: string;
  status: "estimated" | "fixed" | "not_constrained" | "not_in_model";
  uncertainty: number | null;
  unit: string;
  value: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "PredictionCurve".
 */
export interface PredictionCurve {
  /**
   * e.g. 'proper_motion', 'parallax' contributions
   */
  components: {
    [k: string]: CurveComponent;
  };
  dec_offset_mas: number[];
  note: string;
  origin: "model_prediction";
  ra_cosdec_offset_mas: number[];
  sigma_dec_mas: number[] | null;
  sigma_ra_cosdec_mas: number[] | null;
  t_mjd_tdb: number[];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FitResidual".
 */
export interface FitResidual {
  d_dec_mas: number;
  d_ra_cosdec_mas: number;
  epoch_mjd_tdb: number;
  included: boolean;
  measurement_id: string;
  normalized_dec: number;
  normalized_ra: number;
  sigma_dec_mas: number;
  sigma_ra_cosdec_mas: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SourceMeasurement".
 */
export interface SourceMeasurement {
  association_note: string | null;
  band_id: string;
  corr_ra_dec: number | null;
  cov_xy_px: [[number, number], [number, number]] | null;
  dataset_id: string;
  dec_deg: number | null;
  epoch: Epoch;
  fit_chi2_reduced: number | null;
  flux: number | null;
  flux_err: number | null;
  flux_unit: string | null;
  frame_id: string;
  /**
   * Deterministic: <dataset>:<source>:<frame>:<method>
   */
  id: string;
  method: "psf_gaussian_fit" | "windowed_centroid";
  method_version: string;
  n_pixels: number | null;
  observation_id: string;
  origin: "derived_measurement";
  provenance: Provenance;
  psf_fwhm_arcsec: number | null;
  quality: Quality;
  ra_deg: number | null;
  /**
   * e.g. {'centroid': .., 'registration': ..}
   */
  sigma_components_mas: {
    [k: string]: number;
  };
  sigma_dec_mas: number | null;
  sigma_ra_cosdec_mas: number | null;
  snr: number | null;
  source_id: string;
  status: "measured" | "pending" | "rejected" | "not_detected" | "missing_frame" | "outside_coverage" | "ambiguous";
  status_reason: string | null;
  uncertainty_status: "estimated" | "propagated" | "catalog_reported" | "not_available" | "not_applicable";
  /**
   * e.g. 'registered:<frame_id>'
   */
  wcs_used: string | null;
  /**
   * Native frame, 0-based pixel centres
   */
  x_px: number | null;
  y_px: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "EvidenceSelection".
 */
export interface EvidenceSelection {
  band_ids: string[];
  epochs: Epoch[];
  frame_ids: string[];
  observation_ids: string[];
  view: ViewState;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ViewState".
 */
export interface ViewState {
  band_id: string | null;
  /**
   * Common-grid pixel at the viewer centre
   */
  center_x_px: number | null;
  center_y_px: number | null;
  compare_frame_id: string | null;
  fov_arcsec: number | null;
  frame_id: string | null;
  mode: "explore" | "analyze";
  /**
   * Display-only settings
   */
  stretch: {
    [k: string]: number | string;
  };
  zoom: number | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SimulationSection".
 */
export interface SimulationSection {
  generator: string;
  generator_version: string;
  seed: number;
  /**
   * Truth for this record's sources only; separate from measurements
   */
  truth: SimulationTruth | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SimulationTruth".
 */
export interface SimulationTruth {
  dataset_id: string;
  frames: FrameTruth[];
  generator: string;
  generator_version: string;
  origin: "simulation_truth";
  /**
   * Per-frame true positions for non-stationary truth sources
   */
  positions: TruthPosition[];
  scenario_parameters: {
    [k: string]: unknown;
  };
  seed: number;
  sources: TruthSource[];
  warning: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FrameTruth".
 */
export interface FrameTruth {
  frame_id: string;
  /**
   * @minItems 2
   * @maxItems 2
   */
  header_error_arcsec: [number, number];
  header_rotation_error_deg: number;
  /**
   * @minItems 2
   * @maxItems 2
   */
  pointing_offset_px: [number, number];
  rotation_deg: number;
  true_wcs: WCSDescription;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "TruthPosition".
 */
export interface TruthPosition {
  dec_deg: number;
  flux: number;
  frame_id: string;
  ra_deg: number;
  truth_id: string;
  x_px: number;
  y_px: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "TruthSource".
 */
export interface TruthSource {
  dec_deg: number;
  /**
   * Mean flux in electrons per exposure
   */
  flux_by_band: {
    [k: string]: number;
  };
  in_simulated_catalog: boolean;
  kind: "stationary_star" | "moving_nearby_source" | "variable_star";
  /**
   * Validation-only association to a detection
   */
  matched_detected_source_id: string | null;
  origin: "simulation_truth";
  parallax_mas: number;
  pmdec_mas_yr: number;
  pmra_mas_yr: number;
  ra_deg: number;
  radial_velocity_km_s: number;
  reference_epoch: Epoch;
  truth_id: string;
  variability: {
    [k: string]: number;
  } | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SourceIdentity".
 */
export interface SourceIdentity {
  catalog_associations: CatalogAssociation[];
  label: string;
  origin: "derived_measurement";
  reference_position: SkyPosition;
  source_id: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "EvidenceValidation".
 */
export interface EvidenceValidation {
  errors: string[];
  fit_input_hash_matches: boolean | null;
  recomputed_fit_status: "current" | "stale" | "none";
  /**
   * Normalised record when valid
   */
  record: EvidenceRecord | null;
  valid: boolean;
  warnings: string[];
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "FitRequest".
 */
export interface FitRequest {
  dataset_id: string;
  excluded_measurement_ids: string[];
  measurements: SourceMeasurement[];
  model: "static" | "proper_motion" | "proper_motion_parallax";
  /**
   * Default: mean epoch of included measurements
   */
  reference_epoch_mjd_tdb: number | null;
  source_id: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "HealthStatus".
 */
export interface HealthStatus {
  contracts_version: string;
  skyshift_version: string;
  software: SoftwareVersion[];
  status: "ok";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "MeasurementSet".
 */
export interface MeasurementSet {
  association_method: string;
  band_ids: string[];
  dataset_id: string;
  measurements: SourceMeasurement[];
  method: "psf_gaussian_fit" | "windowed_centroid";
  method_version: string;
  notes: string[];
  source_id: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ProviderCapability".
 */
export interface ProviderCapability {
  checked_utc: string | null;
  detail: string;
  name: string;
  status: "documented" | "implemented" | "tested" | "failed" | "unavailable" | "not_run" | "not_implemented";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ProviderStatus".
 */
export interface ProviderStatus {
  access_route: string;
  capabilities: ProviderCapability[];
  id: "synthetic" | "spherex" | "gaia_dr3" | "wise" | "neossat";
  last_reviewed_utc: string | null;
  name: string;
  notes: string[];
  references: Reference[];
  release_policy: string;
  role: "image" | "catalog" | "image+catalog";
  status: "documented" | "implemented" | "tested" | "failed" | "unavailable" | "not_run" | "not_implemented";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "Reference".
 */
export interface Reference {
  title: string;
  url: string;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ReproductionCheck".
 */
export interface ReproductionCheck {
  abs_diff: number | null;
  passed: boolean;
  quantity: string;
  reproduced: number | null;
  saved: number | null;
  tolerance: number;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ReproductionReport".
 */
export interface ReproductionReport {
  checks: ReproductionCheck[];
  reason: string;
  reproducible: boolean;
  software: SoftwareVersion[];
  status: "reproduced" | "mismatch" | "not_reproducible";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ResolveResult".
 */
export interface ResolveResult {
  in_dataset_field: boolean | null;
  kind: "coordinates" | "source_id" | "unresolved";
  message: string;
  position: SkyPosition | null;
  query: string;
  source_id: string | null;
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "SuiteRun".
 */
export interface SuiteRun {
  command: string | null;
  counts: {
    [k: string]: number;
  };
  duration_s: number | null;
  note: string | null;
  ran: boolean;
  started_utc: string | null;
  suite: "pytest" | "vitest" | "playwright";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "TestResult".
 */
export interface TestResult {
  category: string;
  duration_s: number | null;
  file: string | null;
  id: string;
  message: string | null;
  name: string;
  status: "passed" | "failed" | "skipped" | "error" | "not_run";
  suite: "pytest" | "vitest" | "playwright";
}
/**
 * This interface was referenced by `SkyShiftContracts`'s JSON-Schema
 * via the `definition` "ValidationReport".
 */
export interface ValidationReport {
  /**
   * False when no report file exists yet
   */
  available: boolean;
  /**
   * Filled by the API at request time
   */
  current_source_hash: string | null;
  environment: {
    [k: string]: string;
  };
  generated_utc: string | null;
  results: TestResult[];
  schema_version: "skyshift.validation/1";
  source_hash: string | null;
  /**
   * True if sources changed since the report was generated
   */
  stale: boolean | null;
  suites: SuiteRun[];
}
