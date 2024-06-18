import os

from BMC import IpmiBMC

bmc_hostname = os.environ.get('BMC_HOSTNAME')
bmc_username = os.environ.get('BMC_USERNAME')
bmc_password = os.environ.get('BMC_PASSWORD')
ipmi_bmc = IpmiBMC(bmc_hostname=bmc_hostname, bmc_username=bmc_username, bmc_password=bmc_password)

print(f'Current power: {ipmi_bmc.current_power}')
