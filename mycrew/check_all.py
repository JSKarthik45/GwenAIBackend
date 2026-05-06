import ast
for f in ['src/mycrew/main.py', 'src/mycrew/crew.py']:
    with open(f, encoding='utf-8') as fh:
        try:
            ast.parse(fh.read())
            print(f'{f}: SYNTAX OK')
        except SyntaxError as e:
            print(f'{f}: SYNTAX ERROR - {e}')

import yaml
for f in ['src/mycrew/config/agents.yaml', 'src/mycrew/config/tasks.yaml']:
    with open(f, encoding='utf-8') as fh:
        try:
            data = yaml.safe_load(fh.read())
            print(f'{f}: YAML OK - keys: {list(data.keys())}')
        except Exception as e:
            print(f'{f}: YAML ERROR - {e}')
