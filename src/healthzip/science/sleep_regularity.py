"""Sleep timing on a circular clock and comparison of measured states 24 h apart."""

import math
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from .contracts import instant
from .state import ASLEEP, stage, stream_key


def sleep_regularity(rows, episodes, window):
    zone = ZoneInfo(window.timezone)
    result = {}
    grouped = defaultdict(list)
    for row in rows:
        if row.get("canonical_type") == "sleep_stage":
            grouped[stream_key(row)].append(row)
    for key, values in grouped.items():
        changes = defaultdict(lambda: [0, 0])
        for row in values:
            annotation = stage(row)
            if annotation not in ASLEEP | {"awake"}:
                continue
            start = max(instant(row["event_start"]), instant(window.start))
            end = min(instant(row["event_end"]), instant(window.end), instant(window.cutoff_time))
            if end <= start:
                continue
            j = int(annotation == "awake")
            changes[start][j] += 1
            changes[end][j] -= 1
        states = []
        asleep = awake = 0
        previous = None
        for moment, (sa, wa) in sorted(changes.items()):
            if previous is not None and (asleep > 0) != (awake > 0):
                states.append((previous, moment, "asleep" if asleep else "awake"))
            asleep += sa
            awake += wa
            previous = moment
        lag = timedelta(hours=24)
        i = j = 0
        valid = agree = 0.0
        paired_states = set()
        paired_by_hour = defaultdict(float)
        paired_intervals = []
        while i < len(states) and j < len(states):
            a, b, x = states[i]
            c, d, y = states[j]
            c, d = c - lag, d - lag
            sec = (min(b, d) - max(a, c)).total_seconds()
            if sec > 0:
                valid += sec
                agree += sec * (x == y)
                paired_states.update((x, y))
                left, right = max(a, c), min(b, d)
                paired_intervals.append((left, right))
                while left < right:
                    boundary = min(
                        right, left.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                    )
                    paired_by_hour[left.astimezone(zone).hour] += (boundary - left).total_seconds()
                    left = boundary
            if b <= d:
                i += 1
            if d <= b:
                j += 1
        total = max(
            0.0,
            (
                min(instant(window.end), instant(window.cutoff_time)) - instant(window.start) - lag
            ).total_seconds(),
        )
        starts = []
        for ep in episodes:
            if list(key) == ep["protocol"] and ep["intervals"]:
                at = instant(ep["intervals"][0]["start"]).astimezone(zone)
                starts.append((at.hour * 60 + at.minute + at.second / 60) * math.tau / 1440)
        z = (sum(complex(math.cos(v), math.sin(v)) for v in starts) / len(starts)) if starts else 0j
        exclusions = []
        cursor = instant(window.start)
        last_possible = min(instant(window.end), instant(window.cutoff_time)) - lag
        for a, b in paired_intervals:
            if a > cursor:
                exclusions.append([cursor.isoformat(), a.isoformat()])
            cursor = max(cursor, b)
        if cursor < last_possible:
            exclusions.append([cursor.isoformat(), last_possible.isoformat()])
        result[key] = {
            "observed_start_circular_mean_minutes": (math.atan2(z.imag, z.real) % math.tau)
            * 1440
            / math.tau
            if abs(z) > 1e-8
            else None,
            "observed_start_resultant_length": abs(z) if starts else None,
            "episode_count": len(starts),
            "sri": (200 * agree / valid - 100)
            if valid and valid >= total and paired_states == {"awake", "asleep"}
            else None,
            "paired_clock_hour_minutes": {
                str(h): s / 60 for h, s in sorted(paired_by_hour.items())
            },
            "unpaired_anchor_ranges": exclusions,
            "observed_pair_sri": (200 * agree / valid - 100)
            if valid and paired_states == {"awake", "asleep"}
            else None,
            "observed_pair_scope": "仅两种状态均有测量的有效状态对；未测时段不参与该条件统计。",
            "paired_minutes": valid / 60,
            "possible_pair_minutes": total / 60,
            "unpaired_minutes": max(0, total - valid) / 60,
            "reason": "完整 SRI 只在所选比较范围的 24 小时状态对全部可判定且两种状态都有记录时报告。",
        }
    return result
