import torch
import smplx

try:
    mano_model_dir = "backend/data/mano"
    print(f"Attempting to load MANO models from: {mano_model_dir}")
    
    # Try loading the right hand
    mano_right = smplx.create(mano_model_dir, 'mano', is_rhand=True, use_pca=False, flat_hand_mean=True)
    print("SUCCESS: Loaded MANO_RIGHT.pkl")
    
    # Try loading the left hand
    mano_left = smplx.create(mano_model_dir, 'mano', is_rhand=False, use_pca=False, flat_hand_mean=True)
    print("SUCCESS: Loaded MANO_LEFT.pkl")
    
    # Test a dummy forward pass
    dummy_pose = torch.zeros((1, 45)) # 15 joints * 3 angles
    output = mano_right(hand_pose=dummy_pose)
    print(f"SUCCESS: Forward pass successful. Output joints shape: {output.joints.shape}")
    
except Exception as e:
    print(f"ERROR: {e}")
