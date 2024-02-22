import subprocess
import threading
from pathlib import Path
from pprint import pprint
from time import monotonic_ns, sleep

from aiohttp import web

RAPL_PATH = "/sys/devices/virtual/powercap/intel-rapl/"
RAPL_SAMPLE_TIME_SECS = .25
HTTP_202_ACCEPTED = 202


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

    async def firestarter(self, request):
        args = await request.json()
        print(f'Firestarter route args: {args}, {type(args)}')
        
        # if args is junk or contains unknown fields, this blows up
        self.firestarter_thread = threading.Thread(target=self.launch_firestarter, args=args)
        self.firestarter_thread.start()
        return web.json_response(None, status=HTTP_202_ACCEPTED)

    def launch_firestarter(self, args):
        print(f'launch_firestarter() args: {args}, {type(args)}')
        runtime_secs = args.get('runtime_secs', 30)
        pct_load = args.get('pct_load', 100)
        n_threads = args.get('n_threads', 0)
        command_line = f'{self.firestarter_path} --quiet --timeout {runtime_secs} --load {pct_load} --threads {n_threads}'
        print(f'Firestarter command:\n\t{command_line}')
        subprocess.run(command_line.split())

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
