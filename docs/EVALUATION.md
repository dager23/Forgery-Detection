# DocAuth evaluation

Generated 2026-10-22 08:48 UTC.

### Before calibration (default engine)

400 samples (200 tampered, 200 genuine)

| Module | ROC-AUC | Flag rate genuine | Flag rate tampered |
|---|---|---|---|
| cnn | 0.685 | 100.0% | 100.0% |
| copymove | 0.523 | 1.0% | 3.5% |
| ela | 0.545 | 0.5% | 0.0% |
| jpeg | 0.540 | 10.0% | 13.5% |
| metadata | 0.500 | 0.0% | 0.0% |
| noise | 0.538 | 0.5% | 8.0% |
| segmentation | 0.947 | 51.0% | 97.0% |

**Fused ROC-AUC: 0.860**

| Truth \ Verdict | Accepted | Suspicious | Rejected |
|---|---|---|---|
| Genuine | 0.0% | 38.5% | 61.5% |
| Tampered | 0.0% | 2.5% | 97.5% |

### After calibration (2-fold cross-fitted)

400 samples (200 tampered, 200 genuine)

| Module | ROC-AUC | Flag rate genuine | Flag rate tampered |
|---|---|---|---|
| cnn | 0.684 | 5.5% | 27.5% |
| copymove | 0.523 | 1.0% | 3.5% |
| ela | 0.544 | 5.5% | 9.0% |
| jpeg | 0.539 | 4.5% | 10.0% |
| metadata | 0.500 | 0.0% | 0.0% |
| noise | 0.533 | 5.5% | 11.0% |
| segmentation | 0.947 | 5.0% | 86.0% |

**Fused ROC-AUC: 0.947**

| Truth \ Verdict | Accepted | Suspicious | Rejected |
|---|---|---|---|
| Genuine | 88.0% | 10.0% | 2.0% |
| Tampered | 11.5% | 2.5% | 86.0% |
