# CapIoT

CapIoT is a command-line tool to **automate IoT experiments on Android & iOS apps** and **capture their network traffic**. It’s built for security engineers and researchers who want **repeatable, scripted interactions** on LAN and WAN setups and **complete traffic traces**—with optional TLS interception and frida hooks.

## Table of Contents
- [What Can I Use It For?](#what-can-i-use-it-for)
- [Key Features](#key-features)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
  - [Image Crop Regions](#image-crop-regions)
  - [Sleep Timings](#sleep-timings)
- [Commands](#commands)
- [Platform Notes](#platform-notes)
  - [iOS vs Android](#ios-vs-android)
- [Extending CapIoT](#extending-capiot)

## What Can I Use It For?

**Example scenario — App ↔ IoT device analysis (same LAN):**  
You want to understand how the *IoT* mobile app communicates with your smart plug on your home network.

With CapIoT you can:
- automatically **launch the app**, **tap** through actions like “Power On/Off,”
- **capture traffic on the server** (`tcpdump` on wifi interface) and **on the phone** (PCAPdroid/iOS tcpdump),
- Run experiments where the app and device are on the same network (LAN) and the device and phone are on different networks (WAN)
- **proxy** traffic via **mitmproxy** and **export SSL keys**,
- **bypass** certificate pinning via **frida**,
- **repeat** the same steps multiple times (no-frida / frida phases) to compare behavior,
- validate UI changes with **screenshots** and **similarity checks**.

### A typical experiment flow

1. **Setup** (optional): record a brief setup phase (e.g., device onboarding) with captures running.  
2. **Record** coordinates.
2. **No-Frida phase**:  
   - start server capture (tcpdump)  
   - start phone capture (PCAPdroid / tcpdump on iOS)  
   - launch app → run scripted `tap X Y` interactions  
   - take screenshots and **compare vs. baselines (SSIM)**  
   - keep capturing for a **post-interaction window** to include all related traffic  
3. **Frida phase**:  
   - run `mitmdump` (transparent mode) and **SSL key log**  
   - start `frida` hooks (e.g., TLS unpinning)  
   - repeat interactions & captures  
4. **Tear-down**: stop captures, copy artifacts, summarize iterations.

---

## Key Features

- 🚀 One command to run full experiments (per-run artifact folders)
- 🌐 LAN & WAN profiles: capture on the same network or different networks.
- 🔍 TLS introspection – MITM, SSL key log export, frida hooks.
- 📸 UI automation (`tap X Y`) + **screenshot similarity (SSIM)**
- 🧰 Utilities:
  - `check-config`
  - `dump-app`
  - `record-coordinates`
- 🧩 Extensible: add your own runner via `@register(priority=N)`
- 🗂️ Clear folder structure per run (`frida/`, `no_frida/`, `mitm/`, `sslkeys/`, `logs/`)

---

## Getting Started
```bash
# Clone repository
git clone https://github.com/SecPriv/CapIoT.git
cd capiot

# Create & activate virtual environment (choose one or both)
python3 -m venv .android   # or: python3 -m venv .ios
source .android/bin/activate  # or. source .ios/bin/activate

# Install dependencies for your platform
pip install -U pip 
pip install '.[android]'   # or: pip install '.[ios]'
```
Follow **[SETUP.md](SETUP.md)** for server and device prerequisites.


Get device identifiers:

```bash
adb devices        # Android: ADB device id
idevice_id -l      # iOS: UDID
```

---

## Configuration

CapIoT reads a YAML file describing platform, profile, and paths.

A template is provided in **`config/config.yaml`**. Check out also some example configuration files in **`config/examples`**.

### Image Crop Regions 
To **reduce false positives from dynamic UI elements** (e.g., the clock, notifications, rotating banners), we crop the screenshot to a **region of interest** and compute similarity **only within that region**.

Example:
```json
{
  "iot_device_name": [
    {"x": 258, "y": 2142, "width": 123, "height": 114},
    {"x": 258, "y": 2142, "width": 123, "height": 114}
  ]
}

```
### Sleep Timings
You can provide custom delays between certain actions. Simply add the path to your config file (see `config.yaml`). 
The file is hot-reloaded, so any tweaks to those sleep times take effect immediately while experiments are running.
Example:
```yaml
start_app: 15          # wait after launching the app
stop_app: 10           # wait after stopping the app
after_tap: 2           # delay after each tap before screenshot
after_similarity: 9    # delay after screenshot comparison
between_iterations: 300  # keep capturing after UI action to include all related traffic
```

---

## Commands

| Command | Purpose |
|---------|---------|
| `capiot check-config` | Validate a YAML config |
| `capiot record-coordinates` | Capture baseline screenshots & tap points |
| `capiot run` | Execute the full experiment pipeline |
| `capiot dump-app` | Pull APK/IPA & permissions for static analysis |

### Validate a config

```bash
capiot check-config --config /path/to/config.yaml
```

### Record tap coordinates

```bash
capiot record-coordinates --platform <android or ios>  --phone-id <ADB_ID or UDID>   --package-name com.example.app --device-name iot_device_name --output /data/coords
```

Artefacts are written to `/data/coords/iot_device_name`:
- Text file: `<data/coords/iot_device_name>/<iot_device_name>.txt`.  
    Each actionable line must be **exactly**:
    ```
    tap X Y
    ```
- Baseline screenshots 

#### iOS Manual Coordinate Recording

On iOS, the coordinate recorder cannot automatically capture taps due to iOS limitations. Instead:
1. Run `record-coordinates` to capture screenshots.  
2. Open each screenshot in **GIMP**.  
3. Click the target and note pixel coordinates. 
4. Add `tap x y` lines to coordinates file (i.e., `<data/coords/iot_device_name>/<iot_device_name>.txt`).


### Run an experiment

```bash
capiot run -p com.example.app -i <ADB_ID or UDID> -d iot_device_name --config /path/to/config.yaml
```

Artifacts are written to:

```
<output_path>/<device_name>/<YYYY-MM-DD_HH-MM>/
  frida/
  no_frida/
  mitm/
  sslkeys/
  logs/
```

### Dump an app

```bash
# Android
capiot dump-app -f android -p com.example.app -i <ADB_ID> -o ./apk

# iOS
capiot dump-app -f ios -p com.example.app -i <UDID> --ssh-host 192.168.1.13 --ssh-port 22 --ssh-user mobile -o ./ipa
```

Results:
- Android → `./apk/com.example.app/` (`*.apk`, optionally `permissions.txt`)  
- iOS → `./ipa/com.example.app_dump.ipa` + `permissions/com.example.app_Info.plist`

---

## Platform Notes

### iOS vs Android
- No Bluetooth log collection due to iOS limitations.
- iOS has no PCAPdroid-like tool for per-app captures, so CapIoT relies on the system’s App Privacy Report to list the domains each app contacts; to preserve that report, the app is left installed after the experiment.
- No device reboot after full experiment (breaks `palera1n` jailbreak). 
- **Coordinates must be recorded manually** (see the GIMP workflow above).

---

## Extending CapIoT
You can define your own experiment workflow by creating your own runner. At launch, the framework evaluates every registered runner and picks the one with the highest priority whose can_handle() method returns True for the loaded configuration.
### How to create a runner
1. **Subclass `BaseRunner`**. 
2. **Decorate with `@register(priority=N)`**. A higher priority value wins when multiple runners match.
3. **Implement two methods:**
   - `@classmethod can_handle(cls, cfg)` – return `True` if this runner should execute for the given config. 
   - `def run(self, ctx)` – perform all experiment steps.
4. **Add custom keys** to your `config.yaml` if needed — they are passed through unchanged.

**Example**
```python
from runners import BaseRunner, register

@register(priority=0)
class CustomRunner(BaseRunner):
    @classmethod
    def can_handle(cls, config) -> bool:
        return getattr(config, "custom_key", False) is True

    def run(self, ctx):
        # your workflow here
        ...
```

---


Happy capturing! 🚀





