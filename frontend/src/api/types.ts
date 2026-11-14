/* Literal aliases derived from the generated contracts (so they cannot drift). */
import type { Epoch, ModelFit, Observation, Provenance, ProviderStatus, Quality, SourceMeasurement, TestResult } from './contracts.gen'

export type * from './contracts.gen'
export type DataOrigin = Provenance['origin']
export type IntegrationStatus = ProviderStatus['status']
export type QualityLevel = Quality['status']
export type MeasurementStatus = SourceMeasurement['status']
export type AstrometricModel = ModelFit['model']
export type TimeScale = Epoch['scale']
export type ObservationStatus = Observation['status']
export type TestStatus = TestResult['status']
