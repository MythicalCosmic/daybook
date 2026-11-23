# Ko‘z box: the agent (`koz-agent`)

The Ko‘z agent runs on a PC at the pharmacy (Windows 10/11 or Linux, x86-64). It reads the
cameras, finds people with a small detector (YOLOX-tiny on the CPU), and sends Daybook only
numbers, alerts and, when asked, pictures and short clips. The contract with Daybook is
[`docs/KOZ.md`](../../docs/KOZ.md); this folder is its own Python project.

## Setting up a pharmacy PC

1. **Install uv** (it brings its own Python):
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Get the agent** (this `edge/koz` folder) onto the PC and install it:

   ```
   cd edge/koz
   uv sync
   ```

   This installs NumPy, OpenCV (headless), ONNX Runtime, httpx and imageio-ffmpeg (which ships
   the `ffmpeg` binary). Nothing else.
3. **Check the PC**: `uv run koz-agent selftest`. The first run downloads the YOLOX-tiny model
   (20 MB, Apache-2.0) from Megvii's official release, checks its SHA-256 and prints how long one
   picture takes (about 33 ms on an i5-13420H). It also says which H.264 encoder this PC has and
   whether Daybook is reachable.
4. **Pair the box**: in Daybook open **Ko‘z → Cameras and boxes → Add a box**, choose the
   branch, and run the command it shows within 15 minutes:

   ```
   uv run koz-agent pair https://daybook.example KOZ-7F3K-92QD
   ```
5. **The NVR's login** (Hikvision): `uv run koz-agent nvr set 192.168.0.250`. The agent asks for
   the user and password (the password is not shown) and tries them **once**. A wrong login stops
   at once with "wrong NVR login" and nothing is saved: Hikvision locks an account after a few
   failed logins, so check the password before trying again. `--time` says how the NVR reads
   playback times: `auto` (its own zone, read from the NVR), `utc`, or an offset like `+05:00`.
6. **See the cameras**: `uv run koz-agent sources` lists the NVR channels (`nvr:3` is channel 3),
   other streams and the generated scene. A stream that is not on the NVR:
   `uv run koz-agent sources add rtsp kassa-2 rtsp://user:pass@192.168.0.64/stream2`.
7. **Run it**: `uv run koz-agent run`. The local status page is on
   <http://127.0.0.1:8737> (this PC only). Then, in Daybook, give each camera its role, draw its
   zones and switch it on: the agent analyses only enabled cameras, but sends a snapshot of every
   camera so they can be set up.

The first build has no installer or Windows service (§11). To start it with the PC, use Task
Scheduler (a task "At log on" running `uv run koz-agent run` in this folder) on Windows, or a
systemd user unit on Linux (`ExecStart=/home/<user>/.local/bin/uv run --directory
/opt/koz koz-agent run`, `Restart=always`).

### The commands

| Command | What it does |
|---|---|
| `koz-agent pair <url> <code>` | Pairs the PC with Daybook once and keeps the token locally. |
| `koz-agent nvr set <host>` | Asks for the NVR's user and password, checks them once, keeps them. `nvr list`, `nvr remove <host>`. |
| `koz-agent sources` | NVR channels, RTSP and file sources, the scenes. `--refresh` asks the NVR again; `--suggest-zones` prints zones that fit the scene; `add` / `remove`. |
| `koz-agent run` | The service, with the status page on :8737. `--scene demo` uses the generated scene instead of cameras. |
| `koz-agent selftest` | Model, inference time, encoder, server reachability. |
| `koz-agent devserver` | A fake Daybook (device API only) for trying a box without the backend. |

## Privacy (contract §8)

- **No face recognition.** The detector finds the shape of a person, nothing more; nobody is
  identified, and nothing is compared between days or cameras.
- **Video stays at the pharmacy.** What leaves the PC: live frames only while someone watches the
  camera in Daybook (Daybook keeps them 10 s and never stores them), the alert photo of an
  incident, snapshots for setting up the cameras, and the clips someone asked for.
- **Masks** black out their area in everything the agent sends (snapshots, live frames, alert
  photos, recordings, so clips from the recorder too) and people inside them are ignored. Clips
  fetched from the NVR's own recording are not masked. With **privacy_blur**, heads are blurred
  on alert photos.
