import asyncio
import os

from ipmi_bmc import IpmiBMC

bmc_hostname = os.environ.get('BMC_HOSTNAME')
bmc_username = os.environ.get('BMC_USERNAME')
bmc_password = os.environ.get('BMC_PASSWORD')
ipmi_bmc = IpmiBMC(bmc_hostname=bmc_hostname, bmc_username=bmc_username, bmc_password=bmc_password)


async def main():
    print(f'Current power: {await ipmi_bmc.current_power}')


asyncio.run(main())
