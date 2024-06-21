import asyncio
import os
import threading

from BMC import BMC_Type
from Collector import Collector

bmc_hostname = os.environ.get('BMC_HOSTNAME')
bmc_username = os.environ.get('BMC_USERNAME')
bmc_password = os.environ.get('BMC_PASSWORD')


async def test_ipmi():
    sleep_time = 10
    collector = Collector(bmc_hostname, bmc_username, bmc_password, BMC_Type.IPMI, 'http://t3r1nod23:5432',
                          'collector_test.db')
    collect_thread = threading.Thread(target=asyncio.run, args=(collector.start_collect(),))
    collect_thread.start()
    print("Started collect thread, sleeping for {sleep_time} seconds")
    await asyncio.sleep(sleep_time)
    await collector.end_collect()
    collect_thread.join()


async def main():
    await test_ipmi()


asyncio.run(main())
