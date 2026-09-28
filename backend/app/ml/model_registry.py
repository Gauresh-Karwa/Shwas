from __future__ import annotations
import os
from functools import lru_cache
from typing import Optional

_CHECKPOINT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "models", "gnn_best.pt")


@lru_cache(maxsize=1)
def get_gnn_model():
    try:
        import torch
        from app.ml.gnn_model import SpatialGNN
        path = os.path.abspath(_CHECKPOINT_PATH)
        if not os.path.exists(path):
            return None
        model = SpatialGNN()
        state = torch.load(path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        return model
    except Exception:
        return None