- **Passwords never leave the PC and are never logged.** The Daybook token and the camera and
  NVR passwords are kept with Windows DPAPI (only this Windows user on this PC can read them) or
  in a file with mode 600 on Linux. Addresses in the logs are masked (`rtsp://***@host…`).
- The local status page answers only on `127.0.0.1` and refuses requests for any other host name.

## How it keeps the PC cool

- One inference budget for all cameras: at most 6 a second in all (`max_inferences_per_s`), and
  each enabled camera at most `analysis_fps` (2 by default), taking turns. ONNX Runtime uses 2
  threads.
- Streams are read from the NVR's **sub-stream** (`…/Channels/<ch>02`); every packet is decoded,
  but pictures are converted only as often as they are needed.
- The recorder keeps only `counter` cameras (when `record_counter` is on), in H.264 segments of
  up to 60 s with a keyframe every second, for `record_hours`. The encoder is probed in this order:
  `h264_mf` (Windows Media Foundation, often hardware), `libopenh264`, `libx264`. This build of
  ffmpeg has `h264_mf` and `libx264` on Windows.

While Daybook is unreachable, minute stats and alerts wait on disk (SQLite, up to 7 days) and go
out in order when it is back. A revoked token makes the agent try once every 10 minutes.

## The generated scene

`koz-agent run --scene demo` needs no cameras: it draws a pharmacy seen by two ceiling cameras,
`sim:counter` (the counter, role `counter`) and `sim:door` (the entrance, role `entrance`), at
960×540, and uses the scene's exact boxes as detections. Customers come in through the sliding
door, queue at the two tills, are served (the pharmacist fetches the medicine from the shelves)
and leave with a paper bag, or without one if they waited too long.

| Scene | What happens |
|---|---|
| `calm` | Two pharmacists, a steady trickle; the queue stays at 0–2. |
| `rush` | A wave while one pharmacist is alone: the queue grows to 5–6, the second opens Kassa 2, it clears. |
| `break` | The only pharmacist steps away for 2.5 minutes while customers wait. |
| `demo` | calm → rush → break every 8 minutes: a queue alert around 3:00, nobody at the counter from 5:20 (an alert at about 6:50), back at 7:30. |

- `--at 150` starts 150 s into the loop (the rush); `--seed 3` brings other people; the same
  scene and seed always give the same pictures.
- Without pairing the agent uses the scene's own zones (`koz-agent sources --suggest-zones`
  prints them) and shows everything on the status page; `?tv=1` is the full-screen TV view.
- To try the whole flow with a fake Daybook, in two terminals:

  ```
  uv run koz-agent devserver --auto-setup          # prints a pairing command
  uv run koz-agent pair http://127.0.0.1:8780 KOZ-…
  uv run koz-agent run --scene demo
  ```

  Set `KOZ_HOME` to a spare folder to keep such a trial apart from the real box.

## Where things are

`%LOCALAPPDATA%\Daybook\Koz` on Windows, `~/.local/share/daybook-koz` on Linux (`KOZ_HOME`
overrides it): `agent.json` (settings, no secrets), `secrets.dpapi` / `secrets.json`,
`config.json` (the last config from Daybook, so the box keeps working offline after a restart),
`outbox.sqlite3`, `models/`, `recordings/`, `logs/agent.log`.

## Development

```
cd edge/koz
uv sync
uv run pytest
```

The tests cover geometry, the tracker, line crossings, waits, the incident hysteresis, minute
stats, the client (with `httpx.MockTransport`) and its offline queue, the YOLOX decode on
synthetic tensors, the scene, NVR URLs and XML, the recorder's maths with a real encode, the
status page, and an end-to-end run: both sim cameras on the demo scene against a fake Daybook for
10 minutes of scene time (on a fake clock, in about 10 s). Tests that need the encoder or the
downloaded model skip themselves when those are missing. No test opens a webcam or contacts a
device.

The side of an entrance line (§4) is named as people see the picture: walking from A to B, `left`
is your left hand. Image y grows downwards, so `left` is where (B − A) × (P − A) < 0; for a line
drawn left to right, `left` is the side above it. The dashboard's zone editor draws the same arrow.
