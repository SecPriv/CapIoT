from __future__ import annotations
import logging, time
from . import BaseRunner, register
from ..context import ExperimentContext, ExperimentError
from ..communication import android as phone
from ..communication import server
from ..utils.process_handler import ProcessHandle
from ..actions import iptables
from ..actions.user_interaction import  print_status_msg, prompt_user

logger = logging.getLogger("capiot.runner.android.lan")

@register(priority=0)
class AndroidLanRunner(BaseRunner):
    @classmethod
    def can_handle(cls, config) -> bool:
        return config.platform == "android" and config.network_profile == "lan"

    def run(self, ctx: ExperimentContext):
        """
        LAN (same-network) experiment:
          - enable BT
          - optional setup-phase recording
          - N no-frida iterations
          - N frida iterations
          - optional BT log pull & cleanup at end
        """
        overall_process = None
        try:
            print_status_msg("🔵 Enabling Bluetooth on phone…")
            phone.enable_bluetooth(ctx.phone_id)

            print_status_msg("🟢 Starting overall capture on server…")
            logger.info("Starting overall tcpdump on %s", ctx.config.server_interface)
            overall_pcap = ctx.experiment_path / f"overall-{ctx.device_name}.pcap"
            overall_process: ProcessHandle = server.start_tcpdump(ctx.config.server_interface, overall_pcap)


            if prompt_user("❓ Record setup phase of IoT device?"):
                _record_setup_phase(ctx)

            while not prompt_user("🧭 Enter y when you finish taking the coordinates."):
                logger.info("Waiting for user to finish taking coordinates...")


            print_status_msg("▶️  Starting NO-FRIDA phase…")
            _iteration_phase(ctx,use_frida=False)

            print_status_msg("▶️  Starting FRIDA phase…")
            _iteration_phase(ctx,use_frida=True)
        except Exception as ex:
            raise ExperimentError(ex)
        finally:
            print_status_msg("🛑 Stopping overall capture…")
            logger.info("Stopping overall tcpdump...")
            if overall_process:
                overall_process.kill_tree()
            clean_up(ctx)


def clean_up(ctx: ExperimentContext):
    try:
        print_status_msg("📥 Pulling Bluetooth log from phone…")
        logger.info("Pulling bluetooth log from phone...")
        phone.pull_bluetooth_log_to_server(ctx.phone_id, ctx.device_name, ctx.experiment_path, ctx.config.android.bluetooth_log_path)

        print_status_msg("🧹 Uninstalling app…")
        logger.info("Uninstalling app...")
        phone.uninstall_app(ctx.phone_id, ctx.package_name)

        print_status_msg("🔁 Rebooting phone…")
        logger.info("Rebooting phone...")
        phone.reboot(ctx.phone_id)

        summary = ctx.summarise_iterations()
        logging.info(summary)
        print_status_msg(f"📜 {summary}")
    except Exception as ex:
        raise ExperimentError(ex)

def _record_setup_phase(ctx: ExperimentContext) -> None:
    phone_id = ctx.phone_id
    pcapdroid_api_key = ctx.config.android.pcapdroid_api_key
    print_status_msg("📼 Recording setup phase…")
    logger.info("--- SETUP PHASE ---")
    target_dir = ctx.experiment_path.parent

    logger.info("SETUP: Starting server tcpdump")
    server_pcap = target_dir / f"setup-server-{ctx.device_name}.pcap"
    server_process = server.start_tcpdump(ctx.config.server_interface, server_pcap)

    logger.info("SETUP: Starting PCAPDroid")
    phone_pcap_name = f"setup-phone-{ctx.device_name}.pcap"
    phone.start_pcapdroid(phone_id, ctx.package_name, phone_pcap_name, ctx.config.phone_interface, pcapdroid_api_key)

    while not prompt_user("📼 Enter 'y' when setup is finished"):
        print_status_msg("⏳ Waiting for setup to finish…")

    logger.info("SETUP: Stopping server tcpdump")
    server_process.kill_tree()
    logger.info("SETUP: Stopping PCAPDroid")
    phone.stop_pcapdroid(phone_id, pcapdroid_api_key)

    logger.info("SETUP: Pulling pcap from phone")
    phone_pcap_path = ctx.config.android.pcap_download_path/phone_pcap_name
    destination_path = target_dir / phone_pcap_name
    phone.pull_file_to_server(phone_id, phone_pcap_path, destination_path)
    logger.info("SETUP: Deleting pcap from phone")
    phone.delete_file_from_phone(phone_id, phone_pcap_path)
    logger.info("SETUP: Complete")
    print_status_msg(f"✅ Setup phase captured. Saved to {target_dir}")


