"""Run with: streamlit run app.py"""
import os
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import database as db
from ui import apply_style, hero, sidebar_brand, chart_style, empty_state, CATEGORY_COLORS
from data_processing import (CATEGORIES, FIELDS, dashboard_metrics, duplicate_flags,
                             export_csv, filter_expenses, read_csv_preview, validate_expense)
from insights import spending_insights
from ml_models import MIN_HISTORY, categorize, forecast_spending, train_categorizer

ROOT = Path(__file__).resolve().parent
DATA_HOME = Path(os.environ.get('EXPENSE_TRACKER_DATA_DIR', ROOT / 'local_data'))


@st.cache_data(ttl=60)
def load_expenses(path):
    return db.read_expenses(path)


@st.cache_resource
def load_categorizer(training_bytes):
    from io import BytesIO
    try:
        return train_categorizer(pd.read_csv(BytesIO(training_bytes)))
    except (ValueError, pd.errors.ParserError) as exc:
        return {'model': None, 'error': str(exc)}


def changed(message):
    load_expenses.clear()
    st.session_state['notice'] = message
    st.rerun()


def money(value):
    return f'₹{value:,.2f}'


def dashboard(frame, today):
    st.subheader('Your spending at a glance')
    st.caption('See your recorded spending. Add an expense whenever you pay for something.')
    a, b, c = st.columns(3)
    a.button('Add an expense', type='primary', on_click=navigate, args=('Add expense',), use_container_width=True)
    b.button('Import a CSV', on_click=navigate, args=('Import CSV',), use_container_width=True)
    c.button('Set a budget', on_click=navigate, args=('Budget & insights',), use_container_width=True)
    if frame.empty:
        empty_state()
        st.info('Get started: 1. Add an expense or import a CSV. 2. Set your monthly budget. 3. Return here to see your spending.')
        return
    start_default = frame['date'].min().date() if not frame.empty else today.replace(day=1)
    with st.expander('Filter by date & category', expanded=False):
        left, right = st.columns(2)
        start = left.date_input('From', start_default, max_value=today, key='overview_from')
        end = right.date_input('To', today, max_value=today, key='overview_to')
        categories = st.multiselect('Categories', CATEGORIES, default=CATEGORIES, key='overview_categories')
    search = st.text_input('Search descriptions', key='overview_search', placeholder='Search coffee, groceries, metro…')
    if start > end:
        st.warning('From date must be on or before To date.')
        return
    filtered = filter_expenses(frame, start, end, categories, search)
    st.caption(f"{start:%d %b %Y} – {end:%d %b %Y}  ·  {len(categories)} categories  ·  {len(filtered):,} transactions")
    metrics = dashboard_metrics(filtered, start, end, today)
    columns = st.columns(4)
    for col, label, value in zip(columns, ['Total spending', 'Current month', 'Average per day', 'Top category'],
                                  [money(metrics['total']), money(metrics['current_month']), money(metrics['daily_average']), metrics['top_category']]):
        col.metric(label, value)
    st.caption('Metrics respect all filters. Daily average includes every day in the selected range, including zero-spend days.')
    if filtered.empty:
        empty_state()
    else:
        monthly = filtered.assign(month=filtered['date'].dt.to_period('M').dt.to_timestamp()).groupby('month', as_index=False)['amount'].sum()
        daily = filtered.groupby('date')['amount'].sum().reindex(pd.date_range(start, end), fill_value=0).rename_axis('date').reset_index()
        category = filtered.groupby('category', as_index=False)['amount'].sum().sort_values('amount', ascending=False)
        a, b = st.columns([1.6, 1])
        with a.container(border=True):
            st.subheader('Spending over time')
            st.caption('Monthly totals · INR')
            chart = px.bar(monthly, x='month', y='amount', color_discrete_sequence=['#087F73'])
            chart.update_traces(marker_cornerradius=5, hovertemplate='%{x|%b %Y}<br>₹%{y:,.2f}<extra></extra>')
            chart.update_xaxes(dtick='M3' if len(monthly) > 18 else 'M1', tickformat='%b %y')
            st.plotly_chart(chart_style(chart), use_container_width=True, config={'displayModeBar': False}, theme=None)
        with b.container(border=True):
            st.subheader('Where it goes')
            st.caption('Category share · INR')
            chart = px.pie(category, names='category', values='amount', hole=.72,
                           color='category', color_discrete_map=CATEGORY_COLORS)
            chart.update_traces(textinfo='none', marker=dict(line=dict(color='#F5F7FA', width=3)),
                                hovertemplate='%{label}<br>₹%{value:,.2f} · %{percent}<extra></extra>')
            chart.update_layout(legend=dict(orientation='h', y=-.12, x=.5, xanchor='center', font_size=13),
                                annotations=[dict(text='SPENDING', x=.5, y=.5, showarrow=False, font=dict(size=14,color='#27384D'))])
            st.plotly_chart(chart_style(chart), use_container_width=True, config={'displayModeBar': False}, theme=None)
        with st.container(border=True):
            st.subheader('Daily rhythm')
            st.caption('See the peaks and quieter days in your spending.')
            chart = px.area(daily, x='date', y='amount', color_discrete_sequence=['#6F73D2'])
            chart.update_traces(line_width=2, fillcolor='rgba(111,115,210,0.12)',
                                hovertemplate='%{x|%d %b %Y}<br>₹%{y:,.2f}<extra></extra>')
            st.plotly_chart(chart_style(chart, 240), use_container_width=True, config={'displayModeBar': False}, theme=None)
    st.subheader('Transaction history')
    st.caption('Your saved records. Open Transactions in the sidebar to edit or delete an expense.')
    st.dataframe(filtered[['id'] + FIELDS], hide_index=True, use_container_width=True,
                 column_config={'id': st.column_config.NumberColumn('ID', format='%d'),
                                'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'),
                                'description': st.column_config.TextColumn('Description', width='large'),
                                'amount': st.column_config.NumberColumn('Amount (₹)', format='₹ %.2f'),
                                'category': 'Category', 'category_source': 'Categorized by'})
    st.download_button('Export filtered CSV', export_csv(filtered), 'filtered_expenses.csv', 'text/csv', icon=':material/download:')


