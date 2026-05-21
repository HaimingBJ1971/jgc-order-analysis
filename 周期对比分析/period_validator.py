"""
Period validator for weekly/monthly comparison analysis.

Validates that input data covers a complete week (Mon-Sun) or month (1st-last).
"""

from datetime import datetime, timedelta
import calendar


def validate_period(dates, mode):
    """
    Validate period completeness.

    Args:
        dates: list of date strings "YYYY-MM-DD" from the input data
        mode: "week" or "month"

    Returns:
        dict with keys:
            - valid: bool
            - errors: list of error messages
            - period_label: human-readable period label
            - period_start: "YYYY-MM-DD"
            - period_end: "YYYY-MM-DD"
            - iso_year: int (week mode only)
            - iso_week: int (week mode only)
            - year: int
            - month: int (month mode only)
            - missing_dates: list of missing dates (if any)
    """
    if not dates:
        return {'valid': False, 'errors': ['没有找到有效日期数据']}

    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(str(d)[:10], "%Y-%m-%d"))
        except ValueError:
            continue

    if not parsed:
        return {'valid': False, 'errors': ['无法解析任何日期']}

    parsed = sorted(set(parsed))
    data_start = parsed[0]
    data_end = parsed[-1]

    if mode == 'week':
        return _validate_week(parsed, data_start, data_end)
    elif mode == 'month':
        return _validate_month(parsed, data_start, data_end)
    else:
        return {'valid': False, 'errors': [f'未知模式: {mode}']}


def _validate_week(parsed, data_start, data_end):
    errors = []
    weekday_start = data_start.weekday()  # 0=Mon, 6=Sun
    weekday_end = data_end.weekday()

    if weekday_start != 0:
        errors.append(f'起始日期 {data_start.strftime("%Y-%m-%d")} 是星期{_weekday_cn(weekday_start)}，应为星期一')
    if weekday_end != 6:
        errors.append(f'结束日期 {data_end.strftime("%Y-%m-%d")} 是星期{_weekday_cn(weekday_end)}，应为星期日')

    expected_end = data_start + timedelta(days=6)
    if data_end != expected_end:
        errors.append(f'日期跨度不是7天: {data_start.strftime("%Y-%m-%d")} ~ {data_end.strftime("%Y-%m-%d")}')

    # Check for missing days
    all_days = set(d.strftime("%Y-%m-%d") for d in parsed)
    expected_days = []
    cursor = data_start
    while cursor <= data_end:
        expected_days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    missing = [d for d in expected_days if d not in all_days]

    if missing:
        errors.append(f'缺少 {len(missing)} 天数据: {", ".join(missing)}')

    iso_year, iso_week, _ = data_start.isocalendar()
    period_label = f'{iso_year}年第{iso_week}周（{data_start.strftime("%m月%d日")}-{data_end.strftime("%m月%d日")}）'

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'period_label': period_label,
        'period_start': data_start.strftime("%Y-%m-%d"),
        'period_end': data_end.strftime("%Y-%m-%d"),
        'iso_year': iso_year,
        'iso_week': iso_week,
        'missing_dates': missing,
    }


def _validate_month(parsed, data_start, data_end):
    errors = []
    expected_first = data_start.replace(day=1)
    if data_start != expected_first:
        errors.append(f'起始日期 {data_start.strftime("%Y-%m-%d")} 不是当月1号')

    last_day = calendar.monthrange(data_start.year, data_start.month)[1]
    expected_last = data_start.replace(day=last_day)
    if data_end != expected_last:
        errors.append(f'结束日期 {data_end.strftime("%Y-%m-%d")} 不是当月最后一天（{expected_last.strftime("%Y-%m-%d")}）')

    # Month must span single month
    if data_start.year != data_end.year or data_start.month != data_end.month:
        errors.append(f'日期跨月: {data_start.strftime("%Y-%m-%d")} ~ {data_end.strftime("%Y-%m-%d")}')

    # Check for missing days
    all_days = set(d.strftime("%Y-%m-%d") for d in parsed)
    expected_days = []
    cursor = data_start
    while cursor <= data_end:
        expected_days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    missing = [d for d in expected_days if d not in all_days]
    if missing:
        errors.append(f'缺少 {len(missing)} 天数据: {", ".join(missing)}')

    period_label = f'{data_start.year}年{data_start.month}月'

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'period_label': period_label,
        'period_start': data_start.strftime("%Y-%m-%d"),
        'period_end': data_end.strftime("%Y-%m-%d"),
        'year': data_start.year,
        'month': data_start.month,
        'missing_dates': missing,
    }


def get_comparison_periods(period_info, mode):
    """
    Compute 环比 and 同比 date ranges.

    Returns:
        dict with keys:
            - ringbi_start, ringbi_end: 环比 period dates
            - tongbi_start, tongbi_end: 同比 period dates
            - ringbi_label, tongbi_label: human-readable labels
            - ringbi_missing, tongbi_missing: list of dates that comparison needs
    """
    result = {}

    if mode == 'week':
        # 环比: previous week (7 days back)
        start = datetime.strptime(period_info['period_start'], "%Y-%m-%d")
        ringbi_start = start - timedelta(days=7)
        ringbi_end = ringbi_start + timedelta(days=6)
        result['ringbi_start'] = ringbi_start.strftime("%Y-%m-%d")
        result['ringbi_end'] = ringbi_end.strftime("%Y-%m-%d")
        result['ringbi_label'] = f'上周（{ringbi_start.strftime("%m/%d")}-{ringbi_end.strftime("%m/%d")}）'

        # 同比: same ISO week last year
        iso_year = period_info['iso_year']
        iso_week = period_info['iso_week']
        tongbi_start = _iso_week_to_monday(iso_year - 1, iso_week)
        tongbi_end = tongbi_start + timedelta(days=6)
        result['tongbi_start'] = tongbi_start.strftime("%Y-%m-%d")
        result['tongbi_end'] = tongbi_end.strftime("%Y-%m-%d")
        result['tongbi_label'] = f'去年同周（{tongbi_start.strftime("%m/%d")}-{tongbi_end.strftime("%m/%d")}）'

    elif mode == 'month':
        # 环比: previous month
        year = period_info['year']
        month = period_info['month']
        if month == 1:
            ringbi_year = year - 1
            ringbi_month = 12
        else:
            ringbi_year = year
            ringbi_month = month - 1
        ringbi_last = calendar.monthrange(ringbi_year, ringbi_month)[1]
        result['ringbi_start'] = f"{ringbi_year}-{ringbi_month:02d}-01"
        result['ringbi_end'] = f"{ringbi_year}-{ringbi_month:02d}-{ringbi_last:02d}"
        result['ringbi_label'] = f'上月（{ringbi_year}年{ringbi_month}月）'

        # 同比: same month last year
        tongbi_last = calendar.monthrange(year - 1, month)[1]
        result['tongbi_start'] = f"{year - 1}-{month:02d}-01"
        result['tongbi_end'] = f"{year - 1}-{month:02d}-{tongbi_last:02d}"
        result['tongbi_label'] = f'去年同月（{year - 1}年{month}月）'

    return result


def _iso_week_to_monday(iso_year, iso_week):
    """Convert ISO year + week number to the Monday of that week."""
    # Jan 4 is always in ISO week 1
    jan4 = datetime(iso_year, 1, 4)
    # Monday of week 1
    mon_week1 = jan4 - timedelta(days=jan4.weekday())
    return mon_week1 + timedelta(weeks=iso_week - 1)


def _weekday_cn(weekday):
    names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    return names[weekday]
