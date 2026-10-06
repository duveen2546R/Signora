import numpy as np
import sys

# Add backend to path so we can import your module
sys.path.append('backend')
from app.validation.case_study import single_trial_test

print("--- Testing the HAC Statistical Test Logic ---")

# Simulate 101 frames of smooth, autocorrelated error data (like human motion)
phases = np.linspace(0, 4*np.pi, 101)
base_error = 0.3 + 0.1 * np.sin(phases) # Base error curve

# 1. TIE: Both have similar error (with slight random noise)
suit_tie = base_error + np.random.normal(0, 0.01, 101)
non_suit_tie = base_error + np.random.normal(0, 0.01, 101)
res_tie = single_trial_test(suit_tie, non_suit_tie)

print("\n[Scenario 1] TIE (Both have ~0.30 error)")
print(f"Difference: {res_tie['mean_difference_shoulder_widths']:.4f}")
print(f"P-value:    {res_tie['p_value_one_sided']:.4f}  <-- (Should be around 0.50, NOT significant)")

# 2. ROKOKO IS BETTER: Rokoko error is 0.10, DeepMotion error is 0.40
suit_good = base_error - 0.20 + np.random.normal(0, 0.01, 101)
non_suit_bad = base_error + 0.10 + np.random.normal(0, 0.01, 101)
res_rokoko_wins = single_trial_test(suit_good, non_suit_bad)

print("\n[Scenario 2] ROKOKO IS BETTER (Rokoko is 0.30 shoulder widths closer)")
print(f"Difference: {res_rokoko_wins['mean_difference_shoulder_widths']:.4f}")
print(f"P-value:    {res_rokoko_wins['p_value_one_sided']:.4e}  <-- (Should be < 0.05, HIGHLY significant)")

# 3. DEEPMOTION IS BETTER: Rokoko error is 0.40, DeepMotion error is 0.10
res_deepmotion_wins = single_trial_test(non_suit_bad, suit_good)
print("\n[Scenario 3] DEEPMOTION IS BETTER")
print(f"Difference: {res_deepmotion_wins['mean_difference_shoulder_widths']:.4f}")
print(f"P-value:    {res_deepmotion_wins['p_value_one_sided']:.4f}  <-- (Should be near 1.0, because test checks if *Rokoko* is better)")

