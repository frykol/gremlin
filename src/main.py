import os
import sys
import json
import signal
import errno
import asyncio
from asyncio import subprocess as asp
import builtins

from .config import load_config
from .dev_connection.ws_server import WsServer
from .websocket_config import build_bind_address


SIM_LOG = "sim.log"


def _is_broken_pipe_error(exc: Exception) -> bool:
    return isinstance(exc, BrokenPipeError) or (
        isinstance(exc, OSError) and getattr(exc, "errno", None) in {errno.EPIPE, errno.EINVAL}
    )


async def _write_instruction_to_child(pm_state, msg, stop_program_manager):
    proc = pm_state.get("proc")
    cmd_writer = pm_state.get("cmd_writer")

    if proc is None or cmd_writer is None:
        return False

    if proc.returncode is not None:
        print("Program manager has exited, cleaning up pipe")
        await stop_program_manager()
        return False

    try:
        cmd_writer.write(json.dumps(msg) + "\n")
        cmd_writer.flush()
    except Exception as e:
        if _is_broken_pipe_error(e):
            print(f"Child pipe is closed: {e}")
            await stop_program_manager()
            return False
        raise

    return True


async def _drain_stream_to_log(stream, log_file):
    while True:
        line = await stream.readline()
        if not line:
            break
        try:
            decoded = line.decode("utf-8", errors="replace")
        except Exception:
            try:
                decoded = str(line)
            except Exception:
                decoded = "\n"

        # Print to terminal using the original print (avoid recursion with patched print)
        try:
            if hasattr(builtins, "ORIGINAL_PRINT"):
                builtins.ORIGINAL_PRINT(decoded, end="")
            else:
                builtins.print(decoded, end="")
        except Exception:
            pass

        try:
            log_file.write(decoded)
            log_file.flush()
        except Exception:
            pass


async def _read_pipe_lines(fd, handler):
    # blocking fd read in thread
    f = os.fdopen(fd, "r", encoding="utf-8", buffering=1)
    try:
        while True:
            line = await asyncio.to_thread(f.readline)
            if not line:
                await asyncio.sleep(0.1)
                continue
            await handler(line.rstrip("\n"))
    finally:
        try:
            f.close()
        except Exception:
            pass


