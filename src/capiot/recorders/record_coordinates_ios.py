import logging
from ..communication import ios as phone
from pathlib import Path
import time, sys
from ..actions.user_interaction import print_status_msg, prompt_user

logger = logging.getLogger("capiot.recorders.coordinates.ios")

def record_coordinates_ios(
    phone_id: str,
    package_name: str,
    device_name: str,
    output_path: str
) -> None:
    output_path = Path(output_path) / device_name
    output_path.mkdir(parents=True, exist_ok=True)

    taps_coordinates_file = output_path / f"{device_name}.txt"
    taps_coordinates_file.touch(exist_ok=True)
    print_status_msg(
        "\n"
        "iOS Screenshot Recorder\n"
        "-----------------------\n"
        f"UDID      : {phone_id}\n"
        f"IoT Device: {device_name}\n"
        f"App       : {package_name}\n"
        f"Saving to : {output_path}\n\n"
        "Instructions   : \n"
        "  • Drive the app to the state you want.\n"
        "  • When prompted, confirm to capture a screenshot.\n"
        "  • Repeat as needed; press CTRL+C to stop.\n"
        "Notes:\n"
        "  • Screenshots are saved as baseline_tap-<N>.png\n"
        f" • An empty coordinates file is created: {taps_coordinates_file.name}\n"
    )
    print_status_msg(f"Launching {package_name} on {phone_id}")
    phone.start_app(phone_id, package_name)
    x = y = None
    screenshot_index = 1

    try:
        while True:
            while prompt_user("Take screenshot?"):
                baseline_image_path = output_path / f"baseline_tap-{screenshot_index}.png"
                phone.take_screenshot(baseline_image_path)
                print_status_msg(f"Please wait, saving screenshot...")
                screenshot_index += 1
                time.sleep(2)
                print_status_msg(f"Screenshot saved: {baseline_image_path}")
    except KeyboardInterrupt:
        print_status_msg("\nStopping screenshot capture.")
        print_status_msg(f"Don't forget to extract coordinates from screenshots and save it to {taps_coordinates_file}.")
        sys.exit(0)