def add_expense_page(path, trained, today):
    st.subheader('Record an expense')
    st.caption('Enter what you paid for, the date and amount. Everything is saved when you click Save expense.')
    revision = st.session_state.get('expense_form_revision', 0)
    with st.form(f'add_expense_{revision}'):
        description = st.text_input('Description', max_chars=300, placeholder='For example: groceries or metro ticket')
        date_col, amount_col = st.columns(2)
        day = date_col.date_input('Expense date', today, max_value=today)
        amount = amount_col.number_input('Amount (INR)', min_value=0.0, max_value=1_000_000_000.0, step=10.0, format='%.2f')
        choice = st.selectbox('Category', ['Suggest automatically'] + CATEGORIES,
                              help='Choose a category yourself, or let the app suggest one from your description.')
        st.caption('Automatic categories can be wrong. Review or change them later in Transactions.')
        submitted = st.form_submit_button('Save expense', type='primary', use_container_width=True)
    if submitted:
        try:
            predicted, source = categorize(description, trained)
            automatic = choice == 'Suggest automatically'
            row = validate_expense(day, description, amount, predicted if automatic else choice, today)
            row['category_source'] = source if automatic else 'manual'
            db.add_expense(path, row)
            st.session_state['expense_form_revision'] = revision + 1
            changed(f"Expense saved: {money(row['amount'])} in {row['category']}. You can review it in Transactions.")
        except ValueError as exc:
            st.error(str(exc))
    st.button('View saved transactions', on_click=navigate, args=('Transactions',))


