# Todo

A minimal todo app — Python backend, server-rendered HTML, one file, no
separate frontend and no JavaScript.

## Run it

```bash
pip install -r requirements.txt
python main.py
```

Then open <http://localhost:8080>.

## Deploy it

Add it to Universal Local Deployer with:

| Setting | Value |
|---|---|
| Port inside the container | `8080` |
| Health check path | `/healthz` |

## Notes

Every link and form action is **relative** (`add`, `toggle/3`, `.`), never
root-absolute (`/add`). That is what lets the identical code work both at
`http://localhost:8080/` and behind a path prefix at
`https://your-tunnel/todo/`.

## Where the todos are stored

| Situation | Storage |
|---|---|
| Nothing configured (`python main.py`) | A SQLite file (`todos.db`, or the path in `TODO_DB`). Inside a container it is lost when the container is replaced. |
| `DATABASE_URL=mysql://user:password@host:3306/db` | MySQL. The `todos` table is created on first start. |

The page footer says which one is in use.

With Universal Local Deployer you do not set `DATABASE_URL` yourself: create a
MySQL database, open this app's **Databases** card, **Link** it, and redeploy.
The variable is injected on every deploy, and the todos then survive redeploys.
