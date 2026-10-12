from datetime import date
import numpy as np
import pandas as pd
import pytest

import database as db
from data_processing import (dashboard_metrics, duplicate_flags, export_csv,
                             filter_expenses, read_csv_preview, validate_expense)
from generate_sample_data import classification_data, generate_transactions
from insights import budget_summary, spending_insights
from ml_models import (categorize, complete_monthly_totals, forecast_features,
                       forecast_spending, predict_steps, train_categorizer)

TODAY = date(2026, 10, 12)


def row(**changes):
    base = dict(date='2026-09-10', description='Metro ticket', amount=60, category='Transport')
    base.update(changes)
    return base


def frame(rows):
    result = pd.DataFrame(rows)
    result['date'] = pd.to_datetime(result['date'])
    return result


@pytest.mark.parametrize('amount', [0, -1, 'NaN', 'inf', 'abc', '12.345', 1_000_000_001])
def test_invalid_amounts(amount):
    with pytest.raises(ValueError):
        validate_expense(**dict(day='2026-01-01', description='Lunch', amount=amount, category='Food', today=TODAY))


@pytest.mark.parametrize('day', ['2026-02-30', '01/02/2026', '2027-01-01', '20260101', ''])
def test_invalid_dates(day):
    with pytest.raises(ValueError):
        validate_expense(day, 'Lunch', 10, 'Food', TODAY)


@pytest.mark.parametrize('description,category', [('', 'Food'), ('  ', 'Food'), ('Lunch', 'Invalid')])
def test_required_fields(description, category):
    with pytest.raises(ValueError):
        validate_expense('2026-01-01', description, 10, category, TODAY)


def test_csv_reports_errors_and_optional_categories():
    data = 'date,description,amount\n2026-01-01,Lunch,10\n2026-02-30,Bad,10\n2026-01-02,Zero,0\n2026-01-03,extra,10,oops\n'
    valid, errors = read_csv_preview(data, TODAY)
    assert len(valid) == 1 and valid.iloc[0]['category'] == ''
    assert len(errors) == 3


@pytest.mark.parametrize('text', ['', 'date,date,amount\n', 'description,amount\nLunch,10', 'date,description,amount\n2026-01-01,"unfinished,20'])
def test_malformed_csv_does_not_partially_import(text):
    valid, errors = read_csv_preview(text, TODAY)
    assert valid.empty and not errors.empty


def test_duplicate_detection_and_atomic_import(tmp_path):
    path = tmp_path / 'test.sqlite3'
    db.init_db(path)
    db.add_expense(path, row())
    incoming = pd.DataFrame([row(category='Other'), row(description='Bus'), row(description='Bus')])
    assert duplicate_flags(incoming, db.read_expenses(path)).tolist() == [True, False, True]
    assert db.import_expenses(path, incoming.to_dict('records')) == (1, 2)
    assert db.import_expenses(path, [row()], skip_duplicates=False) == (1, 0)
    with pytest.raises(ValueError):
        db.import_expenses(path, [row(description='New'), row(amount=0)])
    assert len(db.read_expenses(path)) == 3


def test_crud_persists_and_is_parameterized(tmp_path):
    path = tmp_path / 'personal.sqlite3'
    db.init_db(path)
    identity = db.add_expense(path, row(description="Lunch'); DROP TABLE expenses; --", amount=.29))
    assert db.read_expenses(path).iloc[0]['amount'] == .29
    db.update_expense(path, identity, row(amount=100.12))
    db.init_db(path)
    assert db.read_expenses(path).iloc[0]['amount'] == 100.12
    db.save_budget(path, 12000.50)
    assert db.get_budget(path) == 12000.50
    db.delete_expense(path, identity)
    assert db.read_expenses(path).empty
    demo = tmp_path / 'demo.sqlite3'
    db.init_db(demo)
    db.add_expense(demo, row())
    assert db.read_expenses(path).empty


