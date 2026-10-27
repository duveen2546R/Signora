import numpy as np
from typing import Tuple, List, Dict

def compute_nonconformity(y_true: np.ndarray, q_pred: np.ndarray, peak_prob: float) -> float:
    """
    Computes the nonconformity score for a single keypoint prediction.
    
    Args:
        y_true: The true 2D location of the keypoint (e.g., from manual annotation).
        q_pred: The predicted 2D location from the pose estimator (e.g., DWPose).
        peak_prob: The confidence score or peak probability from the heatmap.
        
    Returns:
        The nonconformity score (Euclidean distance scaled by inverse probability).
    """
    # Adding a small epsilon to prevent division by zero if peak_prob is exactly 0
    epsilon = 1e-8
    distance = np.linalg.norm(y_true - q_pred)
    return distance / (peak_prob + epsilon)

def calibrate_conformal_predictor(nonconformity_scores: List[float], alpha: float = 0.10) -> float:
    """
    Determines the critical threshold (q-hat) for the conformal prediction sets
    based on a calibration set of nonconformity scores.
    
    Args:
        nonconformity_scores: List of scores calculated on the calibration dataset.
        alpha: The desired miscoverage rate (e.g., 0.10 for 90% confidence).
        
    Returns:
        The critical nonconformity threshold.
    """
    n = len(nonconformity_scores)
    # The (1 - alpha)(n + 1)/n quantile
    q_level = np.ceil((n + 1) * (1 - alpha)) / n
    q_level = min(q_level, 1.0) # Cap at 1.0
    
    # Calculate the empirical quantile
    q_hat = np.quantile(nonconformity_scores, q_level)
    return q_hat

def get_conformal_ellipse_radius(peak_prob: float, q_hat: float) -> float:
    """
    Calculates the radius of the conformal uncertainty ellipse/circle for a new prediction.
    
    Args:
        peak_prob: The confidence score of the new prediction.
        q_hat: The critical threshold determined from calibration.
        
    Returns:
        The radius of the uncertainty region in pixels.
    """
    epsilon = 1e-8
    # Rearranging the nonconformity function: distance = score * peak_prob
    # The max allowed distance is bounded by q_hat
    radius = q_hat * peak_prob
    return radius

def is_point_within_conformal_region(target_point: np.ndarray, predicted_point: np.ndarray, radius: float) -> bool:
    """
    Checks if a target point (e.g., projected FBX joint) falls within the conformal region of the predicted video landmark.
    """
    distance = np.linalg.norm(target_point - predicted_point)
    return distance <= radius
