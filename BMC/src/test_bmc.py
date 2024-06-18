import asyncio
import os

from ipmi_bmc import IpmiBMC
from redfish_bmc import RedfishBMC

bmc_hostname = os.environ.get('BMC_HOSTNAME')
bmc_username = os.environ.get('BMC_USERNAME')
bmc_password = os.environ.get('BMC_PASSWORD')
ipmi_bmc = IpmiBMC(bmc_hostname=bmc_hostname, bmc_username=bmc_username, bmc_password=bmc_password)
redfish_bmc = RedfishBMC(bmc_hostname=bmc_hostname, bmc_username=bmc_username, bmc_password=bmc_password)


async def test_ipmi():
    current_power = await ipmi_bmc.current_power
    assert current_power > 0

    current_cap_level = await ipmi_bmc.current_cap_level
    assert current_cap_level is None or current_cap_level > 0

    print(f'IPMI Current power: {await ipmi_bmc.current_power}')


async def main():
    await test_ipmi()


asyncio.run(main())
