import asyncio
import datetime
import logging
import sqlite3
from datetime import datetime as dt, timedelta, UTC

import aiohttp

from BMC import BMC_Type, IpmiBMC, RedfishBMC

logger = logging.getLogger(__name__)


def adapt_timestamp_iso_string(timestamp: datetime.datetime):
    return timestamp.isoformat()


class Collector:
    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_file, ipmitool_path=None):
        self.bmc_hostname = bmc_hostname
        self.agent_url = agent_url if agent_url.startswith('http') else f'http://{agent_url}'
        self.agent_url.rstrip('/')
        self.db_file = db_file
        sqlite3.register_adapter(datetime.date, adapt_timestamp_iso_string)
        sqlite3.register_adapter(datetime.datetime, adapt_timestamp_iso_string)
        self.create_db_tables()

        self.http_session = None

        if bmc_type == BMC_Type.IPMI:
            self.bmc = IpmiBMC(bmc_hostname, bmc_username, bmc_password, ipmitool_path)
        else:
            self.bmc = RedfishBMC(bmc_hostname, bmc_username, bmc_password)

        self.do_collect = True

    def create_db_tables(self):
        create_bmc_table_sql = '''\
        create table if not exists bmc(
            timestamp text primary key, -- ISO8601 strings ("YYYY-MM-DD HH:MM:SS")
            power integer not null check (power > 0), 
            cap_level integer
        );
        '''

        create_rapl_table_sql = '''\
        create table if not exists rapl(
            timestamp text not null, -- ISO8601 strings ("YYYY-MM-DD HH:MM:SS")
            package text not null,
            power integer not null check (power > 0),
            primary key (timestamp, package));'''

        create_system_info_table_sql = '''\
        create table if not exists system_info(
            hostname text not null,
            os_name text not null,
            architecture text not null,
            cpus integer not null,
            threads_per_core integer,
            cores_per_socket integer,
            sockets integer
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
            sys_vendor text);
        '''

        with sqlite3.connect(self.db_file) as db:
            db.execute(create_bmc_table_sql)
            db.execute(create_rapl_table_sql)
            db.execute(create_system_info_table_sql)
            db.execute('commit;')

    async def start_collect(self, freq=1):
        await self.collect_system_information()
        sample_interval = timedelta(seconds=1 / freq)
        next_collect_timestamp = dt.now(UTC)
        with sqlite3.connect(self.db_file) as db:
            while self.do_collect:
                timestamp = dt.now(UTC)
                if (sleep_time := (next_collect_timestamp - timestamp).total_seconds()) > 0:
                    await asyncio.sleep(sleep_time)
                next_collect_timestamp = timestamp + sample_interval

                bmc_sample = await self.sample_bmc()
                agent_sample = await self.sample_agent()
                self.save_sample(db, timestamp, bmc_sample, agent_sample)

    async def connect(self):
        self.http_session = aiohttp.ClientSession()

    async def disconnect(self):
        if self.http_session is not None:
            await self.http_session.close()
            self.http_session = None

    async def end_collect(self):
        self.do_collect = False
        await self.disconnect()

    async def stop_collect(self):
        await self.end_collect()

    async def sample_agent(self):
        endpoint = self.agent_url + '/rapl_power'
        async with aiohttp.ClientSession().get(endpoint) as resp:
            if resp.status < 300:
                rapl_data = await resp.json()
                for d in rapl_data:
                    logger.debug(f'rapl,{d.package},{d.power}')

                return rapl_data
            else:
                logger.error("Failed to get rapl data from agent. Status code: {resp.status}\n{resp}")
                return None

    async def sample_bmc(self):
        bmc_power = await self.bmc.current_power
        bmc_cap_level = await self.bmc.current_cap_level
        return {
            'bmc_power': bmc_power,
            'bmc_cap_level': bmc_cap_level
        }

    async def collect_system_information(self):
        endpoint = self.agent_url + '/system_info'
        async with aiohttp.ClientSession().get(endpoint) as resp:
            print(f"{resp.status=}")
            if resp.status < 300:
                print("inserting into database")
                system_info = await resp.json()
                columns = ",".join(system_info)
                placeholders = ",".join(list("?" * len(system_info)))
                sql = f'insert into system_info ({columns}) values ({placeholders});'
                logger.debug(f'System info sql: {sql}')
                with sqlite3.connect(self.db_file) as db:
                    db.execute(sql, system_info.values)
            else:
                print("** SYSTEM INFO COLLECT FAIL **")
                logger.error("Failed to get system information. Status code: {resp.status}\n{resp}")

    def save_sample(self, db, timestamp, bmc_sample, agent_sample):
        self.save_bmc_sample(db, timestamp, bmc_sample)
        self.save_agent_sample(db, timestamp, agent_sample)

    @staticmethod
    def save_bmc_sample(db, timestamp, bmc_sample):
        sql = 'insert into bmc(timestamp, power, cap_level) values(?, ?, ?);'
        data = [timestamp, bmc_sample.bmc_power, bmc_sample.bmc_cap_level]
        db.execute(sql, data)
        logger.debug(f'bmc,{timestamp},{bmc_sample.bmc_power}{bmc_sample.bmc_cap_level}')

    @staticmethod
    def save_agent_sample(db, timestamp, agent_sample):
        data = [[timestamp, package, power] for package, power in agent_sample]
        sql = 'insert into rapl(timestamp, package, power) values (?, ? ?);'
        db.executemany(sql, data)
