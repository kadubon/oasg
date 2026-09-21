"""Installed-facing commands keep inspection inert and errors structured."""

from importlib.resources import files

from typer.testing import CliRunner

from oasg.cli import app
from oasg.collective import api
from oasg.collective.schemas import schema_documents
from oasg.collective.wire import encoded, loads
from test_collective import contract_key, sources


def test_packaged_additive_schemas():
    for name, schema in schema_documents().items():
        resource = files("oasg.collective").joinpath(
            "resources/collective-" + name + ".schema.json"
        )
        assert loads(resource.read_bytes()) == schema
        assert schema["additionalProperties"] is False
        assert schema["$id"].startswith("urn:oasg:collective:")
    assert api.Contract is not None


def test_cli_read_and_check(tmp_path):
    runner = CliRunner()
    contract, key, public = contract_key()
    pair = sources(contract, key)
    cpath, spath, rpath = [
        tmp_path / name for name in ("contract.json", "source.json", "report.json")
    ]
    cpath.write_bytes(encoded(contract))
    spath.write_bytes(encoded(pair[1]))
    result = runner.invoke(app, ["collective", "inspect", str(cpath)])
    assert result.exit_code == 0, result.output
    assert loads(result.output.encode())["execution_authorization"] is False
    result = runner.invoke(app, ["collective", "project", str(cpath), str(spath), public.hex()])
    assert result.exit_code == 0, result.output
    rpath.write_text(result.output, encoding="utf-8")
    result = runner.invoke(app, ["collective", "check", str(cpath), str(rpath), public.hex()])
    assert result.exit_code == 0, result.output
    rpath.write_bytes(encoded(api.compare(contract, *pair, public)))
    result = runner.invoke(app, ["collective", "check", str(cpath), str(rpath), public.hex()])
    assert result.exit_code == 0, result.output
    assert loads(result.output.encode())["local_gate_status"] == "safe_promotion"
    result = runner.invoke(
        app, ["collective", "project", str(cpath), str(spath), "invalid-public-key"]
    )
    assert result.exit_code == 2
    assert loads(result.output.encode())["status"] == "rejected"


def test_cli_no_implicit_initialization(tmp_path):
    runner = CliRunner()
    root = tmp_path / "absent"
    for arguments in (
        ["status", str(root)],
        ["replay", str(root)],
        ["example", "--out", str(root)],
        ["reconcile", str(root)],
    ):
        result = runner.invoke(app, ["collective", *arguments])
        assert result.exit_code == 0, result.output
        assert not root.exists()
    result = runner.invoke(app, ["collective", "support"])
    assert result.exit_code == 0, result.output
    assert not loads(result.output.encode())["execution_authorization"]


def test_interrupted_execution_is_structured_and_not_retried(tmp_path, monkeypatch):
    from oasg.collective import runtime

    calls = []

    def interrupted(root):
        calls.append(root)
        raise RuntimeError("selected crash control")

    monkeypatch.setattr(runtime, "example", interrupted)
    result = CliRunner().invoke(
        app, ["collective", "example", "--out", str(tmp_path / "unused"), "--execute"]
    )
    assert result.exit_code == 2
    assert loads(result.output.encode())["status"] == "execution_interrupted"
    assert len(calls) == 1


def test_nonobject_report_is_structured_rejection(tmp_path):
    contract, _, public = contract_key()
    cpath, rpath = tmp_path / "contract.json", tmp_path / "report.json"
    cpath.write_bytes(encoded(contract))
    rpath.write_text("[]", encoding="utf-8")
    result = CliRunner().invoke(app, ["collective", "check", str(cpath), str(rpath), public.hex()])
    assert result.exit_code == 2
    assert loads(result.output.encode())["status"] == "rejected"
