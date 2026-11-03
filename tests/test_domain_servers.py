import tomllib

from mcp.client import Client

from commonwealth.cli import configure
from commonwealth.core.registry import OperationalState
from commonwealth.core.skills import load_skills
from commonwealth.runtime import SKILLS_DIR
from commonwealth.servers.build import build_server
from tests.conftest import build_ctx


def test_both_domain_servers_can_be_installed_alongside_the_existing_server():
    client = configure.CLIENTS["claude-code"]
    doc = {"mcpServers": {"private": {"command": "mine"}}}
    for profile in ("all", "geo", "civic", "geo"):
        doc = configure.merged(doc, client, profile)
    servers = doc[client.key]
    assert servers["private"] == {"command": "mine"}
    for name, profile in [("commonwealth", "all"), ("commonwealth-civic", "civic"),
                          ("commonwealth-geo", "geo")]:
        assert servers[name]["args"][-3:] == ["serve", "--profile", profile]
        block = tomllib.loads(configure.render_toml_block(profile))
        assert block["mcp_servers"][name] == servers[name]


async def test_specialized_servers_offer_their_domain_and_shared_discovery():
    ctx = build_ctx()
    for profile in ("geo", "civic"):
        async with Client(build_server(ctx, profile)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
        assert {n.partition(".")[0] for n in names} == {"registry", profile}
        assert "registry.search_sources" in names
    assert ctx.server_name == "commonwealth"


async def test_client_can_discover_and_read_every_shipped_skill_without_installing_it():
    skills = load_skills(SKILLS_DIR)
    async with Client(build_server(build_ctx(), "all")) as client:
        prompts = {p.name: p for p in (await client.list_prompts()).prompts}
        assert set(prompts) == {s.name for s in skills}
        for skill in skills:
            assert prompts[skill.name].description == skill.description
            args = {"question": "Which record supports this?"} if skill.accepts_question else {}
            assert [a.name for a in (prompts[skill.name].arguments or [])] == list(args)
            messages = (await client.get_prompt(skill.name, args)).messages
            assert messages[0].content.text.startswith(skill.body)
            assert not messages[0].content.text.startswith("---")
            if args:
                assert messages[1].content.text == args["question"]
        templates = (await client.list_resource_templates()).resource_templates
        assert {str(t.uri_template) for t in templates} == {
            "commonwealth://results/{result_id}", "commonwealth://evidence/{result_id}"}


async def test_prompt_explains_a_registry_gap_and_a_profile_gap_independently():
    ctx = build_ctx()
    for sid in ("va-alexandria-city-meetings", "va-richmond-city-meetings"):
        ctx.sources.set_operational(sid, OperationalState.unavailable)
    async with Client(build_server(ctx, "geo")) as client:
        prompt = await client.get_prompt("recorded-vote-check", {"question": "Who voted?"})
        walk = prompt.messages[0].content.text
        assert "No active source currently answers:" in walk
        assert "Profile 'geo' omits" in walk
