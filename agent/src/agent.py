import shlex
import subprocess
import threading
from pathlib import Path
from pprint import pprint
from time import monotonic_ns, sleep

from aiohttp import web

RAPL_PATH = "/sys/devices/virtual/powercap/intel-rapl/"
RAPL_SAMPLE_TIME_SECS = .25
HTTP_202_ACCEPTED = 202
HTTP_409_CONFLICT = 409


# Utility functions


def run_command(command):
    """Executes command as a subprocess, ensuring the language is et to en_US.
    Returns the stdout & stderr of the command as strings"""
    return subprocess.run(
            shlex.split(command),
            encoding="utf8",
            text=True,
            capture_output=True,
            env={
                "LANG": "en_US.UTF-8",
            }
    )


def os_name():
    """Reads /etc/os-release to determine the OS name
    NOTE: This routine only works on Linux"""

    os_data = Path("/etc/os-release").read_text().splitlines()
    os_data = {d[0]: d[1] for d in [
        e.strip().split('=') for e in os_data
    ] if len(d) == 2
               }
    os_name = (
            os_data.get("PRETTY_NAME") or
            f"{os_data.get('NAME', 'Unknown')} {os_data.get('VERSION', '')}"
    )
    return {"os_name": os_name.strip('"')}


def hostname():
    """Does what is says on the can - returns the hostname"""
    return {"hostname": run_command("hostname -s").stdout.strip()}


def cpu_info():
    """Runs lscpu to collect details regarding the installed CPUs"""
    CPU_KEYS = [
        "Architecture",
        "CPU(s)",
        "Thread(s) per core",
        "Core(s) per socket",
        "Socket(s)",
        "Vendor ID",
        "Model name",
        "CPU MHz",
        "CPU max MHz",
        "CPU min MHz",
    ]

    cpu_data = run_command("lscpu").stdout
    # Transform each line into dictionary entry, split on colon ':'
    cpu_data = {d[0]: d[1] for d in [line.strip().split(":") for line in cpu_data.splitlines()]}
    # make all the keys lowercase and replace spaces with underscores
    return {k.lower().replace(" ", "_"): cpu_data[k].strip() for k in CPU_KEYS}


def hw_info():
    """Returns platform/firmware info"""
    dmi_path = Path("/sys/devices/virtual/dmi/id")
    dmi_files = [
        "bios_date",
        "bios_vendor",
        "bios_version",
        "board_name",
        "board_vendor",
        "board_version",
        "sys_vendor",
    ]
    return {
        f: dmi_path.joinpath(f).read_text().strip() for f in dmi_files
    }


def system_info():
    return web.json_response(
            hw_info() |
            cpu_info() |
            hostname() |
            os_name()
    )


class CappingAgent:
    def __init__(self, port_number: int, firestarter_path: str):
        """
        Params:
            firestarter_path: str - the filepath to the firestarter executable
        """

        self.firestarter_path = firestarter_path
        self.firestarter_thread = None
        # Get the list of packages/sockets
        packages_paths = list(Path(RAPL_PATH).glob('intel-rapl:[0-9]*'))
        pprint(packages_paths)

        # For each package, create a dictionary with the energy file path,
        # max_energy_range_uj and package name
        self.package_info = {
            path: {
                'energy_uj_path': path.joinpath('energy_uj'),
                'name': path.joinpath('name').read_text().strip(),
                'max_energy': self.read_energy_path(path, read_max_energy=True)
            }
            for path in packages_paths
        }
        pprint(self.package_info)
        self.app = web.Application()

        self.app.add_routes([
            web.get('/rapl_power', self.rapl_power),
            web.post('/firestarter', self.firestarter),
            web.get('/system_info', system_info)
        ])
        web.run_app(self.app(), port=port_number)

    async def rapl_power(self, _request):
        """\
        Calculates the current socket power consumption for all sockets

        For each socket, read the current energy value, sleep for a short period,
        then re-read the energy value. Power is then energy delta divided by time
        delta.

        Params:
            none
        Returns:
            JSON list of power consumption
        """

        # Get the initial energy readings
        start_values = {
            path: {
                'energy_uj': self.read_energy_path(path),
                'timestamp': monotonic_ns()
            }
            for path in self.package_info
        }

        # Wait a while for energy to be consumed
        sleep(RAPL_SAMPLE_TIME_SECS)

        # Build a dictionary of powers, keyed on package name.
        package_powers = {}
        for path, reading in start_values.items():
            package_name = self.package_info[path]['name']
            start_energy = reading['energy_uj']
            start_timestamp = reading['timestamp']
            end_energy = self.read_energy_path(path)
            end_timestamp = monotonic_ns()

            # Check for wrap-around
            energy_delta = (
                end_energy - start_energy if end_energy > start_energy
                else self.package_info[path]['max_energy'] - start_energy + end_energy
            )

            # The power of each package/socket = delta_energy / delta_time
            time_delta_ns = end_timestamp - start_timestamp
            package_power_watts = energy_delta / time_delta_ns * 1000
            package_powers[package_name] = package_power_watts

        return web.json_response(package_powers)

    async def firestarter(self, request: web.Request):
        """"/firestarter route handler.

        @param request - the request object provided by aiohttp
        """

        # If firestarter already running return 409 - conflict
        if self.firestarter_thread is not None and self.firestarter_thread.is_alive():
            return web.json_response({'error': 'Firestarter already running'}, status=HTTP_409_CONFLICT)

        # 'join()' any previous thread. Given that the thread must be complete
        # at this point (see previous check), then this will return immediately.

        if self.firestarter_thread is not None:
            self.firestarter_thread.join()

        # pull out the request arguments
        json_body = await request.json()
        self.firestarter_thread = threading.Thread(target=self.launch_firestarter, args=[json_body], name='Firestarter')
        self.firestarter_thread.start()
        return web.json_response(None, status=HTTP_202_ACCEPTED)

    def launch_firestarter(self, args):
        """Launches the firestarter subprocess.

        @param args: {str: int} - list of firestarter arguments
            timeout → runtime_secs
            load → pct_load
            threads → n_threads
        """

        runtime_secs = args.get('runtime_secs', 30)
        pct_load = args.get('pct_load', 100)
        n_threads = args.get('n_threads', 0)
        command_line = f'{self.firestarter_path} --quiet --timeout {runtime_secs} --load {pct_load} --threads {n_threads}'

        # Launch the subprocess, sending the firestarter banner to /dev/null
        subprocess.run(command_line.split(), stdout=subprocess.DEVNULL)

    def read_energy_path(self, path, read_max_energy=False):
        """\
        Reads a RAPL energy file. If max is true, reads the max_energy_range_uj file.
        Otherwise, read the energy_uj file

        Params:
            path: the path to the package directory
            read_max_energy: flag if true, read max_energy_range_uj, otherwise energy_uj
        Returns:
            The value of the file as an integer
        """
        energy_path = (
            path.joinpath('max_energy_range_uj') if read_max_energy
            else self.package_info[path]['energy_uj_path']
        )
        return int(energy_path.read_text().strip())


if __name__ == '__main__':
    agent = CappingAgent(port_number=5432, firestarter_path='/home_nfs/wainj/local/bin/firestarter')
