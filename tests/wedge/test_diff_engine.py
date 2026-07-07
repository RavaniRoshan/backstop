import pytest
from wedge.diff_engine import compute_similarity, compare_patches

def test_compute_similarity():
    assert compute_similarity("", "") == 1.0
    assert compute_similarity("a", "a") == 1.0
    assert compute_similarity("a", "b") == 0.0
    
    # 50% similar
    sim = compute_similarity("abc", "abd")
    assert sim > 0.6 and sim < 0.7  # (2*2) / (3+3) = 4/6 = 0.666

def test_compare_patches_empty():
    assert compare_patches([]) == {}

def test_compare_patches_converged():
    patches = [
        {"main.py": "patch A"},
        {"main.py": "patch A"},
        {"main.py": "patch A"},
    ]
    result = compare_patches(patches)
    assert "main.py" in result
    assert result["main.py"]["status"] == "converged"
    assert result["main.py"]["average_similarity"] == 1.0

def test_compare_patches_diverged():
    patches = [
        {"main.py": "patch alpha which is long"},
        {"main.py": "completely different text"},
        {"main.py": "something else entirely foo bar"},
    ]
    result = compare_patches(patches)
    assert "main.py" in result
    assert result["main.py"]["status"] == "diverged"
    assert result["main.py"]["average_similarity"] < 0.8

def test_compare_patches_partial():
    patches = [
        {"main.py": "patch 12345"},
        {"main.py": "patch 12345"},
        {"main.py": "patch 12399"},
    ]
    result = compare_patches(patches)
    assert "main.py" in result
    assert result["main.py"]["status"] == "partial"
    assert result["main.py"]["average_similarity"] > 0.8
    assert result["main.py"]["average_similarity"] < 1.0
