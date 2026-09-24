import math
import torch
import pytest
from app.ml.gnn_model import (
    normalise_lat,
    normalise_lon,
    temporal_encoding,
    build_knn_graph,
    SpatialGATLayer,
    SpatialGNN,
    gnn_interpolate,
    LAT_MIN,
    LAT_MAX,
    LON_MIN,
    LON_MAX,
)

def test_normalise_lat_lon_bounds():
    assert normalise_lat(LAT_MIN) == pytest.approx(0.0)
    assert normalise_lat(LAT_MAX) == pytest.approx(1.0)
    assert normalise_lon(LON_MIN) == pytest.approx(0.0)
    assert normalise_lon(LON_MAX) == pytest.approx(1.0)

def test_temporal_encoding_properties():
    for h in [0, 6, 12, 18, 23]:
        for w in [0, 3, 6]:
            hs, hc, ws, wc = temporal_encoding(h, w)
            assert pytest.approx(hs**2 + hc**2, abs=1e-5) == 1.0
            assert pytest.approx(ws**2 + wc**2, abs=1e-5) == 1.0

def test_temporal_encoding_hour_zero():
    hs, hc, ws, wc = temporal_encoding(0, 0)
    assert pytest.approx(hs, abs=1e-5) == 0.0
    assert pytest.approx(hc, abs=1e-5) == 1.0

def test_build_knn_graph_shapes():
    lats = [19.0, 19.1, 19.2, 19.05]
    lons = [72.8, 72.85, 72.9, 72.82]
    k = 2
    edge_index, edge_weight = build_knn_graph(lats, lons, k=k)
    assert edge_index.shape == (2, len(lats) * k)
    assert edge_weight.shape == (len(lats) * k,)
    assert (edge_weight > 0).all()

def test_spatial_gat_layer_shape():
    layer = SpatialGATLayer(in_dim=16, out_dim=16, n_heads=4, dropout=0.0)
    x = torch.randn(5, 16)
    edge_index = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 0]], dtype=torch.long)
    edge_weight = torch.ones(4)
    out = layer(x, edge_index, edge_weight)
    assert out.shape == (5, 16)

def test_spatial_gnn_model_forward():
    model = SpatialGNN(k_neighbours=3, n_heads=4, dropout=0.0)
    model.eval()
    n_nodes = 6
    feats = torch.randn(n_nodes, 9)
    lats = [19.0 + i * 0.02 for i in range(n_nodes)]
    lons = [72.8 + i * 0.02 for i in range(n_nodes)]
    with torch.no_grad():
        preds = model(feats, lats, lons)
    assert preds.shape == (n_nodes, 1)
    assert (preds >= 0.0).all() and (preds <= 1.0).all()

def test_gnn_interpolate_output_bounds():
    model = SpatialGNN(k_neighbours=2, n_heads=4, dropout=0.0)
    query_lat, query_lon = 19.05, 72.85
    station_lats = [19.0, 19.1, 19.2]
    station_lons = [72.8, 72.9, 72.85]
    station_aqis = [80.0, 120.0, 95.0]
    result = gnn_interpolate(
        model=model,
        query_lat=query_lat,
        query_lon=query_lon,
        station_lats=station_lats,
        station_lons=station_lons,
        station_aqis=station_aqis,
        hour=10,
        weekday=2,
    )
    assert isinstance(result, float)
    assert 0.0 <= result <= 500.0
