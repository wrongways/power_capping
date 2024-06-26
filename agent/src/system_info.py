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
    name = (
        os_data.get('PRETTY_NAME')
        or f"{os_data.get('NAME', '')} {os_data.get('VERSION', '')}"
    )
    return {'os_name': name.strip('"')}


def hostname():
    """Does what is says on the can - returns the hostname."""
    return {'hostname': run_command('hostname -s').stdout.strip()}


def cpu_info():
    """Runs lscpu to collect details regarding the installed CPUs."""
    cpu_keys = [
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

    def to_int(s):
        """Convert string int to int or zero"""
        try:
            i = int(s)
        except ValueError:
            i = 0
        return i

    cpu_data = run_command('lscpu').stdout
    # Transform each line into dictionary entry, split on colon ':'
    cpu_data = {d[0]: d[1] for d in [line.strip().split(':') for line in cpu_data.splitlines()]}
    # make all the keys lowercase and replace spaces with underscores
    cpu_data = {k.lower().replace(' ', '_').replace('(s)', 's'): cpu_data.get(k, '').strip() for k in cpu_keys}
    integer_keys = ('cpus', 'threads_per_core', 'cores_per_socket', 'sockets', 'cpu_mhz', 'cpu_min_mhz', 'cpu_max_mhz')
    for k in integer_keys:
        cpu_data[k] = to_int(cpu_data[k])

    return cpu_data


def hw_info():
    """Returns platform/firmware info."""
    dmi_root = Path('/sys/devices/virtual/dmi/id')
    dmi_files = [
        'bios_date',
        'bios_vendor',
        'bios_version',
        'board_name',
        'board_vendor',
        'board_version',
        'sys_vendor',
    ]
    # List of dmi paths
    dmi_paths = [dmi_root.joinpath(f) for f in dmi_files]

    print({p.name: p.read_text().strip() for p in dmi_paths if p.exists()})
    # For each dmi path that exists, create dictionary
    # with name as key and stripped contents as value
    return {p.name: p.read_text().strip() for p in dmi_paths if p.exists()}


def system_info():
    """Returns the aggregated dictionary containing all non-null/non-empty system information."""
    all_info = hw_info() | cpu_info() | hostname() | os_name()
    compact_info = {k: v for k, v in all_info.items() if v}
    print(f'system_info: {compact_info}')
    return compact_info
