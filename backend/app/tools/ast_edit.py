"""
AST-aware file editing using tree-sitter.
Supports Python, JavaScript/TypeScript, Go, Rust.
"""
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from tree_sitter import Language, Parser, Node, Tree
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
import tree_sitter_go as tsgo
import tree_sitter_rust as tsrust


# Language registry
_LANGUAGES: dict[str, Language] = {}
_PARSERS: dict[str, Parser] = {}


def _get_language(file_ext: str) -> Optional[Language]:
    """Get tree-sitter language for file extension."""
    ext = file_ext.lower()
    
    if ext in ('.py',):
        lang_key = 'python'
        if lang_key not in _LANGUAGES:
            _LANGUAGES[lang_key] = Language(tspython.language())
        return _LANGUAGES[lang_key]
    
    elif ext in ('.js', '.jsx', '.mjs', '.cjs'):
        lang_key = 'javascript'
        if lang_key not in _LANGUAGES:
            _LANGUAGES[lang_key] = Language(tsjavascript.language())
        return _LANGUAGES[lang_key]
    
    elif ext in ('.ts', '.tsx'):
        lang_key = 'typescript'
        if lang_key not in _LANGUAGES:
            _LANGUAGES[lang_key] = Language(tstypescript.language_typescript())
        return _LANGUAGES[lang_key]
    
    elif ext in ('.go',):
        lang_key = 'go'
        if lang_key not in _LANGUAGES:
            _LANGUAGES[lang_key] = Language(tsgo.language())
        return _LANGUAGES[lang_key]
    
    elif ext in ('.rs',):
        lang_key = 'rust'
        if lang_key not in _LANGUAGES:
            _LANGUAGES[lang_key] = Language(tsrust.language())
        return _LANGUAGES[lang_key]
    
    return None


def _get_parser(language: Language) -> Parser:
    """Get or create parser for language."""
    lang_name = str(language)
    if lang_name not in _PARSERS:
        parser = Parser(language)
        _PARSERS[lang_name] = parser
    return _PARSERS[lang_name]


def parse_file(content: str, file_path: str) -> Optional[Tree]:
    """Parse file content and return syntax tree."""
    ext = Path(file_path).suffix
    language = _get_language(ext)
    if not language:
        return None
    
    parser = _get_parser(language)
    return parser.parse(content.encode('utf-8'))


def get_node_text(node: Node, content: bytes) -> str:
    """Get text content of a node."""
    return content[node.start_byte:node.end_byte].decode('utf-8')


@dataclass
class Symbol:
    """Represents a code symbol (function, class, etc.)."""
    name: str
    type: str  # 'function', 'class', 'method', etc.
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    parent: Optional[str] = None
    signature: str = ""
    docstring: str = ""


