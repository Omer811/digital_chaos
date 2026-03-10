from __future__ import annotations

import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


class PCAError(RuntimeError):
    pass


def run_pca(
    samples_df: pd.DataFrame,
    feature_columns: list[str],
    components: int = 3,
    standardize: bool = True,
) -> tuple[pd.DataFrame, PCA]:
    if components < 1:
        raise PCAError("components must be >= 1")

    data = samples_df[feature_columns].to_numpy()

    if standardize:
        scaler = StandardScaler()
        data = scaler.fit_transform(data)

    pca = PCA(n_components=components)
    transformed = pca.fit_transform(data)

    pca_cols = [f"PC{i + 1}" for i in range(components)]
    out_df = pd.DataFrame(transformed, columns=pca_cols)
    out_df.insert(0, "sample_index", samples_df["sample_index"].values)
    return out_df, pca
