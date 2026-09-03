import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_PARTS = {'.git', '__pycache__', '.pytest_cache', '.venv', 'venv', 'node_modules'}
TEXT_SUFFIXES = {'.py', '.js', '.html', '.css', '.md', '.txt', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg', '.env'}

# Fail only on values that look like real embedded credentials, not on variable names.
PATTERNS = [
    re.compile(r"(?i)(SECRET_KEY|ADMIN_PASSWORD|DATABASE_URL|API_KEY|ACCESS_TOKEN)\s*=\s*['\"][^'\"]{12,}['\"]"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)postgres(?:ql)?://[^\s:@/]+:[^\s@/]{6,}@"),
]

violations = []
for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
        continue
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {'Procfile'}:
        continue
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        continue
    rel = path.relative_to(ROOT)
    for pattern in PATTERNS:
        if pattern.search(text):
            violations.append(str(rel))
            break

if violations:
    print('Potential embedded production credentials found:')
    for item in sorted(set(violations)):
        print(f' - {item}')
    sys.exit(1)

print('Repository hygiene check passed: no obvious embedded production credentials.')