def extract_symbols(tree: Tree, content: bytes, file_path: str) -> List[Symbol]:
    """Extract symbols from syntax tree."""
    symbols = []
    ext = Path(file_path).suffix.lower()
    
    def walk(node: Node, parent_name: str = None):
        # Python
        if ext == '.py':
            if node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0]
                    docstring = _get_python_docstring(node, content)
                    symbols.append(Symbol(
                        name=name,
                        type='function' if not parent_name else 'method',
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=parent_name,
                        signature=sig,
                        docstring=docstring,
                    ))
            elif node.type == 'class_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0]
                    docstring = _get_python_docstring(node, content)
                    symbols.append(Symbol(
                        name=name,
                        type='class',
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=None,
                        signature=sig,
                        docstring=docstring,
                    ))
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.children:
                            walk(child, name)
        
        # JavaScript/TypeScript
        elif ext in ('.js', '.jsx', '.ts', '.tsx'):
            if node.type in ('function_declaration', 'function_expression', 'arrow_function', 'method_definition'):
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0][:200]
                    symbols.append(Symbol(
                        name=name,
                        type='function' if node.type != 'method_definition' else 'method',
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=parent_name,
                        signature=sig,
                    ))
            elif node.type == 'class_declaration':
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0]
                    symbols.append(Symbol(
                        name=name,
                        type='class',
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=None,
                        signature=sig,
                    ))
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.children:
                            walk(child, name)
        
        # Go
        elif ext == '.go':
            if node.type == 'function_declaration':
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0]
                    symbols.append(Symbol(
                        name=name,
                        type='function',
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=parent_name,
                        signature=sig,
                    ))
            elif node.type == 'type_declaration':
                for spec in node.children:
                    if spec.type == 'type_spec':
                        name_node = spec.child_by_field_name('name')
                        if name_node:
                            name = get_node_text(name_node, content)
                            sig = get_node_text(spec, content).split('\n')[0]
                            symbols.append(Symbol(
                                name=name,
                                type='type',
                                start_line=spec.start_point[0] + 1,
                                end_line=spec.end_point[0] + 1,
                                start_byte=spec.start_byte,
                                end_byte=spec.end_byte,
                                parent=None,
                                signature=sig,
                            ))
        
        # Rust
        elif ext == '.rs':
            if node.type == 'function_item':
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0]
                    symbols.append(Symbol(
                        name=name,
                        type='function',
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=parent_name,
                        signature=sig,
                    ))
            elif node.type in ('struct_item', 'enum_item', 'impl_item', 'trait_item'):
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = get_node_text(name_node, content)
                    sig = get_node_text(node, content).split('\n')[0]
                    symbols.append(Symbol(
                        name=name,
                        type=node.type.replace('_item', ''),
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        parent=None,
                        signature=sig,
                    ))
        
        # Recurse
        for child in node.children:
            walk(child, parent_name)
    
    walk(tree.root_node)
    return symbols


def _get_python_docstring(node: Node, content: bytes) -> str:
    """Extract docstring from Python function/class."""
    body = node.child_by_field_name('body')
    if not body:
        return ""
    for child in body.children:
        if child.type == 'expression_statement':
            for grandchild in child.children:
                if grandchild.type == 'string':
                    text = get_node_text(grandchild, content)
                    if text.startswith('"""') and text.endswith('"""'):
                        return text[3:-3].strip()
                    elif text.startswith("'''") and text.endswith("'''"):
                        return text[3:-3].strip()
                    elif text.startswith('"') and text.endswith('"'):
                        return text[1:-1].strip()
                    elif text.startswith("'") and text.endswith("'"):
                        return text[1:-1].strip()
    return ""


def find_symbol(tree: Tree, content: bytes, symbol_name: str, symbol_type: str = None, parent_name: str = None, file_path: str = "") -> Optional[Symbol]:
    """Find a specific symbol in the tree."""
    symbols = extract_symbols(tree, content, file_path)
    for sym in symbols:
        if sym.name == symbol_name:
            if symbol_type and sym.type != symbol_type:
                continue
            if parent_name and sym.parent != parent_name:
                continue
            return sym
    return None


def replace_symbol(content: str, tree: Tree, symbol: Symbol, new_code: str) -> str:
    """Replace a symbol with new code."""
    content_bytes = content.encode('utf-8')
    before = content_bytes[:symbol.start_byte]
    after = content_bytes[symbol.end_byte:]
    return before.decode('utf-8') + new_code + after.decode('utf-8')


def insert_after_symbol(content: str, tree: Tree, symbol: Symbol, new_code: str) -> str:
    """Insert code after a symbol."""
    content_bytes = content.encode('utf-8')
    before = content_bytes[:symbol.end_byte]
    after = content_bytes[symbol.end_byte:]
    if not new_code.endswith('\n'):
        new_code += '\n'
    return before.decode('utf-8') + new_code + after.decode('utf-8')


def insert_before_symbol(content: str, tree: Tree, symbol: Symbol, new_code: str) -> str:
    """Insert code before a symbol."""
    content_bytes = content.encode('utf-8')
    before = content_bytes[:symbol.start_byte]
    after = content_bytes[symbol.start_byte:]
    if not new_code.endswith('\n'):
        new_code += '\n'
    return before.decode('utf-8') + new_code + after.decode('utf-8')


