"""Nova — a voice-first AI OS core for the Windows desktop.

The one architectural rule: the LLM never touches the OS. The brain emits a
structured Plan (see nova.schema); the agent executor is the only code that
acts on the machine, and every action is verified.
"""

__version__ = "0.1.0"
