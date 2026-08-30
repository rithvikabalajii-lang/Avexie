"""Exercise successful, network-blocked, and resource-limited Judge0 submissions."""

from __future__ import annotations

import asyncio
import json

from avexie.tools.run_code import run_code


async def main() -> None:
    normal = await run_code('python', 'print(6 * 7)')
    assert normal['exit_code'] == 0 and normal['stdout'].strip() == '42'

    network = await run_code(
        'python',
        """import socket
s = socket.socket()
s.settimeout(1)
try:
    s.connect(('1.1.1.1', 443))
    print('EGRESS_ALLOWED')
except Exception as error:
    print('EGRESS_BLOCKED', type(error).__name__)
""",
    )
    assert 'EGRESS_BLOCKED' in network['stdout']
    assert 'EGRESS_ALLOWED' not in network['stdout']

    limited = await run_code(
        'python',
        'while True:\n    pass',
        limits={'cpu_time': 0.5, 'wall_time': 2.0},
    )
    assert limited['timed_out'] or limited['status_id'] in {5, 13}

    print(json.dumps({
        'status': 'passed',
        'normal_execution': normal,
        'network_isolation': network,
        'resource_limit': limited,
        'external_calls': 0,
    }, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
