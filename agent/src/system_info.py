"""Utility functions to extract the platform information for the system under test."""
import shlex
import subprocess
from pathlib import Path


def run_command(command):
    """Executes command as a subprocess.

    Ensures that the language is et to en_US.
    Returns the stdout & stderr of the command as strings.
    """
    return subprocess.run(
        shlex.split(command),
        encoding='utf8',
        text=True,
        capture_output=True,
        env={
            'LANG': 'en_US.UTF-8',
        },
    )


def os_name():
    """Reads /etc/os-release to determine the OS name.

    NOTE: This routine only works on Linux.
    """
    os_data = Path('/etc/os-release').read_text().splitlines()
    os_data = {d[0]: d[1] for d in [e.strip().split('=') for e in os_data] if len(d) == 2}
    os_name = (
        os_data.get('PRETTY_NAME')
        or f"{os_data.get('NAME', 'Unknown')} {os_data.get('VERSION', '')}"
    )
    return {'os_name': os_name.strip('"')}


def hostname():
    """Does what is says on the can - returns the hostname."""
    return {'hostname': run_command('hostname -s').stdout.strip()}


def cpu_info():
    """Runs lscpu to collect details regarding the installed CPUs."""
    CPU_KEYS = [
        'Architecture',
        'CPU(s)',
        'Thread(s) per core',
        'Core(s) per socket',
        'Socket(s)',
        'Vendor ID',
        'Model name',
        'CPU MHz',
        'CPU max MHz',
        'CPU min MHz',
    ]

    cpu_data = run_command('lscpu').stdout
    # Transform each line into dictionary entry, split on colon ':'
    cpu_data = {d[0]: d[1] for d in [line.strip().split(':') for line in cpu_data.splitlines()]}
    # make all the keys lowercase and replace spaces with underscores
    return {k.lower().replace(' ', '_'): cpu_data.get(k, 'Unknown').strip() for k in CPU_KEYS}


def hw_info():
    """Returns platform/firmware info."""
    dmi_path = Path('/sys/devices/virtual/dmi/id')
    dmi_files = [
        'bios_date',
        'bios_vendor',
        'bios_version',
        'board_name',
        'board_vendor',
        'board_version',
        'sys_vendor',
    ]
    return {f: dmi_path.joinpath(f).read_text().strip() for f in dmi_files}


def system_info():
    """Returns the aggregated dictionary containing all system information."""
    return hw_info() | cpu_info() | hostname() | os_name()
