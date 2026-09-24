import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional
LAT_MIN, LAT_MAX = (18.85, 19.3)
LON_MIN, LON_MAX = (72.75, 73.0)
AQI_MAX = 500.0
KM_PER_DEG_LAT = 111.0

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = (math.radians(lat1), math.radians(lat2))
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def normalise_lat(lat: float) -> float:
    return (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)

def normalise_lon(lon: float) -> float:
    return (lon - LON_MIN) / (LON_MAX - LON_MIN)

def temporal_encoding(hour: int, weekday: int) -> tuple[float, float, float, float]:
    hs = math.sin(2 * math.pi * hour / 24)
    hc = math.cos(2 * math.pi * hour / 24)
    ws = math.sin(2 * math.pi * weekday / 7)
    wc = math.cos(2 * math.pi * weekday / 7)
    return (hs, hc, ws, wc)

def build_knn_graph(lats: list[float], lons: list[float], k: int=5) -> tuple[torch.Tensor, torch.Tensor]:
    N = len(lats)
    k = min(k, N - 1)
    if k == 0:
        return (torch.zeros(2, 0, dtype=torch.long), torch.zeros(0))
    dist_matrix = [[haversine_km(lats[i], lons[i], lats[j], lons[j]) if i != j else float('inf') for j in range(N)] for i in range(N)]
    srcs, tgts, weights = ([], [], [])
    for i in range(N):
        row = dist_matrix[i]
        nearest = sorted(range(N), key=lambda j: row[j])[:k]
        for j in nearest:
            srcs.append(i)
            tgts.append(j)
            weights.append(1.0 / (row[j] ** 2 + 1e-06))
    edge_index = torch.tensor([srcs, tgts], dtype=torch.long)
    edge_weight = torch.tensor(weights, dtype=torch.float32)
    return (edge_index, edge_weight)

class SpatialGATLayer(nn.Module):

    def __init__(self, in_dim: int, out_dim: int, n_heads: int=4, dropout: float=0.1):
        super().__init__()
        assert out_dim % n_heads == 0, 'out_dim must be divisible by n_heads'
        self.H = n_heads
        self.D = out_dim // n_heads
        self.scale = math.sqrt(self.D)
        self.W_q = nn.Linear(in_dim, out_dim, bias=False)
        self.W_k = nn.Linear(in_dim, out_dim, bias=False)
        self.W_v = nn.Linear(in_dim, out_dim, bias=False)
        self.out = nn.Linear(out_dim, out_dim)
        self.drop = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(out_dim)
        self.res = nn.Linear(in_dim, out_dim, bias=False) if in_dim != out_dim else nn.Identity()

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor, edge_weight: torch.Tensor) -> torch.Tensor:
        N = x.size(0)
        src_idx, tgt_idx = (edge_index[0], edge_index[1])
        Q = self.W_q(x).view(N, self.H, self.D)
        K = self.W_k(x).view(N, self.H, self.D)
        V = self.W_v(x).view(N, self.H, self.D)
        attn = (Q[tgt_idx] * K[src_idx]).sum(-1) / self.scale
        dist_bias = torch.log(edge_weight + 1e-08).unsqueeze(-1)
        attn = attn + dist_bias
        max_per_tgt = torch.full((N, self.H), float('-inf'), device=x.device)
        max_per_tgt.scatter_reduce_(0, tgt_idx.unsqueeze(-1).expand_as(attn), attn, reduce='amax', include_self=True)
        attn_shifted = attn - max_per_tgt[tgt_idx]
        exp_attn = torch.exp(attn_shifted)
        sum_exp = torch.zeros(N, self.H, device=x.device)
        sum_exp.scatter_add_(0, tgt_idx.unsqueeze(-1).expand_as(exp_attn), exp_attn)
        alpha = exp_attn / (sum_exp[tgt_idx] + 1e-08)
        alpha = self.drop(alpha)
        weighted_v = alpha.unsqueeze(-1) * V[src_idx]
        agg = torch.zeros(N, self.H, self.D, device=x.device)
        idx_expand = tgt_idx.view(-1, 1, 1).expand_as(weighted_v)
        agg.scatter_add_(0, idx_expand, weighted_v)
        out = agg.view(N, self.H * self.D)
        out = self.out(out)
        return self.norm(out + self.res(x))

class SpatialGNN(nn.Module):
    IN_DIM = 9
    HIDDEN_DIM = 64

    def __init__(self, k_neighbours: int=5, n_heads: int=4, dropout: float=0.15):
        super().__init__()
        self.k = k_neighbours
        self.input_proj = nn.Sequential(nn.Linear(self.IN_DIM, self.HIDDEN_DIM), nn.ReLU())
        self.gat1 = SpatialGATLayer(self.HIDDEN_DIM, self.HIDDEN_DIM, n_heads, dropout)
        self.gat2 = SpatialGATLayer(self.HIDDEN_DIM, self.HIDDEN_DIM, n_heads, dropout)
        self.head = nn.Sequential(nn.Linear(self.HIDDEN_DIM, 32), nn.ReLU(), nn.Dropout(dropout), nn.Linear(32, 1), nn.Sigmoid())

    def forward(self, node_feats: torch.Tensor, lats: list[float], lons: list[float]) -> torch.Tensor:
        edge_index, edge_weight = build_knn_graph(lats, lons, k=self.k)
        edge_index = edge_index.to(node_feats.device)
        edge_weight = edge_weight.to(node_feats.device)
        x = self.input_proj(node_feats)
        x = F.relu(self.gat1(x, edge_index, edge_weight))
        x = self.gat2(x, edge_index, edge_weight)
        return self.head(x)

def gnn_interpolate(model: SpatialGNN, query_lat: float, query_lon: float, station_lats: list[float], station_lons: list[float], station_aqis: list[float], hour: int, weekday: int, station_aqis_1h: list[float | None] | None=None, station_aqis_3h: list[float | None] | None=None, device: torch.device | None=None) -> float:
    if device is None:
        device = next(model.parameters()).device
    hs, hc, ws, wc = temporal_encoding(hour, weekday)
    all_lats = [query_lat] + list(station_lats)
    all_lons = [query_lon] + list(station_lons)
    feats = []
    feats.append([normalise_lat(query_lat), normalise_lon(query_lon), 0.0, 0.0, 0.0, hs, hc, ws, wc])
    for i, (lat, lon, aqi) in enumerate(zip(station_lats, station_lons, station_aqis)):
        aqi_norm = aqi / AQI_MAX
        lag1 = station_aqis_1h[i] if station_aqis_1h and station_aqis_1h[i] is not None else None
        lag3 = station_aqis_3h[i] if station_aqis_3h and station_aqis_3h[i] is not None else None
        lag1_norm = lag1 / AQI_MAX if lag1 is not None else aqi_norm
        lag3_norm = lag3 / AQI_MAX if lag3 is not None else aqi_norm
        feats.append([normalise_lat(lat), normalise_lon(lon), aqi_norm, lag1_norm, lag3_norm, hs, hc, ws, wc])
    feat_tensor = torch.tensor(feats, dtype=torch.float32, device=device)
    model.eval()
    with torch.no_grad():
        preds = model(feat_tensor, all_lats, all_lons)
    predicted_aqi = preds[0, 0].item() * AQI_MAX
    return max(0.0, min(AQI_MAX, predicted_aqi))
