"""A small todo app: Python backend, server-rendered HTML, one file.

Run it with `python main.py`.

Every URL in the HTML is **relative** (`add`, `toggle/3`, `.`) rather than
root-absolute (`/add`). That is what lets the same code work unchanged whether
it is served at `http://localhost:8080/` or behind a path prefix at
`https://your-tunnel/todo/`. See docs/base-path.md in the deployer for why
that matters.

Where the todos live
--------------------
* **No configuration:** a SQLite file beside the code, so `python main.py`
  just works. Inside a container that file is lost when the container is
  replaced.
* **`DATABASE_URL=mysql://...`:** MySQL instead. Universal Local Deployer sets
  this variable itself when a MySQL database is linked to the app, so the
  todos then survive every redeploy.
"""

from __future__ import annotations

import contextlib
import html
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

# Kept beside the code so a bind-mounted volume can persist it later.
DB_PATH = Path(os.environ.get("TODO_DB", "todos.db"))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_MYSQL = DATABASE_URL.startswith("mysql://")

SCHEMA_SQLITE = """
    CREATE TABLE IF NOT EXISTS todos (
        id    INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT    NOT NULL,
        done  INTEGER NOT NULL DEFAULT 0
    )
"""

SCHEMA_MYSQL = """
    CREATE TABLE IF NOT EXISTS todos (
        id    INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        done  TINYINT NOT NULL DEFAULT 0
    ) CHARACTER SET utf8mb4
"""

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Session:
    """One connection, one way to run SQL — whichever database is behind it.

    Statements are written once with `?` placeholders (SQLite's style); for
    MySQL they are rewritten to `%s`. Rows come back indexable by column name
    either way, so nothing else in this file cares which database it is.
    """

    def __init__(self, connection) -> None:
        self.connection = connection

    def execute(self, sql: str, params: tuple = ()):
        if USE_MYSQL:
            cursor = self.connection.cursor()
            cursor.execute(sql.replace("?", "%s"), params)
            return cursor
        return self.connection.execute(sql, params)


