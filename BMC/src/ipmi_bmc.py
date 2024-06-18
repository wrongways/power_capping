"""Concrete implementation of the BMC abstract class for IPMI BMCs."""

import argparse
import asyncio
from enum import Enum
from typing import NamedTuple

from bmc import BMC


class Result(NamedTuple):
    """Result type from running IPMI command."""

    ok: bool
    stdout: str | None = None
    stderr: str | None = None
    args: str | None = None
    bmc_dict: {str: str} = {}


class IPMI_COMMAND(str, Enum):
    """Enum for the IPMI DCMI power commands."""
    GET_DCMI_POWER = 'dcmi power reading'
    GET_DCMI_POWER_CAP = 'dcmi power get_limit'
    SET_DCMI_POWER_CAP = 'dcmi power set_limit limit'
    ACTIVATE_CAPPING = 'dcmi power activate'
    DEACTIVATE_CAPPING = 'dcmi power deactivate'


class IpmiBMC(BMC):
    """Concrete implementation of the abstract BMC base class using IPMI/DCMI POWER."""
    def __init__(
            self, bmc_hostname: str, bmc_username: str, bmc_password: str, ipmitool_path='/usr/bin/ipmitool'
    ):
        """Constructor.
        
        @param bmc_hostname: hostname or ip address of bmc
        @param bmc_username: username with rights to access DCMI power.
        @param bmc_password: password for bmc user
        @param ipmitool_path: the fully qualified path the ipmitool executable
        """
        super().__init__(bmc_hostname, bmc_username, bmc_password)
        self.ipmitool = ipmitool_path
        self.command_prefix = f'-H {bmc_hostname} -U {bmc_username} -P {bmc_password}'

    @property
    async def current_power(self) -> int:
        """Return the instantaneous power draw."""
        impi_power_tag = 'Instantaneous power reading'
        result = await self.run_ipmi_command(IPMI_COMMAND.GET_DCMI_POWER.value)
        if not result.ok:
            self.panic(IPMI_COMMAND.GET_DCMI_POWER.value, result)
        else:
            # Value comes back as “300 Watts” - just need the integer part
            return int(result.bmc_dict[impi_power_tag].split()[0])

    @property
    async def current_cap_level(self) -> int | None:
        """Return the current power cap level (in Watts)."""
        result = await self.run_ipmi_command(IPMI_COMMAND.GET_DCMI_POWER_CAP.value)
        if not result.ok:
            self.panic(IPMI_COMMAND.GET_DCMI_POWER.value, result)

        if result.bmc_dict.get('Current Limit State') == 'No Active Power Limit':
            return None
        else:
            power_limit_string: str = result.bmc_dict.get('Power Limit')
            cap_value, _ = power_limit_string.split()
            return int(cap_value)

    async def set_cap_level(self, new_cap_level: int):
        """Set the cap level to new_cap_level Watts.

        @param new_cap_level: The power cap level to set (in Watts).
        """
        set_cap_cmd = f'{IPMI_COMMAND.SET_DCMI_POWER_CAP.value} {new_cap_level}'
        result = await self.run_ipmi_command(set_cap_cmd)
        if not result.ok:
            self.panic(set_cap_cmd, result)

    async def activate_capping(self):
        """Activate capping."""
        print('activating capping')
        result = await self.run_ipmi_command(IPMI_COMMAND.ACTIVATE_CAPPING.value)
        if not result.ok:
            self.panic(IPMI_COMMAND.ACTIVATE_CAPPING.value, result)

    async def deactivate_capping(self):
        """Deactivate capping."""
        print('deactivating capping')
        result = await self.run_ipmi_command(IPMI_COMMAND.DEACTIVATE_CAPPING.value)
        if not result.ok:
            self.panic(IPMI_COMMAND.ACTIVATE_CAPPING.value, result)

    @property
    async def capping_is_active(self) -> bool:
        """Returns boolean indicating if capping is active."""
        cap_level = await self.current_cap_level
        return cap_level is not None

    async def run_ipmi_command(self, command: str) -> Result:
        """Method to run any ipmi command and collect the result in a Result class.

        @param command: string containing the ipmitool command.
        @return Result: result structure capturing stdout and stderr
        """
        command_args = f'{self.command_prefix} {command}'
        program = self.ipmitool

        print(f'running {program} {command_args}')

        # LANG must be set to 'en_US' to parse the output
        env = {'LANG': 'en_US.UTF-8'}
        stdout = asyncio.subprocess.PIPE
        stderr = asyncio.subprocess.PIPE
        proc = await asyncio.create_subprocess_exec(
                program, *command_args.split(), stdout=stdout, stderr=stderr, env=env
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            return Result(
                    ok=False,
                    stdout=stdout.decode('ascii'),
                    stderr=stderr.decode('ascii'),
                    args=command_args,
            )
        else:
            ipmi_fields = {
                f[0].strip(): f[1].strip()
                for f in [line.split(':') for line in stdout.decode('ascii').splitlines()]
                if len(f) == 2
            }
            return Result(ok=True, bmc_dict=ipmi_fields)

    def panic(self, command: str, result: Result):
        """Throw RuntimeError exception with formatted message."""
        msg = f"""{self.ipmitool} {self.command_prefix} {command} command failed\n
        stderr: {result.stderr}\
        stdout: {result.stdout}\
        bmc_dict:\n' + json.dumps(result.bmc_dict, indent=2, sort_keys=True)
        """
        raise RuntimeError(msg)


if __name__ == '__main__':

    def parse_args() -> argparse.Namespace:
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
        bmc = IpmiBMC(args.hostname, args.username, args.password, args.ipmitool)
        # await bmc.activate_capping()
        print(await bmc.current_power)
        print(await bmc.current_cap_level)
        await bmc.set_cap_level(600)

    program_args = parse_args()
    asyncio.run(main(program_args))