def transactions_page(frame, path, today):
    st.subheader('Your transactions')
    st.caption('Find a purchase, review its category, or correct a saved entry.')
    if frame.empty:
        st.info('No transactions yet. Add your first expense or import your existing records.')
        st.button('Add your first expense', type='primary', on_click=navigate, args=('Add expense',))
        return
    search = st.text_input('Find a transaction', placeholder='Search a description')
    a, b = st.columns(2)
    start = a.date_input('Start date', frame['date'].min().date(), max_value=today)
    end = b.date_input('End date', today, max_value=today)
    categories = st.multiselect('Show categories', CATEGORIES, default=CATEGORIES)
    if start > end:
        st.warning('Start date must be on or before end date.')
        return
    frame = filter_expenses(frame, start, end, categories, search)
    st.caption(f'{len(frame):,} matching transactions')
    shown = frame[['id'] + FIELDS + ['category_source']].copy()
    shown['category_source'] = shown['category_source'].map({'manual': 'Chosen by you', 'model': 'Suggested automatically', 'fallback': 'Needs review', 'synthetic': 'Synthetic (legacy)'})
    st.dataframe(shown, hide_index=True, use_container_width=True,
                 column_config={'amount': st.column_config.NumberColumn('Amount (₹)', format='₹ %.2f'),
                                'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'),
                                'category_source': 'Category choice'})
    st.download_button('Download these transactions', export_csv(frame), 'expenses.csv', 'text/csv')
    st.subheader('Edit or delete an expense')
    if frame.empty:
        st.info('No transactions match your filters. Try another date, category or search.')
        return
    selected_id = st.selectbox('Choose a transaction to edit', frame['id'].tolist(),
                               format_func=lambda value: f"{frame.loc[frame.id == value, 'date'].iloc[0]:%d %b %Y} · {frame.loc[frame.id == value, 'description'].iloc[0]} · {money(frame.loc[frame.id == value, 'amount'].iloc[0])} · #{value}")
    row = frame.loc[frame.id == selected_id].iloc[0]
    with st.form(f'edit_{selected_id}'):
        edited_day = st.date_input('Edit date', row['date'].date(), max_value=today)
        edited_description = st.text_input('Edit description', row['description'], max_chars=300)
        edited_amount = st.number_input('Edit amount (INR)', value=float(row['amount']), min_value=0.0, max_value=1_000_000_000.0, format='%.2f')
        edited_category = st.selectbox('Edit category', CATEGORIES, index=CATEGORIES.index(row['category']))
        st.caption('Check the category before saving. Your selection replaces any automatic suggestion.')
        save = st.form_submit_button('Save changes', type='primary')
    if save:
        try:
            updated = validate_expense(edited_day, edited_description, edited_amount, edited_category, today)
            updated['category_source'] = 'manual'
            db.update_expense(path, selected_id, updated)
            changed('Expense updated.')
        except ValueError as exc:
            st.error(str(exc))
    confirm = st.checkbox('I confirm deletion of this transaction', key=f'delete_confirm_{selected_id}')
    if st.button('Delete selected expense', disabled=not confirm):
        db.delete_expense(path, selected_id)
        changed('Expense deleted.')


def csv_import(frame, path, trained, today):
    st.subheader('Import your expenses')
    st.write('1. Download the format template. 2. Fill it with your own expenses. 3. Upload and review before saving.')
    st.download_button('Download CSV template', 'date,description,amount,category\n',
                       'expense_template.csv', 'text/csv')
    st.caption('Use dates like YYYY-MM-DD and positive INR amounts like 120.50. Category is optional; automatic suggestions can be reviewed in Transactions.')
    upload = st.file_uploader('Upload expenses CSV', type=['csv'])
    if upload is None:
        return
    if upload.size > 5 * 1024 * 1024:
        st.error('Please use a CSV smaller than 5 MB.')
        return
    valid, errors = read_csv_preview(upload.getvalue(), today)
    if not errors.empty:
        st.warning(f'{len(errors)} validation error(s). Only valid rows can be imported.')
        st.dataframe(errors, hide_index=True)
    if valid.empty:
        st.info('No valid rows to import.')
        return
    rows = []
    for row in valid.to_dict('records'):
        if not row['category']:
            row['category'], row['category_source'] = categorize(row['description'], trained)
        else:
            row['category_source'] = 'manual'
        rows.append(row)
    preview = pd.DataFrame(rows)
    preview['duplicate'] = duplicate_flags(preview, frame)
    st.write(f"Valid rows: {len(preview)} · Invalid rows/errors: {len(errors)} · Duplicates: {int(preview['duplicate'].sum())}")
    st.caption('Duplicates match date, trimmed case-sensitive description, and amount in paise, regardless of category; checks include existing records and earlier rows in this upload.')
    st.dataframe(preview, hide_index=True, use_container_width=True)
    skip = st.checkbox('Skip duplicates', value=True)
    acknowledge = True
    if not errors.empty:
        acknowledge = st.checkbox('Import only the valid rows; discard the invalid rows')
    if st.button('Import reviewed rows', disabled=not acknowledge, type='primary'):
        added, skipped = db.import_expenses(path, rows, skip)
        changed(f'Imported {added} expense(s); skipped {skipped} duplicate(s).')
    st.caption('To override an imported prediction, open Transactions after import.')


