"""Print measured results on committed synthetic data; no database access."""
import json
from pathlib import Path
import pandas as pd
from ml_models import train_categorizer, forecast_spending

ROOT = Path(__file__).resolve().parent

if __name__ == '__main__':
    category = train_categorizer(pd.read_csv(ROOT / 'data/category_training.csv'))
    forecast = forecast_spending(pd.read_csv(ROOT / 'data/sample_expenses.csv'), today='2026-10-12')
    output = {'data': 'SYNTHETIC ONLY', 'forecast_as_of': '2026-10-12',
              'categorization': {key: value for key, value in category.items()
                                 if key not in ['model', 'train_descriptions', 'test_descriptions']},
              'forecast': {key: value for key, value in forecast.items()
                           if key not in ['evaluation', 'monthly']}}
    if forecast['available']:
        output['forecast']['evaluation'] = forecast['evaluation'].to_dict('records')
    print(json.dumps(output, indent=2))
