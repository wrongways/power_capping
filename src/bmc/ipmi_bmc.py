import argparse
import asyncio
import json
from enum import Enum

from bmc import BMC, Result


class IPMI_COMMAND(str, Enum):
    GET_DCMI_POWER = 'dcmi power reading'
    GET_DCMI_POWER_CAP = 'dcmi power get limit'
    SET_DCMI_POWER_CAP = 'dcmi power set_limit limit'
    ACTIVATE_CAPPING = 'dcmi power activate'


class IPMI_BMC(BMC):
    def __init__(
        self, bmc_hostname: str, bmc_username: str, bmc_password: str, ipmitool_path: str
    ):
        super().__init__(bmc_hostname, bmc_username, bmc_password)
        self.ipmitool = ipmitool_path
        self.command_prefix = f'-H {bmc_hostname} -U {bmc_username} -P {bmc_password}'
        print(f'ipmi prefix: {self.command_prefix}')

    @property
    async def current_power(self) -> float:
        impi_power_tag = 'Instantaneous power reading'
        result = await self.run_ipmi_command(IPMI_COMMAND.GET_DCMI_POWER)
        if not result.ok:
            self.panic(IPMI_COMMAND.GET_DCMI_POWER, result)
        else:
            return float(result.bmc_dict[impi_power_tag])

    @property
    async def current_cap_level(self) -> float | None:
        result = await self.run_ipmi_command(IPMI_COMMAND.GET_DCMI_POWER_CAP)
        if not result.ok:
            self.panic(IPMI_COMMAND.GET_DCMI_POWER, result)

        if result.bmc_dict.get('Current Limit State') == 'No Active Power Limit':
            return None
        else:
            power_limit_string: str = result.bmc_dict.get('Power Limit')
            cap_value, _ = power_limit_string.split()
            return float(cap_value)

    async def set_cap_level(self, new_cap_level: float):
        set_cap_cmd = f'{IPMI_COMMAND.SET_DCMI_POWER_CAP} {new_cap_level}'
        result = await self.run_ipmi_command(set_cap_cmd)
        if not result.ok:
            self.panic(set_cap_cmd, result)

    async def activate_capping(self):
        print('activating capping')
        result = await self.run_ipmi_command(IPMI_COMMAND.ACTIVATE_CAPPING)
        if not result.ok:
            self.panic(IPMI_COMMAND.ACTIVATE_CAPPING, result)

    async def run_ipmi_command(self, command: IPMI_COMMAND) -> Result:
        command_args = f'{self.command_prefix} {command.value}'
        program = self.ipmitool

        print(f'running {program} {command_args} – from {command}')

        # LANG must be set to 'en_US' to parse the output
        env = {'LANG': 'en_US.UTF-8'}
        stdout = asyncio.subprocess.PIPE
        stderr = asyncio.subprocess.PIPE
        proc = await asyncio.create_subprocess_exec(
            program, command_args, stdout=stdout, stderr=stderr, env=env
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            return Result(ok=False, stdout=stdout, stderr=stderr, args=command_args)
        else:
            ipmi_fields = {
                f[0].strip(): f[1].strip()
                for f in [line.split(':') for line in stdout.splitlines()]
                if len(f) == 2
            }
            return Result(ok=True, bmc_dict=ipmi_fields)

    def panic(self, command: str, result: Result):
        msg = f'{self.ipmitool} {self.command_prefix} {command} command failed\n'
        f'stderr: {result.stderr}\n'
        f'stdout: {result.stdout}\n'
        'bmc_dict:\n' + json.dumps(result.bmc_dict, indent=2, sort_keys=True)
        raise RuntimeError(msg)


if __name__ == '__main__':

    def parse_args():
        parser = argparse.ArgumentParser(
            prog='IPMI BMC Test tool',
            description='Runs some elementary tests against a bmc',
        )

        parser.add_argument('-H', '--hostname', required=True, help='BMC hostname/ip')
        parser.add_argument('-U', '--username', required=True, help='BMC username')
        parser.add_argument('-P', '--password', required=True, help='BMC password')
        parser.add_argument(
                '-i',
                '--ipmitool',
                default='/usr/bin/ipmitool',
                help='Full path to the ipmitool executable',
        )

        return parser.parse_args()


    async def main(args):
        bmc = IPMI_BMC(args.hostname, args.username, args.password, args.ipmitool)
        await bmc.activate_capping()
        print(await bmc.current_power)

args = parse_args()
asyncio.run(main(args))
