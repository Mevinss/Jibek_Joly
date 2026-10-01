"""
Dataset loader demonstration script.
Demonstrates ingestion of tabular data, structural graph nodes/edges,
sequential route features, and train/validation/test split assignment.
"""

from pathlib import Path
import json
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
TABULAR_PATH = BASE_DIR / "processed_tabular" / "train_delays_tabular.parquet"
NODES_PATH = BASE_DIR / "graph_and_sequences" / "graph" / "nodes_features.parquet"
EDGES_PATH = BASE_DIR / "graph_and_sequences" / "graph" / "edges_features.parquet"
SEQ_PATH = BASE_DIR / "graph_and_sequences" / "sequences" / "route_sequences.parquet"
SPLITS_PATH = BASE_DIR / "graph_and_sequences" / "splits.json"


class SequenceGraphDatasetDemo:
    """
    Demonstrates how to group route_sequences.parquet into sequence samples
    and map station IDs to graph node indices for neural models (GRU / GNN).
    """
    def __init__(self, seq_df: pd.DataFrame, nodes_df: pd.DataFrame, splits: dict, split_name: str = "train", max_seq_len: int = 10):
        self.max_seq_len = max_seq_len
        # Filter run IDs matching the target split ('train', 'val', or 'test')
        self.split_runs = set(run_id for run_id, split_val in splits.items() if split_val == split_name)

        # 1. Map station IDs to contiguous graph node indices (0 ... N-1)
        self.station_map = {station_id: idx for idx, station_id in enumerate(nodes_df["id"].values)}

        # 2. Filter sequences by split
        seq_filtered = seq_df[seq_df["run_id"].astype(str).isin(self.split_runs)].copy()
        seq_filtered["station_node_idx"] = seq_filtered["station_id"].map(self.station_map).fillna(-1).astype(int)

        # 3. Numeric feature columns for sequence steps
        self.seq_num_cols = [
            "delay_departure_min", "time_reserve_min", "arrival_hour_sin", "arrival_hour_cos",
            "temperature_2m", "snowfall", "snow_depth", "is_freezing_threshold", "is_heavy_precipitation"
        ]
        available_cols = [c for c in self.seq_num_cols if c in seq_filtered.columns]

        # 4. Construct sequence samples per train run
        self.samples = []
        for run_id, group in seq_filtered.groupby("run_id"):
            group = group.sort_values("stop_order").reset_index(drop=True)
            if len(group) < 2:
                continue

            num_matrix = group[available_cols].fillna(0.0).values.astype(np.float32)
            node_indices = group["station_node_idx"].values
            targets = group["delta_delay"].values.astype(np.float32)

            # Target step i (from 1 to len-1)
            for i in range(1, len(group)):
                if np.isnan(targets[i]):
                    continue
                start_idx = max(0, i - self.max_seq_len)
                seq_matrix = num_matrix[start_idx:i]
                seq_nodes = node_indices[start_idx:i]

                self.samples.append({
                    "run_id": str(run_id),
                    "target_step": i,
                    "target_node": node_indices[i],
                    "target_delta_delay": targets[i],
                    "seq_features": seq_matrix,
                    "seq_node_indices": seq_nodes,
                    "seq_len": len(seq_matrix)
                })

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        return self.samples[idx]


def main():
    print("--- Tabular Dataset ---")
    if TABULAR_PATH.exists():
        df_tabular = pd.read_parquet(TABULAR_PATH)
        print(f"Tabular dataset loaded. Shape: {df_tabular.shape} (stop_order >= 2)")

    print("\n--- Train/Validation/Test Benchmark Splits ---")
    if SPLITS_PATH.exists():
        with open(SPLITS_PATH, "r", encoding="utf-8") as f:
            splits = json.load(f)
        split_counts = pd.Series(list(splits.values())).value_counts()
        print("  Splits distribution:")
        for split_k, count_v in split_counts.items():
            print(f"    {split_k}: {count_v} train runs")

    print("\n--- Structural Representation (Graph & Sequences) ---")
    if NODES_PATH.exists() and EDGES_PATH.exists() and SEQ_PATH.exists():
        df_nodes = pd.read_parquet(NODES_PATH)
        df_edges = pd.read_parquet(EDGES_PATH)
        df_seq = pd.read_parquet(SEQ_PATH)

        print(f"  Station nodes: {df_nodes.shape[0]} stations (features: {df_nodes.shape[1]})")
        print(f"  Track edges: {df_edges.shape[0]} atomized segments (features: {df_edges.shape[1]})")
        print(f"  Route sequences: {df_seq.shape[0]} stops (features: {df_seq.shape[1]}, includes stop_order = 1)")

        print("\n--- Sequence-Graph Data ---")
        train_dataset = SequenceGraphDatasetDemo(
            seq_df=df_seq,
            nodes_df=df_nodes,
            splits=splits,
            split_name="train",
            max_seq_len=10
        )
        print(f"  Constructed train sequence samples: {len(train_dataset)}")
        if len(train_dataset) > 0:
            sample = train_dataset[0]
            print(f"  Sample 0 -> run_id: {sample['run_id']}, target_node: {sample['target_node']}, "
                  f"target_delta_delay: {sample['target_delta_delay']:.2f} min, "
                  f"seq_len: {sample['seq_len']}, seq_shape: {sample['seq_features'].shape}")


if __name__ == "__main__":
    main()
