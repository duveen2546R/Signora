"""Manual examples for the maximum-deviation domain engine."""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'backend'))
from app.validation.case_study import evaluate_functional_domain


if __name__ == '__main__':
    for name, errors in {
        'Within margin': np.full(101, .01),
        'One severe frame': np.r_[np.full(100, .01), .2],
        'Missing tracking': np.full(101, np.nan),
    }.items():
        result = evaluate_functional_domain(errors, .05, 'Path')
        print(f"{name}: {result['status']}, max deviation={result['max_deviation']}")
