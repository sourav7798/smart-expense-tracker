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
from generate_sample_data import generate_transactions
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


def dashboard(frame, today, mode):
    st.subheader('Your spending at a glance')
    st.caption('A little visibility goes a long way. Explore where your money goes.')
    start_default = frame['date'].min().date() if not frame.empty else today.replace(day=1)
    with st.expander('Filter by date & category', expanded=False):
        left, right = st.columns(2)
        start = left.date_input('From', start_default, max_value=today, key=f'from_{mode}')
        end = right.date_input('To', today, max_value=today, key=f'to_{mode}')
        categories = st.multiselect('Categories', CATEGORIES, default=CATEGORIES, key=f'categories_{mode}')
    search = st.text_input('Search descriptions', key=f'search_{mode}', placeholder='Search coffee, groceries, metro…')
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
            st.plotly_chart(chart_style(chart), use_container_width=True, config={'displayModeBar': False})
        with b.container(border=True):
            st.subheader('Where it goes')
            st.caption('Category share · INR')
            chart = px.pie(category, names='category', values='amount', hole=.72,
                           color='category', color_discrete_map=CATEGORY_COLORS)
            chart.update_traces(textinfo='none', marker=dict(line=dict(color='#F5F7FA', width=3)),
                                hovertemplate='%{label}<br>₹%{value:,.2f} · %{percent}<extra></extra>')
            chart.update_layout(legend=dict(orientation='h', y=-.12, x=.5, xanchor='center', font_size=11),
                                annotations=[dict(text='SPENDING', x=.5, y=.5, showarrow=False, font=dict(size=12,color='#63778A'))])
            st.plotly_chart(chart_style(chart), use_container_width=True, config={'displayModeBar': False})
        with st.container(border=True):
            st.subheader('Daily rhythm')
            st.caption('See the peaks and quieter days in your spending.')
            chart = px.area(daily, x='date', y='amount', color_discrete_sequence=['#6F73D2'])
            chart.update_traces(line_width=2, fillcolor='rgba(111,115,210,0.12)',
                                hovertemplate='%{x|%d %b %Y}<br>₹%{y:,.2f}<extra></extra>')
            st.plotly_chart(chart_style(chart, 240), use_container_width=True, config={'displayModeBar': False})
    st.subheader('Transaction history')
    st.caption('Every entry, in one place. Edit or remove a record in Manage expenses.')
    st.dataframe(filtered[['id'] + FIELDS + ['category_source']], hide_index=True, use_container_width=True,
                 column_config={'id': st.column_config.NumberColumn('ID', format='%d'),
                                'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'),
                                'description': st.column_config.TextColumn('Description', width='large'),
                                'amount': st.column_config.NumberColumn('Amount (₹)', format='₹ %.2f'),
                                'category': 'Category', 'category_source': 'Categorized by'})
    st.download_button('Export filtered CSV', export_csv(filtered), 'filtered_expenses.csv', 'text/csv', icon=':material/download:')


def manage(frame, path, trained, today):
    st.subheader('Add an expense')
    description = st.text_input('Description', max_chars=300, key='new_description')
    predicted, source = categorize(description, trained)
    st.caption(f'Suggested category: {predicted} · source: {source}. Choose a manual category to override.')
    with st.form('add_expense', clear_on_submit=True):
        date_col, amount_col = st.columns(2)
        day = date_col.date_input('Expense date', today, max_value=today)
        amount = amount_col.number_input('Amount (INR)', min_value=0.0, max_value=1_000_000_000.0, step=10.0, format='%.2f')
        choice = st.selectbox('Category', ['Use suggestion'] + CATEGORIES)
        submitted = st.form_submit_button('Save expense', type='primary', use_container_width=True)
    if submitted:
        try:
            category = predicted if choice == 'Use suggestion' else choice
            row = validate_expense(day, description, amount, category, today)
            row['category_source'] = source if choice == 'Use suggestion' else 'manual'
            db.add_expense(path, row)
            changed('Expense saved.')
        except ValueError as exc:
            st.error(str(exc))
    st.subheader('Edit or delete an expense')
    if frame.empty:
        st.info('No saved expenses yet.')
        return
    selected_id = st.selectbox('Select transaction ID', frame['id'].tolist(),
                               format_func=lambda value: f"#{value} · {frame.loc[frame.id == value, 'description'].iloc[0]}")
    row = frame.loc[frame.id == selected_id].iloc[0]
    with st.form(f'edit_{selected_id}'):
        edited_day = st.date_input('Edit date', row['date'].date(), max_value=today)
        edited_description = st.text_input('Edit description', row['description'], max_chars=300)
        edited_amount = st.number_input('Edit amount (INR)', value=float(row['amount']), min_value=0.0, max_value=1_000_000_000.0, format='%.2f')
        edited_category = st.selectbox('Edit category', CATEGORIES, index=CATEGORIES.index(row['category']))
        st.caption(f"Current category source: {row['category_source']}. Saving an edit marks the category as manually reviewed.")
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
    st.subheader('CSV import preview')
    st.download_button('Download CSV template', 'date,description,amount,category\n2026-01-15,Metro ticket,60,Transport\n2026-01-16,Cafe coffee,120,\n',
                       'expense_template.csv', 'text/csv')
    st.caption('UTF-8 CSV · date: YYYY-MM-DD · INR amount: positive, up to two decimals · category optional. Blank categories receive a model suggestion (or Other fallback).')
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
    st.caption('To override an imported prediction, use Manage expenses after import.')


