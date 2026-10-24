"""Explicit employee decisions for offline test scenarios only."""
import asyncio

async def employee_tool(visitor, call_id, name, parameters, decision='allow'):
    task = asyncio.create_task(visitor.tool(call_id, name, parameters))
    try:
        async with asyncio.timeout(2):
            while not task.done():
                pending = [r for r in visitor.approvals.snapshot() if r['status'] == 'pending']
                if pending:
                    assert not visitor.door.open, 'Door opened before employee confirmation'
                    visitor.approvals.decide(pending[-1]['id'], decision)
                    break
                await asyncio.sleep(0)
        return await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
