import asyncio
import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, UTC

import aiohttp

from BMC import BMC_Type, IpmiBMC, RedfishBMC

logging.basicConfig(level='DEBUG')
logger = logging.getLogger(__name__)


class Collector:
    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_path, ipmitool_path=None):
        self.bmc_hostname = bmc_hostname
        self.agent_url = agent_url if agent_url.startswith('http') else f'http://{agent_url}'
        self.agent_url.rstrip('/')
        self.db_path = db_path
        sqlite3.register_adapter(date, lambda timestamp: timestamp.isoformat(timespec='milliseconds'))
        sqlite3.register_adapter(datetime, lambda timestamp: timestamp.isoformat(timespec='milliseconds'))
        self.create_db_tables()

        self.http_session = None

        if bmc_type == BMC_Type.IPMI:
            self.bmc = IpmiBMC(bmc_hostname, bmc_username, bmc_password, ipmitool_path)
        else:
            self.bmc = RedfishBMC(bmc_hostname, bmc_username, bmc_password)

        self.do_collect = True

    async def bmc_connect(self):
        if isinstance(self.bmc, RedfishBMC):
            await self.bmc.connect()

    def bmc_type(self):
        return "redfish" if isinstance(self.bmc, RedfishBMC) else "ipmi"

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
                power float not null check (power > 0),
                primary key (timestamp, package)
            );
            '''

        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            db.execute(create_bmc_table_sql)
            db.execute(create_rapl_table_sql)

    async def start_collect(self, freq=1):

        sample_interval = timedelta(seconds=1 / freq)
        next_collect_timestamp = datetime.now(UTC)

        while self.do_collect:
            timestamp = datetime.now(UTC)
            if (sleep_time := (next_collect_timestamp - timestamp).total_seconds()) > 0:
                await asyncio.sleep(sleep_time)
            next_collect_timestamp = timestamp + sample_interval

            bmc_sample = await self.sample_bmc()
            agent_sample = await self.sample_agent()
            self.save_sample(timestamp, bmc_sample, agent_sample)
            logger.debug(json.dumps(bmc_sample, indent=3))
            logger.debug(json.dumps(agent_sample, indent=3))

    def end_collect(self):
        logger.debug("Stopping Collection")
        self.do_collect = False
        logger.debug(f"{self.do_collect=}")

    async def sample_agent(self):
        endpoint = self.agent_url + '/rapl_power'
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint) as resp:
                if resp.status < 300:
                    rapl_data = await resp.json()
                    logger.debug(f'{rapl_data=}')
                    print(f'{rapl_data=}')
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

    def save_sample(self, timestamp, bmc_sample, agent_sample):
        with sqlite3.connect(self.db_path, check_same_thread=False) as db:
            self.save_bmc_sample(db, timestamp, bmc_sample)
            self.save_agent_sample(db, timestamp, agent_sample)

    @staticmethod
    def save_bmc_sample(db, timestamp, bmc_sample):
        logger.debug(f'save_bmc_sample: {bmc_sample}')
        sql = 'insert into bmc(timestamp, power, cap_level) values(?, ?, ?);'
        data = (timestamp, bmc_sample.get('bmc_power'), bmc_sample.get('bmc_cap_level'))
        logger.debug(f'save_bmc_sample: {data=}')
        db.execute(sql, data)

    @staticmethod
    def save_agent_sample(db, timestamp, agent_sample):
        logger.debug(f'save_agent_sample: {agent_sample}')
        data = [[timestamp, package, power] for package, power in agent_sample.items()]
        sql = 'insert into rapl(timestamp, package, power) values (?, ?, ?);'
        db.executemany(sql, data)
