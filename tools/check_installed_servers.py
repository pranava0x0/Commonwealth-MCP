"""Build a wheel, install it outside the checkout, and exercise both MCP servers."""
import asyncio
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import venv


async def probe(profile: str, expected_tool: str, prompt: str, question: str | None = None) -> None:
    # These imports run only in the environment containing the installed wheel.
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters

    name = f"commonwealth-{profile}"
    scripts = Path(sysconfig.get_path("scripts"))
    executable = scripts / (name + ".exe" if sys.platform == "win32" else name)
    server = StdioServerParameters(
        command=str(executable),
        env={"COMMONWEALTH_DENY_NETWORK": "1", "XDG_STATE_HOME": str(Path.cwd() / "state")},
    )
    async with asyncio.timeout(45), Client(server) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert expected_tool in tools, (name, tools)
        assert {tool.partition(".")[0] for tool in tools} == {profile, "registry"}, (name, tools)

        prompts = {item.name: item for item in (await client.list_prompts()).prompts}
        arguments = {"question": question} if question is not None else {}
        assert {arg.name for arg in prompts[prompt].arguments or []} == set(arguments), name
        messages = (await client.get_prompt(prompt, arguments)).messages
        assert prompt.replace("-", " ") in messages[0].content.text.lower(), name
        if question is not None:
            assert messages[-1].content.text == question, name

        result = await client.call_tool("registry.resolve_jurisdiction", {"query": "Richmond City"})
        assert not result.is_error, result.content
        assert result.structured_content["_execution"]["server"] == name, result.structured_content
        assert result.structured_content["data"]["resolved"]["id"] == "va:richmond-city"
        print(f"{name}: {len(tools)} tools, {prompt} loaded, Richmond City resolved")


async def check_both() -> None:
    await probe("civic", "civic.get_meeting_agenda", "recorded-vote-check", "Who voted?")
    await probe("geo", "geo.find_parcel", "parcel-zoning-screen")


def check_wheel() -> None:
    script = Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix="commonwealth-wheel-") as scratch:
        cwd = Path(scratch)
        env = cwd / "venv"
        venv.EnvBuilder(with_pip=True).create(env)
        python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        pip = [str(python), "-I", "-m", "pip"]
        subprocess.run([*pip, "wheel", "--no-deps", str(script.parents[1])], cwd=cwd, check=True)
        (wheel,) = cwd.glob("commonwealth_mcp-*.whl")
        subprocess.run([*pip, "install", str(wheel)], cwd=cwd, check=True)
        subprocess.run([str(python), "-I", str(script), "--probe"], cwd=cwd, check=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        asyncio.run(check_both())
    else:
        check_wheel()
