from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from tracefold.risk import fit_isotonic_calibrator, synthetic_calibration_records
from tracefold.schemas.phase5 import (
    CalibrationModel,
    CalibrationRecord,
    Phase5Report,
    RecoveryResult,
)
from tracefold.serialization import canonical_json_bytes


def build_phase5_report(
    records: Iterable[CalibrationRecord] | None = None,
    *,
    model: CalibrationModel | None = None,
    results: Iterable[RecoveryResult] = (),
) -> Phase5Report:
    selected_records = tuple(synthetic_calibration_records()) if records is None else tuple(records)
    selected_model = model or fit_isotonic_calibrator(selected_records)
    selected_results = tuple(results)
    action_counts = Counter(item.final_action.value for item in selected_results)
    recovery_success_count = sum(
        item.final_status == "passed" and bool(item.attempts) for item in selected_results
    )
    fallback_count = sum(item.final_action.value == "full_fallback" for item in selected_results)
    restored_counts = [item.restored_span_count for item in selected_results]
    mean_restored = (
        f"{sum(restored_counts) / len(restored_counts):.6f}" if restored_counts else None
    )
    final_reductions = {
        item.original_raw_result.source_id: item.final_reduction for item in selected_results
    }
    statuses = [
        (
            item.example_id,
            item.verifier_status,
            "passed" if item.observed_outcome == 0 else "recovery_required",
        )
        for item in selected_records
    ]
    return Phase5Report(
        calibration_record_count=len(selected_records),
        calibration_status=selected_model.status,
        brier_score=selected_model.brier_score,
        calibration_error=selected_model.calibration_error,
        action_counts=dict(sorted(action_counts.items())),
        recovery_success_count=recovery_success_count,
        fallback_count=fallback_count,
        mean_restored_tokens=mean_restored,
        final_reductions=final_reductions,
        verification_statuses_before_after=statuses,
    )


def main() -> None:
    report = build_phase5_report()
    print(canonical_json_bytes(report.model_dump(mode="json")).decode("utf-8"))


if __name__ == "__main__":
    main()


__all__ = ["build_phase5_report", "main"]
