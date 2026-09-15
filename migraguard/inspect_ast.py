import sqlglot
from sqlglot import exp

print("=== ADD CONSTRAINT FK — deep dive into Constraint node ===")
node = sqlglot.parse_one("ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (user_id) REFERENCES users(id);", read='postgres')
for a in (node.args.get('actions') or []):
    for sub in (a.args.get('expressions') or []):
        print('Constraint type:', type(sub).__name__)
        print('Constraint args:', list(sub.args.keys()))
        print('Constraint this:', sub.args.get('this'), type(sub.args.get('this')).__name__ if sub.args.get('this') else None)
        for expr in (sub.args.get('expressions') or []):
            print('  sub-expr type:', type(expr).__name__, 'args:', list(expr.args.keys()) if hasattr(expr, 'args') else 'N/A')

print()
print("=== ADD PRIMARY KEY — deep Constraint ===")
node2 = sqlglot.parse_one("ALTER TABLE products ADD CONSTRAINT pk PRIMARY KEY (id);", read='postgres')
for a in (node2.args.get('actions') or []):
    for sub in (a.args.get('expressions') or []):
        print('Constraint type:', type(sub).__name__)
        print('Constraint this:', sub.args.get('this'), type(sub.args.get('this')).__name__ if sub.args.get('this') else None)
        for expr in (sub.args.get('expressions') or []):
            print('  sub-expr type:', type(expr).__name__)

print()
print("=== ADD CHECK CONSTRAINT ===")
node3 = sqlglot.parse_one("ALTER TABLE t ADD CONSTRAINT chk CHECK (amount > 0);", read='postgres')
for a in (node3.args.get('actions') or []):
    for sub in (a.args.get('expressions') or []):
        print('Constraint type:', type(sub).__name__)
        print('Constraint this:', sub.args.get('this'), type(sub.args.get('this')).__name__ if sub.args.get('this') else None)
        for expr in (sub.args.get('expressions') or []):
            print('  sub-expr type:', type(expr).__name__)

print()
print("=== ColumnDef with inline REFERENCES ===")
node4 = sqlglot.parse_one("ALTER TABLE comments ADD COLUMN post_id INT REFERENCES posts(id);", read='postgres')
for a in (node4.args.get('actions') or []):
    print('action type:', type(a).__name__)
    if type(a).__name__ == 'ColumnDef':
        print('col name:', a.args.get('this').name if a.args.get('this') else None)
        for c in (a.args.get('constraints') or []):
            print('  constraint kind type:', type(c.args.get('kind')).__name__)
            print('  constraint kind args:', list(c.args.get('kind').args.keys()) if hasattr(c.args.get('kind'), 'args') else 'N/A')

print()
print("=== DROP COLUMN — what is inside Drop action ===")
node5 = sqlglot.parse_one("ALTER TABLE users DROP COLUMN legacy_token;", read='postgres')
for a in (node5.args.get('actions') or []):
    print('action type:', type(a).__name__)
    print('action kind:', a.args.get('kind'))
    print('action tables:', a.args.get('tables'))
    print('action expressions:', a.args.get('expressions'))

print()
print("=== CREATE INDEX — table and column extraction ===")
ci = sqlglot.parse_one("CREATE INDEX CONCURRENTLY idx_x ON users (email);", read='postgres')
ci_this = ci.args.get('this')
print('Index table:', ci_this.args.get('table'))
tbl = ci_this.args.get('table')
print('Table name:', tbl.name if hasattr(tbl, 'name') else str(tbl))
params = ci_this.args.get('params')
cols = params.args.get('columns') or []
for c in cols:
    print('  col type:', type(c).__name__, 'name:', c.name if hasattr(c, 'name') else str(c))
    # Ordered node wraps the actual col
    actual = c.args.get('this') if hasattr(c, 'args') else c
    print('  actual col type:', type(actual).__name__, 'name:', actual.name if hasattr(actual, 'name') else str(actual))
