from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


class PipelineLauncherError(RuntimeError):
    pass


SEED_WAVEFORMS = [
    "sine",
    "square",
    "triangle",
    "sawtooth",
    "pulse",
    "chirp",
    "exp_decay",
    "random_noise",
]

CONFIG_KEYS = {
    "tag",
    "output_dir",
    "config_out",
    "dry_run",
    "fqbn",
    "port",
    "baud_rate",
    "upload",
    "sketch_path",
    "samples_per_slice",
    "buffer_samples",
    "time_slices",
    "max_samples",
    "periods_per_signal",
    "seed_waveform",
    "seed_waveforms",
    "all_seed_waveforms",
    "random_noise_seed",
    "stop_when_decay",
    "decay_threshold_norm",
    "decay_metric",
    "min_slices_before_decay_check",
    "pwm_pin",
    "analog_pin",
    "settle_us",
    "oversample_count",
    "oversample_delay_us",
    "alpha_permille",
    "progress_every_steps",
    "serial_timeout_seconds",
    "handshake_timeout_seconds",
    "plot_3d_mode",
    "stl_enabled",
    "stl_ratio_x",
    "stl_ratio_y",
}


def resolve_python() -> str:
    py = shutil.which("python3")
    if py:
        return py
    raise PipelineLauncherError("python3 not found in PATH")


def build_config(
    args: argparse.Namespace,
    seed_waveform: str,
    run_tag: str,
    run_output_dir: Path,
    upload_before_run: bool,
) -> dict:
    max_samples = args.max_samples
    if max_samples is None:
        max_samples = args.samples_per_slice * args.time_slices

    return {
        "arduino": {
            "fqbn": args.fqbn,
            "port": args.port,
            "baud_rate": args.baud_rate,
            "upload_before_run": upload_before_run,
            "sketch_path": args.sketch_path,
        },
        "experiment": {
            "steps": args.samples_per_slice * args.time_slices,
            "sine_samples_per_cycle": args.samples_per_slice,
            "buffer_samples": args.buffer_samples,
            "periods_per_signal": args.periods_per_signal,
            "seed_waveform": seed_waveform,
            "random_noise_seed": args.random_noise_seed,
            "time_slices": args.time_slices,
            "max_samples": max_samples,
            "stop_when_decay": args.stop_when_decay,
            "decay_threshold_norm": args.decay_threshold_norm,
            "decay_metric": args.decay_metric,
            "min_slices_before_decay_check": args.min_slices_before_decay_check,
            "pwm_pin": args.pwm_pin,
            "analog_pin": args.analog_pin,
            "settle_us": args.settle_us,
            "oversample_count": args.oversample_count,
            "oversample_delay_us": args.oversample_delay_us,
            "alpha_permille": args.alpha_permille,
            "progress_every_steps": args.progress_every_steps,
            "serial_timeout_seconds": args.serial_timeout_seconds,
            "handshake_timeout_seconds": args.handshake_timeout_seconds,
        },
        "output": {
            "dir": str(run_output_dir),
            "csv": f"{run_tag}_steps.csv",
            "plot_2d_png": f"{run_tag}_2d.png",
            "plot_2d_html": f"{run_tag}_2d.html",
            "plot_3d_png": f"{run_tag}_3d.png",
            "plot_3d_html": f"{run_tag}_3d.html",
            "plot_3d_mode": args.plot_3d_mode,
            "stl_enabled": args.stl_enabled,
            "stl_ratio_x": args.stl_ratio_x,
            "stl_ratio_y": args.stl_ratio_y,
            "stl_file": f"{run_tag}_surface_outputonly_medratio.stl",
        },
    }


