"""e_mcp.logic.echo: the in-between of the template — a name comes in, a greeting goes out.

Logic is pure: no ports, no I/O, no framework. Replace it with your domain and the edges stay."""


def greet(name: str) -> str:
    """The greeting the demo tool returns; the empty name greets the world."""
    return f"hello {name}" if name else "hello world"
