import difflib
from typing import Dict, List, Any

def compute_similarity(patch1: str, patch2: str) -> float:
    """Computes similarity ratio between two patch strings using difflib."""
    if not patch1 and not patch2:
        return 1.0
    seq = difflib.SequenceMatcher(None, patch1, patch2)
    return seq.ratio()

def compare_patches(patches: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Compares patches from multiple runners.
    Expects patches to be a list of dicts, where each dict maps filename -> patch string.
    """
    if not patches:
        return {}

    all_files = set()
    for p in patches:
        all_files.update(p.keys())

    results = {}
    for filename in all_files:
        file_patches = [p.get(filename, "") for p in patches]
        
        # Calculate pairwise similarities
        similarities = []
        for i in range(len(file_patches)):
            for j in range(i + 1, len(file_patches)):
                sim = compute_similarity(file_patches[i], file_patches[j])
                similarities.append(sim)
        
        avg_sim = sum(similarities) / len(similarities) if similarities else 1.0
        
        # Categorize convergence
        if avg_sim == 1.0:
            status = "converged"
        elif avg_sim > 0.8:
            status = "partial"
        else:
            status = "diverged"
            
        results[filename] = {
            "average_similarity": avg_sim,
            "status": status,
            "patches": file_patches,
        }

    return results
