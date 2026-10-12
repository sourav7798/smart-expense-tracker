"""Exercise user-facing navigation and real persistence in isolated local storage."""
from pathlib import Path
from streamlit.testing.v1 import AppTest
import database as db
from generate_sample_data import generate_transactions

APP = Path(__file__).resolve().parents[1] / 'app.py'


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def go(app, page):
    by_label(app.radio, 'Go to').set_value(page).run()
    assert not app.exception


def test_user_journey_crud_budget_and_no_demo(tmp_path, monkeypatch):
    monkeypatch.setenv('EXPENSE_TRACKER_DATA_DIR', str(tmp_path))
    # A legacy demo database must never be read, imported, or deleted by the app.
    legacy = tmp_path / 'demo.sqlite3'
    legacy.write_bytes(b'legacy demo must remain untouched')
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert by_label(app.radio, 'Go to').options == ['Overview', 'Add expense', 'Transactions', 'Import CSV', 'Budget & insights', 'Help']
    assert not app.metric  # No fake numbers or generated transactions on first launch.
    by_label(app.button, 'Add an expense').click().run()
    assert by_label(app.radio, 'Go to').value == 'Add expense'
    by_label(app.text_input, 'Description').set_value('Cafe coffee')
    by_label(app.number_input, 'Amount (INR)').set_value(150)
    by_label(app.selectbox, 'Category').select('Food')
    by_label(app.button, 'Save expense').click().run()
    personal = tmp_path / 'personal.sqlite3'
    assert not app.exception
    assert db.read_expenses(personal).iloc[0]['amount'] == 150
    assert by_label(app.text_input, 'Description').value == ''
    by_label(app.button, 'View saved transactions').click().run()
    by_label(app.number_input, 'Edit amount (INR)').set_value(200)
    by_label(app.button, 'Save changes').click().run()
    assert db.read_expenses(personal).iloc[0]['amount'] == 200
    go(app, 'Overview')
    assert app.metric[0].value == '₹200.00'
    assert len(app.get('plotly_chart')) == 3
    go(app, 'Budget & insights')
    by_label(app.number_input, 'Monthly budget (INR; 0 disables)').set_value(100)
    by_label(app.button, 'Save monthly budget').click().run()
    assert db.get_budget(personal) == 100
    assert any('Over budget' in item.value for item in app.error)
    assert any('Not enough historical data' in item.value for item in app.info)
    go(app, 'Transactions')
    by_label(app.checkbox, 'I confirm deletion of this transaction').check().run()
    by_label(app.button, 'Delete selected expense').click().run()
    assert db.read_expenses(personal).empty
    assert legacy.read_bytes() == b'legacy demo must remain untouched'
    fresh = AppTest.from_file(str(APP), default_timeout=30).run()
    go(fresh, 'Budget & insights')
    assert by_label(fresh.number_input, 'Monthly budget (INR; 0 disables)').value == 100


def test_existing_records_survive_and_user_can_find_them(tmp_path, monkeypatch):
    monkeypatch.setenv('EXPENSE_TRACKER_DATA_DIR', str(tmp_path))
    personal = tmp_path / 'personal.sqlite3'
    db.init_db(personal)
    db.add_expense(personal, dict(date='2026-01-10', description='Existing purchase', amount=250, category='Food'))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert len(db.read_expenses(personal)) == 1
    go(app, 'Transactions')
    by_label(app.text_input, 'Find a transaction').set_value('not matching').run()
    assert not app.selectbox
    assert any('No transactions match' in item.value for item in app.info)
    go(app, 'Import CSV')
    assert any('1. Download' in item.value for item in app.markdown)
    go(app, 'Help')
    assert any('Where is my data saved?' == item.label for item in app.expander)
    go(app, 'Add expense')
    by_label(app.button, 'Save expense').click().run()
    assert app.error
    assert len(db.read_expenses(personal)) == 1


def test_forecast_uses_saved_history_only_after_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv('EXPENSE_TRACKER_DATA_DIR', str(tmp_path))
    personal = tmp_path / 'personal.sqlite3'
    db.init_db(personal)
    # Synthetic fixtures are used only for tests, never loaded by the user app.
    from datetime import date
    db.import_expenses(personal, generate_transactions(date.today()).to_dict('records'))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    go(app, 'Budget & insights')
    assert not any('Estimated spending' in item.label for item in app.metric)
    by_label(app.checkbox, 'My history covers all spending from the first recorded month through last month').check().run()
    assert not app.exception
    assert any('Estimated spending' in item.label for item in app.metric)
    assert not (tmp_path / 'demo.sqlite3').exists()
