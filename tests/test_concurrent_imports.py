"""A GIL flip is reported against the import that caused it, not a concurrent one.

The wrapper checks the process-wide gil_enabled() after each loader call returns, so a thread
finishing an unrelated import can see another thread's flip. frontrun explores the interleavings
of two concurrent imports through the real wrapper. Only the GIL flag is modeled: the culprit's
create_module sets it, as CPython does for an extension without Py_mod_gil, and emits the
RuntimeWarning CPython emits in that thread (or not: a filter or warnings capture can swallow it).
"""

import os
import threading
import types
import warnings

import pytest

os.environ.setdefault('GILGUARD_ACTION', 'off')  # the guard itself is driven through _instrument below
import gilguard  # noqa: E402

frontrun = pytest.importorskip('frontrun')

GIL = [False]


class Loader:
    def __init__(self, flips_gil, warns=True):
        self.flips_gil = flips_gil
        self.warns = warns

    def create_module(self, spec):
        if self.flips_gil and not GIL[0]:
            GIL[0] = True
            if self.warns:
                warnings.warn(
                    f"The global interpreter lock (GIL) has been enabled to load module '{spec.name}', which has "
                    'not declared that it can run safely without the GIL.',
                    RuntimeWarning,
                )
            return types.ModuleType(spec.name)
        return None

    def exec_module(self, module):
        pass


class State:
    def __init__(self, warns):
        GIL[0] = False
        gilguard._reported = False
        gilguard._flip_thread = None
        # Created at import, before frontrun patched threading; recreate it so the scheduler sees it.
        gilguard._report_lock = threading.Lock()
        self.culprit = Loader(flips_gil=True, warns=warns)
        self.innocent = Loader(flips_gil=False)
        gilguard._instrument(self.culprit)
        gilguard._instrument(self.innocent)
        self.outcome = {}


def _record(state, who, call):
    try:
        call()
        state.outcome[who] = 'ok'
    except gilguard.GILEnabledError as e:
        state.outcome[who] = f'blamed {e.report.module}'


def import_extension(state):
    spec = types.SimpleNamespace(name='gilneeder._speedups', origin='/site-packages/gilneeder/_speedups.so')
    _record(state, 'gilneeder', lambda: state.culprit.create_module(spec))


def import_pure_python(state):
    module = types.ModuleType('innocent')
    module.__spec__ = types.SimpleNamespace(origin='/app/innocent.py')
    _record(state, 'innocent', lambda: state.innocent.exec_module(module))


CORRECT = {'gilneeder': 'blamed gilneeder._speedups', 'innocent': 'ok'}


@pytest.mark.parametrize('warns', [True, False], ids=['cpython-warning', 'warning-swallowed'])
def test_concurrent_import_is_not_blamed_for_another_threads_gil_flip(monkeypatch, warns):
    monkeypatch.setattr(gilguard, '_installed', True)
    monkeypatch.setattr(gilguard, '_action', 'raise')
    monkeypatch.setattr(gilguard, 'gil_enabled', lambda: GIL[0])
    monkeypatch.setattr(warnings, 'showwarning', gilguard._showwarning)
    # The distribution lookup scans installed metadata under the import system's locks; it doesn't
    # affect which module is blamed.
    monkeypatch.setattr(gilguard, '_distribution_for', lambda module: (None, None))

    outcomes = []

    def names_the_culprit(state):
        outcomes.append(state.outcome)
        return state.outcome == CORRECT

    with warnings.catch_warnings():
        warnings.simplefilter('always', RuntimeWarning)
        result = frontrun.explore(
            setup=lambda: State(warns),
            workers=[import_extension, import_pure_python],
            invariant=names_the_culprit,
            trace_packages=['gilguard'],
            max_executions=300,
        )
    assert result.property_holds, next(o for o in outcomes if o != CORRECT)