def _iteration_phase(ctx: ExperimentContext, use_frida: bool) -> None:
    phone_id = ctx.phone_id
    package_name = ctx.package_name
    pcapdroid_api_key = ctx.config.android.pcapdroid_api_key
    phone_pcap_name = None

    num_iterations = ctx.config.frida_iterations if use_frida else ctx.config.no_frida_iterations
    phase_name = "frida" if use_frida else "no_frida"
    logger.info("--- %s phase: %d iterations---", phase_name.upper(), num_iterations)
    print_status_msg(f"➡️  {phase_name.upper()} phase: {num_iterations} iterations")

    target_dir = ctx.experiment_path / phase_name
    target_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, num_iterations + 1):
        print_status_msg(f"  • {phase_name} iteration {i}/{num_iterations}…")
        logger.info("--- %s ITERATION %02d ---", phase_name.upper(), i)

        server_process = mitm_process = frida_process = None
        success = True
        try:
            if use_frida:
                logger.info("%s %02d: Applying iptables rules", phase_name.upper(), i)
                iptables.apply_rules(ctx.config.iptables_script_up_path)

            logger.info("%s %02d: Starting server tcpdump", phase_name.upper(), i)
            server_pcap = target_dir / f"iteration-{i}-{phase_name}-server-{ctx.device_name}.pcap"
            server_process = server.start_tcpdump(ctx.config.server_interface, server_pcap)

            logger.info("%s %02d: Starting PCAPdroid", phase_name.upper(), i)
            phone_pcap_name = f"iteration-{i}-{phase_name}-phone-{ctx.device_name}.pcap"
            phone.start_pcapdroid(phone_id, package_name, phone_pcap_name, ctx.config.phone_interface, pcapdroid_api_key)

            print_status_msg("    · Starting app…")
            if use_frida:
                log_folder = ctx.experiment_path / "logs"

                logger.info("%s %02d: Starting mitmdump", phase_name.upper(), i)
                mitm_dump_path = ctx.experiment_path / f"mitm/iteration-{i}-mitmdump-{ctx.device_name}"
                sslkey_logile = ctx.experiment_path / f"sslkeys/iteration-{i}-sslkeys-{ctx.device_name}.txt"
                mitm_process = server.start_mitmdump(
                    outfile=mitm_dump_path,
                    sslkey_logfile=sslkey_logile,
                    log_folder=log_folder,
                )

                logger.info("%s %02d: Starting frida", phase_name.upper(), i)
                frida_process = server.start_frida(phone_id, package_name, log_folder)
            else:
                logger.info("%s %02d: Starting app", phase_name.upper(), i)
                phone.start_app(phone_id, package_name)

            sleep_time = ctx.sleep_times.get("start_app", 15)
            time.sleep(sleep_time)

            print_status_msg("    · Triggering taps on phone…")
            logger.info("%s %02d: Triggering taps on phone", phase_name.upper(), i)
            success = phone.trigger_taps_on_phone(ctx, i, use_frida)
            msg = "    · ✅ Taps OK" if success else "    · ❌ Taps had mismatches - see logs/screenshots"
            print_status_msg(msg)

            sleep_time = ctx.sleep_times.get("between_iterations", 300)
            print_status_msg(f"    · Sleeping for {int(sleep_time)} seconds…")
            logger.info("%s %02d: Sleeping for %ds", phase_name.upper(), i, sleep_time)
            time.sleep(sleep_time)
        except Exception as ex:
            success = False
            logger.error("%s %02d failed: %s", phase_name.upper(), i, ex, exc_info=True)
        finally:
            logger.info("%s %02d: Stopping PCAPdroid", phase_name.upper(), i)
            phone.stop_pcapdroid(phone_id, pcapdroid_api_key)

            logger.info("%s %02d: Stopping server tcpdump ", phase_name.upper(), i)
            server_process.kill_tree()

            if mitm_process:
                logger.info("%s %02d: Stopping mitm ", phase_name.upper(), i)
                mitm_process.kill_tree()
            if frida_process:
                logger.info("%s %02d: Stopping frida ", phase_name.upper(), i)
                frida_process.kill_tree()

            logger.info("%s %02d: Pulling pcap to server", phase_name.upper(), i)
            phone_pcap_path = ctx.config.android.pcap_download_path / phone_pcap_name
            destination_path = target_dir / phone_pcap_name
            phone.pull_file_to_server(phone_id, phone_pcap_path, destination_path)
            logger.info("%s %02d: Deleting pcap from phone ", phase_name.upper(), i)
            phone.delete_file_from_phone(phone_id, phone_pcap_path)

            if use_frida:
                logger.info("%s %02d: Deleting iptables rules", phase_name.upper(), i)
                iptables.apply_rules(ctx.config.iptables_script_down_path)

            print_status_msg("    · Stopping app…")
            logger.info("%s %02d: Stopping app", phase_name.upper(), i)
            phone.stop_app(phone_id, package_name)
            sleep_time = ctx.sleep_times.get("stop_app", 15)
            time.sleep(sleep_time)
            ctx.record_iteration_result(phase_name, i, success)

    logger.info("--- %s phase complete ---", phase_name.upper())



