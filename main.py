"""A small todo app: Python backend, server-rendered HTML, one file.

Run it with `python main.py`.

Every URL in the HTML is **relative** (`add`, `toggle/3`, `.`) rather than
root-absolute (`/add`). That is what lets the same code work unchanged whether
it is served at `http://localhost:8080/` or behind a path prefix at
`https://your-tunnel/todo/`. See docs/base-path.md in the deployer for why
that matters.
"""

from __future__ import annotations

import html
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

# Kept beside the code so a bind-mounted volume can persist it later.
DB_PATH = Path(os.environ.get("TODO_DB", "todos.db"))

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT    NOT NULL,
                done  INTEGER NOT NULL DEFAULT 0
            )
            """
        )


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
    <span>{remaining} left</span>
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
