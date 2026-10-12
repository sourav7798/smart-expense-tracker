"""Rule-based summaries: none of these functions is a trained AI model."""
from datetime import date
import calendar
import pandas as pd


def budget_summary(spent, budget):
    if spent < 0 or budget < 0:
        raise ValueError('Spending and budget cannot be negative.')
    return {'spent': spent, 'budget': budget, 'remaining': budget - spent,
            'usage_percent': spent / budget * 100 if budget > 0 else None,
            'overspent': max(0, spent - budget) if budget > 0 else 0}


def spending_insights(frame, budget, today=None):
    today = pd.Timestamp(today or date.today()).normalize()
    current_start = today.replace(day=1)
    previous_start = current_start - pd.DateOffset(months=1)
    matched_days = min(today.day, calendar.monthrange(previous_start.year, previous_start.month)[1])
    current_end = current_start + pd.Timedelta(days=matched_days - 1)
    previous_end = previous_start + pd.Timedelta(days=matched_days - 1)
    current_total = float(frame.loc[frame['date'].between(current_start, today), 'amount'].sum())
    current_matched = float(frame.loc[frame['date'].between(current_start, current_end), 'amount'].sum())
    previous_matched = float(frame.loc[frame['date'].between(previous_start, previous_end), 'amount'].sum())
    totals = frame.groupby('category')['amount'].sum().sort_values(ascending=False)
    threshold = None
    unusual = frame.iloc[:0].copy()
    if len(frame) >= 8:
        q1, q3 = frame['amount'].quantile([.25, .75])
        threshold = float(q3 + 1.5 * (q3 - q1))
        unusual = frame[frame['amount'] > threshold].copy()
    suggestions = []
    if not totals.empty:
        suggestions.append(f'{totals.index[0]} is your largest category: INR {totals.iloc[0]:,.2f}. Review its transactions for optional purchases.')
    if previous_matched > 0 and current_matched > previous_matched:
        suggestions.append(f'Spending in the matched {matched_days}-day period rose by INR {current_matched - previous_matched:,.2f}. Check which purchases explain the increase.')
    status = budget_summary(current_total, budget)
    if budget == 0:
        suggestions.append('Set a monthly budget to track spending against your own target.')
    elif status['overspent'] > 0:
        suggestions.append(f'You are INR {status["overspent"]:,.2f} over budget. Review discretionary expenses before adding more.')
    else:
        suggestions.append(f'INR {status["remaining"]:,.2f} remains in this month’s budget.')
    return {'budget': status, 'current_matched': current_matched, 'previous_matched': previous_matched,
            'matched_days': matched_days, 'change_percent': (current_matched / previous_matched - 1) * 100 if previous_matched > 0 else None,
            'unusual': unusual, 'threshold': threshold, 'suggestions': suggestions,
            'top_category': totals.index[0] if not totals.empty else None}
