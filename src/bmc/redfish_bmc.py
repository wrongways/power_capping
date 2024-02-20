import argparse
import asyncio

import aiohttp

from bmc import BMC

REDFISH_ROOT = '/redfish/v1'


class RedfishBMC(BMC):
    def __init__(self, bmc_hostname: str, bmc_username: str, bmc_password: str):
        super().__init__(bmc_hostname, bmc_username, bmc_password)
        self.token = ''
        self.session_id = None
        self.motherboard_path = None  # includes self.redfish_root
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

    async def identify_motherboard(self):
        """
        Finds the redfish path to the motherboard.

        Known motherboards are 'motherboard', 'self', and '1'.
        GPU boards are not managed.
        """

        chassis_endpoint = f'{self.redfish_root}/Chassis'
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.get(chassis_endpoint, headers=headers, ssl=False) as r:
                json_body = await r.json()
                if not (200 <= r.status < 300):
                    raise RuntimeError(
                            f'Failed to establish redfish session: {r.headers} {json_body}'
                    )

                # Chassis are held under the '@odata.id' key in the 'Members' array
                paths = [member.get('@odata.id') for member in json_body.get('Members')]
                known_boards = {'motherboard', 'self', '1'}
                for path in paths:
                    if path.lower() in known_boards:
                        self.motherboard_path = f'{chassis_endpoint}/{path}'
                        break

    @property
    async def current_power(self) -> int:
        """
        Reads the current power draw.

        Returns: Power draw in Watts
        """
        motherboard_endpoint = f'{self.motherboard_path}/Power}
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.get(motherboard_endpoint, headers=headers, ssl=False) as r:
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
        await bmc.connect()
        power = await bmc.current_power
        print(f'Current power draw: {power}')
        print('Disconnecting')
        await bmc.disconnect()

    program_args = parse_args()
    asyncio.run(main(program_args))
