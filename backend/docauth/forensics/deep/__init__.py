"""Deep-learning forensic modules served through ONNX Runtime.

Models are trained with PyTorch in ``ml/`` and exported to ONNX; the backend only needs
``onnxruntime``. The I/O contract (shared with ``ml/docauth_ml/export.py``):

* ``classifier.onnx`` - input ``patches`` float32 [N, 3, 128, 128] RGB in [0, 1];
  output ``logits`` float32 [N, 2] (index 1 = manipulated).
* ``segmenter.onnx`` - input ``image`` float32 [1, 3, H, W] RGB in [0, 1], H and W multiples
  of 32; output ``mask`` float32 [1, 1, H, W] logits (manipulated pixels).
"""

from pathlib import Path

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
PATCH = 128
SEG_TILE = 512
SEG_OVERLAP = 64
