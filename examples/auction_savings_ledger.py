# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Auction Savings Ledger - a worked consumer example for
ReverseAuctionTaskboard. Contains NONE of the primitive's own machinery: no
exec_prompt, no eq_principle, and no web fetching anywhere in this file.

What it does: anyone permissionlessly registers a pointer here --
(task_address, display_name) -- against a live ReverseAuctionTaskboard
instance. This ledger never re-judges anything and never trusts the
pointer's implied outcome; every read pulls the referenced task's own
`get_task_state` view live, reporting how much of the original max_budget
was actually saved by the auction (max_budget minus the winning bid) once
the task completes -- so a savings figure cannot be forged for a task that
never actually finished, or for an address that was never actually deployed
as a task at all.

Complete integration surface used here (<=10 lines):

    task = gl.get_contract_at(task_address)
    state = task.view().get_task_state()
    completed = state["status"] == 3
    saved = state["max_budget"] - state["winning_amount"] if completed else 0
"""

from genlayer import *


@gl.contract_interface
class IReverseAuctionTaskboard:
    class View:
        def get_task_state(self) -> dict: ...

    class Write:
        pass


STATUS_COMPLETED = 3

MAX_NAME_CHARS = 80
MAX_ENTRIES = 500


@allow_storage
class Entry:
    task_address: Address
    display_name: str
    registrant: Address


class AuctionSavingsLedger(gl.Contract):
    """
    A read-side directory over one or more independently-deployed
    ReverseAuctionTaskboard instances. Registering an entry is a purely
    deterministic write: it stores a label and a pointer, and never
    verifies the referenced task actually exists, because that would
    require calling back into the task during a write. This ledger's only
    consequential decision (how much the auction actually saved) is made
    later, at read time, straight off the task's own live state.
    """

    entries: TreeMap[u256, Entry]
    next_entry_id: u256

    def __init__(self) -> None:
        self.next_entry_id = u256(0)

    @gl.public.write
    def register_entry(self, task_address: str, display_name: str) -> u256:
        if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > MAX_NAME_CHARS:
            raise gl.vm.UserError("EXPECTED: display_name required, 1-80 chars")

        addr = task_address if isinstance(task_address, Address) else Address(task_address)
        if bytes(addr.as_bytes) == b"\x00" * Address.SIZE:
            raise gl.vm.UserError("EXPECTED: task_address must not be the zero address")

        if int(self.next_entry_id) >= MAX_ENTRIES:
            raise gl.vm.UserError(f"EXPECTED: ledger is at capacity ({MAX_ENTRIES} entries)")

        entry_id = self.next_entry_id
        self.next_entry_id = u256(int(self.next_entry_id) + 1)

        entry = self.entries.get_or_insert_default(entry_id)
        entry.task_address = addr
        entry.display_name = display_name.strip()[:MAX_NAME_CHARS]
        entry.registrant = gl.message.sender_address if isinstance(gl.message.sender_address, Address) else Address(gl.message.sender_address)

        return entry_id

    @gl.public.view
    def savings_report(self, entry_id: u256) -> dict:
        entry = self.entries.get(entry_id)
        if entry is None:
            return {"exists": False}

        task = IReverseAuctionTaskboard(entry.task_address)
        try:
            state = task.view().get_task_state()
        except Exception:  # noqa: BLE001 -- not a real task at all
            return {
                "exists": True,
                "display_name": str(entry.display_name),
                "note": "pointer does not reference a real task",
                "completed": False,
                "saved": -1,
            }

        completed = int(state["status"]) == STATUS_COMPLETED
        saved = int(state["max_budget"]) - int(state["winning_amount"]) if completed else 0
        return {
            "exists": True,
            "display_name": str(entry.display_name),
            "completed": completed,
            "max_budget": int(state["max_budget"]),
            "winning_amount": int(state["winning_amount"]) if completed else 0,
            "saved": saved,
        }

    @gl.public.view
    def get_entry_count(self) -> u256:
        return self.next_entry_id
