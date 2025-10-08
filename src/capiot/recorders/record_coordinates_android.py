import logging
from ..communication import android as phone
from pathlib import Path
import time
from ..actions.user_interaction import print_status_msg

logger = logging.getLogger("capiot.recorders.coordinates.android")

def record_coordinates_android(
    phone_id: str,
    package_name: str,
    device_name: str,
    output_path: str
) -> None:
    output_path = Path(output_path) / device_name
    output_path.mkdir(parents=True, exist_ok=True)
    taps_coordinates_file = output_path / f"{device_name}.txt"
    print_status_msg(
        "\n"
        "Android Screenshot Recorder\n"
        "-----------------------\n"
        f"UDID      : {phone_id}\n"
        f"IoT Device: {device_name}\n"
        f"App       : {package_name}\n"
        f"Saving to : {output_path}\n\n"
        "How it works:\n"
        "  • Listens to touch events on the device.\n"
        "  • On each completed tap, it appends 'tap <x> <y>' to the coordinates file\n"
        "    and captures a screenshot named baseline_tap-<N>.png.\n"
        "Instructions:\n"
        "  • Use the app as normal; taps are recorded automatically.\n"
        "  • Press CTRL+C to stop at any time.\n"
        "Notes:\n"
        "  • Screenshots are saved as baseline_tap-<N>.png\n"
        f"  • A coordinates file is created: {taps_coordinates_file.name}\n"
    )
    print_status_msg(f"Launching {package_name} on {phone_id}")
    phone.start_app(phone_id, package_name)

    x = y = None
    touch = False
    screenshot_index = 1

    process = phone.capture_taps_live(phone_id)
    print_status_msg("Recording taps… press Ctrl-C to stop.")
    try:
        with taps_coordinates_file.open("w") as out:
            for line in process.stdout:
                line = line.strip()
                if "BTN_TOUCH" in line:
                    touch = True
                if touch:
                    if "ABS_MT_POSITION_X" in line:
                        x = int(line.strip().split(" ")[-1], 16)
                    elif "ABS_MT_POSITION_Y" in line:
                        y = int(line.strip().split(" ")[-1], 16)
                        if x is not None and y is not None:
                            out.write(f"tap {x} {y}\n")
                            out.flush()
                            print_status_msg(f"Tap: ({x}, {y})")
                            print_status_msg(f"Please wait, saving screenshot...")
                            time.sleep(2)

                            baseline_image_path = output_path / f"baseline_tap-{screenshot_index}.png"
                            phone.take_screenshot(phone_id, baseline_image_path)
                            screenshot_index += 1
                            time.sleep(2)
                            print_status_msg(f"Screenshot saved: {baseline_image_path}")

                            touch = False
    except KeyboardInterrupt:
        print_status_msg("Stopping coordinate recording (Ctrl-C).")
    finally:
        process.terminate()

    print_status_msg(f"Captured taps saved to {output_path}")