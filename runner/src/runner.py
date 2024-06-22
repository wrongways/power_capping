"""The test run driver.

Calibrates the system under test, looking at power consumption at idle and full CPU load,
to establish min and max power consumption (without loading any GPUs) and the minimum cap level
"""
import argparse
import asyncio
import sys
from math import ceil

import aiohttp

from BMC import BMC_Type, IpmiBMC, RedfishBMC
from collector import Collector

HTTP_202_ACCEPTED = 202


class Runner:
    """Test run driver main class."""

    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path, ipmitool_path=None):
        # Ensure that agent url starts with http
        self.agent_url = agent_url if agent_url.startswith('http') else f'http://{agent_url}'

        # Establish BMC type
        bmc_type = BMC_Type.IPMI if bmc_type == 'ipmi' else BMC_Type.REDFISH
        if bmc_type == BMC_Type.IPMI:
            self.bmc = IpmiBMC(bmc_hostname, bmc_username, bmc_password, ipmitool_path)
            self.collector = Collector(bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path,
                                       ipmitool_path)
        else:
            self.bmc = RedfishBMC(bmc_hostname, bmc_username, bmc_password)
            self.collector = Collector(bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path)

    async def calibrate(self):
        """Establish min/max power draws and capping levels"""
        min_power, max_power = await self.get_min_max_power()
        max_power = ceil(int(max_power * 1.2) // 10) * 10  # Give a bit of headroom and round to 10
        capping_levels = await self.find_capping_levels(min_power, max_power)

    async def get_min_max_power(self):
        """Establishes the min/max power consumption of the system under test.

            Assumes that the system under test is at (close to) idle
        """

        sample_duration_secs = 10
        min_power = min([await self.bmc.current_power for _ in range(sample_duration_secs)])
        await self.run_firestarter(load_pct=100, n_threads=0, runtime_secs=30)
        max_power = 0
        for _ in range(sample_duration_secs):
            await asyncio.sleep(1)
            max_power = max(max_power, await self.bmc.current_power)

        print(f"Min power: {min_power} W, max power: {max_power} W")
        return min_power, max_power

    async def run_firestarter(self, load_pct, n_threads, runtime_secs):
        """Get the agent to run firestarter with the provided parameters."""

        firestarter_endpoint = f'{self.agent_url}/firestarter'
        firestarter_args = {
            'load_pct': load_pct,
            'n_threads': n_threads,
            'runtime_secs': runtime_secs,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(firestarter_endpoint, json=firestarter_args, ssl=False) as resp:
                if resp.status != HTTP_202_ACCEPTED:
                    print(f"Failed to launch firestarter: {resp.status}")

    async def find_capping_levels(self, min_power, max_power):
        """Determine the available capping levels."""

        power_delta = 10  # Watts
        capping_levels = set()
        max_tries = 3
        current_cap_level = 999_999_999
        for cap_level in range(max_power, min_power, -power_delta):
            print(f'Trying to cap at {cap_level}', end='. ')
            try_count = 0
            while try_count < max_tries:
                try_count += 1
                await self.bmc.set_cap_level(cap_level)
                await asyncio.sleep(0.5)
                new_cap_level = await self.bmc.current_cap_level
                if new_cap_level != current_cap_level:
                    assert new_cap_level < current_cap_level
                    current_cap_level = new_cap_level
                    capping_levels.add(new_cap_level)
                    print(f' - set to {new_cap_level}', end='')
                    break

            print()

        print(f'Capping levels: {", ".join(sorted(capping_levels))}')



if __name__ == "__main__":
    def parse_args():
        parser = argparse.ArgumentParser(
                prog='Capping test tool',
                description='Runs some capping tests against a given system',
        )
        parser.add_argument('-H', '--bmc_hostname', required=True, help='BMC hostname/ip')
        parser.add_argument('-U', '--bmc_username', required=True, help='BMC username')
        parser.add_argument('-P', '--bmc_password', required=True, help='BMC password')
        parser.add_argument('-t', '--bmc_type', required=True, choices=['ipmi', 'redfish'], help='BMC password')
        parser.add_argument('-a', '--agent_url', required=True,
                            help='hostname and port number of the agent running on the system under test')
        parser.add_argument('-d', '--db_path', metavar='<PATH TO DB FILE>', required=True,
                            help='''Path to the sqlite3 db on the local system holding the collected statistics. \
                            If the file does not exist, it will be created, otherwise the tables will be updated \
                            with the data from this run.\
                            ''')
        parser.add_argument('-i', '--ipmitool_path',
                            required='ipmi' in sys.argv,
                            metavar='<PATH TO IPMITOOL>',
                            default='/usr/bin/ipmitool',
                            help='Path to ipmitool on the local system. Only required if bmc_type="ipmi".')

        return parser.parse_args()


    async def main():
        args = vars(parse_args())
        print(args)

        runner = Runner(**args)
        if args.get('bmc_type') == 'redfish':
            await runner.bmc.connect()
            await runner.collector.bmc.connect()
        await runner.calibrate()


    asyncio.run(main())
