from __future__ import annotations
import logging, time
from . import BaseRunner, register
from ..context import ExperimentContext, ExperimentError
from ..communication import ios as phone
from ..communication import server
from ..communication import ssh
from ..actions import iptables
from ..actions.user_interaction import  print_status_msg, prompt_user

logger = logging.getLogger("capiot.runner.ios.wan")

@register(priority=0)
class iOSWanRunner(BaseRunner):
    @classmethod
    def can_handle(cls, config) -> bool:
        return config.platform == "ios" and config.network_profile == "wan"

    def run(self, ctx: ExperimentContext):
        """
        WAN (different-network) experiment:
          - N no-frida iterations
          - N frida iterations
        """
        overall_process = None
        try:
            print_status_msg("❗ Don't forget to turn off bluetooth")
            print_status_msg("❗ Don't forget to turn on App Privacy Report in iOS Settings")
            print_status_msg("🟢 Starting overall capture on server…")
            logger.info("Starting overall tcpdump on %s", ctx.config.server_interface)
            overall_pcap = ctx.experiment_path / f"overall-{ctx.device_name}.pcap"
            overall_process = server.start_tcpdump(ctx.config.server_interface, overall_pcap)

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
            summary = ctx.summarise_iterations()
            logging.info(summary)
            print_status_msg(f"📜 {summary}")
            print_status_msg("❗ Don't forget to collect contacted domains in App Privacy Report")


def _iteration_phase(ctx: ExperimentContext, use_frida: bool) -> None:
    udid = ctx.phone_id
    package_name = ctx.package_name
    phone_pcap_name = None
    phone_tcpdump_pid = None

    num_iterations = ctx.config.frida_iterations if use_frida else ctx.config.no_frida_iterations
    phase_name = "frida" if use_frida else "no_frida"
    logger.info("--- %s phase: %d iterations---", phase_name.upper(), num_iterations)
    print_status_msg(f"➡️  {phase_name.upper()} phase: {num_iterations} iterations")

    target_dir = ctx.experiment_path / phase_name
    target_dir.mkdir(parents=True, exist_ok=True)
    log_folder = ctx.experiment_path / "logs"

    ssh.create_folder(ctx.config.ios.ssh, str(ctx.config.ios.phone_pcap_save_path))

    for i in range(1, num_iterations + 1):
        print_status_msg(f"  • {phase_name} iteration {i}/{num_iterations}…")
        logger.info("--- %s ITERATION %02d ---", phase_name.upper(), i)

        server_process = mitm_process = frida_process = remote_pid = remote_tcpdump_filename = remote_pcap_name = None
        success = True
        try:
            if use_frida:
                logger.info("%s %02d: Applying iptables rules", phase_name.upper(), i)
                iptables.apply_rules(ctx.config.iptables_script_up_path)

            logger.info("%s %02d: Starting server tcpdump", phase_name.upper(), i)
            server_pcap = target_dir / f"iteration-{i}-{phase_name}-server-{ctx.device_name}.pcap"
            server_process = server.start_tcpdump(ctx.config.server_interface, server_pcap)

            logger.info("%s %02d: Starting phone tcpdump", phase_name.upper(), i)
            phone_pcap_name = f"iteration-{i}-{phase_name}-phone-{ctx.device_name}.pcap"
            phone_pcap_path = ctx.config.ios.phone_pcap_save_path / phone_pcap_name
            phone_tcpdump_pid = ssh.start_remote_tcpdump(ctx.config.ios.ssh, ctx.config.phone_interface, phone_pcap_path)

            logger.info("%s %02d: Starting remote server tcpdump", phase_name.upper(), i)
            remote_pcap_name = f"iteration-{i}-{phase_name}-remote-{ctx.device_name}.pcap"
            remote_tcpdump_filename = f"/tmp/{remote_pcap_name}"
            remote_pid = ssh.start_remote_tcpdump(ctx.config.remote_server_ssh, ctx.config.remote_server_interface,
                                                  remote_tcpdump_filename)


            print_status_msg("    · Starting app…")
            if use_frida:
                logger.info("%s %02d: Starting mitmdump", phase_name.upper(), i)
                mitm_dump_path = ctx.experiment_path / f"mitm/iteration-{i}-mitmdump-{ctx.device_name}"
                sslkey_logile = ctx.experiment_path / f"sslkeys/iteration-{i}-sslkeys-{ctx.device_name}.txt"
                mitm_process = server.start_mitmdump(
                    outfile=mitm_dump_path,
                    sslkey_logfile=sslkey_logile,
                    log_folder=log_folder,
                    port=8082
                )

            logger.info("%s %02d: Starting app", phase_name.upper(), i)
            phone.start_app(udid, package_name)

            sleep_time = ctx.sleep_times.get("start_app", 15)
            time.sleep(sleep_time)

            if use_frida:
                logger.info("%s %02d: Starting objection", phase_name.upper(), i)
                frida_process = server.start_objection(udid, package_name, log_folder)

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
            logger.info("%s %02d: Stopping remote server tcpdump ", phase_name.upper(), i)
            ssh.stop_remote_tcpdump(ctx.config.remote_server_ssh, remote_pid)

            logger.info("%s %02d: Stopping phone tcpdump", phase_name.upper(), i)
            phone.stop_tcpdump(ctx.config.ios.ssh, phone_tcpdump_pid)

            logger.info("%s %02d: Stopping server tcpdump ", phase_name.upper(), i)
            server_process.kill_tree()

            if mitm_process:
                logger.info("%s %02d: Stopping mitm ", phase_name.upper(), i)
                mitm_process.kill_tree()
            if frida_process:
                logger.info("%s %02d: Stopping frida ", phase_name.upper(), i)
                frida_process.kill_tree()

            logger.info("%s %02d: Pulling pcap to server", phase_name.upper(), i)
            local_path = target_dir / phone_pcap_name
            phone_pcap_path = ctx.config.ios.phone_pcap_save_path / phone_pcap_name
            ssh.download_remote_file(ctx.config.ios.ssh, phone_pcap_path, str(local_path))

            logger.info("%s %02d: Downloading remote tcpdump ", phase_name.upper(), i)
            local_path = target_dir / remote_pcap_name
            ssh.download_remote_file(ctx.config.remote_server_ssh, remote_tcpdump_filename, str(local_path))


            if use_frida:
                server.reset_terminal()
                logger.info("%s %02d: Deleting iptables rules", phase_name.upper(), i)
                iptables.apply_rules(ctx.config.iptables_script_down_path)

            print_status_msg("    · Stopping app…")
            logger.info("%s %02d: Stopping app", phase_name.upper(), i)
            phone.stop_app()
            sleep_time = ctx.sleep_times.get("stop_app", 15)
            time.sleep(sleep_time)
            ctx.record_iteration_result(phase_name, i, success)

    logger.info("--- %s phase complete ---", phase_name.upper())