def run_cmd(cmd: list[str]) -> None:
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise PipelineLauncherError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def parse_seed_waveforms(args: argparse.Namespace) -> list[str]:
    if args.all_seed_waveforms:
        return SEED_WAVEFORMS[:]

    raw_modes = args.seed_waveforms
    if isinstance(raw_modes, list):
        modes = [str(m).strip() for m in raw_modes if str(m).strip()]
    elif str(raw_modes).strip():
        modes = [m.strip() for m in str(raw_modes).split(",") if m.strip()]
    else:
        modes = []

    if modes:
        invalid = [m for m in modes if m not in SEED_WAVEFORMS]
        if invalid:
            raise PipelineLauncherError(
                f"Unsupported seed waveform(s): {', '.join(invalid)}. "
                f"Allowed: {', '.join(SEED_WAVEFORMS)}"
            )
        if not modes:
            raise PipelineLauncherError("No valid seed waveforms provided to --seed-waveforms")
        return modes

    return [args.seed_waveform]


def load_launcher_config(path: str) -> dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise PipelineLauncherError(f"Pipeline config not found: {cfg_path}")
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineLauncherError(f"Invalid JSON in pipeline config: {cfg_path} ({exc})") from exc

    if not isinstance(data, dict):
        raise PipelineLauncherError("Pipeline config must be a JSON object")

    unknown = sorted(set(data.keys()) - CONFIG_KEYS)
    if unknown:
        raise PipelineLauncherError(
            f"Unknown keys in pipeline config: {', '.join(unknown)}. "
            f"Allowed keys: {', '.join(sorted(CONFIG_KEYS))}"
        )
    return data


