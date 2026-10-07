from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.dispatch.eligibility import check_eligibility
from src.dispatch.models import Baler, DispatchField, DispatchResult, DispatchStop, BalerRoute, UnservedField
from src.dispatch.travel import GeodesicDistanceProvider, TravelMatrixProvider

LOGGER = logging.getLogger(__name__)
def load_dispatch_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "dispatch.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config


def _minutes(text: str | None, default: str) -> int:
    hour, minute = map(int, (text or default).split(":"))
    if hour not in range(24) or minute not in range(60):
        raise ValueError(f"Invalid local clock time: {text}")
    return hour * 60 + minute


def _baler_shift_minutes(baler: Baler, config: dict[str, Any]) -> int:
    hours = config["working_hours"]
    start = _minutes(baler.working_start, hours["default_start"])
    end = _minutes(baler.working_end, hours["default_end"])
    if end <= start:
        raise ValueError(f"Baler {baler.baler_id} has invalid working hours")
    available = _minutes(baler.available_from, baler.working_start) if baler.available_from else start
    if available < start or available >= end:
        return 0
    return end - available


def _service_minutes(field: DispatchField, baler: Baler, config: dict[str, Any]) -> int:
    rate = baler.service_rate_acres_per_hour or config["service_assumptions"]["default_service_rate_acres_per_hour"]
    acres = field.area_ha * float(config["service_assumptions"]["hectares_to_acres"])
    return max(1, math.ceil(acres / rate * 60))


def optimize_dispatch(fields: list[DispatchField | dict[str, Any]],
                      balers: list[Baler | dict[str, Any]],
                      travel_provider: TravelMatrixProvider | None = None,
                      config: dict[str, Any] | None = None) -> DispatchResult:
    """Assign each eligible field at most once under baler area, straw, shift and distance limits.

    OR-Tools is used when installed. The deliberately marked greedy fallback keeps
    fixtures usable in constrained environments without claiming solver parity.
    """
    cfg = config or load_dispatch_config()
    provider = travel_provider or GeodesicDistanceProvider()
    field_rows = [x if isinstance(x, DispatchField) else DispatchField.model_validate(x) for x in fields]
    baler_rows = [x if isinstance(x, Baler) else Baler.model_validate(x) for x in balers]
    if len({f.field_id for f in field_rows}) != len(field_rows):
        raise ValueError("Duplicate field_id values are not allowed in one dispatch run")
    if len({b.baler_id for b in baler_rows}) != len(baler_rows):
        raise ValueError("Duplicate baler_id values are not allowed in one dispatch run")

    weather = cfg["weather"]
    eligibility = [check_eligibility(
        f, unknown_weather_policy=weather["unknown_policy"],
        accepted_quality=tuple(weather["accepted_quality"]),
        require_high_risk=bool(cfg["prioritisation"]["require_high_risk"])) for f in field_rows]
    eligible = [f for f, e in zip(field_rows, eligibility) if e.eligible]
    ineligible = [UnservedField(field_id=e.field_id,
                                 reason=e.reasons[0] if e.reasons else "INELIGIBLE",
                                 details=e.reasons, provenance=next(f.provenance for f in field_rows if f.field_id == e.field_id))
                  for e in eligibility if not e.eligible]
    available = [b for b in baler_rows if b.status == "AVAILABLE" and _baler_shift_minutes(b, cfg) > 0]
    require_buyer = bool(cfg["constraints"].get("require_buyer_match", False))
    no_buyer: list[DispatchField] = []
    if require_buyer:
        no_buyer = [f for f in eligible if not f.buyer_id]
        eligible = [f for f in eligible if f.buyer_id]
        ineligible.extend(UnservedField(field_id=f.field_id, reason="NO_COMPATIBLE_BUYER",
                                        details=["No capacity-safe buyer assignment was supplied"], provenance=f.provenance)
                          for f in no_buyer)
    if not available:
        unserved = ineligible + [UnservedField(field_id=f.field_id, reason="NO_AVAILABLE_BALER",
                                               details=["No baler is AVAILABLE within its working window"], provenance=f.provenance)
                                  for f in eligible]
        return DispatchResult(dispatch_run_id=str(uuid.uuid4()), method="ORTOOLS_V1_UNAVAILABLE",
                              solver_status="NO_AVAILABLE_BALER", baler_routes=[], unserved_fields=unserved,
                              eligibility=eligibility, distance_method=provider.method,
                              provenance=_run_provenance(field_rows, available))

    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        LOGGER.warning("OR-Tools unavailable; dispatch is using the explicit GREEDY_FALLBACK")
        routes, dropped = _greedy_route(eligible, available, provider, cfg)
        method, status = "GREEDY_FALLBACK", "FEASIBLE_FALLBACK"
    else:
        routes, dropped, status = _ortools_route(eligible, available, provider, cfg, pywrapcp, routing_enums_pb2)
        method = "ORTOOLS_V1"
    dropped_fields = {f.field_id: f for f in eligible}
    unserved = ineligible + [UnservedField(field_id=fid, reason=reason,
                                           details=[reason.replace("_", " ").title()], provenance=dropped_fields[fid].provenance)
                              for fid, reason in dropped.items()]
    return DispatchResult(dispatch_run_id=str(uuid.uuid4()), method=method, solver_status=status,
                          baler_routes=routes, unserved_fields=unserved, eligibility=eligibility,
                          distance_method=provider.method, provenance=_run_provenance(field_rows, available),
                          created_at=datetime.now(timezone.utc))


