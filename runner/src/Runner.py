"""The test run driver.

Calibrates the system under test, looking at power consumption at idle and full CPU load,
to establish min and max power consumption (without loading any GPUs) and the minimum cap level
"""

import asyncio
import json
import logging
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, UTC

import aiohttp

from BMC import IpmiBMC, RedfishBMC
from cli import parse_args
from collector import Collector
from runner.config import runner_config

HTTP_202_ACCEPTED = 202


logging.basicConfig(level='DEBUG')
logger = logging.getLogger(__name__)


class Runner:
    """Test run driver main class."""

    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path, ipmitool_path=None):
        # Ensure that agent url starts with http
        self.test_id = None
        self.previous_cap_level = None
        self.agent_url = agent_url if agent_url.startswith('http') else f'http://{agent_url}'
        self.db_path = db_path
        self.create_db_tables()
        sqlite3.register_adapter(datetime, lambda timestamp: timestamp.isoformat(timespec='milliseconds'))
        sqlite3.register_adapter(date, lambda timestamp: timestamp.isoformat(timespec='milliseconds'))

        # Establish BMC type
        if bmc_type == 'ipmi':
            logger.debug('Creating IPMI BMC')
            self.bmc = IpmiBMC(bmc_hostname, bmc_username, bmc_password, ipmitool_path)
        else:
            logger.debug('Creating Redfish BMC')
            self.bmc = RedfishBMC(bmc_hostname, bmc_username, bmc_password)

        logger.debug(f'Runner BMC type: {self.bmc_type}')

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

    async def launch_firestarter(self, load_pct, runtime_secs):
        """Request that the agent run firestarter with the provided parameters."""

        firestarter_endpoint = f'{self.agent_url}/firestarter'
        firestarter_args = {
            'load_pct': load_pct,
            'runtime_secs': runtime_secs,
        }

        logger.debug(f"Launching firestarter: {json.dumps(firestarter_args, indent=3)}")
        async with aiohttp.ClientSession() as session:
            async with session.post(firestarter_endpoint, json=firestarter_args, ssl=False) as resp:
                if resp.status != HTTP_202_ACCEPTED:
                    logger.error(f"Failed to launch firestarter: {resp.status} - {await resp.json()}")

    async def run_test(self, cap_from, cap_to, n_steps=1, load_pct=100,
                       pause_load_between_cap_settings=False
                       ):
        """Run a given test configuration"""

        warmup_seconds = runner_config['warmup_seconds']
        per_step_runtime_seconds = runner_config['per_step_runtime_seconds']
        inter_step_pause_seconds = runner_config['inter_step_pause_seconds']
        self.previous_cap_level = None

        assert n_steps > 0

        if pause_load_between_cap_settings:
            firestarter_runtime = per_step_runtime_seconds
        else:
            firestarter_runtime = warmup_seconds + n_steps * per_step_runtime_seconds

        cap_delta = (cap_from - cap_to) // n_steps
        start_time = datetime.now(UTC)

        if pause_load_between_cap_settings:
            # Initial conditions - set cap from value
            self.log_cap_level(cap_from)
            await self.bmc.set_cap_level(cap_from)
            await asyncio.sleep(inter_step_pause_seconds)

            cap_level = cap_from
            for _ in range(n_steps):
                await self.launch_firestarter(load_pct, firestarter_runtime)
                await asyncio.sleep(firestarter_runtime + inter_step_pause_seconds)
                cap_level -= cap_delta
                self.log_cap_level(cap_level)
                await self.bmc.set_cap_level(cap_level)

        else:
            cap_level = runner_config['uncapped_power']
            self.log_cap_level(cap_level)
            await self.bmc.set_cap_level(cap_level)
            await self.launch_firestarter(load_pct, firestarter_runtime)
            await asyncio.sleep(warmup_seconds)
            cap_level = cap_from
            for _ in range(n_steps):
                self.log_cap_level(cap_level)
                await self.bmc.set_cap_level(cap_level)
                await asyncio.sleep(per_step_runtime_seconds)
                cap_level -= cap_delta

            await asyncio.sleep(inter_step_pause_seconds)

        end_time = datetime.now(UTC)
        self.log_test_run(start_time, end_time, cap_from, cap_to, n_steps, load_pct,
                          pause_load_between_cap_settings)

    async def run_campaign(self,
                           min_load, max_load, load_delta,
                           cap_min, cap_max, cap_delta
                           ):
        """Generate the combinations of test configurations and calls run_test for each"""

        assert min_load <= max_load
        assert cap_min < cap_max and cap_delta > 0
        assert load_delta > 0 or min_load == max_load
        assert load_delta <= (max_load - min_load)

        n_steps = (cap_max - cap_min) // cap_delta

        # If load_delta = 0, then min_load == max_load
        # Bump the load_delta to 1 to ensure loop exit
        load_delta = max(1, load_delta)

        for load in range(min_load, max_load + 1, load_delta):
            for pause in (True, False):
                # Increase setting upward
                await self.run_test(cap_min, cap_max, n_steps, load_pct=load,
                                    pause_load_between_cap_settings=pause)

                # Run setting cap down
                await self.run_test(cap_max, cap_min, n_steps, load_pct=load,
                                    pause_load_between_cap_settings=pause)

    def create_db_tables(self):
        """Creates the capping and test tables in the db."""

        capping_table_sql = 'create table if not exists capping_commands(timestamp datetime, cap_level integer);'
        test_table_sql = '''create table if not exists tests(
            test_id integer primary key,    -- rowid will auto-increment
            start_time datetime not null, 
            end_time datetime not null, 
            cap_from integer not null,
            cap_to integer not null,
            n_steps integer not null,
            load_pct integer not null, 
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

    def log_test_run(self, start_time, end_time, cap_from, cap_to, n_steps, load_pct,
                     pause_load_between_cap_settings
                     ):
        """Insert details of single test run into the tests table."""

        sql = '''\
        insert into tests(start_time, end_time, cap_from, cap_to, n_steps, load_pct, 
        pause_load_between_cap_settings)
        values(?, ?, ?, ?, ?, ?, ?, ?);'''
        data = (start_time, end_time, cap_from, cap_to, n_steps, load_pct, pause_load_between_cap_settings)
        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            db.execute(sql, data)

    def log_cap_level(self, cap_level):
        """Insert a timestamped change into the capping_commands table.

        To reflect the cap level on a plot, log the previous cap level at 1ms
        earlier than the new cap level
        """

        sql = 'insert into capping_commands(timestamp, cap_level) values(?, ?);'
        now = datetime.now(UTC)
        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            # If there was an earlier cap level recorded log it as ending just
            # before setting the new level
            if self.previous_cap_level is not None:
                just_before_now = now - timedelta(milliseconds=1)
                data = (just_before_now, self.previous_cap_level)
                db.execute(sql, data)

            data = (now, cap_level)
            db.execute(sql, data)

        self.previous_cap_level = cap_level


if __name__ == "__main__":
    async def main():
        args = runner_config | vars(parse_args())
        if args.get('db_path') is None:
            agent = args.get('agent_url').lstrip('http://').rstrip('/')
            agent = re.sub(r':\d+', '', agent)
            logger.debug(f'Agent: {agent}')
            timestamp = datetime.now().strftime('%a_%d_%b_%Hh%M')
            db_path = f'{agent}_{timestamp}_capping_test.db'
            args['db_path'] = db_path

        logger.info(f"Results database file: {args.get('db_path')}")
        runner_keys = 'bmc_hostname bmc_username bmc_password bmc_type agent_url db_path ipmitool_path'.split()
        runner_args = {k: args.get(k) for k in runner_keys}
        campaign_keys = 'min_load max_load load_delta cap_min cap_max cap_delta'
        campaign_args = {k: args.get(k) for k in campaign_keys}

        runner = Runner(**runner_args)
        collector = Collector(**runner_args)
        await runner.bmc_connect()
        await runner.bmc.activate_capping()
        await collector.bmc_connect()
        await runner.collect_system_information()
        logger.info("Launching collector")
        collect_thread = threading.Thread(target=asyncio.run, args=(collector.start_collect(),))
        collect_thread.start()
        logger.info("Starting campaign")

        await runner.run_campaign(**campaign_args)
        logger.info("Run test ended, halting collector")

        # Log the final cap level
        runner.log_cap_level(runner.previous_cap_level)

        # Wait a while to ensure the collector has samples beyond the
        # end_timestamp of the tests table.
        await asyncio.sleep(3)
        collector.end_collect()
        collect_thread.join()
        logger.info("Collector ended")

    asyncio.run(main())
