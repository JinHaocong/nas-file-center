from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CronValidationError(ValueError):
    pass


class CronNoOccurrenceError(CronValidationError):
    pass


@dataclass(frozen=True)
class CronField:
    values: frozenset[int]
    wildcard: bool


@dataclass(frozen=True)
class CronExpression:
    minute: CronField
    hour: CronField
    day_of_month: CronField
    month: CronField
    day_of_week: CronField
    source: str

    def matches_date(self, value: date) -> bool:
        if value.month not in self.month.values:
            return False

        dom_match = value.day in self.day_of_month.values
        # Python Monday=0..Sunday=6 -> cron Sunday=0.
        cron_dow = (value.weekday() + 1) % 7
        dow_match = cron_dow in self.day_of_week.values

        # Standard cron day semantics: when both DOM and DOW are restricted,
        # either field may match. When one is wildcard, the restricted field
        # controls the date.
        if self.day_of_month.wildcard and self.day_of_week.wildcard:
            return True
        if self.day_of_month.wildcard:
            return dow_match
        if self.day_of_week.wildcard:
            return dom_match
        return dom_match or dow_match


_FIELD_SPECS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 6),
)

_UNSIGNED_INT_RE = re.compile(r"^[0-9]+$")


def _parse_uint(raw: str, *, field_name: str) -> int:
    if not _UNSIGNED_INT_RE.fullmatch(raw):
        raise CronValidationError(
            f"{field_name} must use numeric values only; got {raw!r}"
        )
    return int(raw)


def _parse_field(raw: str, *, field_name: str, minimum: int, maximum: int) -> CronField:
    if not raw or raw.strip() != raw or any(ch.isspace() for ch in raw):
        raise CronValidationError(f"{field_name} contains invalid whitespace")

    wildcard = raw == "*"
    values: set[int] = set()

    for part in raw.split(","):
        if not part:
            raise CronValidationError(f"{field_name} contains an empty list item")

        if part.count("/") > 1:
            raise CronValidationError(f"{field_name} has an invalid step expression: {part!r}")

        if "/" in part:
            base, step_raw = part.split("/", 1)
            step = _parse_uint(step_raw, field_name=field_name)
            if step <= 0:
                raise CronValidationError(f"{field_name} step must be positive")
        else:
            base = part
            step = 1

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            if base.count("-") != 1:
                raise CronValidationError(f"{field_name} has an invalid range: {base!r}")
            start_raw, end_raw = base.split("-", 1)
            start = _parse_uint(start_raw, field_name=field_name)
            end = _parse_uint(end_raw, field_name=field_name)
            if start > end:
                raise CronValidationError(
                    f"{field_name} ranges cannot wrap or descend: {base!r}"
                )
        else:
            start = _parse_uint(base, field_name=field_name)
            # A stepped single value means "from N through the field maximum".
            end = maximum if "/" in part else start

        if start < minimum or start > maximum or end < minimum or end > maximum:
            raise CronValidationError(
                f"{field_name} values must be between {minimum} and {maximum}"
            )

        values.update(range(start, end + 1, step))

    if not values:
        raise CronValidationError(f"{field_name} resolves to no values")

    return CronField(values=frozenset(values), wildcard=wildcard)


def parse_cron_expression(expression: str) -> CronExpression:
    if not isinstance(expression, str):
        raise CronValidationError("cron expression must be a string")

    normalized = " ".join(expression.strip().split())
    parts = normalized.split(" ") if normalized else []
    if len(parts) != 5:
        raise CronValidationError("cron expression must contain exactly five fields")

    fields = [
        _parse_field(raw, field_name=name, minimum=minimum, maximum=maximum)
        for raw, (name, minimum, maximum) in zip(parts, _FIELD_SPECS, strict=True)
    ]

    return CronExpression(
        minute=fields[0],
        hour=fields[1],
        day_of_month=fields[2],
        month=fields[3],
        day_of_week=fields[4],
        source=normalized,
    )


def resolve_scheduler_timezone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name or name.strip() != name:
        raise CronValidationError("timezone must be a non-empty IANA zone name")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronValidationError(f"invalid IANA timezone: {name}") from exc


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CronValidationError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _valid_fold_zero_candidate(
    local_date: date,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> datetime | None:
    naive = datetime.combine(local_date, time(hour=hour, minute=minute))
    local = naive.replace(tzinfo=tz, fold=0)
    utc_value = local.astimezone(timezone.utc)

    # Round-trip validation rejects nonexistent spring-forward wall times.
    round_trip = utc_value.astimezone(tz)
    if round_trip.replace(tzinfo=None) != naive:
        return None
    if round_trip.fold != 0:
        return None
    return utc_value


def next_occurrence(
    expression: str | CronExpression,
    timezone_name: str,
    *,
    after_utc: datetime,
    horizon_days: int = 366 * 8,
) -> datetime:
    cron = (
        expression
        if isinstance(expression, CronExpression)
        else parse_cron_expression(expression)
    )
    tz = resolve_scheduler_timezone(timezone_name)
    after = _as_utc(after_utc)

    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days <= 0:
        raise CronValidationError("horizon_days must be a positive integer")

    start_date = after.astimezone(tz).date()
    sorted_hours = sorted(cron.hour.values)
    sorted_minutes = sorted(cron.minute.values)

    for day_offset in range(horizon_days + 1):
        candidate_date = start_date + timedelta(days=day_offset)
        if not cron.matches_date(candidate_date):
            continue

        for hour_value in sorted_hours:
            for minute_value in sorted_minutes:
                candidate_utc = _valid_fold_zero_candidate(
                    candidate_date,
                    hour_value,
                    minute_value,
                    tz,
                )
                if candidate_utc is None:
                    continue
                if candidate_utc > after:
                    return candidate_utc

    raise CronNoOccurrenceError(
        f"no cron occurrence found within {horizon_days} days for {cron.source!r}"
    )


def next_occurrences(
    expression: str | CronExpression,
    timezone_name: str,
    *,
    after_utc: datetime,
    count: int,
) -> list[datetime]:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 100:
        raise CronValidationError("count must be between 1 and 100")

    cron = (
        expression
        if isinstance(expression, CronExpression)
        else parse_cron_expression(expression)
    )
    cursor = _as_utc(after_utc)
    result: list[datetime] = []
    for _ in range(count):
        cursor = next_occurrence(cron, timezone_name, after_utc=cursor)
        result.append(cursor)
    return result
