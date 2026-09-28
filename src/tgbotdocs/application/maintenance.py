"""Resource-lifetime cleanup retries, independent of user activity."""

import asyncio


async def cleanup_sweep(lifecycle, interval_s=60.0):
    while True:
        await asyncio.sleep(interval_s)
        await lifecycle.retry_pending()


async def stop_task(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
