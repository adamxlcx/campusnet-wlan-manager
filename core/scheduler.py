# -*- coding: utf-8 -*-
"""智能闹钟式计划规则。

规则模型（config.schedules[]）
    id / name / enabled / action("connect"|"reconnect"|"check") /
    target_network / need_login(null=跟随网络配置) / time("HH:MM") /
    window_minutes（补执行窗口）/ retry_interval_seconds / max_attempts_per_day /
    repeat{mode:"once"|"daily"|"weekly"|"monthly", weekdays[1-7], days[], months[1-12], date}

核心能力：next_run / previous_run / is_due / describe / can_attempt。
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MODE_NAMES = {"once": "仅一次", "daily": "每天", "weekly": "每周", "monthly": "每月"}
_VALID_MODES = ("once", "daily", "weekly", "monthly")
_MAX_SCAN_DAYS = 800  # 覆盖“每月的某一天 + 月份过滤”等最坏情况


# --------------------------------------------------------------------------- #
# 基础解析
# --------------------------------------------------------------------------- #
def parse_hhmm(text: str) -> dtime:
    try:
        hh, mm = str(text or "00:00").split(":")[:2]
        return dtime(int(hh) % 24, int(mm) % 60)
    except Exception:  # noqa: BLE001
        return dtime(0, 0)


def parse_date(text: str) -> date | None:
    text = str(text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _day_matches(rule: dict, day: date) -> bool:
    """该日期是否命中规则的重复模式（不含时间判断）。"""
    repeat = rule.get("repeat") or {}
    mode = str(repeat.get("mode") or "daily").lower()
    months = repeat.get("months") or []
    if months and day.month not in months:
        return False

    if mode == "once":
        target = parse_date(repeat.get("date"))
        return target == day
    if mode == "daily":
        return True
    if mode == "weekly":
        weekdays = repeat.get("weekdays") or []
        return day.isoweekday() in weekdays
    if mode == "monthly":
        days = repeat.get("days") or []
        for d in days:
            d = int(d)
            if d > 0 and day.day == d:
                return True
            if d < 0 and day.day == (_days_in_month(day.year, day.month) + 1 + d):
                # -1 = 月末，-2 = 倒数第二天，与日历“月末”用法一致
                return True
        return False
    return False


def _occurrence(rule: dict, day: date) -> datetime:
    return datetime.combine(day, parse_hhmm(rule.get("time")))


# --------------------------------------------------------------------------- #
# next_run / previous_run
# --------------------------------------------------------------------------- #
def next_run(rule: dict, now: datetime | None = None) -> datetime | None:
    """计算下一次触发时间；无未来触发点（如已过期的“仅一次”）返回 None。"""
    if not rule:
        return None
    now = now or datetime.now()
    repeat = rule.get("repeat") or {}
    mode = str(repeat.get("mode") or "daily").lower()
    if mode not in _VALID_MODES:
        mode = "daily"

    if mode == "once":
        target = parse_date(repeat.get("date"))
        if target is None:
            return None
        dt = _occurrence(rule, target)
        return dt if dt > now else None

    # 从最小的可能日期开始探测：需要往前跳以保证 next_run >= now 但不越界
    start = now.date()
    if str(rule.get("time") or "") and _day_matches(rule, start):
        if _occurrence(rule, start) > now:
            return _occurrence(rule, start)
    for i in range(1, _MAX_SCAN_DAYS + 1):
        day = start + timedelta(days=i)
        if _day_matches(rule, day):
            return _occurrence(rule, day)
    return None


def previous_run(rule: dict, now: datetime | None = None) -> datetime | None:
    """最近一次已经到点的触发时间（<= now）。"""
    if not rule:
        return None
    now = now or datetime.now()
    today = now.date()
    if _day_matches(rule, today):
        dt = _occurrence(rule, today)
        if dt <= now:
            return dt
    for i in range(1, _MAX_SCAN_DAYS + 1):
        day = today - timedelta(days=i)
        if _day_matches(rule, day):
            return _occurrence(rule, day)
    return None


def is_due(rule: dict, now: datetime | None = None, last_run_iso: str = "",
           window_minutes: int | None = None) -> bool:
    """当前是否处于该规则的“可执行窗口”内，且本次到点后还没执行过。"""
    now = now or datetime.now()
    if not rule or not rule.get("enabled", True):
        return False
    window = rule.get("window_minutes") if window_minutes is None else window_minutes
    try:
        window_minutes = int(window if window is not None else 180)
    except (TypeError, ValueError):
        window_minutes = 180
    effective_seconds = max(60.0, float(window_minutes) * 60.0)

    prev = previous_run(rule, now)
    if prev is None:
        return False
    if (now - prev).total_seconds() > effective_seconds:
        return False
    last = _parse_iso(last_run_iso)
    if last is not None and last >= prev:
        return False
    return True


def _window_minutes(rule: dict) -> int:
    """规则的补执行窗口（分钟），非法值回退 180。"""
    try:
        return int(rule.get("window_minutes") if rule.get("window_minutes") is not None else 180)
    except (TypeError, ValueError):
        return 180


def _parse_iso(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text))
    except Exception:  # noqa: BLE001
        return None


def can_attempt(rule: dict, state: dict, now: datetime | None = None) -> tuple:
    """是否允许执行/再次尝试。

    依次判定：①是否处于“到点 + 补执行窗口”（且本次尚未执行过）
              ②重试间隔是否已到  ③当日尝试次数是否已达上限。
    返回 (允许, 原因)。
    """
    now = now or datetime.now()
    state = state or {}
    rid = rule.get("id")

    # ① 到点 + 补执行窗口 + 本次是否已执行过
    last_run_iso = (state.get("last_run") or {}).get(rid, "")
    if not is_due(rule, now, last_run_iso):
        prev = previous_run(rule, now)
        if prev is None:
            return False, "近期没有到点的触发时间"
        window_minutes = max(60.0, float(_window_minutes(rule)) * 60.0)
        if (now - prev).total_seconds() > window_minutes:
            return False, f"已超出补执行窗口（{_window_minutes(rule)} 分钟）"
        return False, "本次到点后已执行过，等待下一个触发时间"

    last_attempt = _parse_iso(state.get("last_attempt_iso", {}).get(rid, ""))
    if last_attempt is None:
        ts = (state.get("last_attempt") or {}).get(rid)
        if ts:
            try:
                last_attempt = datetime.fromtimestamp(float(ts))
            except Exception:  # noqa: BLE001
                last_attempt = None
    interval = int(rule.get("retry_interval_seconds") or 0)
    if last_attempt and interval > 0 and (now - last_attempt).total_seconds() < interval:
        remain = interval - (now - last_attempt).total_seconds()
        return False, f"重试间隔未到（还有 {int(remain)}s）"

    max_attempts = int(rule.get("max_attempts_per_day") or 0)
    if max_attempts > 0:
        used = _attempts_today(state, rid, now)
        if used >= max_attempts:
            return False, f"今日尝试次数已达上限（{used}/{max_attempts}）"
    return True, ""


def _attempts_today(state: dict, rule_id: str, now: datetime) -> int:
    counter = (state.get("attempts_by_day") or {}).get(rule_id) or {}
    return int(counter.get(now.date().isoformat(), 0))


def bump_attempt(state: dict, rule_id: str, now: datetime | None = None) -> None:
    """把一次尝试记到 state（供跨轮/跨进程持久化）。"""
    now = now or datetime.now()
    by_day = state.setdefault("attempts_by_day", {}).setdefault(rule_id, {})
    key = now.date().isoformat()
    by_day[key] = int(by_day.get(key, 0)) + 1
    state.setdefault("last_attempt_iso", {})[rule_id] = now.isoformat(timespec="seconds")
    state.setdefault("last_attempt", {})[rule_id] = now.timestamp()
    # 清理过期计数
    cutoff = (now.date() - timedelta(days=7)).isoformat()
    for day in [d for d in by_day if d < cutoff]:
        by_day.pop(day, None)


def mark_done(state: dict, rule_id: str, when: datetime | None = None) -> None:
    when = when or datetime.now()
    state.setdefault("last_run", {})[rule_id] = when.isoformat(timespec="seconds")


def describe(rule: dict) -> str:
    repeat = rule.get("repeat") or {}
    mode = str(repeat.get("mode") or "daily").lower()
    months = repeat.get("months") or []
    month_text = ""
    if months:
        month_text = "".join(f"{m}月" for m in months) + "的"

    if mode == "once":
        when = f"{repeat.get('date') or '（未指定日期）'} {rule.get('time')}"
    elif mode == "daily":
        when = f"{month_text}每天 {rule.get('time')}"
    elif mode == "weekly":
        names = "、".join(WEEKDAY_NAMES[d - 1] for d in sorted(repeat.get("weekdays") or [])
                          if 1 <= int(d) <= 7)
        when = f"{month_text}每{names or '（未选择星期）'} {rule.get('time')}"
    else:
        days = []
        for d in sorted(repeat.get("days") or []):
            days.append("月末" if int(d) == -1 else f"{int(d)}日")
        when = f"{month_text}每月 {'、'.join(days) or '（未选择日期）'} {rule.get('time')}"

    window = int(rule.get("window_minutes") or 0)
    window_text = f"（补执行窗口 {window} 分钟）" if window > 0 else "（无补执行窗口）"
    target = rule.get("target_network") or "（未指定网络）"
    login_text = "" if rule.get("need_login") is None else (
        "，登录" if rule.get("need_login") else "，不登录")
    return f"{rule.get('name') or rule.get('id')}：{when} → {target}{login_text}{window_text}"


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #
class Scheduler:
    """基于规则列表 + 运行时状态的调度器（纯计算，不执行动作）。"""

    def __init__(self, cfg: dict | None = None, state: dict | None = None):
        self.cfg = cfg or {}
        self.state = state if state is not None else {}

    def reload(self, cfg: dict, state: dict | None = None) -> None:
        self.cfg = cfg or {}
        if state is not None:
            self.state = state

    @property
    def rules(self) -> list:
        return list((self.cfg or {}).get("schedules") or [])

    def due_rules(self, now: datetime | None = None) -> list:
        """返回此刻需要执行的规则（含尝试次数/间隔判定）。"""
        now = now or datetime.now()
        last_runs = self.state.get("last_run") or {}
        due = []
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            if not is_due(rule, now, last_runs.get(rule.get("id"), "")):
                continue
            ok, reason = can_attempt(rule, self.state, now)
            if not ok:
                continue
            due.append(rule)
        return due

    def next_runs(self, now: datetime | None = None, limit: int = 0) -> list:
        """[(rule, next_datetime)]，按时间升序。"""
        now = now or datetime.now()
        items = []
        for rule in self.rules:
            dt = next_run(rule, now)
            if dt is not None:
                items.append((rule, dt))
        items.sort(key=lambda item: item[1])
        return items[:limit] if limit else items

    def seconds_until_next(self, now: datetime | None = None) -> float | None:
        items = self.next_runs(now, limit=1)
        if not items:
            return None
        now = now or datetime.now()
        return max(0.0, (items[0][1] - now).total_seconds())

    def pending_retry_rules(self, now: datetime | None = None) -> list:
        """到点但尚未成功（上次尝试在重试间隔之外）的规则。"""
        now = now or datetime.now()
        last_runs = self.state.get("last_run") or {}
        out = []
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            if not is_due(rule, now, last_runs.get(rule.get("id"), "")):
                continue
            out.append(rule)
        return out

    def summary(self, now: datetime | None = None) -> list:
        now = now or datetime.now()
        rows = []
        for rule, dt in self.next_runs(now):
            rows.append({
                "id": rule.get("id"),
                "name": rule.get("name"),
                "enabled": rule.get("enabled", True),
                "target_network": rule.get("target_network"),
                "need_login": rule.get("need_login"),
                "schedule": describe(rule),
                "next_run": dt.isoformat(timespec="seconds"),
                "next_run_in_seconds": round((dt - now).total_seconds(), 1),
            })
        for rule in self.rules:
            if rule.get("enabled", True) and next_run(rule, now) is None:
                rows.append({
                    "id": rule.get("id"), "name": rule.get("name"), "enabled": True,
                    "target_network": rule.get("target_network"),
                    "need_login": rule.get("need_login"),
                    "schedule": describe(rule), "next_run": None,
                    "next_run_in_seconds": None,
                    "note": "无未来触发点（仅一次且时间已过）",
                })
        return rows
