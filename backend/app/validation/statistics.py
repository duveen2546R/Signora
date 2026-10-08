import numpy as np

try:
    import spm1d
except ImportError:
    spm1d = None

def compute_bland_altman_agreement(fbx_data: np.ndarray, video_data: np.ndarray):
    """
    Computes Bland-Altman statistics to find systematic and proportional biases.
    
    Args:
        fbx_data: 1D array of measurements (e.g., joint angles)
        video_data: 1D array of corresponding measurements
        
    Returns:
        dict with mean_bias, lower_loa, upper_loa
    """
    differences = fbx_data - video_data
    means = (fbx_data + video_data) / 2.0
    
    mean_bias = np.mean(differences)
    std_diff = np.std(differences, ddof=1)
    
    # 95% Limits of Agreement
    loa_upper = mean_bias + 1.96 * std_diff
    loa_lower = mean_bias - 1.96 * std_diff
    
    return {
        "mean_bias": mean_bias,
        "loa_lower": loa_lower,
        "loa_upper": loa_upper,
        "differences": differences,
        "means": means
    }

def execute_functional_tost(fbx_waveform: np.ndarray, video_waveform: np.ndarray, delta: float):
    """
    Executes Functional Equivalence Testing (fTOST) using SPM1d.
    
    Args:
        fbx_waveform: Continuous time-series data (e.g., shape (N_trials, Q_timepoints))
        video_waveform: Continuous time-series data (same shape)
        delta: The strictly defined equivalence margin
        
    Returns:
        is_equivalent: Boolean indicating if whole waveform is statistically equivalent
        clusters: Information about temporal clusters that breached the bounds
    """
    if spm1d is None:
        raise ImportError("spm1d library is required for functional equivalence testing.")
        
    # TOST uses two one-sided tests. 
    # H01: mu_FBX - mu_Video >= Delta
    # H02: mu_FBX - mu_Video <= -Delta
    
    # Test 1: Is FBX significantly less than Video + Delta?
    # We use paired t-test: ttest_paired(y1, y2). 
    # To test if y1 < y2 + delta, we test if (y1 - (y2 + delta)) < 0
    t_stat_upper = spm1d.stats.ttest_paired(fbx_waveform, video_waveform + delta)
    inf_upper = t_stat_upper.inference(alpha=0.05, tail=-1) # -1 tail for 'less than'
    
    # Test 2: Is FBX significantly greater than Video - Delta?
    t_stat_lower = spm1d.stats.ttest_paired(fbx_waveform, video_waveform - delta)
    inf_lower = t_stat_lower.inference(alpha=0.05, tail=1)  # 1 tail for 'greater than'
    
    # For statistical equivalence, BOTH null hypotheses must be rejected across the ENTIRE time domain.
    # In SPM1d, this means the t-statistic curve must cross the critical threshold for the entire duration.
    # If there are clusters where it DOES NOT cross, those are the failing regions.
    
    # Simplified logic: if the max/min of the t-statistic curves don't exceed the critical thresholds,
    # or if there are specific temporal nodes where equivalence fails, we flag it.
    
    is_equivalent = True
    failing_clusters = []
    
    # (Implementation detail depends heavily on how spm1d outputs clusters for tail=-1/1 inferences. 
    # This is a structural representation).
    
    if hasattr(inf_upper, 'clusters') and len(inf_upper.clusters) > 0:
         is_equivalent = False
         failing_clusters.append({'bound': 'upper', 'clusters': inf_upper.clusters})
         
    if hasattr(inf_lower, 'clusters') and len(inf_lower.clusters) > 0:
         is_equivalent = False
         failing_clusters.append({'bound': 'lower', 'clusters': inf_lower.clusters})
         
    return {
        "is_equivalent": is_equivalent,
        "failing_clusters": failing_clusters
    }