def connect_mysql():
    # Imported here so running without MySQL never needs the driver installed.
    import pymysql
    import pymysql.cursors

    parts = urlsplit(DATABASE_URL)
    return pymysql.connect(
        host=parts.hostname,
        port=parts.port or 3306,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        database=parts.path.lstrip("/"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


@contextlib.contextmanager
def db():
    """A session that commits on success, rolls back on error, always closes.

    A connection per request is plenty for a todo list, and it means a database
    restart heals itself: the next request simply connects again.
    """
    if USE_MYSQL:
        connection = connect_mysql()
    else:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
    try:
        yield Session(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    # The deployer only starts this container once the database answers, but a
    # database can still be a moment slower than us after a restart — so try a
    # few times before giving up loudly.
    attempts = 10 if USE_MYSQL else 1
    for attempt in range(1, attempts + 1):
        try:
            with db() as session:
                session.execute(SCHEMA_MYSQL if USE_MYSQL else SCHEMA_SQLITE)
            return
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(2)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Todo</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#161922; --line:#262b38; --text:#e6e8ec;
    --muted:#939aa8; --accent:#5b8cff; --green:#3fb950; --red:#f85149;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); min-height:100vh;
         font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:34rem; margin:0 auto; padding:3rem 1.25rem 4rem; }}
  h1 {{ font-size:1.6rem; margin:0 0 .25rem; }}
  .sub {{ color:var(--muted); margin:0 0 2rem; font-size:.92rem; }}

  form.add {{ display:flex; gap:.5rem; margin-bottom:1.5rem; }}
  input[type=text] {{ flex:1; padding:.7rem .85rem; background:var(--panel);
    color:var(--text); border:1px solid var(--line); border-radius:9px; font:inherit; }}
  input[type=text]:focus {{ outline:2px solid var(--accent); outline-offset:-1px; }}
  button {{ font:inherit; cursor:pointer; border-radius:9px; border:1px solid transparent;
    padding:.7rem 1.1rem; background:var(--accent); color:#fff; }}
  button:hover {{ filter:brightness(1.1); }}

  ul {{ list-style:none; padding:0; margin:0; }}
  li {{ display:flex; align-items:center; gap:.75rem; padding:.75rem .9rem;
        background:var(--panel); border:1px solid var(--line);
        border-radius:9px; margin-bottom:.55rem; }}
  li.done .title {{ text-decoration:line-through; color:var(--muted); }}
  .title {{ flex:1; word-break:break-word; }}
  .icon {{ background:none; border:none; padding:.15rem .4rem; font-size:1.05rem;
           color:var(--muted); }}
  .icon:hover {{ color:var(--text); }}
  .icon.tick:hover {{ color:var(--green); }}
  .icon.remove:hover {{ color:var(--red); }}
  .inline {{ display:inline; margin:0; }}

  .empty {{ text-align:center; color:var(--muted); padding:2.5rem 1rem;
            border:1px dashed var(--line); border-radius:9px; }}
  footer {{ margin-top:2rem; color:var(--muted); font-size:.85rem;
            display:flex; justify-content:space-between; gap:1rem; }}
</style>
</head>
<body>
<main>
  <h1>Todo</h1>
  <p class="sub">Running from a container on your own machine.</p>

  <form class="add" method="post" action="add">
    <input type="text" name="title" placeholder="What needs doing?"
           autocomplete="off" required autofocus maxlength="200">
    <button type="submit">Add</button>
  </form>

  {items}

  <footer>
    <span>{remaining} left &middot; stored in {storage}</span>
    <span>served by {hostname}</span>
  </footer>
</main>
</body>
</html>
"""

EMPTY = '<p class="empty">Nothing here yet. Add something above.</p>'

ITEM = """<li class="{css}">
  <form class="inline" method="post" action="toggle/{id}">
    <button class="icon tick" type="submit" title="Toggle">{mark}</button>
  </form>
  <span class="title">{title}</span>
  <form class="inline" method="post" action="delete/{id}">
    <button class="icon remove" type="submit" title="Delete">&#10005;</button>
  </form>
</li>"""


def render() -> str:
    with db() as connection:
        rows = connection.execute(
            "SELECT id, title, done FROM todos ORDER BY done, id DESC"
        ).fetchall()

    if rows:
        items = "<ul>" + "".join(
            ITEM.format(
                id=row["id"],
                css="done" if row["done"] else "",
                mark="&#9745;" if row["done"] else "&#9744;",
                # Escape: the title is whatever the user typed.
                title=html.escape(row["title"]),
            )
            for row in rows
        ) + "</ul>"
    else:
        items = EMPTY

    return PAGE.format(
        items=items,
        remaining=sum(1 for row in rows if not row["done"]),
        storage="MySQL" if USE_MYSQL else "SQLite (lost on redeploy)",
        hostname=html.escape(os.environ.get("HOSTNAME", "this machine")),
    )


# `.` sends the browser back to the list relative to wherever we are mounted,
# so no route needs to know its own prefix.
def back() -> RedirectResponse:
    return RedirectResponse(".", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(render())


@app.post("/add")
async def add(title: str = Form(...)) -> RedirectResponse:
    cleaned = title.strip()
    if cleaned:
        with db() as connection:
            connection.execute("INSERT INTO todos (title) VALUES (?)", (cleaned[:200],))
    return back()


@app.post("/toggle/{todo_id}")
async def toggle(todo_id: int) -> RedirectResponse:
    with db() as connection:
        connection.execute(
            "UPDATE todos SET done = 1 - done WHERE id = ?", (todo_id,)
        )
    return back()


@app.post("/delete/{todo_id}")
async def delete(todo_id: int) -> RedirectResponse:
    with db() as connection:
        connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return back()


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


init_db()


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 so the port is reachable from outside the container. PORT is
    # supplied by the deployer; 8080 is the local default.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
