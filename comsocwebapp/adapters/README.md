# `comsocwebapp.adapters` — supporting a new social-choice library

This folder is the only place that knows anything about external solver
libraries. Everything else in the package — the blueprints, the templates, the
database layer — works with plain dicts and lists.

```
adapters/
├── generic.py     library-independent: SQL rows -> dicts, sets, lists
├── fairpyx.py     fair allocation of indivisible items
├── abcvoting.py   approval-based committee voting
├── pabutools.py   participatory budgeting
└── __init__.py    re-exports the generic names, registers the library rules
```

## What `generic.py` gives you

Call these from your adapter instead of writing SQL:

| Function | Shape returned |
| --- | --- |
| `fetch_setting(setting_id)` | `{'id', 'title', 'pref_format', 'status', 'budget_limit'}` |
| `fetch_options(setting_id)` | `[{'id', 'position', 'name', 'description', 'cost'}, ...]` ordered by position |
| `preference_matrix(setting_id, scope, by_name)` | `{user_id: {option: value}}`, rectangular |
| `approval_sets(setting_id, scope, by_name)` | `{user_id: {options with value > 0}}` |
| `rankings(setting_id, scope, by_name)` | `{user_id: [best, ..., worst]}` |
| `option_costs(setting_id, by_name)` | `{option: cost}` |

`scope` is one of `SCOPE_ALL`, `SCOPE_REAL`, `SCOPE_DUMMY` — whether the rule
runs on real participants, generated dummy users, or both.

`by_name=True` keys options by their name (nicer in a log the participants
read); `by_name=False` keys them by `options.id`, which is what you want when
the winners have to be mapped back into the database.

## Adding a library, in four steps

### 1. Create `adapters/yourlib.py`

Copy the shape of an existing file. Two rules matter:

* **Import the library inside the functions, never at module level.** The
  optional extras must stay optional: importing `comsocwebapp.adapters` has to
  work on an installation that does not have your library.
* **Naming the file after the library is fine.** Python 3 imports are absolute,
  so `import yourlib` inside `comsocwebapp/adapters/yourlib.py` still resolves
  to the installed package, not to this file.

```python
"""Adapter for yourlib -- what problem it solves."""
from . import generic

LIBRARY = "yourlib"


def available() -> bool:
    try:
        import yourlib  # noqa: F401
    except ImportError:
        return False
    return True


def to_yourlib_instance(setting_id: int, scope: str = generic.SCOPE_ALL):
    """Turn the stored preferences into whatever yourlib consumes."""
    import yourlib

    matrix = generic.preference_matrix(setting_id, scope, by_name=True)
    return yourlib.Instance(matrix)
```

### 2. Register the rules in the same file

A rule is a callable `(setting_id, scope, **params) -> rules.RuleResult`.
Import `rules` *inside* `register_rules()`: `rules` depends on the adapters, so
importing it at module level would close an import cycle.

```python
def register_rules() -> None:
    from .. import rules

    @rules.register_rule("yourlib_some_rule")
    def yourlib_some_rule(setting_id, scope=generic.SCOPE_ALL, **params):
        import yourlib

        outcome = yourlib.solve(to_yourlib_instance(setting_id, scope))
        return rules.RuleResult(
            outcome=[...],                      # option ids, or "agent:item|item"
            log_lines=["why these winners"],    # shown to admins and participants
        )
```

`outcome` and `log_lines` are serialised into `execution_logs.outcome` and
`execution_logs.run_log` (VARCHAR(4000) each, truncated if longer). Putting
option **ids** in `outcome` is what lets the participant results page print
option names instead of raw numbers.

### 3. Add the module to `LIBRARY_ADAPTERS` in `__init__.py`

```python
from . import abcvoting, fairpyx, generic, pabutools, yourlib

LIBRARY_ADAPTERS = (fairpyx, abcvoting, pabutools, yourlib)
```

That is what makes `installed_libraries()` report it and
`register_library_rules()` call it. The new rules then appear automatically in
the admin's rule dropdown — on installations that have the library, and only
there.

### 4. Declare the optional dependency in `pyproject.toml`

```toml
[project.optional-dependencies]
yourlib = ["yourlib"]
all = ["fairpyx", "abcvoting", "pabutools", "yourlib"]
```

## Testing it

Guard the test with `pytest.importorskip` so the suite still passes without the
extra installed:

```python
def test_yourlib_bridge(app, setting):
    pytest.importorskip("yourlib")
    ...
```

See `tests/test_adapters.py` for the existing examples.
