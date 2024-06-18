import asyncio
import os

from ipmi_bmc import IpmiBMC
from redfish_bmc import RedfishBMC


async def main():
    bmc_hostname = os.environ.get('BMC_HOSTNAME')
    bmc_username = os.environ.get('BMC_USERNAME')
    bmc_password = os.environ.get('BMC_PASSWORD')
    ipmi_bmc = IpmiBMC(bmc_hostname=bmc_hostname, bmc_username=bmc_username, bmc_password=bmc_password)
    redfish_bmc = RedfishBMC(bmc_hostname=bmc_hostname, bmc_username=bmc_username, bmc_password=bmc_password)

    print(f'IPMI Current power: {await ipmi_bmc.current_power}')
    print(f'Redfish Current power: {await redfish_bmc.current_power}')


asyncio.run(main())
