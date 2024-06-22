"""The test run driver.

Calibrates the system under test, looking at power consumption at idle and full CPU load,
to establish min and max power consumption (without loading any GPUs) and the minimum cap level
"""
import argparse
import asyncio
import sys

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
        """Establishes the min/max power consumption of the system under test."""

        sample_duration_secs = 10
        min_power = min([self.bmc.current_power for _ in range(sample_duration_secs)])
        await self.run_firestarter(load_pct=100, n_threads=0, runtime_secs=sample_duration_secs)
        max_power = 0
        for _ in range(sample_duration_secs):
            await asyncio.sleep(1)
            max_power = max(max_power, await self.bmc.current_power)

        print(f"Min power: {min_power} W, max power: {max_power} W")

    async def run_firestarter(self, load_pct, n_threads, runtime_secs):
        firestarter_endpoint = f'{self.agent_url}/firestarter'
        firestarter_args = {
            'load_pct': load_pct,
            'n_threads': n_threads,
            'runtime_secs': runtime_secs,
        }

        with aiohttp.ClientSession() as session:
            with session.post(firestarter_endpoint, json=firestarter_args, ssl=False) as resp:
                if resp.status != HTTP_202_ACCEPTED:
                    print(f"Failed to launch firestarter: {resp.status}")


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
            runner.bmc.connect()
            runner.collector.bmc.connect()
        await runner.calibrate()


    asyncio.run(main())