def insert_inside_class(content: str, tree: Tree, class_symbol: Symbol, new_code: str, file_path: str) -> str:
    """Insert code inside a class body (Python)."""
    ext = Path(file_path).suffix.lower()
    content_bytes = content.encode('utf-8')
    
    # Find the class node and its body
    body_node = None
    for child in tree.root_node.children:
        if child.start_byte == class_symbol.start_byte and child.end_byte == class_symbol.end_byte:
            for c in child.children:
                if c.type == 'block':
                    body_node = c
                    break
            break
    
    if body_node:
        indent = '    '
        before = content_bytes[:body_node.end_byte]
        after = content_bytes[body_node.end_byte:]
        lines = new_code.splitlines()
        indented = '\n'.join(indent + line for line in lines)
        if not indented.endswith('\n'):
            indented += '\n'
        # Add blank line before new method for readability
        indented = '\n' + indented
        return before.decode('utf-8') + indented + after.decode('utf-8')
    else:
        return insert_before_symbol(content, tree, class_symbol, new_code)


def add_import(content: str, tree: Tree, import_stmt: str, file_path: str) -> str:
    """Add an import statement at the appropriate location."""
    ext = Path(file_path).suffix.lower()
    content_bytes = content.encode('utf-8')
    
    if ext == '.py':
        last_import_end = 0
        for node in tree.root_node.children:
            if node.type in ('import_statement', 'import_from_statement'):
                last_import_end = max(last_import_end, node.end_byte)
        
        if last_import_end > 0:
            before = content_bytes[:last_import_end]
            after = content_bytes[last_import_end:]
            return before.decode('utf-8') + '\n' + import_stmt + after.decode('utf-8')
        else:
            lines = content.splitlines(keepends=True)
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith('#!') or line.startswith('# -*-'):
                    insert_at = i + 1
                else:
                    break
            lines.insert(insert_at, import_stmt + '\n')
            return ''.join(lines)
    
    elif ext in ('.js', '.jsx', '.ts', '.tsx'):
        last_import_end = 0
        def walk(node):
            nonlocal last_import_end
            if node.type in ('import_statement', 'import_declaration'):
                last_import_end = max(last_import_end, node.end_byte)
            for child in node.children:
                walk(child)
        walk(tree.root_node)
        
        if last_import_end > 0:
            before = content_bytes[:last_import_end]
            after = content_bytes[last_import_end:]
            return before.decode('utf-8') + '\n' + import_stmt + after.decode('utf-8')
    
    elif ext == '.go':
        for node in tree.root_node.children:
            if node.type == 'import_declaration':
                for child in node.children:
                    if child.type == 'import_spec_list':
                        before = content_bytes[:child.end_byte - 1]
                        after = content_bytes[child.end_byte - 1:]
                        return before.decode('utf-8') + '\n\t' + import_stmt + after.decode('utf-8')
    
    elif ext == '.rs':
        last_use_end = 0
        def walk(node):
            nonlocal last_use_end
            if node.type == 'use_declaration':
                last_use_end = max(last_use_end, node.end_byte)
            for child in node.children:
                walk(child)
        walk(tree.root_node)
        
        if last_use_end > 0:
            before = content_bytes[:last_use_end]
            after = content_bytes[last_use_end:]
            return before.decode('utf-8') + '\n' + import_stmt + after.decode('utf-8')
    
    return import_stmt + '\n' + content


def get_supported_operations() -> List[str]:
    """Get list of AST-aware operations."""
    return [
        'ast_replace_function',
        'ast_replace_class',
        'ast_replace_method',
        'ast_add_import',
        'ast_add_function',
        'ast_add_method',
        'ast_get_symbols',
        'ast_find_symbol',
    ]


def is_ast_supported(file_path: str) -> bool:
    """Check if AST editing is supported for this file."""
    ext = Path(file_path).suffix.lower()
    return ext in ('.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs')