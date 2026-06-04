"""DocuDog orchestrator: JSON config, idle scheduling, watchdog, routing."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
import warnings
from typing import Any

import psutil
from docudog import context_bundles, inference, lineage, router, single_file, watcher
from docudog.config_loader import load_app_config

logger = logging.getLogger(__name__)


def _flush_logs() -> None:
    for h in logging.root.handlers:
        try:
            h.flush()
        except OSError:
            pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except OSError:
        pass


def load_config(config_path: str) -> dict[str, Any]:
    """
    Load config.json in the same directory as config_path (or treat config_path as base_dir),
    then merge config.yml / config.yaml if present.
    """
    p = os.path.normpath(os.path.abspath(config_path))
    base_dir = p if os.path.isdir(p) else os.path.dirname(p)
    json_path = os.path.join(base_dir, "config.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(json_path)
    return load_app_config(base_dir)


def load_state(state_path: str) -> dict[str, Any]:
    path = os.path.normpath(os.path.expandvars(state_path))
    if not os.path.isfile(path):
        return {"version": 1, "files": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "files" not in data:
        data["files"] = {}
    return data


def save_state_atomic(state_path: str, state: dict[str, Any]) -> None:
    path = os.path.normpath(os.path.expandvars(state_path))
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _run_lock_path(cfg: dict[str, Any], state_path: str) -> str:
    raw = str((cfg.get("paths") or {}).get("run_lock_path", "") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    base = os.path.dirname(os.path.normpath(os.path.expandvars(state_path)))
    return os.path.join(base or os.path.expanduser("~"), "DocuDog_main.lock")


def _paths_equivalent(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _read_run_lock(lock_path: str) -> tuple[int | None, str | None]:
    try:
        with open(lock_path, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.readlines() if ln.strip()]
    except OSError:
        return None, None
    if not lines:
        return None, None
    try:
        pid = int(lines[0])
    except ValueError:
        return None, None
    main = lines[1] if len(lines) > 1 else None
    return pid, main


def _proc_references_main(proc: psutil.Process, main_abs: str) -> bool:
    try:
        cmd = proc.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False
    main_nc = os.path.normcase(os.path.normpath(main_abs))
    for arg in cmd:
        try:
            if os.path.normcase(os.path.normpath(arg)) == main_nc:
                return True
        except OSError:
            continue
    blob = os.path.normcase(" ".join(cmd))
    return main_nc in blob


def _ensure_single_instance_or_replace(cfg: dict[str, Any], state_path: str) -> str:
    """
    If another DocuDog main.py (same script path as this file) is running, terminate it.
    Then write a PID lock for this process.
    """
    lock_path = _run_lock_path(cfg, state_path)
    our_main = os.path.normpath(os.path.abspath(__file__))
    our_pid = os.getpid()

    if os.path.isfile(lock_path):
        old_pid, old_main = _read_run_lock(lock_path)
        need_kill = False

        if old_pid and old_pid != our_pid:
            try:
                proc = psutil.Process(old_pid)
            except psutil.NoSuchProcess:
                proc = None
            if proc is not None and proc.is_running():
                same_script = bool(old_main) and _paths_equivalent(old_main, our_main)
                legacy_match = (not old_main) and _proc_references_main(proc, our_main)
                if same_script or legacy_match:
                    need_kill = True
                else:
                    logger.error(
                        "Run lock is held by pid=%s (different main.py path). Not killing. "
                        "Remove lock file if it is stale: %s",
                        old_pid,
                        lock_path,
                    )
                    raise SystemExit(1)

        if need_kill:
            logger.warning(
                "Stopping previous DocuDog instance (pid=%s) holding %s",
                old_pid,
                lock_path,
            )
            try:
                proc = psutil.Process(old_pid)
                proc.terminate()
                try:
                    proc.wait(timeout=12)
                except psutil.TimeoutExpired:
                    logger.warning("Previous instance did not exit; killing pid=%s", old_pid)
                    proc.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                logger.error(
                    "No permission to stop previous DocuDog (pid=%s). Close it manually.",
                    old_pid,
                )
                raise SystemExit(1) from None

        try:
            os.remove(lock_path)
        except OSError:
            pass

    d = os.path.dirname(lock_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as f:
        f.write(f"{our_pid}\n{our_main}\n")
    return lock_path


def _release_run_lock(lock_path: str) -> None:
    if not lock_path or not os.path.isfile(lock_path):
        return
    try:
        old_pid, _ = _read_run_lock(lock_path)
        if old_pid == os.getpid():
            os.remove(lock_path)
    except OSError:
        pass


def apply_background_priority() -> None:
    """Lower OS scheduling priority to reduce interactive jank."""
    try:
        p = psutil.Process()
        # Win32 has no literal LOW_PRIORITY_CLASS; IDLE/BelowNormal are the practical knobs.
        if os.name == "nt":
            p.nice(psutil.IDLE_PRIORITY_CLASS)
        else:
            p.nice(10)
        logger.debug("Process priority set for background-friendly scheduling.")
    except Exception as e:
        logger.warning("Could not adjust process priority: %s", e)


def _probe_dir_writable(dir_path: str) -> tuple[bool, str]:
    if not (dir_path or "").strip():
        dir_path = "."
    try:
        os.makedirs(dir_path, exist_ok=True)
        probe = os.path.join(dir_path, ".docudog_write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.remove(probe)
        except OSError:
            pass
        return True, ""
    except OSError as e:
        return False, str(e)


def _log_startup_environment_sanity(
    cfg: dict[str, Any],
    state_path: str,
    report_path: str,
) -> None:
    """Non-fatal checks: state/report parents, watch roots, optional GET /v1/models."""
    sparent = os.path.dirname(os.path.abspath(state_path))
    if not sparent:
        sparent = "."
    ok, err = _probe_dir_writable(sparent)
    if not ok:
        logger.warning(
            "Startup check: state_path parent may not be writable (%s): %s",
            sparent,
            err,
        )

    rparent = os.path.dirname(os.path.abspath(report_path))
    if not rparent:
        rparent = "."
    ok_r, err_r = _probe_dir_writable(rparent)
    if not ok_r:
        logger.warning(
            "Startup check: report_path parent may not be writable (%s): %s",
            rparent,
            err_r,
        )

    for r in watcher.expand_watch_dirs(cfg):
        if not os.path.isdir(r):
            logger.warning(
                "Startup check: watch path missing or not a directory: %s",
                r,
            )

    model_cfg = cfg.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
    if bool(model_cfg.get("use_mock", False)):
        return
    backend = inference.resolve_inference_backend(model_cfg)
    if backend not in ("lm_studio", "openai_compatible"):
        return
    skip = os.environ.get("DOCUDOG_SKIP_LM_MODEL_PROBE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if skip:
        logger.debug(
            "Startup check: skipping GET /v1/models (DOCUDOG_SKIP_LM_MODEL_PROBE=1)."
        )
        return
    lm_raw = model_cfg.get("lm_studio")
    lm_cfg = lm_raw if isinstance(lm_raw, dict) else {}
    base = str(lm_cfg.get("base_url") or "").strip()
    if not base:
        logger.warning(
            "Startup check: lm_studio.base_url empty — HTTP classify cannot run until set."
        )
        return
    ids, diag = inference.probe_openai_compatible_model_ids(base, timeout=3.0)
    if ids is None:
        logger.warning(
            "Startup check: could not reach LM Studio / OpenAI-compatible server at %s (%s). "
            "Classify may use mock until the server is up.",
            base,
            diag,
        )
    else:
        logger.info(
            "Startup check: GET /v1/models ok at %s (%d model id(s) listed).",
            base,
            len(ids),
        )


def _parse_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DocuDog Stage 1 watcher (idle-aware background classify)."
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help="Classify one file and exit (no watcher, no run lock). Same pipeline as tools/classify_one.py.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one queued file then exit (also DOCUDOG_RUN_ONCE=1).",
    )
    return parser.parse_args()


def _run_once_enabled(args: argparse.Namespace) -> bool:
    if args.once:
        return True
    return os.environ.get("DOCUDOG_RUN_ONCE", "").strip().lower() in ("1", "true", "yes")


def _run_single_file_cli(
    cfg: dict[str, Any],
    state_path: str,
    report_path: str,
    file_path: str,
) -> None:
    """Smoke path: one file, no daemon lock or observer."""
    state = load_state(state_path)

    def persist() -> None:
        save_state_atomic(state_path, state)

    try:
        result = single_file.process_single_path(
            cfg,
            state,
            file_path,
            report_path,
            state_path,
            persist,
        )
    except FileNotFoundError as e:
        print(f"DocuDog: {e}", file=sys.stderr)
        sys.exit(2)

    for line in single_file.format_result_lines(result, report_path):
        print(line)

    if result.outcome == single_file.SingleFileOutcome.REQUEUE:
        sys.exit(1)
    if result.outcome in (
        single_file.SingleFileOutcome.SKIPPED_FILTER,
        single_file.SingleFileOutcome.SKIPPED_EXTRACT,
        single_file.SingleFileOutcome.SKIPPED_EMPTY,
    ):
        sys.exit(3)
    sys.exit(0)


def main() -> None:
    from docudog.env_litert import apply_litert_env_defaults

    apply_litert_env_defaults()

    args = _parse_cli()
    run_once = _run_once_enabled(args)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base_dir, "config.json")
    if not os.path.isfile(cfg_path):
        print(f"config.json not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(cfg_path)

    _log_level = logging.INFO
    if os.environ.get("DOCUDOG_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        _log_level = logging.DEBUG
    _rs = cfg.get("runtime_settings")
    if isinstance(_rs, dict):
        _dbg = _rs.get("debug_python_logs", False)
        if _dbg is True or (isinstance(_dbg, str) and _dbg.strip().lower() in ("1", "true", "yes")):
            _log_level = logging.DEBUG

    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    try:
        import faulthandler

        faulthandler.enable(all_threads=True)
    except Exception:
        pass
    # openpyxl emits noisy UserWarnings on real-world xlsx; keep console readable.
    for _msg in (
        "Data Validation extension is not supported",
        "Workbook contains no default style",
        "Unknown extension is not supported",
        "Conditional Formatting extension is not supported",
        "Cannot parse header or footer",
    ):
        warnings.filterwarnings("ignore", category=UserWarning, message=f".*{_msg}.*")

    inference.log_inference_runtime_summary(cfg)

    paths = cfg.get("paths", {})
    state_path = paths.get(
        "state_path",
        os.path.join("%USERPROFILE%", "Documents", "DocuDog_Data", "state.json"),
    )
    report_path = paths.get(
        "report_path",
        os.path.join("%USERPROFILE%", "Documents", "DocuDog_Reports", "classification_report.md"),
    )
    state_path = os.path.normpath(os.path.expandvars(state_path))
    report_path = os.path.normpath(os.path.expandvars(report_path))

    _log_startup_environment_sanity(cfg, state_path, report_path)

    if args.file:
        inference.startup_model_probe(cfg)
        _run_single_file_cli(cfg, state_path, report_path, args.file)
        return

    run_lock_path = _ensure_single_instance_or_replace(cfg, state_path)
    obs = None
    try:
        state = load_state(state_path)

        def persist() -> None:
            save_state_atomic(state_path, state)

        idle_settings = cfg.get("idle_settings", {})
        idle_seconds = float(idle_settings.get("idle_trigger_seconds", 120))
        if idle_settings.get("skip_idle_wait_for_testing", False):
            idle_seconds = 0.0
            logger.debug(
                "skip_idle_wait_for_testing=true: idle threshold treated as 0s (testing)."
            )
        env_idle = os.environ.get("DOCUDOG_IDLE_TRIGGER_SECONDS")
        if env_idle is not None and str(env_idle).strip() != "":
            idle_seconds = float(env_idle)
            logger.debug(
                "Idle trigger overridden by DOCUDOG_IDLE_TRIGGER_SECONDS=%s", idle_seconds
            )

        apply_background_priority()

        inference.startup_model_probe(cfg)

        fs_event_buffer: list[tuple[str, float]] = []
        fs_buffer_lock = threading.Lock()
        _fs_buffer_cap = context_bundles.event_buffer_cap(cfg)

        def on_fs_event_seen(path: str, t: float) -> None:
            with fs_buffer_lock:
                context_bundles.record_fs_event(fs_event_buffer, path, t, _fs_buffer_cap)

        def fs_event_snapshot() -> list[tuple[str, float]]:
            with fs_buffer_lock:
                return list(fs_event_buffer)

        try:
            lineage.regenerate_if_enabled(cfg, state, report_path)
        except Exception:
            logger.exception("Lineage map initial write failed")

        file_queue: queue.Queue[tuple[str, float]] = queue.Queue()
        obs = watcher.start_observer(cfg, file_queue, on_seen=on_fs_event_seen)
        watcher.seed_queue_from_existing_files(cfg, file_queue, on_seen=on_fs_event_seen)

        ls = cfg.get("lineage_settings") or {}
        lineage_disp: str
        if ls.get("enabled", True):
            op = (ls.get("output_path") or "").strip()
            lineage_disp = (
                os.path.normpath(os.path.expandvars(op))
                if op
                else os.path.join(os.path.dirname(report_path), "DocuDog_lineage.md")
            )
        else:
            lineage_disp = "(disabled)"

        logger.info(
            "DocuDog engine started. Idle trigger=%ss run_once=%s. state=%s report=%s lineage=%s run_lock=%s",
            idle_seconds,
            run_once,
            state_path,
            report_path,
            lineage_disp,
            run_lock_path,
        )
        watch_roots = watcher.expand_watch_dirs(cfg)
        size_lim = cfg.get("file_filters", {}).get("size_limit", {})
        min_bytes = int(size_lim.get("min_bytes", 0))
        max_bytes = int(size_lim.get("max_bytes", 2**62))
        allowed = cfg.get("file_filters", {}).get("allowed_extensions", [])

        logger.debug(
            "Watching: %s | allowed ext: %s | size bytes: [%s, %s]",
            watch_roots,
            allowed,
            min_bytes,
            max_bytes,
        )
        if not any(os.path.isdir(r) for r in watch_roots):
            logger.warning(
                "No existing watch directory — create one or fix config target_directories."
            )

        queue_heartbeat_last = 0.0
        try:
            while True:
                watcher.sleep_while_busy(idle_seconds)
                # Drain while still idle; yield promptly if the user returns.
                while watcher.seconds_since_last_input() >= idle_seconds:
                    try:
                        next_path, file_event_unix = file_queue.get_nowait()
                    except queue.Empty:
                        if run_once:
                            logger.info(
                                "run_once: queue empty after idle wait; exiting without processing."
                            )
                            break
                        time.sleep(0.5)
                        now = time.monotonic()
                        if now - queue_heartbeat_last >= 30.0:
                            logger.debug(
                                "Queue empty; still watching. If report did not change, the same files "
                                "may already be in state (unchanged hash). Try editing/saving a file or "
                                "clear DocuDog_state.json. New files: save under %s (allowed ext, "
                                ">= %s bytes).",
                                watch_roots,
                                min_bytes,
                            )
                            queue_heartbeat_last = now
                        break

                    if watcher.seconds_since_last_input() < idle_seconds:
                        logger.info("User active before processing; re-queuing: %s", next_path)
                        file_queue.put((next_path, file_event_unix))
                        break

                    try:
                        outcome = router.process_file(
                            cfg,
                            state,
                            next_path,
                            report_path,
                            state_path,
                            idle_seconds,
                            watcher.seconds_since_last_input,
                            persist,
                            file_event_unix=file_event_unix,
                            get_fs_event_snapshot=fs_event_snapshot,
                        )
                        if outcome == "requeue":
                            file_queue.put((next_path, file_event_unix))
                            if run_once:
                                logger.info(
                                    "run_once: item requeued (user active); exiting."
                                )
                                break
                        else:
                            try:
                                lineage.regenerate_if_enabled(cfg, state, report_path)
                            except Exception:
                                logger.exception("Lineage map update failed")
                            if run_once:
                                logger.info(
                                    "run_once: processed one queue item (%s); exiting.",
                                    next_path,
                                )
                                break
                    except Exception:
                        logger.exception("Unexpected error while processing %s", next_path)
                        if run_once:
                            break
                if run_once:
                    break
        finally:
            if obs is not None:
                obs.stop()
                obs.join(timeout=5)
                logger.info("Observer stopped.")
                _flush_logs()
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
        _flush_logs()
    finally:
        logger.info("DocuDog exiting (cleanup, run lock will be released).")
        _flush_logs()
        _release_run_lock(run_lock_path)


if __name__ == "__main__":
    main()
