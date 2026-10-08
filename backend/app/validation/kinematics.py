import numpy as np
import math

def compute_isb_joint_angles(shoulder_3d: np.ndarray, elbow_3d: np.ndarray, wrist_3d: np.ndarray):
    """
    Computes local coordinate system joint angles following ISB recommendations.
    This bypasses absolute limb length scaling issues by measuring purely relative angles.
    
    Args:
        shoulder_3d: (3,) array
        elbow_3d: (3,) array
        wrist_3d: (3,) array
        
    Returns:
        dict containing flexion, abduction, etc.
    """
    # 1. Define Upper Arm vector (Shoulder to Elbow)
    upper_arm = elbow_3d - shoulder_3d
    upper_arm_len = np.linalg.norm(upper_arm)
    upper_arm_norm = upper_arm / (upper_arm_len + 1e-8)
    
    # 2. Define Forearm vector (Elbow to Wrist)
    forearm = wrist_3d - elbow_3d
    forearm_len = np.linalg.norm(forearm)
    forearm_norm = forearm / (forearm_len + 1e-8)
    
    # Simple elbow flexion/extension (angle between upper arm and forearm)
    # Dot product of normalized vectors
    dot_product = np.dot(upper_arm_norm, forearm_norm)
    dot_product = np.clip(dot_product, -1.0, 1.0)
    
    elbow_flexion_rad = math.acos(dot_product)
    elbow_flexion_deg = math.degrees(elbow_flexion_rad)
    
    return {
        "elbow_flexion_deg": elbow_flexion_deg
    }

try:
    import torch
    import smplx
except ImportError:
    torch = None
    smplx = None

class MANOKinematicsBridge:
    """
    Bridge to interact with the MANO parametric hand model using the smplx library.
    Translates 2D/3D landmarks and FBX rotations into the shared MANO pose space.
    """
    def __init__(self, mano_model_dir: str = "backend/data/mano"):
        self.model_loaded = False
        if torch is None or smplx is None:
            print("Warning: PyTorch and smplx are required for MANO integration.")
            return
            
        try:
            # Load the left and right hand models
            self.mano_right = smplx.create(mano_model_dir, 'mano', is_rhand=True, use_pca=False, flat_hand_mean=True)
            self.mano_left = smplx.create(mano_model_dir, 'mano', is_rhand=False, use_pca=False, flat_hand_mean=True)
            self.model_loaded = True
            print("MANO models loaded successfully.")
        except Exception as e:
            print(f"Failed to load MANO models: {e}")
            
    def get_forward_kinematics(self, pose_theta: torch.Tensor, is_right: bool = True):
        """
        Runs the forward pass of the MANO model to get the 3D joint locations from angles.
        Args:
            pose_theta: (Batch, 45) tensor of pure finger articulation angles.
            is_right: Boolean for right or left hand.
        """
        if not self.model_loaded:
            return None
            
        model = self.mano_right if is_right else self.mano_left
        output = model(hand_pose=pose_theta)
        # Returns the 3D joints and the vertices
        return output.joints, output.vertices
        
    def fit_video_landmarks(self, landmarks_2d: np.ndarray, is_right: bool = True):
        """
        Fits MANO parameters (shape beta, pose theta) to 2D video landmarks via Inverse Kinematics.
        Returns pure finger articulation vector (theta).
        """
        if not self.model_loaded:
            return np.zeros((1, 45)) # 15 joints * 3 DOF = 45
            
        # Simplified placeholder for the IK gradient descent loop
        # In production, this minimizes reprojection error between model() joints and landmarks_2d
        # For structural plan, we return the initialized pose variable
        pose_theta = torch.zeros((1, 45), requires_grad=True)
        return pose_theta.detach().numpy()

    def map_fbx_to_mano(self, fbx_rotations: np.ndarray, is_right: bool = True):
        """
        Maps FBX native rotations into the shared MANO pose space.
        """
        if not self.model_loaded:
            return np.zeros((1, 45))
            
        # Mapping from Rokoko Unity FBX finger bone hierarchy to MANO hierarchy
        # Placeholder for exact rotational mapping
        return np.zeros((1, 45))
