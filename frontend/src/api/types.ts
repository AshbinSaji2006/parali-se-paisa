import { z } from 'zod';
import type { Geometry } from 'geojson';

export type User = {user_id:string; username:string; role:'ADMIN'|'OFFICIAL'|'FARMER'|'BUYER'|'BALER_OPERATOR'; field_id:string|null; baler_id:string|null; buyer_id:string|null; is_demo:boolean};
export type Values = Record<string, string|number|boolean|null|undefined>;
export interface Intelligence {
  field_status:{status_candidate:string|null;method:string;confidence_band?:string;evidence:string[]};
  straw:{eligible:boolean;reason?:string;area_ha?:number;baseline_yield_t_per_ha?:number;baseline_straw_tonnes?:number;vegetation_adjustment?:number;estimated_straw_tonnes?:number;adjusted_straw_tonnes?:number;lower_estimate_tonnes?:number;upper_estimate_tonnes?:number;estimate_method?:string};
  burn_risk:{risk_score:number|null;risk_level?:string;method:string;score_kind:string;top_factors?:string[];availability?:Record<string,boolean>};
  provenance:{observation_datetime?:string;fixture_or_real:string;model_trust_state:string};
}
export interface FieldRecord {
  field_id:string;district:string|null;village:string|null;area_ha:number|null;geometry:Geometry|null;
  centroid:{latitude:number|null;longitude:number|null};provenance:string;source:string|null;
  properties:{latest_features?:Values};intelligence:Intelligence;
  eligibility:{eligible:boolean;reasons:string[];warnings:string[]};
  history:{observation_datetime:string;features:Values;provenance:string}[];
}
export interface Baler {baler_id:string;name:string;status:string;latitude:number;longitude:number;current_location_lat:number|null;current_location_lon:number|null;working_start:string;working_end:string;available_from:string|null;service_rate_acres_per_hour:number;daily_capacity_acres:number;max_straw_capacity_tonnes:number|null;demo_or_real:string}
export interface Buyer {buyer_id:string;name:string;buyer_type:string;latitude:number;longitude:number;daily_demand_tonnes:number;remaining_demand_tonnes:number;accepted_residue_types:string[];status:string;demo_or_real:string;price_is_verified:boolean;price_per_tonne:number|null;operating_start:string;operating_end:string}
export interface Job {job_id:string;dispatch_run_id:string;field_id:string;baler_id:string;buyer_id:string;state:string;provenance:string}
export interface Run {dispatch:{dispatch_run_id:string;method:string;solver_status:string;distance_method:string;baler_routes:{baler_id:string;total_distance_km:number;distance_method:string;estimated_service_minutes:number;estimated_travel_minutes:number|null;assigned_straw_tonnes:number;stops:{field_id:string;buyer_id:string;sequence:number;estimated_straw_tonnes:number}[]}[];unserved_fields:{field_id:string;reason:string;details:string[]}[]};buyer_matching:{allocations:{field_id:string;buyer_id:string;allocated_tonnes:number}[]}}
export interface Observation {verification_observation_id:string;observation_datetime:string;observation_quality:string;ndvi:number|null;nbr:number|null;bais2:number|null;firms_nearby:boolean|null;evidence:string;evidence_reasons:string[];source_image_id_s2:string|null;source_image_id_s1:string|null;field_status_candidate:string|null}
export interface Verification {verification_id:string;field_id:string;state:string;monitoring_start:string;monitoring_deadline:string;provenance:string;reasons:string[];observations:Observation[]}
export interface Certificate {certificate_id:string;field_id:string;verification_id:string;sha256:string;provenance:string;pdf_available:boolean;qr_available?:boolean;metadata:{monitoring_start:string;monitoring_end:string;generated_at:string;verification_status:string;prototype_disclaimer:string;verification_method:string;satellite_observation_count?:number};integrity_valid?:boolean;integrity_scope?:string}
export interface Snapshot {fields:FieldRecord[];balers:Baler[];buyers:Buyer[];jobs:Job[];runs:Run[];verification:Verification[];certificates:Certificate[];allocations:{field_id:string;buyer_id:string;allocated_tonnes:number;dispatch_run_id:string;match:{distance_km?:number;distance_method?:string}}[];pickup_requests:{field_id:string;request_id:string;created_at:string}[];stats:Record<string,number>;generated_at:string}
export interface SystemStatus {mode:string;demo_mode:boolean;live_verified:boolean;providers:Record<string,string>;notice:string;ephemeral_jwt_key:boolean}

// Runtime boundary checks complement generated OpenAPI request types. A changed
// critical response fails visibly instead of silently displaying wrong data.
export const snapshotSchema = z.object({
  fields:z.array(z.object({field_id:z.string(),provenance:z.string(),centroid:z.object({latitude:z.number().nullable(),longitude:z.number().nullable()}),
    intelligence:z.object({field_status:z.object({status_candidate:z.string().nullable(),method:z.string(),evidence:z.array(z.string())}).passthrough(),
      burn_risk:z.object({risk_score:z.number().min(0).max(1).nullable(),score_kind:z.string(),method:z.string()}).passthrough(),straw:z.object({eligible:z.boolean()}).passthrough(),
      provenance:z.object({fixture_or_real:z.string(),model_trust_state:z.string()}).passthrough()}).passthrough(),
    eligibility:z.object({eligible:z.boolean(),reasons:z.array(z.string()),warnings:z.array(z.string())}),history:z.array(z.object({observation_datetime:z.string(),features:z.record(z.string(),z.unknown()),provenance:z.string()}))}).passthrough()),
  balers:z.array(z.object({baler_id:z.string(),demo_or_real:z.string()}).passthrough()), buyers:z.array(z.object({buyer_id:z.string(),remaining_demand_tonnes:z.number(),demo_or_real:z.string()}).passthrough()),
  jobs:z.array(z.object({job_id:z.string(),state:z.string(),field_id:z.string()}).passthrough()),runs:z.array(z.object({dispatch:z.object({baler_routes:z.array(z.unknown()),unserved_fields:z.array(z.unknown())}).passthrough(),buyer_matching:z.object({allocations:z.array(z.unknown())}).passthrough()})),
  verification:z.array(z.object({verification_id:z.string(),state:z.string(),observations:z.array(z.unknown()),reasons:z.array(z.string())}).passthrough()),certificates:z.array(z.object({certificate_id:z.string(),sha256:z.string().length(64),metadata:z.object({prototype_disclaimer:z.string()}).passthrough()}).passthrough()),
  allocations:z.array(z.object({field_id:z.string(),buyer_id:z.string(),allocated_tonnes:z.number()}).passthrough()),pickup_requests:z.array(z.object({field_id:z.string(),request_id:z.string(),created_at:z.string()})),stats:z.record(z.string(),z.number()),generated_at:z.string()
});
