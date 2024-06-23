"""The test run driver.

Calibrates the system under test, looking at power consumption at idle and full CPU load,
to establish min and max power consumption (without loading any GPUs) and the minimum cap level
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, UTC
from math import ceil

import aiohttp

from BMC import BMC_Type, IpmiBMC, RedfishBMC
from collector import Collector
from runner import config

HTTP_202_ACCEPTED = 202


class Runner:
    """Test run driver main class."""

    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path, ipmitool_path=None):
        # Ensure that agent url starts with http
        self.agent_url = agent_url if agent_url.startswith('http') else f'http://{agent_url}'
        self.db_path = db_path
        self.create_db_tables()
        sqlite3.register_adapter(datetime, lambda timestamp: timestamp.isoformat())

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
        print(f"Min power: {min_power} W, max power: {max_power} W")

        # Pause a while before returning to allow firestarter to finish
        await asyncio.sleep(2)

    async def get_min_max_power(self):
        """Establishes the min/max power consumption of the system under test.

            Assumes that the system under test is at (close to) idle
        """

        sample_duration_secs = 20

        # Determine min power - assumes system idle
        min_power = 999_999_999
        for _ in range(sample_duration_secs + 1):
            await asyncio.sleep(1)
            min_power = min(min_power, await self.bmc.current_power)

        # Launch firestarter and measure max power of sample duration
        await self.launch_firestarter(load_pct=100, n_threads=0, runtime_secs=sample_duration_secs)
        max_power = 0
        for _ in range(sample_duration_secs + 1):
            await asyncio.sleep(1)
            max_power = max(max_power, await self.bmc.current_power)

        return min_power, max_power

    async def launch_firestarter(self, load_pct, n_threads, runtime_secs):
        """Get the agent to run firestarter with the provided parameters."""

        firestarter_endpoint = f'{self.agent_url}/firestarter'
        firestarter_args = {
            'load_pct': load_pct,
            'n_threads': n_threads,
            'runtime_secs': runtime_secs,
        }

        print(f"Launching firestarter: {json.dumps(firestarter_args, indent=3)}")
        async with aiohttp.ClientSession() as session:
            async with session.post(firestarter_endpoint, json=firestarter_args, ssl=False) as resp:
                if resp.status != HTTP_202_ACCEPTED:
                    print(f"Failed to launch firestarter: {resp.status} - {await resp.json()}")

    async def run_test(self, cap_from, cap_to, n_steps=1, load_pct=100, n_threads=0,
                       pause_load_between_cap_settings=False
                       ):
        """Run a given test configuration"""

        warmup_seconds = config.TestConfig.warmup_seconds
        per_step_runtime_seconds = config.TestConfig.per_step_runtime_seconds
        inter_step_pause_seconds = config.TestConfig.inter_step_pause_seconds

        assert n_steps > 0

        if pause_load_between_cap_settings:
            firestarter_runtime = warmup_seconds + per_step_runtime_seconds
        else:
            firestarter_runtime = warmup_seconds + n_steps * per_step_runtime_seconds + (
                        n_steps - 1) * inter_step_pause_seconds

        cap_delta = (cap_from - cap_to) // n_steps

        with sqlite3.connect(self.db_path) as db:
            # Initial conditions - set cap from value
            self.log_cap_level(db, cap_from)
            await self.bmc.set_cap_level(cap_from)
            await asyncio.sleep(inter_step_pause_seconds)

            cap_level = cap_from
            start_time = datetime.now(UTC)
            if pause_load_between_cap_settings:
                for _ in range(n_steps + 1):
                    await self.launch_firestarter(load_pct, n_threads, firestarter_runtime)
                    await asyncio.sleep(firestarter_runtime)
                    cap_level -= cap_delta
                    self.log_cap_level(db, cap_level)
                    await self.bmc.set_cap_level(cap_level)
                    await asyncio.sleep(inter_step_pause_seconds)

            else:
                await self.launch_firestarter(load_pct, n_threads, firestarter_runtime)
                await asyncio.sleep(warmup_seconds)
                for _ in range(n_steps + 1):
                    await asyncio.sleep(per_step_runtime_seconds)
                    cap_level -= cap_delta
                    self.log_cap_level(db, cap_level)
                    await self.bmc.set_cap_level(cap_level)
                    await asyncio.sleep(inter_step_pause_seconds)

            end_time = datetime.now(UTC)
            self.log_test_run(db, start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads,
                              pause_load_between_cap_settings)

    def create_db_tables(self):
        """Creates the capping and test tables in the db."""

        capping_table_sql = 'create table if not exists capping_commands(timestamp text, cap_level integer);'
        test_table_sql = '''create table if not exists tests(
            start_time text not null, 
            end_time text not null, 
            cap_from integer not null,
            cap_to integer not null,
            n_steps integer not null,
            load_pct integer not null, 
            n_threads integer not null,
            pause_load_between_cap_settings integer); -- sqlite does not have boolean type
            '''

        with sqlite3.connect(self.db_path) as db:
            db.execute(capping_table_sql)
            db.execute(test_table_sql)

    @staticmethod
    def log_test_run(db, start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads,
                     pause_load_between_cap_settings
                     ):
        sql = '''\
        insert into tests(start_time, end_time, cap_from, cap_to, load_pct, n_threads, pause_load_between_cap_settings)
        values(?, ?, ?, ?, ?, ?, ?, ?);'''
        data = (start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads, pause_load_between_cap_settings)
        db.execute(sql, data)

    @staticmethod
    def log_cap_level(db, cap_level):
        sql = 'insert into capping_commands(timestamp, cap_level) values(?, ?);'
        data = (datetime.now(UTC), cap_level)
        db.execute(sql, data)


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
        await runner.run_test(cap_from=400, cap_to=800, load_pct=100, n_threads=0,
                              pause_load_between_cap_settings=False)

    asyncio.run(main())