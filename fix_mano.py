import pickle
import os

mano_dir = "backend/data/mano"
files = ["MANO_RIGHT.pkl", "MANO_LEFT.pkl"]

for file in files:
    filepath = os.path.join(mano_dir, file)
    print(f"Fixing {filepath}...")
    
    with open(filepath, 'rb') as f:
        # Load with latin1 encoding to fix Python 2 -> 3 string issues
        data = pickle.load(f, encoding='latin1')
        
    with open(filepath, 'wb') as f:
        pickle.dump(data, f)
        
print("Conversion complete!")
