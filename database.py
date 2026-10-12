"""SQLite storage. Money is stored as integer paise to avoid rounding drift."""
import sqlite3
import math
from pathlib import Path

import pandas as pd
from data_processing import validate_expense

SOURCES = ('manual', 'model', 'fallback', 'synthetic')


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def init_db(path):
    with connect(path) as connection:
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, description TEXT NOT NULL,
            amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
            category TEXT NOT NULL, category_source TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS expenses_date ON expenses(date);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')


def read_expenses(path):
    with connect(path) as connection:
        frame = pd.read_sql_query('SELECT id, date, description, amount_paise, category, category_source FROM expenses ORDER BY date DESC, id DESC', connection)
    frame['date'] = pd.to_datetime(frame['date'], format='%Y-%m-%d')
    frame['amount'] = frame.pop('amount_paise').astype(float) / 100
    return frame


def values_for(row):
    clean = validate_expense(row['date'], row['description'], row['amount'], row['category'])
    source = row.get('category_source', 'manual')
    if source not in SOURCES:
        raise ValueError('Invalid category source.')
    return (clean['date'], clean['description'], int(round(clean['amount'] * 100)), clean['category'], source)


def add_expense(path, row):
    values = values_for(row)
    with connect(path) as connection:
        cursor = connection.execute('INSERT INTO expenses(date,description,amount_paise,category,category_source) VALUES(?,?,?,?,?)', values)
        return cursor.lastrowid


def update_expense(path, expense_id, row):
    values = values_for(row)
    with connect(path) as connection:
        connection.execute('UPDATE expenses SET date=?,description=?,amount_paise=?,category=?,category_source=? WHERE id=?', values + (int(expense_id),))


def delete_expense(path, expense_id):
    with connect(path) as connection:
        connection.execute('DELETE FROM expenses WHERE id=?', (int(expense_id),))


def import_expenses(path, rows, skip_duplicates=True):
    prepared = [values_for(row) for row in rows]  # Validate everything before writing.
    added = skipped = 0
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        seen = set(connection.execute('SELECT date,description,amount_paise FROM expenses').fetchall())
        for values in prepared:
            key = values[:3]
            if skip_duplicates and key in seen:
                skipped += 1
                continue
            connection.execute('INSERT INTO expenses(date,description,amount_paise,category,category_source) VALUES(?,?,?,?,?)', values)
            seen.add(key)
            added += 1
    return added, skipped


def get_budget(path):
    with connect(path) as connection:
        row = connection.execute('SELECT value FROM settings WHERE key=?', ('monthly_budget_paise',)).fetchone()
    return int(row[0]) / 100 if row else 0.0


def save_budget(path, budget):
    if not math.isfinite(budget) or budget < 0 or budget > 1_000_000_000 or round(budget, 2) != budget:
        raise ValueError('Budget must be non-negative with at most two decimals.')
    with connect(path) as connection:
        connection.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('monthly_budget_paise', str(int(round(budget * 100)))))
