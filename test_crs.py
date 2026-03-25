#!/usr/bin/env python3
"""
Quick test script to verify CRS transformation in STAC client.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping

# Test geometry in EPSG:4326 (lat/lon)
test_geometry = {
    "type": "Polygon",
    "coordinates": [[
        [-122.0, 37.0],
        [-122.0, 38.0],
        [-121.0, 38.0],
        [-121.0, 37.0],
        [-122.0, 37.0]
    ]]
}

# Simulate UTM zone 10N (common for California)
target_crs = 'EPSG:32610'

print("Original geometry (EPSG:4326):")
print(test_geometry)

# Transform to UTM
transformed = transform_geom('EPSG:4326', target_crs, test_geometry)
print(f"\nTransformed geometry ({target_crs}):")
print(transformed)

# Verify it's a valid geometry
geom = shape(transformed)
print(f"\nValid geometry: {geom.is_valid}")
print(f"Area: {geom.area}")

print("\nCRS transformation test passed!")