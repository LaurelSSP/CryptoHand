# init_db.py

from sqlalchemy import create_engine
from models import Base
from rich import print
from rich.console import Console

console = Console()

def init_db(db_url='sqlite:///database.db'):
    try:
        engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(engine)
        console.print("[bold green]База данных успешно инициализирована.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Ошибка при инициализации базы данных: {e}[/bold red]")
        exit(1)

if __name__ == "__main__":
    init_db()
