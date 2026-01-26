DUMP_VARS_CODE = """
import base64
import pickle
import sys

def _dump_session_state():
    skip_names = {
        '_dump_session_state', '_ih', '_oh', '_dh', 'In', 'Out', 'get_ipython',
        'exit', 'quit', 'open', '__builtins__', '__name__', '__doc__', '__package__',
        '__loader__', '__spec__', '__annotations__', '__file__', '__cached__',
    }
    skip_types = (type, type(sys), type(lambda: None))
    
    state = {}
    for name, value in list(globals().items()):
        if name.startswith('_'):
            continue
        if name in skip_names:
            continue
        if isinstance(value, skip_types):
            continue
        try:
            state[name] = pickle.dumps(value)
        except Exception:
            pass
    
    return base64.b64encode(pickle.dumps(state)).decode('utf-8')

_dump_session_state()
"""

LOAD_VARS_CODE = """
import base64
import pickle

def _load_session_state(state_b64):
    state = pickle.loads(base64.b64decode(state_b64))
    for name, value_bytes in state.items():
        try:
            globals()[name] = pickle.loads(value_bytes)
        except Exception:
            pass

_load_session_state("{state_b64}")
"""