def insights_page(frame, path, today):
    st.subheader('Your monthly budget')
    st.caption('Set how much you want to spend each month. Budget calculations use all your saved expenses, regardless of dashboard filters.')
    with st.form('budget'):
        budget = st.number_input('Monthly budget (INR; 0 disables)', value=db.get_budget(path), min_value=0.0, max_value=1_000_000_000.0, format='%.2f')
        if st.form_submit_button('Save monthly budget', type='primary'):
            db.save_budget(path, budget)
            changed('Monthly budget saved.')
    result = spending_insights(frame, db.get_budget(path), today)
    status = result['budget']
    st.metric('Current month spending', money(status['spent']))
    if status['usage_percent'] is not None:
        st.progress(min(status['usage_percent'] / 100, 1.0))
        st.write(f"Budget used: {status['usage_percent']:.1f}%")
        if status['overspent']:
            st.error(f"Over budget by {money(status['overspent'])}.")
    st.write(f"Equivalent period comparison: first {result['matched_days']} days of each month.")
    st.write(f"Current: {money(result['current_matched'])} · Previous: {money(result['previous_matched'])}")
    if result['change_percent'] is None:
        st.caption('Percentage change unavailable: previous period has no recorded spending. Missing records may make comparisons misleading.')
    else:
        st.write(f"Change: {result['change_percent']:+.1f}%")
    for suggestion in result['suggestions']:
        st.write('• ' + suggestion)
    st.subheader('Expenses worth reviewing')
    st.caption('These expenses are large compared with your other records. This is a statistical rule, not a fraud warning.')
    with st.expander('How are these expenses selected?'):
        st.write('With at least 8 records, amounts above Q3 + 1.5 × IQR are flagged. IQR is the difference between the 75th and 25th percentiles. Regular bills can be flagged too.')
    if result['threshold'] is None:
        st.info('At least 8 transactions are needed for the unusual-amount rule.')
    else:
        st.write(f"Threshold: {money(result['threshold'])}")
        st.dataframe(result['unusual'][FIELDS], hide_index=True)
    st.divider()
    st.subheader('Plan for next month')
    st.caption(f'Requires {MIN_HISTORY} complete months after discarding the first recorded month and the incomplete current month. Unrecorded intervening months are treated as zero spending.')
    forecast = forecast_spending(frame, today)
    if not forecast['available']:
        st.info(f"Not enough historical data — {forecast['months']} usable complete months; {MIN_HISTORY} required. Keep recording expenses or import your past history. No estimate is made up.")
        return
    confirmed = st.checkbox('My history covers all spending from the first recorded month through last month')
    if not confirmed:
        st.info('Confirm history coverage before interpreting a forecast. Missing imports are not zero spending.')
        return
    st.metric(f"Estimated spending · {forecast['target_month']}", money(forecast['prediction']))
    st.write(f"Last-complete-month baseline estimate: {money(forecast['baseline_prediction'])}")
    st.caption('The current month is incomplete: predict its total first, then recursively predict next month. Negative predictions are clipped to zero. Estimates can be inaccurate and are not spending limits.')
    with st.expander('How reliable is this estimate?'):
        a, b = st.columns(2)
        a.metric('Model MAE · held-out months', money(forecast['model_mae']))
        b.metric('Baseline MAE · held-out months', money(forecast['baseline_mae']))
        if forecast['model_mae'] >= forecast['baseline_mae']:
            st.warning('The model did not beat the simple baseline in this evaluation. Consider the baseline as well.')
        st.caption('Expanding chronological evaluation on the last 3 historical target months; two-step forecasts use only information known two months before each target. Baseline repeats the last observed month for both steps. MAE is average absolute error in INR, not a confidence interval.')
        st.dataframe(forecast['evaluation'].round(2), hide_index=True)


