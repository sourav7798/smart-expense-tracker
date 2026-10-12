"""Validation and small, vectorized transformations shared by UI and storage."""
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

CATEGORIES = ['Food', 'Transport', 'Shopping', 'Bills', 'Entertainment', 'Health', 'Education', 'Other']
FIELDS = ['date', 'description', 'amount', 'category']
MAX_AMOUNT = 1_000_000_000


def validate_expense(day, description, amount, category, today=None):
    today = today or date.today()
    raw_day = str(day).strip()
    try:
        parsed = date.fromisoformat(raw_day)
        if parsed.isoformat() != raw_day or parsed > today:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Date must be YYYY-MM-DD and cannot be in the future.') from None
    description = str(description).strip() if description is not None else ''
    if not description or len(description) > 300:
        raise ValueError('Description is required (maximum 300 characters).')
    try:
        value = Decimal(str(amount).strip())
        if not value.is_finite() or value <= 0 or value > MAX_AMOUNT:
            raise InvalidOperation
        if value != value.quantize(Decimal('0.01')):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ValueError('Amount must be positive, finite, at most 1 billion INR, and have at most 2 decimals.') from None
    category = str(category).strip()
    if category not in CATEGORIES:
        raise ValueError('Choose one of the eight supported categories.')
    return {'date': raw_day, 'description': description, 'amount': float(value), 'category': category}


def read_csv_preview(raw, today=None):
    """Reject a broken CSV structure; report individual invalid rows without importing."""
    valid, errors = [], []
    try:
        text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
        reader = csv.reader(io.StringIO(text), strict=True)
        header = [x.strip().lower() for x in next(reader)]
        if len(header) != len(set(header)) or not set(['date', 'description', 'amount']).issubset(header):
            raise ValueError('CSV requires unique date, description, amount headers; category is optional.')
        if set(header) - set(FIELDS):
            raise ValueError('Unknown columns. Use the downloadable four-column template.')
        for values in reader:
            line = reader.line_num
            if not values or all(not str(v).strip() for v in values):
                errors.append({'row': line, 'error': 'Blank row.'})
                continue
            if len(values) != len(header):
                errors.append({'row': line, 'error': 'Wrong number of fields.'})
                continue
            row = dict(zip(header, values))
            category = row.get('category', '').strip()
            try:
                clean = validate_expense(row['date'], row['description'], row['amount'], category or 'Other', today)
                clean['category'] = category  # A blank value will be predicted in the UI.
                clean['csv_row'] = line
                valid.append(clean)
            except ValueError as exc:
                errors.append({'row': line, 'error': str(exc)})
    except (csv.Error, UnicodeDecodeError, StopIteration, ValueError) as exc:
        return pd.DataFrame(columns=FIELDS + ['csv_row']), pd.DataFrame([{'row': 'file', 'error': str(exc) or 'Empty CSV.'}])
    return pd.DataFrame(valid, columns=FIELDS + ['csv_row']), pd.DataFrame(errors, columns=['row', 'error'])


def transaction_key(row):
    # Category and source are deliberately not part of transaction identity.
    return (str(row['date'])[:10], str(row['description']).strip(), int(round(float(row['amount']) * 100)))


def duplicate_flags(incoming, existing):
    seen = {transaction_key(row) for row in existing.to_dict('records')}
    flags = []
    for row in incoming.to_dict('records'):
        key = transaction_key(row)
        flags.append(key in seen)
        seen.add(key)
    return pd.Series(flags, index=incoming.index, dtype=bool)


def filter_expenses(frame, start, end, categories, search=''):
    mask = frame['date'].between(pd.Timestamp(start), pd.Timestamp(end)) & frame['category'].isin(categories)
    if search.strip():
        mask &= frame['description'].str.contains(search.strip(), case=False, regex=False, na=False)
    return frame.loc[mask].copy()


def dashboard_metrics(frame, start, end, today=None):
    today = pd.Timestamp(today or date.today())
    current = frame[frame['date'].dt.to_period('M') == today.to_period('M')]
    totals = frame.groupby('category')['amount'].sum()
    days = max((pd.Timestamp(end) - pd.Timestamp(start)).days + 1, 1)
    return {'total': frame['amount'].sum(), 'current_month': current['amount'].sum(),
            'daily_average': frame['amount'].sum() / days,
            'top_category': totals.idxmax() if not totals.empty else '—'}


def export_csv(frame):
    exported = frame[FIELDS].copy()
    exported['date'] = pd.to_datetime(exported['date']).dt.strftime('%Y-%m-%d')
    # Neutralize spreadsheet formulas in free-text cells; amounts/dates stay numeric/readable.
    exported['description'] = exported['description'].map(
        lambda s: "'" + s if s.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else s)
    return exported.to_csv(index=False).encode('utf-8-sig')
