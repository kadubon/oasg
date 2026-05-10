# Framework Adapter Patterns

These examples show how OASG can sit beside existing agent frameworks without competing with them.
They add no mandatory dependencies and perform no network calls by default.

The pattern is always the same:

1. let the framework run the agent workflow;
2. convert model/tool/task output into OASG observation events;
3. append those events to an OASG JSONL ledger;
4. use OASG trial ledgers and gates for workflow-policy promotion.

Framework output is observation only. It is not a positive promotion witness by itself.

## Examples

- `plain_python_adapter.py`: wrap a normal Python function or model wrapper.
- `langgraph_adapter.py`: LangGraph owns durable execution; OASG owns promotion gates.
- `crewai_adapter.py`: CrewAI owns crew/task execution; OASG observes outcomes and gates policy
  changes outside the crew.

Run the plain Python example:

```bash
uv run python examples/framework_adapters/plain_python_adapter.py --out examples/framework_adapters/out/plain_python.jsonl
uv run oasg ledger verify examples/framework_adapters/out/plain_python.jsonl
```

The LangGraph and CrewAI files are optional integration sketches. They are importable without those
packages installed and raise clear messages only if you ask them to build framework-specific nodes.
