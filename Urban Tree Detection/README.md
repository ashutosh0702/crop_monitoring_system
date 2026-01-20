# Urban Tree Detection with PointNet - Research Project

A research-focused implementation of urban tree detection using PointNet
for semantic segmentation of LiDAR point cloud data.

## Project Overview

This repository contains Jupyter notebooks documenting the research progression
from baseline segmentation methods to deep learning approaches (PointNet) for
urban tree detection in LiDAR point clouds.

## Installation

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

## Project Structure

```
├── data/                   # LiDAR point cloud data
├── notebooks/              # Research Jupyter notebooks
│   ├── 01_data_exploration.ipynb
│   ├── 02_baseline_segmentation.ipynb
│   ├── 03_pointnet_segmentation.ipynb
│   ├── 04_advanced_pointnet.ipynb
│   └── 05_future_scope.ipynb
├── src/                    # Source code modules
├── scripts/                # Standalone scripts
│   └── inference.py
└── experiments/            # MLflow tracking
```

## Notebooks

| Notebook | Description |
|----------|-------------|
| 01_data_exploration | LiDAR data loading and ground filtering |
| 02_baseline_segmentation | Height-based and clustering methods |
| 03_pointnet_segmentation | PointNet implementation with MLflow |
| 04_advanced_pointnet | Data augmentation and ablation studies |
| 05_future_scope | PointNet++, Transformers, future directions |

## Running Inference

```bash
python scripts/inference.py --input path/to/pointcloud.las --output path/to/output.las
```

## MLflow Tracking

```bash
mlflow ui --backend-store-uri experiments/mlruns
# Open http://127.0.0.1:5000
```

## Technologies

- **PyTorch** - Deep learning framework
- **laspy** - LiDAR point cloud I/O
- **MLflow** - Experiment tracking
- **Open3D** - Point cloud visualization

## Future Work

- PointNet++ with hierarchical learning
- Point Cloud Transformer (PCT)
- Multi-sensor fusion (LiDAR + RGB)
