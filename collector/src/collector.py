import asyncio
import atexit
import sqlite3
from datetime import datetime as dt, timedelta, UTC

from ..bmc import BMC_Type, IpmiBMC, RedfishBMC


class Collector:
    def __init__(self, bmc_hostname, bmc_username, bmc_password, bmc_type, agent_url, db_file, ipmitool_path=None):
        self.bmc_hostname = bmc_hostname
        self.agent_url = agent_url
        self.db_file = db_file
        self.db = sqlite3.connect(db_file)
        self.do_collect = True

        if bmc_type == BMC_Type.IPMI:
            self.bmc = IpmiBMC(bmc_hostname, bmc_username, bmc_password, ipmitool_path)
        else:
            self.bmc = RedfishBMC(bmc_hostname, bmc_username, bmc_password)

        atexit.register(self.db.close)

    async def start_collect(self, freq=1):
        sample_interval = timedelta(seconds=1 / freq)
        next_collect_timestamp = dt.now(UTC)
        while self.do_collect:
            timestamp = dt.now(UTC)
            if (sleep_time := (next_collect_timestamp - timestamp).total_seconds()) > 0:
                await asyncio.sleep(sleep_time)
            next_collect_timestamp = timestamp + sample_interval

            bmc_sample = await self.sample_bmc()
            agent_sample = await self.sample_agent()
            self.save_sample(timestamp, bmc_sample, agent_sample)

    def end_collect(self):
        self.do_collect = False

    async def sample_agent(self):
        pass

    async def sample_bmc(self):
        bmc_power = await self.bmc.current_power
        bmc_cap_level = await self.bmc.current_cap_level
        return {
            'bmc_power': bmc_power,
            'bmc_cap_level': bmc_cap_level
        }

    def save_sample(self, timestamp, bmc_sample, agent_sample):
        self.save_bmc_sample(timestamp, bmc_sample)
        self.save_agent_sample(timestamp, agent_sample)

    def save_bmc_sample(self, timestamp, bmc_sample):
        print(f'bmc,{timestamp},{bmc_sample.bmc_power}{bmc_sample.bmc_cap_level}')

    def save_agent_sample(self, timestamp, agent_sample):
        for package, power in agent_sample:
            print(f'rapl,{timestamp},{package},{power}')
