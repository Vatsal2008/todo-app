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

Todos are stored in a SQLite file inside the container, so they are lost when
the container is replaced. Set `TODO_DB` to a path on a mounted volume to keep
them.
