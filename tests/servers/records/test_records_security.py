import json

import pytest

from commonwealth.adapters.public_records import ORDER_FIELDS
from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.records import (find_permit_outfalls, get_bill, get_bill_votes,
                                           get_election_results, search_purchases)
from commonwealth.fixtures import replay_context


@pytest.mark.parametrize("fn,args", [(get_bill, ("../", "HB1600")), (get_bill, ("20251", "../HB")),
    (get_bill_votes, ("20251", "HB1600", "/elsewhere")), (search_purchases, ()),
    (get_election_results, ("20211102", "Governor", "Virginia")),
    (get_election_results, ("2021-11-02", "Governor", "Virginia")),
    (find_permit_outfalls, ("Richmond City", -77, 37, 10001))])
async def test_invalid_inputs_rejected_before_fetch(fn, args):
    with pytest.raises(InvalidQuery):
        await fn(replay_context([]), *args)


async def test_purchase_filter_is_data_and_projection_excludes_contact_fields(monkeypatch):
    ctx = replay_context([])
    literal = "Vendor' OR 1=1"
    async def page(url, params):
        assert json.loads(params["filters"]) == {"Vendor_Name": literal}
        assert params["offset"] == 25 and params["limit"] == 26
        rows = [{**dict.fromkeys(ORDER_FIELDS), "_id": i, "private_address": "unexpected"} for i in range(26)]
        return {"success": True, "result": {"records": rows}}
    monkeypatch.setattr(ctx.public_records.fetcher, "fetch_json", page)
    result = await search_purchases(ctx, vendor=literal, offset=25)
    block = result.data["results"][0]
    assert block["next_offset"] == 50 and len(block["records"]) == 25
    assert all("private_address" not in r for r in block["records"])