def insights_page(frame, path, today, mode):
    st.subheader('Rule-based spending insights')
    st.caption('Uses all records in the selected mode, independently of dashboard filters. These are calculations and statistical rules, not trained AI.')
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
    st.write('Unusually large transactions')
    st.caption('With at least 8 records: amount > Q3 + 1.5 × IQR, where IQR = Q3 − Q1, across all recorded transactions. A flag is a review aid, not evidence of fraud; regular bills can be flagged.')
    if result['threshold'] is None:
        st.info('At least 8 transactions are needed for the unusual-amount rule.')
    else:
        st.write(f"Threshold: {money(result['threshold'])}")
        st.dataframe(result['unusual'][FIELDS], hide_index=True)
    st.divider()
    st.subheader('Machine learning: next month estimate')
    st.caption(f'Requires {MIN_HISTORY} complete months after discarding the first recorded month and the incomplete current month. Unrecorded intervening months are treated as zero spending.')
    confirmed = st.checkbox('My history covers all spending from the first recorded month through last month', value=mode == 'Synthetic demo')
    if not confirmed:
        st.info('Confirm history coverage before interpreting a forecast. Missing imports are not zero spending.')
        return
    forecast = forecast_spending(frame, today)
    if not forecast['available']:
        st.info(f"Not enough historical data — {forecast['months']} usable complete months; {MIN_HISTORY} required.")
        return
    st.metric(f"Estimated spending · {forecast['target_month']}", money(forecast['prediction']))
    st.write(f"Last-complete-month baseline estimate: {money(forecast['baseline_prediction'])}")
    st.caption('The current month is incomplete: predict its total first, then recursively predict next month. Negative predictions are clipped to zero. Estimates can be inaccurate and are not spending limits.')
    a, b = st.columns(2)
    a.metric('Model MAE · held-out months', money(forecast['model_mae']))
    b.metric('Baseline MAE · held-out months', money(forecast['baseline_mae']))
    if forecast['model_mae'] >= forecast['baseline_mae']:
        st.warning('The model did not beat the simple baseline in this evaluation. Consider the baseline as well.')
    st.caption('Expanding chronological evaluation on the last 3 historical target months; two-step forecasts use only information known two months before each target. Baseline repeats the last observed month for both steps. MAE is average absolute error in INR, not a confidence interval.')
    st.dataframe(forecast['evaluation'].round(2), hide_index=True)


def main():
    st.set_page_config(page_title='Smart Expense Tracker', page_icon='💸', layout='wide')
    apply_style()
    sidebar_brand()
    mode = st.sidebar.radio('Data mode', ['Personal', 'Synthetic demo'])
    today = date.today()
    hero(mode, today)
    path = str(DATA_HOME / ('demo.sqlite3' if mode == 'Synthetic demo' else 'personal.sqlite3'))
    db.init_db(path)
    if mode == 'Synthetic demo':
        st.warning('SYNTHETIC DEMO — generated transactions, separate from your personal database.')
        st.sidebar.caption('Load 30 complete synthetic months ending last month. Existing demo edits are preserved; duplicate records are skipped.')
        if st.sidebar.button('Load synthetic demo data', type='primary', use_container_width=True):
            rows = generate_transactions(today).assign(category_source='synthetic').to_dict('records')
            added, skipped = db.import_expenses(path, rows)
            changed(f'Loaded {added} synthetic transactions; skipped {skipped} duplicates.')
    else:
        st.sidebar.caption('Personal expenses stay in a local SQLite database. No bank connection or external AI API.')
    if st.sidebar.button('Refresh data', icon=':material/refresh:', use_container_width=True):
        load_expenses.clear()
        st.rerun()
    st.sidebar.markdown('<div class="sidebar-note"><strong>Made for your everyday.</strong><br>INR expenses · Local storage<br>Your personal and demo data stay separate.</div>', unsafe_allow_html=True)
    if 'notice' in st.session_state:
        st.success(st.session_state.pop('notice'))
    training_path = ROOT / 'data' / 'category_training.csv'
    trained = load_categorizer(training_path.read_bytes()) if training_path.exists() else {'model': None, 'error': 'Synthetic training file is missing. Run python generate_sample_data.py.'}
    if trained['model'] is None:
        st.warning(trained['error'] + ' Manual categories remain available.')
    frame = load_expenses(path)
    tabs = st.tabs(['Dashboard', 'Manage expenses', 'CSV import', 'Insights & forecast', 'Model evaluation'])
    with tabs[0]:
        dashboard(frame, today, mode)
    with tabs[1]:
        manage(frame, path, trained, today)
    with tabs[2]:
        csv_import(frame, path, trained, today)
    with tabs[3]:
        insights_page(frame, path, today, mode)
    with tabs[4]:
        st.subheader('Synthetic category classifier evaluation')
        st.warning('Training and testing use synthetic descriptions. Shared vocabulary and templates make this task easier than real bank descriptions. Scores do not establish real-world accuracy.')
        if trained['model'] is not None:
            st.metric('Held-out synthetic accuracy', f"{trained['accuracy']:.1%}")
            st.write(f"Stratified 75/25 split · seed 42 · {trained['train_size']} training / {trained['test_size']} test descriptions")
            st.dataframe(pd.DataFrame(trained['report']).T, use_container_width=True)
            st.caption('Normalized exact descriptions never overlap between training and test. TF-IDF is fitted only on the training partition. The deployed pipeline is the evaluated training-only model. Manual overrides are saved but do not automatically retrain it.')

    st.markdown('<div class="footer">SMART EXPENSE TRACKER &nbsp; · &nbsp; Built with Python &nbsp; · &nbsp; Clarity in every transaction</div>', unsafe_allow_html=True)


if __name__ == '__main__':
    main()
