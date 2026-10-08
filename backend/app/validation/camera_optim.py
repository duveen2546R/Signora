import numpy as np
try:
    import torch
    import torch.nn as nn
except ImportError:
    torch = None
    nn = object

class DifferentiableCameraOptimizer(nn.Module if torch else object):
    """
    Optimizes camera extrinsics (Rotation and Translation) to minimize the reprojection error
    between known 3D FBX joints and observed 2D video landmarks.
    """
    def __init__(self, intrinsic_matrix: np.ndarray, initial_t: np.ndarray = None, initial_r: np.ndarray = None):
        super().__init__()
        if torch is None:
            raise ImportError("PyTorch is required for camera optimization.")
            
        # Intrinsic matrix (fixed)
        self.register_buffer('K', torch.tensor(intrinsic_matrix, dtype=torch.float32))
        
        # Extrinsics (learnable)
        if initial_t is None:
            initial_t = np.array([0.0, 0.0, 5.0]) # Assume camera is 5 units away in Z
        if initial_r is None:
            initial_r = np.zeros(3) # Euler angles or axis-angle
            
        self.translation = nn.Parameter(torch.tensor(initial_t, dtype=torch.float32))
        self.rotation_params = nn.Parameter(torch.tensor(initial_r, dtype=torch.float32))
        
    def _rodrigues_rotation(self, r_vec):
        """Convert axis-angle to rotation matrix."""
        theta = torch.norm(r_vec)
        if theta < 1e-6:
            return torch.eye(3, device=r_vec.device)
            
        r = r_vec / theta
        K = torch.zeros((3, 3), device=r_vec.device)
        K[0, 1] = -r[2]
        K[0, 2] = r[1]
        K[1, 0] = r[2]
        K[1, 2] = -r[0]
        K[2, 0] = -r[1]
        K[2, 1] = r[0]
        
        I = torch.eye(3, device=r_vec.device)
        R = I + torch.sin(theta) * K + (1 - torch.cos(theta)) * torch.matmul(K, K)
        return R

    def forward(self, points_3d: torch.Tensor):
        """
        Projects 3D points to 2D using the current camera parameters.
        Args:
            points_3d: Tensor of shape (N, 3)
        Returns:
            points_2d: Projected Tensor of shape (N, 2)
        """
        R = self._rodrigues_rotation(self.rotation_params)
        
        # Transform 3D points to camera coordinate system
        # P_c = R * P_w + t
        points_c = torch.matmul(points_3d, R.t()) + self.translation
        
        # Project to image plane using intrinsic matrix
        # P_img = K * P_c
        points_img = torch.matmul(points_c, self.K.t())
        
        # Perspective divide
        z = points_img[:, 2:3]
        z = torch.clamp(z, min=1e-5) # Prevent division by zero
        points_2d = points_img[:, :2] / z
        
        return points_2d

def optimize_camera_extrinsics(video_landmarks_2d: np.ndarray, fbx_joints_3d: np.ndarray, intrinsic_matrix: np.ndarray, num_iterations: int = 100, lr: float = 0.01):
    """
    Runs the gradient descent optimization loop to find the best camera position.
    """
    if torch is None:
        raise ImportError("PyTorch is required.")
        
    target_2d = torch.tensor(video_landmarks_2d, dtype=torch.float32)
    source_3d = torch.tensor(fbx_joints_3d, dtype=torch.float32)
    
    model = DifferentiableCameraOptimizer(intrinsic_matrix)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()
    
    for i in range(num_iterations):
        optimizer.zero_grad()
        predicted_2d = model(source_3d)
        loss = criterion(predicted_2d, target_2d)
        loss.backward()
        optimizer.step()
        
    return {
        'translation': model.translation.detach().numpy(),
        'rotation': model.rotation_params.detach().numpy(),
        'final_loss': loss.item()
    }
