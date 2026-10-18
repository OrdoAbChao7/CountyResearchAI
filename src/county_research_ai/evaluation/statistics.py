"""仅基于有效运行指标的可重算小样本统计。"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median, stdev

from .metrics import MetricsResult

MetricName = str
_QUALITY_METRICS = {
    "fact_accuracy",
    "key_fact_coverage",
    "evidence_support_rate",
    "error_rate",
    "analysis_depth",
    "report_qa_accuracy",
    "duration_seconds",
    "llm_tokens",
    "search_requests",
    "coverage_per_llm_token",
}


@dataclass(frozen=True)
class MetricObservation:
    run_id: str
    group: str
    region: str
    task_id: str
    repeat: int
    metrics: MetricsResult
    duration_seconds: float | None = None
    resource_usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SummaryRow:
    group: str
    metric: str
    n: int
    mean: float
    median: float
    stdev: float
    ci95_low: float
    ci95_high: float

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "group": self.group,
            "metric": self.metric,
            "n": self.n,
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


@dataclass(frozen=True)
class RegionSummaryRow:
    region: str
    group: str
    metric: str
    n: int
    mean: float
    median: float
    stdev: float
    ci95_low: float
    ci95_high: float

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "region": self.region,
            "group": self.group,
            "metric": self.metric,
            "n": self.n,
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


@dataclass(frozen=True)
class PairedDifference:
    left_group: str
    right_group: str
    metric: str
    n: int
    mean_difference: float
    median_difference: float
    stdev: float
    ci95_low: float
    ci95_high: float

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "left_group": self.left_group,
            "right_group": self.right_group,
            "metric": self.metric,
            "n": self.n,
            "mean_difference": self.mean_difference,
            "median_difference": self.median_difference,
            "stdev": self.stdev,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


def summarize_observations(
    observations: list[MetricObservation],
    *,
    metrics: tuple[MetricName, ...] = tuple(sorted(_QUALITY_METRICS)),
) -> list[SummaryRow]:
    _validate_metric_names(metrics)
    grouped: dict[tuple[str, str], list[float]] = {}
    for observation in observations:
        for metric in metrics:
            value = _observation_metric_value(observation, metric)
            if value is not None:
                grouped.setdefault((observation.group, metric), []).append(value)
    rows: list[SummaryRow] = []
    for (group, metric), values in sorted(grouped.items()):
        rows.append(_summary_row(group, metric, values))
    return rows


def summarize_observations_by_region(
    observations: list[MetricObservation],
    *,
    metrics: tuple[MetricName, ...] = tuple(sorted(_QUALITY_METRICS)),
) -> list[RegionSummaryRow]:
    """Summarize each metric separately for every region and research group."""
    _validate_metric_names(metrics)
    grouped: dict[tuple[str, str, str], list[float]] = {}
    for observation in observations:
        for metric in metrics:
            value = _observation_metric_value(observation, metric)
            if value is not None:
                grouped.setdefault((observation.region, observation.group, metric), []).append(value)
    rows: list[RegionSummaryRow] = []
    for (region, group, metric), values in sorted(grouped.items()):
        summary = _summary_row(group, metric, values)
        rows.append(
            RegionSummaryRow(
                region=region,
                group=group,
                metric=metric,
                n=summary.n,
                mean=summary.mean,
                median=summary.median,
                stdev=summary.stdev,
                ci95_low=summary.ci95_low,
                ci95_high=summary.ci95_high,
            )
        )
    return rows


def paired_difference(
    observations: list[MetricObservation],
    *,
    left_group: str,
    right_group: str,
    metric: MetricName,
) -> PairedDifference:
    _validate_metric_names((metric,))
    left = _index_observations(observations, left_group, metric)
    right = _index_observations(observations, right_group, metric)
    differences = [left[key] - right[key] for key in sorted(left.keys() & right.keys())]
    if not differences:
        raise ValueError("no matched observations for paired difference")
    low, high = _confidence_interval(differences)
    return PairedDifference(
        left_group=left_group,
        right_group=right_group,
        metric=metric,
        n=len(differences),
        mean_difference=mean(differences),
        median_difference=median(differences),
        stdev=stdev(differences) if len(differences) > 1 else 0.0,
        ci95_low=low,
        ci95_high=high,
    )


def _summary_row(group: str, metric: str, values: list[float]) -> SummaryRow:
    low, high = _confidence_interval(values)
    return SummaryRow(
        group=group,
        metric=metric,
        n=len(values),
        mean=mean(values),
        median=median(values),
        stdev=stdev(values) if len(values) > 1 else 0.0,
        ci95_low=low,
        ci95_high=high,
    )


def _confidence_interval(values: list[float]) -> tuple[float, float]:
    center = mean(values)
    if len(values) < 2:
        return center, center
    margin = 1.96 * stdev(values) / (len(values) ** 0.5)
    return center - margin, center + margin


def _index_observations(
    observations: list[MetricObservation], group: str, metric: str
) -> dict[tuple[str, str, int], float]:
    indexed: dict[tuple[str, str, int], float] = {}
    for observation in observations:
        if observation.group != group:
            continue
        key = (observation.region, observation.task_id, observation.repeat)
        if key in indexed:
            raise ValueError(f"duplicate paired observation: {group} {key}")
        value = _observation_metric_value(observation, metric)
        if value is not None:
            indexed[key] = value
    return indexed


def _validate_metric_names(metrics: tuple[str, ...]) -> None:
    unknown = sorted(set(metrics) - _QUALITY_METRICS)
    if unknown:
        raise ValueError(f"unknown metric: {', '.join(unknown)}")


def _observation_metric_value(observation: MetricObservation, metric: str) -> float | None:
    if metric == "duration_seconds":
        return _numeric_or_none(observation.duration_seconds)
    if metric == "llm_tokens":
        return _resource_units(observation.resource_usage, "llm")
    if metric == "search_requests":
        return _resource_units(observation.resource_usage, "search")
    if metric == "coverage_per_llm_token":
        tokens = _resource_units(observation.resource_usage, "llm")
        return (
            observation.metrics.key_fact_coverage / tokens
            if tokens is not None and tokens > 0
            else None
        )
    return _metric_value(observation.metrics, metric)


def _metric_value(result: MetricsResult, metric: str) -> float | None:
    value = getattr(result, metric, None)
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ValueError(f"metric is not numeric: {metric}")
    return float(value)


def _numeric_or_none(value: float | None) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _resource_units(resource_usage: dict[str, int], kind: str) -> float | None:
    values = [
        amount
        for key, amount in resource_usage.items()
        if str(key).rsplit(":", 1)[-1] == kind
    ]
    return float(sum(values)) if values else None
