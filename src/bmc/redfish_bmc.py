import argparse
import asyncio
import json
from pathlib import Path

import aiohttp

from bmc import BMC

REDFISH_ROOT = '/redfish/v1'
KNOWN_MOTHERBOARDS = {'motherboard', 'self', '1'}


class RedfishBMC(BMC):
    def __init__(self, bmc_hostname: str, bmc_username: str, bmc_password: str):
        super().__init__(bmc_hostname, bmc_username, bmc_password)
        self.token = ''
        self.session_id = None
        self._chassis = None
        self.redfish_root = f'https://{bmc_hostname}{REDFISH_ROOT}'

    async def connect(self):
        """Establish a redfish session."""

        session_endpoint = f'{self.redfish_root}/SessionService/Sessions/'
        credentials = {'UserName': self.bmc_username, 'Password': self.bmc_password}
        async with aiohttp.ClientSession() as session:
            async with session.post(session_endpoint, json=credentials, ssl=False) as r:
                json_body = await r.json()
                if not (200 <= r.status < 300):
                    raise RuntimeError(
                            f'Failed to establish redfish session: {r.headers} {json_body}'
                    )
                self.token = r.headers.get('X-Auth-Token')
                self.session_id = json_body.get('Id')
                print(f'Connect status code: {r.status}')

    async def disconnect(self):
        """Disconnects from a redfish session."""

        disconnect_endpoint = f'{self.redfish_root}/SessionService/Sessions/{self.session_id}'
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.delete(disconnect_endpoint, headers=headers, ssl=False) as r:
                await r.text()
                print(f'Disconnect status code: {r.status}')

    @property
    async def chassis(self) -> [str]:
        """
        Lists all chassis - Finds all the members under REDFISH_ROOT/Chassis.

        Returns list of chassis names, caches the result under self.chassis.
        """

        if self._chassis is not None:
            return self._chassis

        chassis_endpoint = f'{self.redfish_root}/Chassis'
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.get(chassis_endpoint, headers=headers, ssl=False) as r:
                json_body = await r.json()
                if not (200 <= r.status < 300):
                    raise RuntimeError(
                            f'Failed to establish redfish session: {r.headers} {json_body}'
                    )

                print(json.dumps(json_body, sort_keys=True, indent=2))
                # Chassis are held under the '@odata.id' key in the 'Members' array
                paths = [member.get('@odata.id') for member in json_body.get('Members')]
                all_chassis = [str(Path(path).name) for path in paths]
                self.chassis = all_chassis
                return all_chassis

    @chassis.setter
    def chassis(self, value):
        self._chassis = value

    @property
    async def motherboard(self):
        chassis = await self.chassis
        for chassis in chassis:
            if chassis in KNOWN_MOTHERBOARDS:
                return chassis

    @property
    async def current_power(self) -> int:
        """
        Reads the current power draw.

        Returns: Power draw in Watts
        """
        motherboard = await self.motherboard
        power_endpoint = f'{self.redfish_root}/Chassis/{motherboard}/Power'
        headers = {'X-Auth-Token': self.token}
        print(f'Connecting to {power_endpoint}')
        async with aiohttp.ClientSession() as session:
            async with session.get(power_endpoint, headers=headers, ssl=False) as r:
                json_body = await r.json()
                if not (200 <= r.status < 300):
                    raise RuntimeError(
                            f'Failed to establish redfish session: {r.headers} {json_body}'
                    )
                power = json_body.get('PowerControl', [{}])[0].get('PowerConsumedWatts')
                return int(power)

    @property
    async def current_cap_level(self) -> int | None:
        return 0

    async def set_cap_level(self, new_cap_level: int):
        pass

    async def deactivate_capping(self):
        pass


if __name__ == '__main__':

    def parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            prog='IPMI BMC Test tool',
            description='Runs some elementary tests against a bmc',
        )
        parser.add_argument('-H', '--hostname', required=True, help='BMC hostname/ip')
        parser.add_argument('-U', '--username', required=True, help='BMC username')
        parser.add_argument('-P', '--password', required=True, help='BMC password')
        return parser.parse_args()

    async def main(args):
        bmc = RedfishBMC(args.hostname, args.username, args.password)
        print('Connecting')
        try:
            await bmc.connect()
            print('Chassis')
            all_chassis = await bmc.chassis
            for chassis in all_chassis:
                print(' -', chassis)

            power = await bmc.current_power
            print(f'Current power draw: {power}')
        finally:
            print('Disconnecting')
            await bmc.disconnect()

    program_args = parse_args()
    asyncio.run(main(program_args))
