"""Python source indexing with explicit lexical bindings and conservative calls."""

import ast
from collections import defaultdict
from pathlib import Path


def module_name(path):
    parts = list(path.with_suffix("").parts)
    if len(parts) > 1 and parts[0] == "src":
        parts.pop(0)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__init__"


class Bindings(ast.NodeVisitor):
    """Collect one scope without descending into another lexical scope."""
    def __init__(self, qualified, module, is_package=False):
        self.qualified, self.module, self.is_package = qualified, module, is_package
        self.names = {}
        self.globals = set()
        self.nonlocals = set()

    def put(self, name, value):
        self.names[name] = value if name not in self.names else None

    def visit_FunctionDef(self, node):
        self.put(node.name, self.qualified + "." + node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        pass

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.put(node.id, None)

    def visit_Global(self, node):
        self.globals.update(node.names)

    def visit_Nonlocal(self, node):
        self.nonlocals.update(node.names)

    def visit_Import(self, node):
        for alias in node.names:
            self.put(alias.asname or alias.name.split('.')[0], alias.name if alias.asname else alias.name.split('.')[0])

    def visit_ImportFrom(self, node):
        base = node.module or ''
        if node.level:
            package = self.module if self.is_package else self.module.rpartition('.')[0]
            parts = package.split('.') if package else []
            base = '.'.join(parts[:max(0, len(parts) - node.level + 1)] + ([base] if base else []))
        for alias in node.names:
            if alias.name != '*':
                self.put(alias.asname or alias.name, '.'.join(filter(None, (base, alias.name))))

    def visit_ExceptHandler(self, node):
        if node.name:
            self.put(node.name, None)
        self.generic_visit(node)

    def visit_ListComp(self, node):
        # Comprehensions have their own scope. Their call sites are left unresolved.
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def scope_bindings(node, qualified, module, is_package):
    result = Bindings(qualified, module, is_package)
    for child in node.body:
        result.visit(child)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
        for arg in args:
            result.names[arg.arg] = None
    for name in result.globals | result.nonlocals:
        result.names.pop(name, None)
    return result


class Parser(ast.NodeVisitor):
    def __init__(self, relative, text):
        self.path = relative.as_posix()
        self.module = module_name(relative)
        self.lines = text.splitlines()
        self.is_package = relative.name == '__init__.py'
        self.scopes = []
        self.active_function = None
        self.symbols, self.calls = [], []
        self.imports = {}
        self.used_ids = set()

    def visit_Module(self, node):
        bindings = scope_bindings(node, self.module, self.module, self.is_package)
        self.scopes.append(('module', self.module, bindings))
        self.imports = bindings.names
        for child in node.body:
            self.visit(child)
        self.scopes.pop()

    def add_symbol(self, node, kind, qualified):
        identifier = f'{self.path}:{qualified}'
        if identifier in self.used_ids:
            identifier += f'@{node.lineno}'
        self.used_ids.add(identifier)
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        text = '\n'.join(self.lines[start - 1:node.end_lineno])
        self.symbols.append({'id': identifier, 'path': self.path, 'name': node.name, 'qualified': qualified,
            'kind': kind, 'start': start, 'end': node.end_lineno, 'text': text,
            'search_text': f'{self.path} {qualified} {ast.get_docstring(node) or ""}\n{text}'})
        return identifier

    def visit_ClassDef(self, node):
        qualified = self.scopes[-1][1] + '.' + node.name
        self.add_symbol(node, 'class', qualified)
        self.scopes.append(('class', qualified, scope_bindings(node, qualified, self.module, self.is_package)))
        previous = self.active_function
        self.active_function = None
        for child in node.body:
            self.visit(child)
        self.active_function = previous
        self.scopes.pop()

    def visit_FunctionDef(self, node):
        parent_kind, parent_name, _ = self.scopes[-1]
        qualified = parent_name + '.' + node.name
        identifier = self.add_symbol(node, 'function', qualified)
        bindings = scope_bindings(node, qualified, self.module, self.is_package)
        args = [*node.args.posonlyargs, *node.args.args]
        # Recognize conventional instance/class receivers only when not reassigned.
        reassigned = Bindings(qualified, self.module, self.is_package)
        for child in node.body:
            reassigned.visit(child)
        decorators = [ast.unparse(d) for d in node.decorator_list]
        if parent_kind == 'class' and args and args[0].arg in {'self', 'cls'} and 'staticmethod' not in decorators:
            if args[0].arg not in reassigned.names:
                bindings.names[args[0].arg] = '@receiver:' + parent_name
        self.scopes.append(('function', qualified, bindings))
        previous, self.active_function = self.active_function, identifier
        for child in node.body:
            self.visit(child)
        self.active_function = previous
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def lookup(self, name):
        current = self.scopes[-1][2]
        if name in current.globals:
            return self.scopes[0][2].names.get(name)
        scopes = self.scopes[:-1] if name in current.nonlocals else self.scopes
        for kind, _, bindings in reversed(scopes):
            if kind == 'class':
                continue  # Methods do not close over their class's namespace.
            if name in bindings.names:
                return bindings.names[name]
        return None

    def visit_Call(self, node):
        if self.active_function:
            target = ast.unparse(node.func)
            parts = target.split('.')
            first = parts[0]
            bound = self.lookup(first) if all(part.isidentifier() for part in parts) else None
            candidate = None
            if bound:
                if bound.startswith('@receiver:'):
                    if len(parts) == 2:
                        candidate = bound.removeprefix('@receiver:') + '.' + parts[1]
                else:
                    candidate = '.'.join([bound, *parts[1:]])
            self.calls.append({'source': self.active_function, 'target': target, 'line': node.lineno,
                               'candidate': candidate})
        self.generic_visit(node)

    def visit_Lambda(self, node):
        pass

    def visit_ListComp(self, node):
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def windows(relative, text, kind='text'):
    lines = text.splitlines()
    records = []
    for start in range(0, len(lines), 64):
        excerpt = '\n'.join(lines[start:start + 80])
        records.append({'id': f'{relative.as_posix()}:lines:{start + 1}', 'path': relative.as_posix(),
            'name': relative.stem, 'qualified': module_name(relative) if kind == 'module' else relative.as_posix(),
            'kind': kind, 'start': start + 1, 'end': min(start + 80, len(lines)), 'text': excerpt,
            'search_text': f'{relative.as_posix()}\n{excerpt}'})
        if start + 80 >= len(lines):
            break
    return records


def parse_file(relative, text):
    if relative.suffix == '.py':
        try:
            tree = ast.parse(text)
            parser = Parser(relative, text)
            parser.visit(tree)
            return [*windows(relative, text, 'module'), *parser.symbols], parser.calls, parser.imports, None
        except (SyntaxError, ValueError, RecursionError) as exc:
            error = f'{relative}:{getattr(exc, "lineno", "?")}: {str(exc)}'
    else:
        error = None
    return windows(relative, text), [], {}, error


def resolve_calls(records, pending, imports):
    qualified = defaultdict(list)
    for record in records:
        if record['kind'] in {'function', 'class'}:
            qualified[record['qualified']].append(record['id'])
    aliases = {}
    for path, bindings in imports.items():
        for name, target in bindings.items():
            if target:
                aliases[module_name(Path(path)) + '.' + name] = target
    edges, unresolved = [], []
    for call in pending:
        candidate = call.get('candidate')
        seen = set()
        while candidate and candidate not in qualified and candidate in aliases and candidate not in seen:
            seen.add(candidate)
            candidate = aliases[candidate]
        targets = qualified.get(candidate, [])
        if len(targets) == 1:
            edges.append({'source': call['source'], 'target': targets[0], 'line': call['line']})
        else:
            unresolved.append(call)
    return edges, unresolved
