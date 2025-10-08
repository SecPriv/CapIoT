import typer
from pathlib import Path
from . import __version__
from .config import load_config, AppConfig, ConfigLoadError, SshConnectionConfig
from .context import ExperimentContext, ExperimentError
from .runners import android_lan, android_wan, ios_wan, ios_lan # needed for runner registration
from .runners import dispatch, RunnerNotFoundError, RunnerAmbiguousError
from .recorders.record_coordinates_android import record_coordinates_android
from .recorders.record_coordinates_ios import record_coordinates_ios
from .dumpers.android_dump import dump_android_apks, AndroidDumpError
from .dumpers.ios_dump import dump_ios_ipa, IOSDumpError

import logging, sys, time
from typing import Optional
from logging.handlers import RotatingFileHandler

logger = logging.getLogger("capiot.cli")

def banner():
        font = r"""
#--------------------------------#
|   ____           ___    _____  |
|  / ___|__ _ _ __|_ _|__|_   _| |
| | |   / _` | '_ \| |/ _ \| |   |
| | |__| (_| | |_) | | (_) | |   |
|  \____\__,_| .__/___\___/|_|   |
|            |_|                 |
#--------------------------------# """
        typer.echo(font)

def setup_logging(debug_file: bool = False, log_file: Path | None = None) -> None:
    """
    Console: WARNING+ only.
    File (if provided): INFO by default; DEBUG if debug_file=True.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(log_file), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.DEBUG if debug_file else logging.INFO)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(fh)

app = typer.Typer(help="CapIoT - Capture IoT traffic and automate experiments.", no_args_is_help=True)

@app.callback(invoke_without_command=True)
def main(version: bool = typer.Option(False, "--version", help="Show CapIoT version.")):
    banner()
    if version:
        typer.echo(f"CapIoT version: {__version__}")
        raise typer.Exit()

@app.command(help="Run a full experiment: launch the app, simulate UI interactions, and capture IoT traffic.")
def run(
    package_name: str = typer.Option(..., "--package-name", "-p", help="App package/bundle id."),
    phone_id: str = typer.Option(..., "--phone-id", "-i", help="Phone id."),
    device_name: str = typer.Option(..., "--device-name", "-d", help="IoT device name."),
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML config."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Enable DEBUG logs in the log file.",
    ),
    log_file: Path | None = typer.Option(None, "--log-file", help="Write logs to this file.")
):
    setup_logging(verbose, log_file)
    start_ts = time.perf_counter()
    try:
        if not config.exists():
            typer.echo(f"Config file not found: {config}", err=True)
            logger.error("Config path does not exist: %s", config)
            raise typer.Exit(code=2)

        typer.echo("⭐ Loading configuration…")
        logger.info("Loading config from %s", config)
        loaded_config: AppConfig = load_config(str(config))

        typer.echo("⭐ Preparing experiment context…")
        logger.debug("Creating ExperimentContext(package=%s, phone=%s, device=%s)",
                     package_name, phone_id, device_name)
        ctx = ExperimentContext.create(loaded_config, package_name, phone_id, device_name)

        typer.echo("▶️  Starting experiment...")
        logger.info("Dispatching experiment to runners")
        dispatch(ctx)

        elapsed = time.perf_counter() - start_ts
        typer.echo(f"✔ Experiment finished (took {elapsed:.1f}s)")
        logger.info("Experiment completed in %.2fs", elapsed)
    except ConfigLoadError as e:
        typer.echo(str(e), err=True)
        logger.error("❌ Config validation failed:\n%s", e)
        raise typer.Exit(code=2)
    except RunnerNotFoundError as e:
        typer.echo(f"❌ {e}", err=True)
        logger.error("Runner selection failed (none matched): %s", e)
        raise typer.Exit(code=2)
    except RunnerAmbiguousError as e:
        typer.echo(f"❌ {e}\nHint: increase specificity or adjust runner priorities.", err=True)
        logger.error("Runner selection ambiguous: %s", e)
        raise typer.Exit(code=2)
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - start_ts
        typer.echo("\nInterrupted by user. Cleaning up…", err=True)
        logger.warning("Interrupted by user after %.2fs", elapsed, exc_info=True)
        raise typer.Exit(code=130)
    except ExperimentError as e:
        typer.echo(f"❌ Experiment failed: {e}", err=True)
        raise typer.Exit(code=2)
    except Exception as e:
        typer.echo(f"❌ Experiment failed: {e}", err=True)
        logger.exception("Experiment failed with an unhandled exception")
        raise typer.Exit(code=1)


@app.command("record-coordinates", help="Record tap coordinates for an app (Android/iOS).")
def record_coordinates(
    phone_id: str = typer.Option(..., "--phone-id", "-i",
                                 help="Phone id."),
    package_name: str = typer.Option(..., "--package-name", "-p",
                                     help="App package/bundle id."),
    device_name: str = typer.Option(..., "--device-name", "-d", help="IoT device name."),
    output_directory: Path = typer.Option(..., "--output", "-o", help="Directory to save output to."),
    platform: str = typer.Option(..., "--platform", "-f", case_sensitive=False, help="android or ios"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Enable DEBUG logs in the log file.",
    ),
    log_file: Path | None = typer.Option(None, "--log-file", help="Write logs to this file.")
):
    setup_logging(verbose, log_file)

    try:
        plat = platform.lower().strip()
        if plat not in {"android", "ios"}:
            typer.echo("Invalid --platform. Use 'android' or 'ios'.", err=True)
            raise typer.Exit(code=2)

        if not output_directory.exists():
            logger.info("Creating output directory: %s", output_directory)
            output_directory.mkdir(parents=True, exist_ok=True)

        if plat == 'android':
            typer.echo("Recording tap coordinates on Android…")
            logger.info("Starting Android coordinate recorder for %s (%s) -> %s",
                        package_name, phone_id, output_directory)
            record_coordinates_android(phone_id, package_name, device_name, str(output_directory))
            logger.info("Android coordinate recording completed")
        else:
            typer.echo("Recording tap coordinates on iOS…")
            logger.info("Starting iOS coordinate recorder for %s (%s) -> %s",
                        package_name, phone_id, output_directory)
            record_coordinates_ios(phone_id, package_name, device_name, str(output_directory))
            logger.info("iOS coordinate recording completed")

        typer.echo("✔ Coordinate recording finished")

    except Exception as e:
        typer.echo(f"❌ Coordinate recording failed: {e}", err=True)
        logger.exception("Coordinate recording failed with an unhandled exception")
        raise typer.Exit(code=1)

@app.command("check-config", help="Validate a CapIoT YAML config and report any errors.")
def check_config(
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML config."),
):
    """
    Validate a CapIoT config file and exit with code 0 on success, 2 on failure.
    """
    try:
        if not config.exists():
            typer.secho(f"❌ Config file not found: {config}", fg=typer.colors.RED)
            raise typer.Exit(code=2)

        typer.echo("🔎 Validating configuration…")
        cfg: AppConfig = load_config(str(config))

        typer.secho("✅ Configuration is valid.", fg=typer.colors.GREEN)
    except ConfigLoadError as e:
        typer.secho("❌ Config validation failed.", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    except Exception as e:
        typer.secho("❌ Configuration is invalid. See details below:", fg=typer.colors.RED)
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)

if __name__ == "__main__":
    app()


@app.command("dump-app", help="Dump app as apk (Android) / ipa (iOS).")
def dump_app(
    platform: str = typer.Option(..., "--platform", "-f", help="android or ios"),
    package_name: str = typer.Option(..., "--package-name", "-p", help="Android package / iOS bundle id"),
    output: Path = typer.Option(..., "--output", "-o", help="Directory to store the dump"),
    phone_id: str = typer.Option(..., "--phone-id", "-i", help="ADB device id (Android) or udid (iOS)"),
    # iOS-specific
    ssh_host: Optional[str] = typer.Option(None, "--ssh-host", "-h", help="SSH host to connect to"),
    ssh_port: int = typer.Option(22, "--ssh-port", help="iOS SSH port (default 22)"),
    ssh_user: str = typer.Option("mobile", "--ssh-user", help="iOS SSH user (default: mobile)"),
    ssh_key_path: Optional[Path] = typer.Option(None, "--ssh-key", help="iOS SSH key path", exists=True),
    ssh_password: Optional[str] = typer.Option(None, "--ssh-password", hide_input=True, envvar="IOS_SSH_PASSWORD", help="iOS SSH password. Omit this flag to be prompted interactively (input is hidden). "
         "Alternatively set via IOS_SSH_PASSWORD. Use either this or --ssh-key.")
 ):
    """
    Dump apps for analysis:
      - ANDROID: pull APK splits and save permissions.txt
      - iOS: copy decrypted .app via SSH and package as IPA
    """
    platform = platform.lower().strip()
    output.mkdir(parents=True, exist_ok=True)
    try:
        if platform == "android":
            typer.echo(f"📦 Pulling APK(s) for {package_name} from {phone_id} …")
            apk_dir = dump_android_apks(
                package_name=package_name,
                phone_id=phone_id,
                base_dir=output,
            )
            typer.secho(f"✅ APK(s) saved to: {apk_dir}", fg=typer.colors.GREEN)


        elif platform == "ios":
            if not ssh_host:
                raise typer.BadParameter("--ssh-host is required for iOS")
            if not ssh_key_path and not ssh_password:
                ssh_password = typer.prompt("iOS SSH password", hide_input=True)
            typer.echo(f"📦 Dumping IPA for {package_name} from UDID {phone_id} …")
            ssh_config = SshConnectionConfig(
                host=ssh_host,
                port=ssh_port,
                username=ssh_user,
                key_path=ssh_key_path if ssh_key_path else None,
                password=ssh_password if ssh_password else None,
            )
            ipa_path = dump_ios_ipa(
                bundle_id=package_name,
                udid=phone_id,
                output_dir=output,
                ssh_config=ssh_config
            )
            typer.secho(f"✅ IPA saved to: {ipa_path}", fg=typer.colors.GREEN)

        else:
            typer.secho("❌ Unknown --platform. Use 'android' or 'ios'.", fg=typer.colors.RED)
            raise typer.Exit(code=2)
    except IOSDumpError as e:
        typer.secho(f"❌ iOS dump failed: {e}\n", fg=typer.colors.RED)
        logger.exception("iOS dump failed (%s on %s)", package_name, phone_id)
        raise typer.Exit(code=1)
    except AndroidDumpError as e:
        typer.secho(f"❌ Android dump failed: {e}\n", fg=typer.colors.RED)
        logger.exception("Android dump failed (%s on %s)", package_name, phone_id)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.secho("❌ Dump failed.", fg=typer.colors.RED)
        logger.exception("Dump failed for platform=%s package=%s", platform, package_name)
        raise typer.Exit(code=1)