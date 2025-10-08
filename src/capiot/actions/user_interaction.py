import typer

def prompt_user(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def print_status_msg(msg: str) -> None:
    """Print a short status line."""
    try:
        typer.echo(msg)
    except Exception:
        print(msg)