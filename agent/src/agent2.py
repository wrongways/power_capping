import argparse
import json
import logging
import subprocess
import threading
from asyncio import sleep
from pathlib import Path
from time import monotonic_ns

from aiohttp import web

from system_info import system_info

RAPL_PATH = "/sys/devices/virtual/powercap/intel-rapl/"
RAPL_SAMPLE_TIME_SECS = .25
HTTP_202_ACCEPTED = 202
HTTP_409_CONFLICT = 409

logger = logging.getLogger(__name__)



async def get_system_info(self):
    return web.json_response(system_info())


def read_energy_path(path, read_max_energy=False):
    """
    Reads a RAPL energy file. If max is true, reads the max_energy_range_uj file.
    Otherwise, read the energy_uj file.

    Params:
        path: the path to the package directory
        read_max_energy: flag if true, read max_energy_range_uj, otherwise energy_uj
    Returns:
        The value of the file as an integer
    """
    energy_path = (
        path.joinpath('max_energy_range_uj') if read_max_energy
        else package_info[path]['energy_uj_path']
    )
    return int(energy_path.read_text().strip())


async def rapl_power(_request):
    """Calculates the current socket power consumption for all sockets.

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
            'energy_uj': read_energy_path(path),
            'timestamp': monotonic_ns()
        }
        for path in package_info
    }

    # Wait a while for energy to be consumed
    await sleep(RAPL_SAMPLE_TIME_SECS)

    # Build a dictionary of powers, keyed on package name.
    package_powers = {}
    for path, reading in start_values.items():
        package_name = package_info[path]['name']
        start_energy = reading['energy_uj']
        start_timestamp = reading['timestamp']
        end_energy = read_energy_path(path)
        end_timestamp = monotonic_ns()

        # Check for wrap-around
        energy_delta = (
            end_energy - start_energy if end_energy > start_energy
            else package_info[path]['max_energy'] - start_energy + end_energy
        )

        # The power of each package/socket = delta_energy / delta_time
        time_delta_ns = end_timestamp - start_timestamp
        package_power_watts = energy_delta / time_delta_ns * 1000
        package_powers[package_name] = package_power_watts

    return web.json_response(package_powers)

    def launch_firestarter(args):
        """Launches the firestarter subprocess.

        @param args: {str: int} - list of firestarter arguments
            timeout → runtime_secs
            load → pct_load
            threads → n_threads
        """
        runtime_secs = args.get('runtime_secs', 30)
        pct_load = args.get('pct_load', 100)
        n_threads = args.get('n_threads', 0)
        command_line = f'{args.firestarter} --quiet --timeout {runtime_secs} --load {pct_load} --threads {n_threads}'

        # Launch the subprocess, sending the firestarter banner to /dev/null
        subprocess.run(command_line.split(), stdout=subprocess.DEVNULL)

    async def firestarter(request: web.Request):
        """"/firestarter route handler.

        @param request - the request object provided by aiohttp
        """
        # If firestarter already running return 409 - conflict
        global firestarter_thread

        if firestarter_thread is not None and firestarter_thread.is_alive():
            return web.json_response({'error': 'Firestarter already running'}, status=HTTP_409_CONFLICT)

        # 'join()' any previous thread. Given that the thread must be complete
        # at this point (see previous check), then this will return immediately.

        if firestarter_thread is not None:
            firestarter_thread.join()

        # pull out the request arguments
        json_body = await request.json()
        firestarter_thread = threading.Thread(target=launch_firestarter, args=[json_body],
                                                   name='Firestarter')
        firestarter_thread.start()
        return web.json_response(None, status=HTTP_202_ACCEPTED)



if __name__ == '__main__':
    packages_paths = list(Path(RAPL_PATH).glob('intel-rapl:[0-9]*'))
    package_info = {
        path: {
            'energy_uj_path': path.joinpath('energy_uj'),
            'name': path.joinpath('name').read_text().strip(),
            'max_energy': read_energy_path(path, read_max_energy=True)
        } for path in packages_paths
    }
    logger.debug(f'{packages_paths=}')
    str_package_info = {str(k): str(v) for k, v in package_info}
    logger.debug(f'package_info:\n{json.dumps(str_package_info, indent=3, sort_keys=True)}')

    firestarter_thread = None

    parser = argparse.ArgumentParser(
            prog='CappingAgent',
            description='Launches the capping tool agent',
    )

    parser.add_argument(
            '-P', '--port',
            default=5432,
            type=int,
            help='Port the agent will listen on'
    )
    parser.add_argument(
            '-f', '--firestarter',
            default='/home_nfs/wainj/local/bin/firestarter',
            help='Fully qualified path to the firestarter load generation programme'
    )

    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-V', '--version', action='version')
    args = parser.parse_args()

