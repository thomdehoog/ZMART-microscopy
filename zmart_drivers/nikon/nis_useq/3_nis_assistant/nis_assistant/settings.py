"""Every constant of the assistant, in one place.

The model's instructions and the advice it is given with a refusal are prose
and stay in ``agent.py``; the numbers and names that one might want to change
are all here. Times are seconds, distances micrometres.
"""

MODEL = "anthropic:claude-opus-5-5"
MODEL_SETTINGS = {
    "anthropic_effort": "high",  # Opus 5.5 defaults to "medium"
    "max_tokens": 16000,  # room for thinking plus a full acquisition plan
    "parallel_tool_calls": False,  # one action at a time, so each is seen before the next
}

# A stage move that travels further than this from where the stage was when the
# operator last wrote (on any one axis, in um) needs their go-ahead in the chat.
CONFIRM_XY_UM = 1000.0
CONFIRM_Z_UM = 100.0
MAX_SWEEP_UM = 100.0  # the longest image-based focus sweep
MAX_EXPOSURE_MS = 60000.0
# For the rough duration in a plan's summary: the time per image besides the
# exposure (moves, saving), and the exposure assumed when a channel sets none.
SECONDS_PER_IMAGE = 1.5
GUESSED_EXPOSURE_MS = 100.0

# The source-reading tools.
SOURCE_MATCHES = 40  # search results returned at most
SOURCE_LINES = 200  # lines read at most in one go

# The conversation is made smaller now and then, between turns (see agent.compact()).
HISTORY_COMPACT_AFTER = 15  # operator turns before the history is made smaller
HISTORY_KEEP_TURNS = 10  # turns kept when it is; older ones are forgotten
HISTORY_FULL_TURNS = 3  # the newest turns keep their state readout and tool results in full
HISTORY_RESULT_CHARS = 300  # an older tool result is cut to this many characters

# -- the window --------------------------------------------------------------------------
OUTPUT_FOLDER = "nis_assistant_runs"  # in the home folder, when --output is not given
# The environment variable that holds the API key, by model provider.
KEY_VARIABLES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}
