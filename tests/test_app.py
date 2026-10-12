"""Exercise real Streamlit forms in isolated temporary databases."""
from pathlib import Path
from streamlit.testing.v1 import AppTest
import database as db

APP = Path(__file__).resolve().parents[1] / 'app.py'


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def test_app_crud_budget_and_demo_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('EXPENSE_TRACKER_DATA_DIR', str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert app.metric[0].value == '₹0.00'
    by_label(app.text_input, 'Description').set_value('Cafe coffee').run()
    by_label(app.number_input, 'Amount (INR)').set_value(150)
    by_label(app.selectbox, 'Category').select('Food')
    by_label(app.button, 'Save expense').click().run()
    assert not app.exception
    personal = tmp_path / 'personal.sqlite3'
    assert db.read_expenses(personal).iloc[0]['amount'] == 150
    by_label(app.number_input, 'Edit amount (INR)').set_value(200)
    by_label(app.button, 'Save changes').click().run()
    assert db.read_expenses(personal).iloc[0]['amount'] == 200
    by_label(app.number_input, 'Monthly budget (INR; 0 disables)').set_value(100)
    by_label(app.button, 'Save monthly budget').click().run()
    assert db.get_budget(personal) == 100
    assert any('Over budget' in element.value for element in app.error)
    by_label(app.checkbox, 'I confirm deletion of this transaction').check().run()
    by_label(app.button, 'Delete selected expense').click().run()
    assert db.read_expenses(personal).empty
    by_label(app.radio, 'Data mode').set_value('Synthetic demo').run()
    by_label(app.button, 'Load synthetic demo data').click().run()
    assert not app.exception
    assert len(db.read_expenses(tmp_path / 'demo.sqlite3')) > 1000
    assert db.read_expenses(personal).empty
    assert any('Estimated spending' in metric.label for metric in app.metric)
    # A fresh app session reads the previously saved budget and personal database.
    fresh = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not fresh.exception
    assert by_label(fresh.number_input, 'Monthly budget (INR; 0 disables)').value == 100
