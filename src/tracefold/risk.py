from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence

from tracefold.hashing import hash_canonical
from tracefold.schemas.common import DiscoveryStatus, FinalAction, HashDomain
from tracefold.schemas.phase2 import ContentType
from tracefold.schemas.phase3 import RawCompressionResult
from tracefold.schemas.phase4 import VerificationReport, VerificationReportStatus
from tracefold.schemas.phase5 import (
    CalibrationModel,
    CalibrationPoint,
    CalibrationRecord,
    CalibrationStatus,
    DataSplit,
    StructuralRiskAssessment,
    StructuralRiskFeatures,
)

COMPONENT_VERSION = "tracefold.structural-risk/0.1.0"
MIN_CALIBRATION_SAMPLES = 30
FIXED_THRESHOLDS = tuple(f"{index / 10:.6f}" for index in range(1, 10))


def _ratio(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{max(0.0, min(1.0, value)):.6f}"


def _float(value: str | None) -> float:
    return 0.0 if value is None else float(value)


def _coverage(discovered: int, verified: int) -> str | None:
    return _ratio(verified / discovered) if discovered else None


def extract_structural_risk_features(
    raw_result: RawCompressionResult,
    report: VerificationReport,
) -> StructuralRiskFeatures:
    failed_by_severity = Counter(item.severity for item in report.failed_checks)
    failed_by_class = Counter(item.class_name for item in report.failed_checks)
    obligation_coverage = {
        name: _coverage(item.discovered, item.verified)
        for name, item in sorted(report.obligation_results.items())
    }
    hard_classes = {
        name: item
        for name, item in report.obligation_results.items()
        if name not in {"structured.json_schema_path", "entity.named"}
    }
    hard_discovered = sum(item.discovered for item in hard_classes.values())
    hard_verified = sum(item.verified for item in hard_classes.values())
    relation_discovered = sum(item.discovered for item in report.relation_results)
    relation_verified = sum(item.verified for item in report.relation_results)
    discovery_statuses = [
        item.discovery_status.value for item in report.obligation_results.values()
    ] + [item.discovery_status.value for item in report.relation_results]
    discovery_status_counts = Counter(discovery_statuses)
    failed_codes = {item.code for item in report.failed_checks}
    requested_budget = raw_result.requested_token_budget
    margin = (
        requested_budget - raw_result.minimum_mandatory_token_count
        if requested_budget is not None
        else None
    )
    return StructuralRiskFeatures(
        run_id=raw_result.run_id,
        verification_status=report.status.value,
        failed_invariant_count=len(report.failed_checks),
        failed_by_severity=dict(sorted(failed_by_severity.items())),
        failed_by_class=dict(sorted(failed_by_class.items())),
        obligation_coverage=obligation_coverage,
        hard_obligation_coverage=_coverage(hard_discovered, hard_verified),
        relation_coverage=_coverage(relation_discovered, relation_verified),
        source_map_coverage=(
            report.source_map_coverage.value if report.source_map_coverage else None
        ),
        discovery_status_counts=dict(sorted(discovery_status_counts.items())),
        parser_warning_count=len(raw_result.warnings),
        extraction_warning_count=len(report.warnings),
        omitted_span_count=len(raw_result.omitted_spans),
        omitted_mandatory_intersection_count=sum(
            1
            for item in report.failed_checks
            if item.code
            in {
                "MANDATORY_EVIDENCE_OMITTED",
                "OBLIGATION_NOT_REPRESENTED",
                "RELATION_NOT_REPRESENTED",
            }
        ),
        requested_reduction=_ratio(raw_result.requested_reduction),
        achieved_reduction=_ratio(raw_result.achieved_reduction),
        mandatory_token_floor=raw_result.minimum_mandatory_token_count,
        requested_budget=requested_budget,
        final_token_count=report.compressed_token_count,
        budget_to_floor_margin=margin,
        unknown_tokenizer="UNKNOWN_TOKENIZER" in failed_codes,
        stale_map=any(
            "STALE" in item.code or "SOURCE_MAP" in item.code for item in report.failed_checks
        ),
        hash_failure=any(item.kind == "hash" for item in report.failed_checks),
        query_hash_failure="QUERY_HASH_MISMATCH" in failed_codes,
        incompressible=raw_result.status.value == "incompressible",
        failed_compression=raw_result.status.value == "failed",
    )


def feature_vector_hash(features: StructuralRiskFeatures) -> str:
    return hash_canonical(
        HashDomain.CERTIFICATE,
        {"phase5_feature_vector": features.model_dump(mode="json")},
    )


def structural_failure_score(features: StructuralRiskFeatures) -> float:
    score = 0.0
    if features.verification_status != VerificationReportStatus.VALID.value:
        score += 0.35
    score += min(0.30, features.failed_invariant_count * 0.05)
    score += 0.20 * (1.0 - _float(features.hard_obligation_coverage))
    score += 0.15 * (1.0 - _float(features.relation_coverage))
    score += 0.15 * (1.0 - _float(features.source_map_coverage))
    if features.discovery_status_counts.get(DiscoveryStatus.UNKNOWN.value, 0):
        score += 0.20
    elif features.discovery_status_counts.get(DiscoveryStatus.PARTIAL.value, 0):
        score += 0.08
    score += min(0.10, (features.parser_warning_count + features.extraction_warning_count) * 0.02)
    score += min(0.15, features.omitted_mandatory_intersection_count * 0.15)
    score += 0.20 if features.unknown_tokenizer else 0.0
    score += 0.15 if features.stale_map else 0.0
    score += 0.15 if features.hash_failure or features.query_hash_failure else 0.0
    score += 0.15 if features.incompressible or features.failed_compression else 0.0
    return min(1.0, score)


def _predict(points: list[CalibrationPoint], score: float) -> float:
    if not points:
        raise ValueError("calibration model has no points")
    for point in points:
        if score <= float(point.score):
            return float(point.probability)
    return float(points[-1].probability)


def _brier(predictions: Iterable[float], outcomes: Iterable[int]) -> float:
    values = [
        (prediction - outcome) ** 2
        for prediction, outcome in zip(predictions, outcomes, strict=True)
    ]
    return sum(values) / len(values) if values else 0.0


def _ece(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    if not predictions:
        return 0.0
    error = 0.0
    total = len(predictions)
    for bucket in range(10):
        selected = [
            index
            for index, probability in enumerate(predictions)
            if min(9, int(probability * 10)) == bucket
        ]
        if not selected:
            continue
        mean_probability = sum(predictions[index] for index in selected) / len(selected)
        mean_outcome = sum(outcomes[index] for index in selected) / len(selected)
        error += len(selected) / total * abs(mean_probability - mean_outcome)
    return error


def _training_hash(records: list[CalibrationRecord]) -> str:
    return hash_canonical(
        HashDomain.RECOVERY_HISTORY,
        {"phase5_calibration_records": [item.model_dump(mode="json") for item in records]},
    )


def _model_hash(payload: dict[str, object]) -> str:
    return hash_canonical(HashDomain.CERTIFICATE, {"phase5_calibration_model": payload})


def fit_isotonic_calibrator(
    records: Iterable[CalibrationRecord],
    *,
    minimum_samples: int = MIN_CALIBRATION_SAMPLES,
) -> CalibrationModel:
    ordered = sorted(records, key=lambda item: item.example_id)
    if len(ordered) != len({item.example_id for item in ordered}):
        raise ValueError("calibration example IDs must be unique")
    training = [item for item in ordered if item.data_split == DataSplit.TRAIN]
    validation = [item for item in ordered if item.data_split == DataSplit.VALIDATION]
    training_hash = _training_hash(ordered)
    feature_names = [
        "raw_structural_risk_score",
        "failed_invariant_count",
        "hard_obligation_coverage",
        "relation_coverage",
        "source_map_coverage",
    ]
    empty_payload: dict[str, object] = {
        "model_version": "1.0.0",
        "model_kind": "isotonic-pav",
        "training_sample_count": len(training),
        "validation_sample_count": len(validation),
        "feature_names": feature_names,
        "fitted_parameters": [],
        "thresholds": list(FIXED_THRESHOLDS),
        "fit_metrics": {"brier_score": None, "calibration_error": None},
        "brier_score": None,
        "calibration_error": None,
        "training_data_hash": training_hash,
        "status": CalibrationStatus.INSUFFICIENT_DATA.value,
    }
    if len(ordered) < minimum_samples or not training or not validation:
        return CalibrationModel(
            model_version="1.0.0",
            model_kind="isotonic-pav",
            training_sample_count=len(training),
            validation_sample_count=len(validation),
            feature_names=feature_names,
            fitted_parameters=[],
            thresholds=list(FIXED_THRESHOLDS),
            fit_metrics={"brier_score": None, "calibration_error": None},
            brier_score=None,
            calibration_error=None,
            model_hash=_model_hash(empty_payload),
            training_data_hash=training_hash,
            status=CalibrationStatus.INSUFFICIENT_DATA,
        )

    points = sorted(
        [
            {
                "score": structural_failure_score(item.feature_vector),
                "outcome": item.observed_outcome,
                "example_id": item.example_id,
            }
            for item in training
        ],
        key=lambda item: (item["score"], item["example_id"]),
    )
    blocks: list[dict[str, float | int]] = []
    for point in points:
        blocks.append({"score": float(point["score"]), "sum": float(point["outcome"]), "count": 1})
        while len(blocks) > 1:
            left, right = blocks[-2], blocks[-1]
            if left["sum"] / left["count"] <= right["sum"] / right["count"]:
                break
            merged = {
                "score": right["score"],
                "sum": left["sum"] + right["sum"],
                "count": left["count"] + right["count"],
            }
            blocks[-2:] = [merged]
    fitted = [
        CalibrationPoint(
            score=_ratio(float(block["score"])) or "0.000000",
            probability=_ratio(float(block["sum"] / block["count"])) or "0.000000",
        )
        for block in blocks
    ]
    predictions = [
        _predict(fitted, structural_failure_score(item.feature_vector)) for item in validation
    ]
    outcomes = [item.observed_outcome for item in validation]
    brier = _ratio(_brier(predictions, outcomes))
    error = _ratio(_ece(predictions, outcomes))
    payload = {
        **empty_payload,
        "training_sample_count": len(training),
        "validation_sample_count": len(validation),
        "fitted_parameters": [item.model_dump(mode="json") for item in fitted],
        "fit_metrics": {"brier_score": brier, "calibration_error": error},
        "brier_score": brier,
        "calibration_error": error,
        "status": CalibrationStatus.CALIBRATED.value,
    }
    return CalibrationModel(
        model_version="1.0.0",
        model_kind="isotonic-pav",
        training_sample_count=len(training),
        validation_sample_count=len(validation),
        feature_names=feature_names,
        fitted_parameters=fitted,
        thresholds=list(FIXED_THRESHOLDS),
        fit_metrics={"brier_score": brier, "calibration_error": error},
        brier_score=brier,
        calibration_error=error,
        model_hash=_model_hash(payload),
        training_data_hash=training_hash,
        status=CalibrationStatus.CALIBRATED,
    )


def verify_calibration_model(
    model: CalibrationModel,
    records: Iterable[CalibrationRecord],
) -> bool:
    ordered = sorted(records, key=lambda item: item.example_id)
    try:
        expected = fit_isotonic_calibrator(ordered)
    except ValueError:
        return False
    if model.model_dump(mode="json") != expected.model_dump(mode="json"):
        return False
    return model.training_data_hash == _training_hash(ordered)


def coverage_at_threshold(
    model: CalibrationModel,
    records: Iterable[CalibrationRecord],
    threshold: float,
) -> str | None:
    if model.status != CalibrationStatus.CALIBRATED:
        return None
    values = [
        _predict(model.fitted_parameters, structural_failure_score(item.feature_vector))
        for item in records
    ]
    return _ratio(sum(value <= threshold for value in values) / len(values)) if values else None


def selective_verification_success(
    model: CalibrationModel,
    records: Iterable[CalibrationRecord],
    threshold: float,
) -> str | None:
    if model.status != CalibrationStatus.CALIBRATED:
        return None
    selected = [
        item
        for item in records
        if _predict(model.fitted_parameters, structural_failure_score(item.feature_vector))
        <= threshold
    ]
    return (
        _ratio(sum(item.observed_outcome == 0 for item in selected) / len(selected))
        if selected
        else None
    )


def assess_structural_risk(
    features: StructuralRiskFeatures,
    *,
    calibration_model: CalibrationModel | None = None,
    recommended_action: FinalAction = FinalAction.EMIT,
    decision_threshold: str | None = "0.500000",
) -> StructuralRiskAssessment:
    raw_score = structural_failure_score(features)
    probability: str | None = None
    status = CalibrationStatus.NOT_AVAILABLE
    model_id: str | None = None
    sample_count = 0
    if calibration_model is not None:
        sample_count = (
            calibration_model.training_sample_count + calibration_model.validation_sample_count
        )
        if calibration_model.status == CalibrationStatus.CALIBRATED:
            probability = _ratio(_predict(calibration_model.fitted_parameters, raw_score))
            status = CalibrationStatus.CALIBRATED
            model_id = (
                f"{calibration_model.model_kind}/{calibration_model.model_version}/"
                f"{calibration_model.model_hash[7:23]}"
            )
        else:
            status = calibration_model.status
            decision_threshold = None
    else:
        decision_threshold = None
    reasons = sorted(
        {
            *features.failed_by_class,
            "verification_failed" if features.verification_status != "valid" else "",
            "unknown_discovery" if features.discovery_status_counts.get("unknown") else "",
            (
                "mandatory_floor"
                if features.budget_to_floor_margin is not None
                and features.budget_to_floor_margin < 0
                else ""
            ),
        }
        - {""}
    )
    return StructuralRiskAssessment(
        assessment_version="1.0.0",
        run_id=features.run_id,
        feature_vector_hash=feature_vector_hash(features),
        raw_structural_risk_score=_ratio(raw_score) or "0.000000",
        structural_failure_probability=probability,
        calibration_status=status,
        calibration_model_id=model_id,
        calibration_sample_count=sample_count,
        decision_threshold=decision_threshold,
        recommended_action=recommended_action,
        reasons=reasons,
        component_version=COMPONENT_VERSION,
    )


def _synthetic_features(
    index: int,
    *,
    failure: bool,
    source_kind: ContentType,
    corruption_type: str,
) -> StructuralRiskFeatures:
    run_id = f"123e4567-e89b-42d3-a456-426614174{index:03d}"
    failed = 1 if failure else 0
    return StructuralRiskFeatures(
        run_id=run_id,
        verification_status="invalid" if failure else "valid",
        failed_invariant_count=failed,
        failed_by_severity={"hard": failed} if failure else {},
        failed_by_class={corruption_type: failed} if failure else {},
        hard_obligation_coverage="0.800000" if failure else "1.000000",
        relation_coverage="0.800000" if failure else "1.000000",
        source_map_coverage="0.900000" if failure else "1.000000",
        discovery_status_counts={"known": 1} if not failure else {"partial": 1},
        parser_warning_count=0,
        extraction_warning_count=0,
        omitted_span_count=1 if failure else 0,
        omitted_mandatory_intersection_count=1 if failure else 0,
        requested_reduction="0.500000",
        achieved_reduction="0.500000" if not failure else "0.700000",
        mandatory_token_floor=20,
        requested_budget=100,
        final_token_count=50,
        budget_to_floor_margin=80,
        unknown_tokenizer=corruption_type == "unknown_tokenizer",
        stale_map=corruption_type in {"stale_source_map", "invalid_compressed_range"},
        hash_failure=corruption_type
        in {"altered_source", "altered_query", "altered_compressed_artifact"},
        query_hash_failure=corruption_type == "altered_query",
        incompressible=corruption_type == "incompressible_result",
        failed_compression=corruption_type == "failed_raw_result",
    )


def _split_for_example(example_id: str) -> DataSplit:
    bucket = hashlib.sha256(example_id.encode("utf-8")).digest()[0] % 5
    return DataSplit.VALIDATION if bucket == 0 else DataSplit.TRAIN


def synthetic_calibration_records() -> tuple[CalibrationRecord, ...]:
    corruption_types = (
        "altered_source",
        "altered_query",
        "altered_compressed_artifact",
        "wrong_token_count",
        "unknown_tokenizer",
        "lost_number_owner",
        "lost_negation",
        "lost_exception",
        "lost_condition_consequence",
        "lost_dialogue_correction",
        "lost_json_anomaly",
        "lost_log_predecessor",
        "lost_trace_id",
        "lost_python_branch_guard",
        "lost_caller_callee",
        "stale_source_map",
        "invalid_compressed_range",
        "mislabelled_synthesized_marker",
        "omitted_mandatory_span",
        "incompressible_result",
        "failed_raw_result",
        "recovery_attempt_exhausted",
    )
    records: list[CalibrationRecord] = []
    for index in range(10):
        features = _synthetic_features(
            index,
            failure=False,
            source_kind=ContentType.DOCUMENT,
            corruption_type="clean_valid_emit",
        )
        records.append(
            CalibrationRecord(
                example_id=f"clean-valid-{index:02d}",
                feature_vector=features,
                observed_outcome=0,
                data_split=_split_for_example(f"clean-valid-{index:02d}"),
                corruption_type="clean_valid_emit",
                source_kind=ContentType.DOCUMENT,
                compressor_status="compressed",
                verifier_status="valid",
            )
        )
    kinds = tuple(ContentType)
    for offset, corruption_type in enumerate(corruption_types, start=10):
        source_kind = kinds[(offset - 10) % 5]
        features = _synthetic_features(
            offset,
            failure=True,
            source_kind=source_kind,
            corruption_type=corruption_type,
        )
        records.append(
            CalibrationRecord(
                example_id=f"corruption-{offset:02d}-{corruption_type}",
                feature_vector=features,
                observed_outcome=1,
                data_split=_split_for_example(f"corruption-{offset:02d}-{corruption_type}"),
                corruption_type=corruption_type,
                source_kind=source_kind,
                compressor_status=(
                    "incompressible" if corruption_type == "incompressible_result" else "compressed"
                ),
                verifier_status="failed" if corruption_type == "failed_raw_result" else "invalid",
            )
        )
    return tuple(records)


__all__ = [
    "COMPONENT_VERSION",
    "FIXED_THRESHOLDS",
    "MIN_CALIBRATION_SAMPLES",
    "assess_structural_risk",
    "coverage_at_threshold",
    "extract_structural_risk_features",
    "feature_vector_hash",
    "fit_isotonic_calibrator",
    "structural_failure_score",
    "synthetic_calibration_records",
    "selective_verification_success",
    "verify_calibration_model",
]