def parse_args() -> argparse.Namespace:
    now_tag = datetime.now().strftime("run_%Y_%m_%d_%H%M%S")

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument(
        "--pipeline-config",
        default="",
        help="Path to JSON file with launcher options (used as defaults)",
    )
    pre_args, remaining = pre.parse_known_args()

    cfg: dict[str, Any] = {}
    if pre_args.pipeline_config:
        cfg = load_launcher_config(pre_args.pipeline_config)

    p = argparse.ArgumentParser(
        description="Manual full feedback pipeline launcher",
        parents=[pre],
    )

    p.add_argument("--tag", default=cfg.get("tag", now_tag), help="Tag prefix for output file names")
    p.add_argument(
        "--output-dir",
        default=cfg.get("output_dir", f"output/sine_feedback/{now_tag}"),
        help="Output directory",
    )
    p.add_argument("--config-out", default=cfg.get("config_out", ""), help="Optional explicit config path")
    p.add_argument("--dry-run", action="store_true", default=bool(cfg.get("dry_run", False)), help="Only generate config, do not run")

    p.add_argument("--fqbn", default=cfg.get("fqbn", "arduino:avr:uno"))
    p.add_argument("--port", default=cfg.get("port", "/dev/cu.usbmodem1201"))
    p.add_argument("--baud-rate", type=int, default=int(cfg.get("baud_rate", 115200)))
    p.add_argument("--upload", action="store_true", default=bool(cfg.get("upload", True)))
    p.add_argument("--no-upload", dest="upload", action="store_false")
    p.add_argument("--sketch-path", default=cfg.get("sketch_path", "arduino/sine_feedback"))

    p.add_argument("--samples-per-slice", type=int, default=int(cfg.get("samples_per_slice", 100)))
    p.add_argument("--time-slices", type=int, default=int(cfg.get("time_slices", 100)))
    p.add_argument(
        "--buffer-samples",
        type=int,
        default=int(cfg.get("buffer_samples", 0)),
        help="Chunk size sent to Arduino per RUN packet. 0 = auto/use board max",
    )
    p.add_argument("--max-samples", type=int, default=cfg.get("max_samples", None))
    p.add_argument("--periods-per-signal", type=float, default=float(cfg.get("periods_per_signal", 1.0)))
    p.add_argument(
        "--seed-waveform",
        choices=SEED_WAVEFORMS,
        default=str(cfg.get("seed_waveform", "sine")),
    )
    p.add_argument(
        "--seed-waveforms",
        default=cfg.get("seed_waveforms", ""),
        help="Comma-separated list of waveforms to run (overrides --seed-waveform)",
    )
    p.add_argument(
        "--all-seed-waveforms",
        action="store_true",
        default=bool(cfg.get("all_seed_waveforms", False)),
        help="Run all supported seed waveforms",
    )
    p.add_argument("--random-noise-seed", type=int, default=int(cfg.get("random_noise_seed", 42)))

    p.add_argument("--stop-when-decay", action="store_true", default=bool(cfg.get("stop_when_decay", False)))
    p.add_argument("--decay-threshold-norm", type=float, default=float(cfg.get("decay_threshold_norm", 0.1)))
    p.add_argument(
        "--decay-metric",
        choices=["mean", "std", "peak_to_peak"],
        default=str(cfg.get("decay_metric", "mean")),
    )
    p.add_argument("--min-slices-before-decay-check", type=int, default=int(cfg.get("min_slices_before_decay_check", 1)))

    p.add_argument("--pwm-pin", type=int, default=int(cfg.get("pwm_pin", 9)))
    p.add_argument("--analog-pin", type=int, default=int(cfg.get("analog_pin", 0)))
    p.add_argument("--settle-us", type=int, default=int(cfg.get("settle_us", 2000)))
    p.add_argument("--oversample-count", type=int, default=int(cfg.get("oversample_count", 16)))
    p.add_argument("--oversample-delay-us", type=int, default=int(cfg.get("oversample_delay_us", 50)))
    p.add_argument("--alpha-permille", type=int, default=int(cfg.get("alpha_permille", 0)))
    p.add_argument("--progress-every-steps", type=int, default=int(cfg.get("progress_every_steps", 1000)))
    p.add_argument("--serial-timeout-seconds", type=float, default=float(cfg.get("serial_timeout_seconds", 25)))
    p.add_argument("--handshake-timeout-seconds", type=float, default=float(cfg.get("handshake_timeout_seconds", 5)))

    p.add_argument(
        "--plot-3d-mode",
        choices=["slice_lines", "markers_only"],
        default=str(cfg.get("plot_3d_mode", "slice_lines")),
    )
    p.add_argument("--stl-enabled", action="store_true", default=bool(cfg.get("stl_enabled", True)))
    p.add_argument("--no-stl", dest="stl_enabled", action="store_false")
    p.add_argument("--stl-ratio-x", type=float, default=float(cfg.get("stl_ratio_x", 0.5)))
    p.add_argument("--stl-ratio-y", type=float, default=float(cfg.get("stl_ratio_y", 0.5)))

    return p.parse_args(remaining)


def main() -> None:
    args = parse_args()
    waveforms = parse_seed_waveforms(args)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    py = resolve_python()
    for i, waveform in enumerate(waveforms):
        run_tag = f"{args.tag}_{waveform}"
        run_output_dir = output_dir / waveform if len(waveforms) > 1 else output_dir
        run_output_dir.mkdir(parents=True, exist_ok=True)

        cfg = build_config(
            args=args,
            seed_waveform=waveform,
            run_tag=run_tag,
            run_output_dir=run_output_dir,
            upload_before_run=(args.upload if i == 0 else False),
        )

        if args.config_out:
            base = Path(args.config_out)
            config_path = base.with_name(f"{base.stem}_{waveform}{base.suffix or '.json'}")
        else:
            config_path = run_output_dir / f"{run_tag}_config.json"

        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"[pipeline-launcher] wrote config: {config_path}")

        if args.dry_run:
            continue

        cmd = [py, "run_sine_feedback.py", "--config", str(config_path)]
        print(f"[pipeline-launcher] running: {' '.join(cmd)}")
        run_cmd(cmd)

    if args.dry_run:
        print("[pipeline-launcher] dry-run mode, not executing pipeline")


if __name__ == "__main__":
    main()