async def main():
    config = load_config("config.json")

    bind_host, bind_port = build_bind_address(config)

    instruction_tab = asyncio.Queue()
    ws = WsServer(bind_host, bind_port, instruction_tab)
    ws_task = asyncio.create_task(ws.connect())

    log_file = open(SIM_LOG, "a", buffering=1, encoding="utf-8")

    # Preserve original print and patch builtins.print to also write to sim.log
    builtins.ORIGINAL_PRINT = builtins.print

    def _patched_print(*args, **kwargs):
        try:
            builtins.ORIGINAL_PRINT(*args, **kwargs)
        except Exception:
            pass
        try:
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            s = sep.join(str(a) for a in args) + end
            log_file.write(s)
            log_file.flush()
        except Exception:
            pass

    builtins.print = _patched_print

    pm_state = {
        "proc": None,
        "cmd_writer": None,
        "tasks": [],
        "last_get_status": None,
    }

    async def send_ws_status(status: str, success: bool = True, message: str | None = None):
        payload = {
            "type": "program_status",
            "status": status,
            "success": success,
        }
        if message is not None:
            payload["message"] = message
        try:
            await ws.send(json.dumps(payload))
        except Exception as e:
            print(f"Failed to send status to websocket: {e}")

    async def handle_child_response(line: str):
        try:
            await ws.send(line)
        except Exception as e:
            print(f"Failed to send to websocket: {e}")

    async def program_is_running() -> bool:
        proc = pm_state["proc"]
        return proc is not None and proc.returncode is None

    async def start_program_manager() -> bool:
        if await program_is_running():
            print("Program manager is already running")
            return False

        cmd_read, cmd_write = os.pipe()
        resp_read, resp_write = os.pipe()

        env = os.environ.copy()
        env["USE_PIPE_WS"] = "1"
        env["PIPE_CMD_FD"] = str(cmd_read)
        env["PIPE_RESP_FD"] = str(resp_write)

        proc = await asp.create_subprocess_exec(
            sys.executable, "-m", "src.program_manager",
            stdout=asp.PIPE, stderr=asp.PIPE,
            pass_fds=(cmd_read, resp_write),
            env=env,
        )

        try:
            os.close(cmd_read)
        except Exception:
            pass
        try:
            os.close(resp_write)
        except Exception:
            pass

        cmd_writer = os.fdopen(cmd_write, "w", encoding="utf-8", buffering=1)

        tasks = []
        if proc.stdout:
            tasks.append(asyncio.create_task(_drain_stream_to_log(proc.stdout, log_file)))
        if proc.stderr:
            tasks.append(asyncio.create_task(_drain_stream_to_log(proc.stderr, log_file)))

        async def monitor_child_exit():
            try:
                await proc.wait()
            except Exception:
                return

            if pm_state.get("proc") is proc:
                print("Program manager exited unexpectedly, cleaning up pipe")
                try:
                    await stop_program_manager()
                except Exception as e:
                    print(f"Error while cleaning up child process: {e}")

        resp_task = asyncio.create_task(_read_pipe_lines(resp_read, handle_child_response))
        tasks.append(resp_task)
        tasks.append(asyncio.create_task(monitor_child_exit()))

        pm_state["proc"] = proc
        pm_state["cmd_writer"] = cmd_writer
        pm_state["tasks"] = tasks

        return True

    async def stop_program_manager() -> bool:
        if not await program_is_running():
            print("Program manager is not running")
            return False

        proc = pm_state["proc"]
        cmd_writer = pm_state["cmd_writer"]
        tasks = pm_state["tasks"]

        try:
            if cmd_writer is not None:
                cmd_writer.close()
        except Exception:
            pass

        try:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        except Exception as e:
            print(f"Error stopping program manager: {e}")

        for t in tasks:
            try:
                t.cancel()
            except Exception:
                pass

        pm_state["proc"] = None
        pm_state["cmd_writer"] = None
        pm_state["tasks"] = []

        return True

    async def handle_instruction(msg):
        if not isinstance(msg, dict):
            return

        # Server requests current program status (heartbeat/poll)
        if msg.get("type") == "get_program_status":
            # update last received time
            try:
                pm_state["last_get_status"] = asyncio.get_running_loop().time()
            except Exception:
                pm_state["last_get_status"] = None

            running = await program_is_running()
            status = "on" if running else "off"
            try:
                await ws.send(json.dumps({
                    "type": "get_program_status",
                    "status": status,
                }))
            except Exception as e:
                print(f"Failed to reply get_program_status: {e}")
            return

        if msg.get("type") == "set_program_status":
            status = str(msg.get("status", "")).lower()
            if status == "on":
                started = await start_program_manager()
                if started:
                    await send_ws_status("on", True, "Program manager started")
                else:
                    await send_ws_status("on", False, "Program manager already running")
            elif status == "off":
                stopped = await stop_program_manager()
                if stopped:
                    await send_ws_status("off", True, "Program manager stopped")
                else:
                    await send_ws_status("off", False, "Program manager is not running")
            else:
                await send_ws_status(status, False, "Unknown status value")
            return

        if await program_is_running():
            try:
                await _write_instruction_to_child(pm_state, msg, stop_program_manager)
            except Exception as e:
                print(f"Failed to write to child pipe: {e}")
        else:
            print("Program manager not running, ignoring instruction:", msg)

    async def process_instructions():
        while True:
            msg = await instruction_tab.get()
            try:
                await handle_instruction(msg)
            except Exception as e:
                print(f"Error handling instruction: {e}")

    async def monitor_heartbeat():
        check_interval = 0.5
        while True:
            try:
                await asyncio.sleep(check_interval)
                if not config.get("automatic_disconnect", True):
                    continue

                timeout = float(config.get("disconnect_timeout", 2))
                last = pm_state.get("last_get_status")
                if last is None:
                    continue

                if await program_is_running():
                    now = asyncio.get_running_loop().time()
                    if now - last > timeout:
                        print(f"No get_program_status from server for {now-last:.1f}s, auto-stopping program_manager")
                        try:
                            await stop_program_manager()
                            await send_ws_status("off", True, "Auto-disconnected due to missing heartbeat")
                        except Exception as e:
                            print(f"Error during auto-disconnect: {e}")
                        pm_state["last_get_status"] = None
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    tasks = [
        asyncio.create_task(process_instructions()),
        ws_task,
        asyncio.create_task(monitor_heartbeat()),
    ]

    shutdown_event = asyncio.Event()

    def _on_signal():
        print("Signal received, shutting down...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, _on_signal)
        loop.add_signal_handler(signal.SIGTERM, _on_signal)
    except NotImplementedError:
        pass

    try:
        await shutdown_event.wait()
    finally:
        await stop_program_manager()

        for t in tasks:
            try:
                t.cancel()
            except Exception:
                pass

        try:
            await ws.close()
        except Exception:
            pass

        try:
            log_file.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
