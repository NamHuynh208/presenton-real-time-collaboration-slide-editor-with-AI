"""Check the revision graph without importing the application or database drivers."""
import ast
from pathlib import Path


def test_migrations_have_one_head():
    backend = Path(__file__).resolve().parents[2]
    revisions = set()
    parents = set()
    for path in (backend / "alembic" / "versions").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            if node.target.id == "revision":
                revisions.add(ast.literal_eval(node.value))
            elif node.target.id == "down_revision":
                parent = ast.literal_eval(node.value)
                if parent is not None:
                    parents.add(parent)
    assert parents <= revisions, "Migration references an unknown parent"
    assert revisions - parents == {"a1b2c3d4e5f6"}, "Expected exactly one migration head"


if __name__ == "__main__":
    test_migrations_have_one_head()
