"""The test run driver.

Calibrates the system under test, looking at power consumption at idle and full CPU load,
to establish min and max power consumption (without loading any GPUs) and the minimum cap level
"""

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import date, datetime, UTC

import aiohttp

from BMC import BMC_Type, IpmiBMC, RedfishBMC
from cli import parse_args
from collector import Collector
from runner import config

HTTP_202_ACCEPTED = 202

logging.basicConfig(level='DEBUG')
logger = logging.getLogger(__name__)


class Runner:
    """Test run driver main class."""

    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path, ipmitool_path=None):
        # Ensure that agent url starts with http
        self.agent_url = agent_url if agent_url.startswith('http') else f'http://{agent_url}'
        self.db_path = db_path
        self.create_db_tables()
        sqlite3.register_adapter(datetime, lambda timestamp: timestamp.isoformat(timespec='milliseconds'))
        sqlite3.register_adapter(date, lambda timestamp: timestamp.isoformat(timespec='milliseconds'))

        # Establish BMC type
        bmc_type = BMC_Type.IPMI if bmc_type == 'ipmi' else BMC_Type.REDFISH
        if bmc_type == BMC_Type.IPMI:
            self.bmc = IpmiBMC(bmc_hostname, bmc_username, bmc_password, ipmitool_path)
        else:
            self.bmc = RedfishBMC(bmc_hostname, bmc_username, bmc_password)

    @property
    def bmc_type(self):
        """Return the type of BMC as string."""
        return 'impi' if isinstance(self.bmc, IpmiBMC) else 'redfish'

    async def bmc_connect(self):
        """Create http session if bmc_type=redfish."""
        if isinstance(self.bmc, RedfishBMC):
            await self.bmc.connect()

    async def collect_system_information(self):
        """Save system information from agent on SUT, complete with BMC and power info into db"""

        logger.debug("Enter collect_system_information()")
        async with aiohttp.ClientSession() as session:
            endpoint = self.agent_url + '/system_info'
            async with session.get(endpoint) as resp:
                if resp.status < 300:
                    system_info = await resp.json()

                    # Add complementary info
                    system_info['bmc_type'] = self.bmc_type

                    # Prepare sql
                    columns = ",".join(system_info)
                    placeholders = ",".join(list("?" * len(system_info)))
                    sql = f'insert into system_info ({columns}) values ({placeholders});'
                    logger.debug(f'System info sql: {sql}')

                    # Execute sql insert
                    print(f'SystemInfo insert: {sql}')
                    print(tuple(system_info.values()))

                    with sqlite3.connect(self.db_path, check_same_thread=False) as db:
                        db.execute(sql, tuple(system_info.values()))
                else:
                    print(f"Failed to get system information. Status code: {resp.status}\n{resp}")

    async def get_min_max_power(self):
        """Establishes the min/max power consumption of the system under test.

            Assumes that the system under test is at (close to) idle
        """

        sample_duration_secs = 20

        # Determine min power - assumes system idle
        min_power = 999_999_999
        for _ in range(sample_duration_secs):
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
        """Request that the agent run firestarter with the provided parameters."""

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
            firestarter_runtime = warmup_seconds + n_steps * per_step_runtime_seconds

        cap_delta = (cap_from - cap_to) // n_steps

        # Initial conditions - set cap from value
        self.log_cap_level(cap_from)

        await self.bmc.set_cap_level(cap_from)
        await asyncio.sleep(inter_step_pause_seconds)

        cap_level = cap_from
        start_time = datetime.now(UTC)
        if pause_load_between_cap_settings:
            for _ in range(n_steps):
                await self.launch_firestarter(load_pct, n_threads, firestarter_runtime)
                await asyncio.sleep(warmup_seconds)
                cap_level -= cap_delta
                self.log_cap_level(cap_level)
                await self.bmc.set_cap_level(cap_level)
                await asyncio.sleep(per_step_runtime_seconds + inter_step_pause_seconds)

        else:
            await self.launch_firestarter(load_pct, n_threads, firestarter_runtime)
            await asyncio.sleep(warmup_seconds)
            for _ in range(n_steps):
                cap_level -= cap_delta
                self.log_cap_level(cap_level)
                await self.bmc.set_cap_level(cap_level)
                await asyncio.sleep(per_step_runtime_seconds)

        end_time = datetime.now(UTC)
        self.log_test_run(start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads,
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

        system_info_table_sql = '''\
            create table if not exists system_info(
                hostname text not null,
                os_name text not null,
                architecture text not null,
                cpus integer not null,
                threads_per_core integer,
                cores_per_socket integer,
                sockets integer,
                vendor_id text,
                model_name text,
                cpu_mhz integer,
                cpu_max_mhz integer,
                cpu_min_mhz integer,
                bios_date text,
                bios_vendor text,
                bios_version text,
                board_name text,
                board_vendor text,
                board_version text,
                sys_vendor text,
                bmc_type text
            );
                '''

        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            db.execute(capping_table_sql)
            db.execute(test_table_sql)
            db.execute(system_info_table_sql)

    def log_test_run(self, start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads,
                     pause_load_between_cap_settings
                     ):
        """Insert details of single test run into the tests table."""

        sql = '''\
        insert into tests(start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads, pause_load_between_cap_settings)
        values(?, ?, ?, ?, ?, ?, ?, ?);'''
        data = (start_time, end_time, cap_from, cap_to, n_steps, load_pct, n_threads, pause_load_between_cap_settings)
        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            db.execute(sql, data)

    def log_cap_level(self, cap_level):
        """Insert a timestamped change into the capping_commands table."""
        sql = 'insert into capping_commands(timestamp, cap_level) values(?, ?);'
        data = (datetime.now(UTC), cap_level)
        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            db.execute(sql, data)


if __name__ == "__main__":
    async def main():
        args = vars(parse_args())
        runner = Runner(**args)
        collector = Collector(**args)
        await runner.bmc.connect()
        await collector.bmc_connect()

        await runner.collect_system_information()
        logger.debug("Launching collector")
        collect_thread = threading.Thread(target=asyncio.run, args=(collector.start_collect(),))
        collect_thread.start()
        logger.debug("Started collect thread")
        logger.debug("Starting runner.run_test()")
        await runner.run_test(cap_from=400, cap_to=800, n_steps=2, load_pct=100, n_threads=0,
                              pause_load_between_cap_settings=False)
        logger.debug("Run test ended, halting collector")
        collector.end_collect()
        logger.debug("Joining collect thread")
        collect_thread.join()
        logger.debug("Collector ended")

    asyncio.run(main())