def navigate(page):
    st.session_state['page'] = page


def help_page(trained):
    st.subheader('How to use your expense tracker')
    st.write('**1. Record spending** — open Add expense, enter a description, date and amount, then save.')
    st.write('**2. Review records** — open Transactions to search, edit, delete or download your expenses.')
    st.write('**3. Bring existing records** — use Import CSV to preview and check your file before saving.')
    st.write('**4. Set a limit** — open Budget & insights to save a monthly budget and track what remains.')
    st.write('**5. See the picture** — Overview shows charts and totals from the expenses you have actually saved.')
    with st.expander('Where is my data saved?'):
        st.write('Your expenses are saved on this computer and remain after restarting the app. Each local installation has one expense book. There are no online accounts or shared-user access controls; use your own installation for separate private records.')
        st.write('Existing saved expenses and budgets are preserved when you update. Export a CSV from Transactions to keep a portable copy of your expenses.')
    with st.expander('Does it connect to my bank?'):
        st.write('No. Enter expenses yourself or import a CSV in the required format. All totals, charts and budgets use those saved records. Nothing is auto-filled with sample transactions.')
    with st.expander('How do automatic categories and forecasts work?'):
        st.write('Category suggestions come from a machine-learning model trained on synthetic labeled descriptions. It can suggest categories for your actual expenses, but check its choices. Unknown descriptions use Other and are marked Needs review.')
        st.write('Forecasts use your own monthly spending history and require at least 15 usable completed months. The first recorded month and current incomplete month are excluded. Budget alerts and spending comparisons are simple rules, not trained AI.')
    with st.expander('Category model evaluation (technical details)'):
        st.caption('Synthetic test scores do not establish accuracy on real transactions.')
        if trained.get('model') is not None:
            st.metric('Held-out synthetic accuracy', f"{trained['accuracy']:.1%}")
            st.dataframe(pd.DataFrame(trained['report']).T, use_container_width=True)
        else:
            st.info('Automatic categorization is unavailable. You can still choose categories manually.')


def main():
    st.set_page_config(page_title='Smart Expense Tracker', page_icon='💸', layout='wide')
    apply_style()
    sidebar_brand()
    page = st.sidebar.radio('Go to', ['Overview', 'Add expense', 'Transactions', 'Import CSV', 'Budget & insights', 'Help'], key='page')
    today = date.today()
    hero(today)
    # Keep the existing filename so all previously saved personal expenses survive updates.
    path = str(DATA_HOME / 'personal.sqlite3')
    db.init_db(path)
    if st.sidebar.button('Refresh data', icon=':material/refresh:', use_container_width=True):
        load_expenses.clear()
        st.rerun()
    st.sidebar.markdown('<div class="sidebar-note"><strong>Track your everyday spending.</strong><br>Add expenses · Review transactions<br>Plan your monthly budget</div>', unsafe_allow_html=True)
    st.sidebar.caption('Saved on this computer · Amounts in INR')
    if 'notice' in st.session_state:
        st.success(st.session_state.pop('notice'))
    training_path = ROOT / 'data' / 'category_training.csv'
    trained = load_categorizer(training_path.read_bytes()) if training_path.exists() else {'model': None, 'error': 'Category suggestions are unavailable.'}
    if trained['model'] is None and page in ['Add expense', 'Import CSV']:
        st.warning('Automatic categorization is unavailable. Choose a category manually; blank imported categories will use Other.')
    frame = load_expenses(path)
    if page == 'Overview':
        dashboard(frame, today)
    elif page == 'Add expense':
        add_expense_page(path, trained, today)
    elif page == 'Transactions':
        transactions_page(frame, path, today)
    elif page == 'Import CSV':
        csv_import(frame, path, trained, today)
    elif page == 'Budget & insights':
        insights_page(frame, path, today)
    else:
        help_page(trained)
    st.markdown('<div class="footer">SMART EXPENSE TRACKER &nbsp; · &nbsp; Track spending. Build better habits.</div>', unsafe_allow_html=True)


if __name__ == '__main__':
    main()
