"""Deterministic SYNTHETIC data only. No real customers or bank transactions."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ITEMS = {
    'Food': ['grocery vegetables', 'restaurant dinner', 'cafe coffee', 'bakery bread', 'canteen lunch', 'pizza delivery', 'fruit market', 'milk delivery', 'breakfast dosa', 'rice groceries', 'tea snacks', 'sandwich meal'],
    'Transport': ['metro ticket', 'bus pass', 'taxi ride', 'auto fare', 'petrol refill', 'train ticket', 'cab airport', 'bike fuel', 'parking charge', 'toll road', 'subway pass', 'diesel refill'],
    'Shopping': ['shirt clothing', 'shoes purchase', 'jeans apparel', 'jacket store', 'kitchen utensils', 'phone accessory', 'furniture purchase', 'bag purchase', 'curtains home', 'headphones store', 'watch purchase', 'bedsheet shopping'],
    'Bills': ['electricity bill', 'water bill', 'internet broadband', 'mobile recharge', 'rent payment', 'gas cylinder', 'maintenance bill', 'wifi subscription', 'telephone bill', 'sewage utility', 'power utility', 'housing rent'],
    'Entertainment': ['cinema ticket', 'movie streaming', 'concert entry', 'gaming subscription', 'theatre show', 'museum ticket', 'amusement park', 'music subscription', 'comedy show', 'bowling session', 'dance show', 'sports match'],
    'Health': ['doctor consultation', 'pharmacy medicine', 'dental checkup', 'hospital visit', 'blood test', 'eye examination', 'physiotherapy session', 'medical scan', 'vitamin medicine', 'clinic appointment', 'health screening', 'vaccination clinic'],
    'Education': ['python course', 'college tuition', 'textbook purchase', 'exam fee', 'school stationery', 'coding workshop', 'library membership', 'online lessons', 'training course', 'study material', 'college books', 'certification exam'],
    'Other': ['charity donation', 'birthday gift', 'courier parcel', 'laundry service', 'haircut salon', 'shoe repair', 'pet grooming', 'luggage storage', 'document printing', 'key duplication', 'tailor alteration', 'community donation'],
}


def classification_data():
    # 36 distinct descriptions per category, with labels assigned by the generator.
    return pd.DataFrame([{'description': f'{context} {item}', 'category': category}
                         for category, items in ITEMS.items()
                         for item in items for context in ['local', 'monthly', 'weekend']])


def generate_transactions(as_of='2026-10-01', months=30, seed=42):
    rng = np.random.default_rng(seed)
    current = pd.Timestamp(as_of).to_period('M')
    periods = pd.period_range(end=current - 1, periods=months, freq='M')
    typical = dict(zip(ITEMS, [450, 250, 1500, 2200, 650, 900, 1000, 350]))
    rows = []
    for index, month in enumerate(periods):
        for category, items in ITEMS.items():
            count = int(rng.integers(3, 7))
            for _ in range(count):
                day = int(rng.integers(1, month.days_in_month + 1))
                scale = (1 + index * .008) * (1 + .10 * np.sin(index * np.pi / 6))
                amount = max(10, round(float(rng.lognormal(np.log(typical[category] * scale), .45)), 2))
                rows.append({'date': f'{month}-{day:02d}', 'description': str(rng.choice(items)),
                             'amount': amount, 'category': category})
    return pd.DataFrame(rows).sort_values('date').reset_index(drop=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate safe synthetic sample files; does not touch any database.')
    parser.add_argument('--as-of', default='2026-10-01', help='First incomplete month (YYYY-MM-DD).')
    args = parser.parse_args()
    output = Path(__file__).parent / 'data'
    output.mkdir(exist_ok=True)
    generate_transactions(args.as_of).to_csv(output / 'sample_expenses.csv', index=False)
    classification_data().to_csv(output / 'category_training.csv', index=False)
    print('Wrote synthetic sample_expenses.csv and category_training.csv (seed=42).')
