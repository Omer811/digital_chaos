from __future__ import annotations

import json
from pathlib import Path

from .arduino_cli import compile_sketch, upload_sketch
from .correlation import lag1_abs_correlation, summarize_correlation
from .entropy import condition_entropy
from .pca_processor import run_pca
from .serial_collector import SamplingRequest, SerialCollectionError, collect_samples
from .visualizations.base import VisualizationContext
from .visualizations.plotly_3d_scatter import Plotly3DScatterVisualizer


def _collect_with_correlation_guard(
    req: SamplingRequest,
    feature_cols: list[str],
    correlation_cfg: dict,
) -> tuple[object, dict]:
    enabled = bool(correlation_cfg.get("auto_increase_delay_until_uncorrelated", False))
    threshold = float(correlation_cfg.get("lag1_abs_threshold", 0.2))
    step_us = int(correlation_cfg.get("delay_step_us", 500))
    max_delay_us = int(correlation_cfg.get("max_delay_us", req.delay_us))
    fail_if_unmet = bool(correlation_cfg.get("fail_if_unmet", True))
    max_attempts = max(1, int(correlation_cfg.get("max_attempts", 25)))

    attempts: list[dict] = []
    raw_df = None

    if not enabled:
        print("[pipeline] Correlation guard disabled; collecting once", flush=True)
        raw_df = collect_samples(req)
        summary = summarize_correlation(
            lag1_abs_correlation(raw_df, feature_cols), threshold=threshold
        )
        print(
            "[pipeline] Correlation summary: "
            f"max_lag1_abs_corr={summary['max_lag1_abs_corr']:.4f}, "
            f"threshold={threshold}",
            flush=True,
        )
        return raw_df, {"enabled": False, "attempts": [summary], "final": summary}

    delay_us = req.delay_us
    for attempt_idx in range(max_attempts):
        print(
            f"[pipeline] Attempt {attempt_idx + 1}/{max_attempts} with delay_us={delay_us}",
            flush=True,
        )
        current_req = SamplingRequest(
            sample_count=req.sample_count,
            pins=req.pins,
            delay_us=delay_us,
            channel_settle_us=req.channel_settle_us,
            throwaway_reads_after_switch=req.throwaway_reads_after_switch,
            progress_every_samples=req.progress_every_samples,
            baud_rate=req.baud_rate,
            port=req.port,
            serial_timeout_seconds=req.serial_timeout_seconds,
            handshake_timeout_seconds=req.handshake_timeout_seconds,
        )

        raw_df = collect_samples(current_req)
        summary = summarize_correlation(
            lag1_abs_correlation(raw_df, feature_cols), threshold=threshold
        )
        summary["delay_us"] = delay_us
        attempts.append(summary)
        print(
            "[pipeline] Correlation result: "
            f"max_lag1_abs_corr={summary['max_lag1_abs_corr']:.4f}, "
            f"threshold={threshold}, pass={summary['passes_threshold']}",
            flush=True,
        )

        if summary["passes_threshold"]:
            print("[pipeline] Threshold met, no retry needed", flush=True)
            return raw_df, {"enabled": True, "attempts": attempts, "final": summary}

        if delay_us >= max_delay_us:
            print("[pipeline] Reached max_delay_us; stopping retries", flush=True)
            break

        next_delay = min(delay_us + step_us, max_delay_us)
        print(
            f"[pipeline] Retrying with higher delay: {delay_us} -> {next_delay} us",
            flush=True,
        )
        delay_us = min(delay_us + step_us, max_delay_us)

    final_summary = attempts[-1] if attempts else {"passes_threshold": False}
    if fail_if_unmet:
        raise SerialCollectionError(
            "Correlation threshold not met after delay tuning. "
            f"Final max lag1 abs corr: {final_summary.get('max_lag1_abs_corr')} "
            f"at delay_us={final_summary.get('delay_us')}."
        )

    if raw_df is None:
        raise SerialCollectionError("No samples were collected during correlation tuning.")
    return raw_df, {"enabled": True, "attempts": attempts, "final": final_summary}