def _run_provenance(fields: list[DispatchField], balers: list[Baler]) -> str:
    classes = {x.provenance for x in fields} | {x.demo_or_real for x in balers}
    if "REAL" in classes and len(classes) == 1:
        return "REAL"
    return "SYNTHETIC" if classes & {"SYNTHETIC", "FIXTURE", "DEMO"} else "UNVERIFIED"


def _node_locations(fields: list[DispatchField], balers: list[Baler]):
    nodes = [(f.field_id, float(f.latitude), float(f.longitude)) for f in fields]
    nodes.extend((b.baler_id, b.route_latitude, b.route_longitude) for b in balers)
    return nodes


def _matrix(nodes, provider):
    result = []
    for from_id, from_lat, from_lon in nodes:
        row = []
        for to_id, to_lat, to_lon in nodes:
            if from_id == to_id:
                row.append(0.0)
            else:
                row.append(provider.distance(from_id, from_lat, from_lon, to_id, to_lat, to_lon).kilometers)
        result.append(row)
    return result


def _ortools_route(fields, balers, provider, cfg, pywrapcp, routing_enums_pb2):
    if not fields:
        return [], {}, "OPTIMAL_EMPTY"
    nodes = _node_locations(fields, balers)
    matrix = _matrix(nodes, provider)
    drive_minutes = _duration_matrix(nodes, provider)
    n_fields = len(fields)
    starts = [n_fields + i for i in range(len(balers))]
    ends = list(starts)
    manager = pywrapcp.RoutingIndexManager(len(nodes), len(balers), starts, ends)
    routing = pywrapcp.RoutingModel(manager)
    # Service duration is baler-specific. Callbacks receive vehicle index for capacity/time.
    def distance_callback(from_index, to_index):
        i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return int(round(matrix[i][j] * 1000))
    distance_index = routing.RegisterTransitCallback(distance_callback)
    distance_weight = float(cfg["prioritisation"]["distance_cost_per_km"])
    def cost_callback(from_index, to_index):
        i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return int(round(matrix[i][j] * distance_weight * 100))
    cost_index = routing.RegisterTransitCallback(cost_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(cost_index)
    area_units = [int(math.ceil(f.area_ha * float(cfg["service_assumptions"]["hectares_to_acres"]) * 100)) for f in fields]
    area_caps = [int(math.floor(b.daily_capacity_acres * 100)) for b in balers]
    def area_callback(from_index):
        node = manager.IndexToNode(from_index)
        return area_units[node] if node < n_fields else 0
    area_index = routing.RegisterUnaryTransitCallback(area_callback)
    routing.AddDimensionWithVehicleCapacity(area_index, 0, area_caps, True, "AreaAcres")
    straw_units = [int(math.ceil(float(f.estimated_straw_tonnes) * 1000)) for f in fields]
    total_straw_cap = sum(straw_units)
    straw_caps = [int(math.floor((b.max_straw_capacity_tonnes or total_straw_cap / 1000) * 1000)) for b in balers]
    def straw_callback(from_index):
        node = manager.IndexToNode(from_index)
        return straw_units[node] if node < n_fields else 0
    straw_index = routing.RegisterUnaryTransitCallback(straw_callback)
    routing.AddDimensionWithVehicleCapacity(straw_index, 0, straw_caps, True, "StrawTonnes")
    service_indices = []
    for vehicle, baler in enumerate(balers):
        def service_callback(from_index, to_index, assigned_baler=baler):
            node = manager.IndexToNode(from_index)
            service_minutes = 0 if node >= n_fields else int(math.ceil(
                fields[node].area_ha * float(cfg["service_assumptions"]["hectares_to_acres"]) /
                assigned_baler.service_rate_acres_per_hour * 60))
            if drive_minutes is not None:
                destination = manager.IndexToNode(to_index)
                service_minutes += drive_minutes[node][destination]
            return service_minutes
        service_indices.append(routing.RegisterTransitCallback(service_callback, vehicle))
    max_shift = max(_baler_shift_minutes(b, cfg) for b in balers)
    routing.AddDimensionWithVehicleTransits(service_indices, 0, max_shift, True, "RouteMinutes")
    service_dim = routing.GetDimensionOrDie("RouteMinutes")
    distance_dim_max = int(cfg["constraints"]["maximum_route_distance_km"] * 1000)
    routing.AddDimension(distance_index, 0, distance_dim_max, True, "DistanceMeters")
    distance_dim = routing.GetDimensionOrDie("DistanceMeters")
    for i, baler in enumerate(balers):
        service_dim.CumulVar(routing.End(i)).SetMax(_baler_shift_minutes(baler, cfg))
        distance_dim.CumulVar(routing.End(i)).SetMax(distance_dim_max)
    base = int(cfg["prioritisation"]["unserved_base_penalty"])
    risk_weight = int(cfg["prioritisation"]["risk_priority_weight"])
    straw_weight = int(cfg["prioritisation"]["straw_priority_weight"])
    for index, field in enumerate(fields):
        risk = field.burn_risk_score or 0
        penalty = base + int(risk * risk_weight) + int(float(field.estimated_straw_tonnes) * straw_weight)
        routing.AddDisjunction([manager.NodeToIndex(index)], penalty)
    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.seconds = int(cfg["constraints"]["solver_time_limit_seconds"])
    solution = routing.SolveWithParameters(search)
    if solution is None:
        return [], {f.field_id: "OPTIMIZER_NO_FEASIBLE_SOLUTION" for f in fields}, "NO_SOLUTION"
    routes: list[BalerRoute] = []
    served: set[str] = set()
    for vehicle, baler in enumerate(balers):
        index = routing.Start(vehicle)
        stops: list[DispatchStop] = []
        distance_km = 0.0
        travel_total = 0
        service_total = 0
        acres_total = 0.0
        straw_total = 0.0
        seq = 1
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            distance_km += matrix[node][next_node]
            if drive_minutes is not None:
                travel_total += drive_minutes[node][next_node]
            if node < n_fields:
                field = fields[node]
                minutes = _service_minutes(field, baler, cfg)
                stops.append(DispatchStop(sequence=seq, field_id=field.field_id,
                                          estimated_straw_tonnes=float(field.estimated_straw_tonnes),
                                          service_minutes=minutes, burn_risk_score=field.burn_risk_score,
                                          burn_risk_level=field.burn_risk_level, risk_method=field.risk_method,
                                          field_status=field.field_status, field_status_source=field.field_status_source,
                                          field_status_confidence=field.field_status_confidence,
                                          harvest_evidence_state=field.harvest_evidence_state,
                                          weather_suitability=field.weather_suitability, weather_source=field.weather_source,
                                          observation_quality=field.observation_quality,
                                          buyer_id=field.buyer_id, provenance=field.provenance))
                seq += 1
                served.add(field.field_id)
                service_total += minutes
                acres_total += field.area_ha * float(cfg["service_assumptions"]["hectares_to_acres"])
                straw_total += float(field.estimated_straw_tonnes)
            index = next_index
        if stops:
            routes.append(BalerRoute(baler_id=baler.baler_id, stops=stops, total_distance_km=round(distance_km, 3),
                                     distance_method=provider.method, estimated_service_minutes=service_total,
                                     estimated_travel_minutes=travel_total if drive_minutes is not None else None,
                                     estimated_total_minutes=service_total + travel_total if drive_minutes is not None else None,
                                     assigned_area_acres=round(acres_total, 3), assigned_straw_tonnes=round(straw_total, 3),
                                     route_duration_basis="SERVICE_PLUS_FIXTURE_DRIVE" if drive_minutes is not None else "SERVICE_ONLY_DISTANCE_NOT_TIME",
                                     provenance=baler.demo_or_real))
    dropped = {f.field_id: _explain_drop(f, balers, provider, cfg) for f in fields if f.field_id not in served}
    status = "FEASIBLE_SOLUTION" if routing.status() == routing_enums_pb2.RoutingSearchStatus.ROUTING_SUCCESS else "LOCAL_SEARCH_PARTIAL"
    return routes, dropped, status


def _duration_matrix(nodes, provider):
    durations = []
    for from_id, from_lat, from_lon in nodes:
        row = []
        for to_id, to_lat, to_lon in nodes:
            if from_id == to_id:
                row.append(0)
                continue
            result = provider.distance(from_id, from_lat, from_lon, to_id, to_lat, to_lon)
            if result.duration_minutes is None:
                return None
            row.append(int(math.ceil(result.duration_minutes)))
        durations.append(row)
    return durations


def _explain_drop(field, balers, provider, cfg):
    acres = field.area_ha * float(cfg["service_assumptions"]["hectares_to_acres"])
    if all(acres > b.daily_capacity_acres for b in balers):
        return "CAPACITY_EXCEEDED"
    if all(_service_minutes(field, b, cfg) > _baler_shift_minutes(b, cfg) for b in balers):
        return "WORKING_HOURS_EXCEEDED"
    if all(_single_field_route_minutes(field, b, provider, cfg) is not None and
           _single_field_route_minutes(field, b, provider, cfg) > _baler_shift_minutes(b, cfg)
           for b in balers):
        return "WORKING_HOURS_EXCEEDED"
    maximum = float(cfg["constraints"]["maximum_route_distance_km"])
    if all(provider.distance(b.baler_id, b.route_latitude, b.route_longitude, field.field_id,
                             float(field.latitude), float(field.longitude)).kilometers > maximum for b in balers):
        return "DISTANCE_LIMIT"
    if all(b.max_straw_capacity_tonnes is not None and float(field.estimated_straw_tonnes) > b.max_straw_capacity_tonnes for b in balers):
        return "CAPACITY_EXCEEDED"
    return "CAPACITY_OR_ROUTE_LIMIT"


def _single_field_route_minutes(field, baler, provider, cfg):
    out = provider.distance(baler.baler_id, baler.route_latitude, baler.route_longitude,
                            field.field_id, float(field.latitude), float(field.longitude))
    back = provider.distance(field.field_id, float(field.latitude), float(field.longitude),
                             baler.baler_id, baler.route_latitude, baler.route_longitude)
    if out.duration_minutes is None or back.duration_minutes is None:
        return None
    return _service_minutes(field, baler, cfg) + math.ceil(out.duration_minutes) + math.ceil(back.duration_minutes)


def _greedy_route(fields, balers, provider, cfg):
    assigned: dict[str, list[DispatchField]] = {b.baler_id: [] for b in balers}
    usage = {b.baler_id: {"area": 0.0, "straw": 0.0, "service": 0, "distance": 0.0} for b in balers}
    locations = {b.baler_id: (b.route_latitude, b.route_longitude) for b in balers}
    dropped = {}
    ordered = sorted(fields, key=lambda f: (-(f.burn_risk_score or 0), -float(f.estimated_straw_tonnes), f.field_id))
    for field in ordered:
        acres = field.area_ha * float(cfg["service_assumptions"]["hectares_to_acres"])
        options = []
        for baler in balers:
            u = usage[baler.baler_id]
            service = _service_minutes(field, baler, cfg)
            out = provider.distance(baler.baler_id, *locations[baler.baler_id], field.field_id,
                                    float(field.latitude), float(field.longitude)).kilometers
            back = provider.distance(field.field_id, float(field.latitude), float(field.longitude), baler.baler_id,
                                     baler.route_latitude, baler.route_longitude).kilometers
            new_distance = u["distance"] + out + back
            if (u["area"] + acres <= baler.daily_capacity_acres and
                (baler.max_straw_capacity_tonnes is None or u["straw"] + float(field.estimated_straw_tonnes) <= baler.max_straw_capacity_tonnes) and
                u["service"] + service <= _baler_shift_minutes(baler, cfg) and
                new_distance <= float(cfg["constraints"]["maximum_route_distance_km"])):
                options.append((new_distance, baler, service, acres, out))
        if not options:
            dropped[field.field_id] = _explain_drop(field, balers, provider, cfg)
            continue
        _, baler, service, acres, out = min(options, key=lambda x: (x[0], x[1].baler_id))
        u = usage[baler.baler_id]
        u["area"] += acres; u["straw"] += float(field.estimated_straw_tonnes); u["service"] += service; u["distance"] += out
        assigned[baler.baler_id].append(field)
        locations[baler.baler_id] = (float(field.latitude), float(field.longitude))
    routes = []
    for baler in balers:
        fields_for_baler = assigned[baler.baler_id]
        if not fields_for_baler:
            continue
        route_distance = 0.0
        previous = (baler.baler_id, baler.route_latitude, baler.route_longitude)
        stops = []
        for seq, field in enumerate(fields_for_baler, 1):
            route_distance += provider.distance(previous[0], previous[1], previous[2], field.field_id,
                                                float(field.latitude), float(field.longitude)).kilometers
            mins = _service_minutes(field, baler, cfg)
            stops.append(DispatchStop(sequence=seq, field_id=field.field_id,
                                      estimated_straw_tonnes=float(field.estimated_straw_tonnes),
                                      service_minutes=mins, burn_risk_score=field.burn_risk_score,
                                      burn_risk_level=field.burn_risk_level, risk_method=field.risk_method,
                                      field_status=field.field_status, field_status_source=field.field_status_source,
                                      field_status_confidence=field.field_status_confidence,
                                      harvest_evidence_state=field.harvest_evidence_state,
                                      weather_suitability=field.weather_suitability, weather_source=field.weather_source,
                                      observation_quality=field.observation_quality,
                                      buyer_id=field.buyer_id, provenance=field.provenance))
            previous = (field.field_id, float(field.latitude), float(field.longitude))
        route_distance += provider.distance(previous[0], previous[1], previous[2], baler.baler_id,
                                            baler.route_latitude, baler.route_longitude).kilometers
        routes.append(BalerRoute(baler_id=baler.baler_id, stops=stops, total_distance_km=round(route_distance, 3),
                                 distance_method=provider.method, estimated_service_minutes=usage[baler.baler_id]["service"],
                                 assigned_area_acres=round(usage[baler.baler_id]["area"], 3),
                                 assigned_straw_tonnes=round(usage[baler.baler_id]["straw"], 3),
                                 provenance=baler.demo_or_real))
    return routes, dropped
