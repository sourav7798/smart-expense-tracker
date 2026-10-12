"""Two small supervised models. Rules and budget arithmetic live in insights.py."""
from datetime import date
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from data_processing import CATEGORIES

MIN_HISTORY = 15
FEATURES = ['previous_month', 'previous_three_average']


def train_categorizer(frame):
    if not {'description', 'category'}.issubset(frame.columns):
        return {'model': None, 'error': 'Training data needs description and category.'}
    clean = frame[['description', 'category']].dropna().copy()
    clean['description'] = clean['description'].astype(str).str.lower().str.strip().str.replace(r'\s+', ' ', regex=True)
    # Conflicting labels are ambiguous; remove them before deduplication and splitting.
    conflicts = clean.groupby('description')['category'].nunique()
    clean = clean[~clean['description'].isin(conflicts[conflicts > 1].index)]
    clean = clean[clean['description'].str.len().gt(0) & clean['category'].isin(CATEGORIES)].drop_duplicates('description')
    counts = clean['category'].value_counts()
    if len(counts) != len(CATEGORIES) or counts.min() < 4 or len(clean) < 40:
        return {'model': None, 'error': 'Insufficient training data: need all 8 categories, at least 4 distinct descriptions each, and 40 total.'}
    train, test = train_test_split(clean, test_size=.25, random_state=42, stratify=clean['category'])
    model = Pipeline([('tfidf', TfidfVectorizer(ngram_range=(1, 2))),
                      ('classifier', LogisticRegression(max_iter=1000, random_state=42))])
    try:
        model.fit(train['description'], train['category'])
        predicted = model.predict(test['description'])
    except ValueError as exc:
        return {'model': None, 'error': f'Training unavailable: {exc}'}
    return {'model': model, 'accuracy': accuracy_score(test['category'], predicted),
            'report': classification_report(test['category'], predicted, output_dict=True, zero_division=0),
            'train_descriptions': train['description'].tolist(), 'test_descriptions': test['description'].tolist(),
            'train_size': len(train), 'test_size': len(test), 'error': None}


def categorize(description, trained):
    if trained.get('model') is None or not description.strip():
        return 'Other', 'fallback'
    model = trained['model']
    if model.named_steps['tfidf'].transform([description]).nnz == 0:
        return 'Other', 'fallback'
    return str(model.predict([description])[0]), 'model'


def complete_monthly_totals(frame, today=None):
    """Exclude current/future months AND first recorded month (possibly partial)."""
    today = pd.Timestamp(today or date.today())
    if frame.empty:
        return pd.Series(dtype=float, name='amount')
    periods = pd.to_datetime(frame['date']).dt.to_period('M')
    start, end = periods.min() + 1, today.to_period('M') - 1
    if start > end:
        return pd.Series(dtype=float, name='amount')
    summed = frame.assign(month=periods).groupby('month')['amount'].sum()
    return summed.reindex(pd.period_range(start, end, freq='M'), fill_value=0).astype(float)


def forecast_features(monthly):
    # shift(1) ensures the target month NEVER enters either feature.
    return pd.DataFrame({'previous_month': monthly.shift(1),
                         'previous_three_average': monthly.shift(1).rolling(3).mean(),
                         'target': monthly}).dropna()


def fit_forecaster(history):
    rows = forecast_features(history)
    return LinearRegression().fit(rows[FEATURES], rows['target'])


def predict_steps(model, history, steps=2):
    values = list(history.astype(float))
    outputs = []
    for _ in range(steps):
        features = pd.DataFrame([[values[-1], np.mean(values[-3:])]], columns=FEATURES)
        value = max(0.0, float(model.predict(features)[0]))
        values.append(value)
        outputs.append(value)
    return outputs


def forecast_spending(frame, today=None):
    today = pd.Timestamp(today or date.today())
    monthly = complete_monthly_totals(frame, today)
    if len(monthly) < MIN_HISTORY:
        return {'available': False, 'reason': 'Not enough historical data', 'months': len(monthly)}
    evaluation = []
    # Last 3 target months: expanding training history ends TWO months before target.
    # This mirrors predicting next month while the current month is incomplete.
    for target_index in range(len(monthly) - 3, len(monthly)):
        history = monthly.iloc[:target_index - 1]
        model = fit_forecaster(history)
        estimate = predict_steps(model, history)[-1]
        evaluation.append({'month': str(monthly.index[target_index]), 'actual': float(monthly.iloc[target_index]),
                           'model': estimate, 'baseline': float(history.iloc[-1]),
                           'last_training_month': str(history.index[-1])})
    evaluation = pd.DataFrame(evaluation)
    model = fit_forecaster(monthly)
    bridge, estimate = predict_steps(model, monthly)
    return {'available': True, 'months': len(monthly), 'target_month': str(today.to_period('M') + 1),
            'prediction': estimate, 'current_month_bridge': bridge, 'baseline_prediction': float(monthly.iloc[-1]),
            'model_mae': mean_absolute_error(evaluation['actual'], evaluation['model']),
            'baseline_mae': mean_absolute_error(evaluation['actual'], evaluation['baseline']),
            'evaluation': evaluation, 'monthly': monthly}