def run_pipeline(config: dict) -> dict[str, object]:
    arduino_cfg = config["arduino"]
    sampling_cfg = config["sampling"]
    processing_cfg = config["processing"]
    entropy_cfg = config.get("entropy", {})
    output_cfg = config["output"]
    correlation_cfg = config.get("correlation", {})

    data_dir = Path(output_cfg["data_dir"])
    plots_dir = Path(output_cfg["plots_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    sketch_path = arduino_cfg["sketch_path"]
    fqbn = arduino_cfg["fqbn"]
    port = arduino_cfg["port"]

    if arduino_cfg.get("upload_before_run", False):
        print("[pipeline] Compiling Arduino sketch", flush=True)
        compile_sketch(sketch_path=sketch_path, fqbn=fqbn)
        print("[pipeline] Uploading Arduino sketch", flush=True)
        upload_sketch(sketch_path=sketch_path, fqbn=fqbn, port=port)

    req = SamplingRequest(
        sample_count=int(sampling_cfg["sample_count"]),
        pins=[int(p) for p in sampling_cfg["pins"]],
        delay_us=int(sampling_cfg["delay_us"]),
        channel_settle_us=int(sampling_cfg.get("channel_settle_us", 200)),
        throwaway_reads_after_switch=int(
            sampling_cfg.get("throwaway_reads_after_switch", 1)
        ),
        progress_every_samples=max(0, int(sampling_cfg.get("progress_every_samples", 100))),
        baud_rate=int(arduino_cfg["baud_rate"]),
        port=str(port),
        serial_timeout_seconds=float(sampling_cfg["serial_timeout_seconds"]),
        handshake_timeout_seconds=float(sampling_cfg["handshake_timeout_seconds"]),
    )

    feature_cols = [f"A{p}" for p in req.pins]
    raw_df, correlation_report = _collect_with_correlation_guard(
        req=req,
        feature_cols=feature_cols,
        correlation_cfg=correlation_cfg,
    )

    raw_csv = data_dir / output_cfg["raw_csv"]
    raw_df.to_csv(raw_csv, index=False)
    print(f"[pipeline] Saved raw samples: {raw_csv}", flush=True)

    pca_df, pca = run_pca(
        samples_df=raw_df,
        feature_columns=feature_cols,
        components=int(processing_cfg.get("pca_components", 3)),
        standardize=bool(processing_cfg.get("standardize", True)),
    )

    pca_csv = data_dir / output_cfg["pca_csv"]
    pca_df.to_csv(pca_csv, index=False)
    print(f"[pipeline] Saved PCA CSV: {pca_csv}", flush=True)
    corr_json = data_dir / output_cfg.get("correlation_report_json", "correlation_report.json")
    corr_json.write_text(json.dumps(correlation_report, indent=2), encoding="utf-8")
    print(f"[pipeline] Saved correlation report: {corr_json}", flush=True)

    entropy_bytes, entropy_report = condition_entropy(raw_df, feature_cols, entropy_cfg)
    entropy_bin = data_dir / output_cfg.get("entropy_bin", "conditioned_entropy.bin")
    entropy_report_json = data_dir / output_cfg.get(
        "entropy_report_json", "entropy_report.json"
    )
    entropy_bin.write_bytes(entropy_bytes)
    entropy_report_json.write_text(json.dumps(entropy_report, indent=2), encoding="utf-8")
    print(
        f"[pipeline] Saved entropy outputs: {entropy_bin} ({len(entropy_bytes)} bytes), "
        f"{entropy_report_json}",
        flush=True,
    )

    viz_ctx = VisualizationContext(output_dir=plots_dir)
    visualizer = Plotly3DScatterVisualizer(
        png_name=output_cfg["plot_png"],
        html_name=output_cfg["plot_html"],
    )
    plot_paths = visualizer.render(pca_df, viz_ctx)
    print(f"[pipeline] Saved plots: {plot_paths}", flush=True)

    return {
        "raw_csv": str(raw_csv),
        "pca_csv": str(pca_csv),
        "correlation_report_json": str(corr_json),
        "correlation_final": correlation_report.get("final"),
        "entropy_bin": str(entropy_bin),
        "entropy_report_json": str(entropy_report_json),
        "entropy_final_bytes": len(entropy_bytes),
        "plots": [str(p) for p in plot_paths],
        "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
    }