def test_budget_and_matched_periods():
    assert budget_summary(125, 100)['usage_percent'] == 125
    assert budget_summary(125, 100)['overspent'] == 25
    assert budget_summary(50, 0)['usage_percent'] is None
    assert budget_summary(50, 100)['remaining'] == 50
    data = frame([row(date='2026-02-28', amount=100), row(date='2026-03-28', amount=120), row(date='2026-03-31', amount=50)])
    result = spending_insights(data, 150, '2026-03-31')
    assert result['matched_days'] == 28
    assert result['current_matched'] == 120
    assert result['budget']['spent'] == 170
    assert result['budget']['overspent'] == 20
    assert result['change_percent'] == pytest.approx(20)


def test_iqr_flags_and_dashboard_empty_range():
    data = frame([row(amount=10)] * 8 + [row(amount=1000)])
    assert len(spending_insights(data, 0, TODAY)['unusual']) == 1
    filtered = filter_expenses(data, '2026-09-01', '2026-09-30', ['Food'])
    metrics = dashboard_metrics(filtered, '2026-09-01', '2026-09-30', TODAY)
    assert metrics['total'] == 0 and metrics['top_category'] == '—'
    metrics = dashboard_metrics(data, '2026-09-01', '2026-09-30', TODAY)
    assert metrics['daily_average'] == 1080 / 30


def test_forecast_features_never_use_target_or_future():
    monthly = pd.Series(np.arange(1., 25.), index=pd.period_range('2024-01', periods=24, freq='M'))
    original = forecast_features(monthly)
    for target in range(3, len(monthly)):
        altered = monthly.copy()
        altered.iloc[target:] = 999999
        changed = forecast_features(altered)
        pd.testing.assert_series_equal(original.iloc[target-3][['previous_month', 'previous_three_average']],
                                       changed.iloc[target-3][['previous_month', 'previous_three_average']])
    assert original.iloc[0]['previous_three_average'] == 2


def test_complete_history_and_insufficient_data():
    data = frame([row(date='2026-07-15', amount=50), row(date='2026-09-01', amount=20), row(date='2026-10-01', amount=999999)])
    monthly = complete_monthly_totals(data, TODAY)
    assert list(monthly.index.astype(str)) == ['2026-08', '2026-09']
    assert monthly.tolist() == [0, 20]
    assert not forecast_spending(data, TODAY)['available']


def test_forecast_is_two_step_chronological_and_current_month_invariant():
    data = generate_transactions()
    result = forecast_spending(data, TODAY)
    assert result['available'] and result['target_month'] == '2026-11'
    assert len(result['evaluation']) == 3
    for evaluated in result['evaluation'].to_dict('records'):
        assert pd.Period(evaluated['month']) - 2 == pd.Period(evaluated['last_training_month'])
    extra = pd.concat([data, pd.DataFrame([row(date='2026-10-10', amount=999999)])], ignore_index=True)
    assert forecast_spending(extra, TODAY)['prediction'] == result['prediction']
    assert result['model_mae'] >= 0 and result['baseline_mae'] >= 0


def test_negative_forecast_is_clipped():
    class NegativeModel:
        def predict(self, data):
            return np.array([-100.0])
    assert predict_steps(NegativeModel(), pd.Series([10., 20., 30.])) == [0., 0.]


def test_classifier_split_and_graceful_fallback():
    data = classification_data()
    result = train_categorizer(pd.concat([data, data], ignore_index=True))
    assert result['model'] is not None
    assert set(result['train_descriptions']).isdisjoint(result['test_descriptions'])
    assert result['train_size'] + result['test_size'] == len(data)
    assert 0 <= result['accuracy'] <= 1
    assert categorize('zxqv zzzunknown', result) == ('Other', 'fallback')
    short = train_categorizer(data.iloc[:2])
    assert short['model'] is None
    assert categorize('lunch', short) == ('Other', 'fallback')


def test_synthetic_reproducibility_and_csv_safety():
    first = generate_transactions()
    pd.testing.assert_frame_equal(first, generate_transactions())
    assert pd.to_datetime(first['date']).dt.to_period('M').nunique() == 30
    exported = export_csv(frame([row(description='=SUM(A1:A9)')])).decode('utf-8-sig')
    assert "'=SUM" in exported
