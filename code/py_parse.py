#!/bin/python3.8
import ast

class Visitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.import_name = filename[:-3]
        self.import_mappings = {}
        return

    def clean_import_names(self, name):
        # Threat to validity in how I handle imports
        return name.split(".")[-1]

    def add_import_mapping(self, asname, name):
        self.import_mappings[self.clean_import_names(asname)] = self.clean_import_names(name)

    def visit_Import(self, node):
        for name in node.names:
            print("import", name)
            if name.asname is not None:
                self.add_import_mapping(name.asname, name.name)
            else:
                self.add_import_mapping(name.name, name.name)

        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for name in node.names:
            print("import from", name)
            if name.asname is not None:
                self.add_import_mapping(name.asname, node.module)
            else:
                self.add_import_mapping(name.name, node.module)

        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        print("func", node.name, node.lineno, node.end_lineno)
        # insert filename, func, start, end
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        print("async func", node.name, node.lineno, node.end_lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        if hasattr(node.func, "id"):
            base = None
            func_name = node.func.id
        else:
            func_name = node.func.attr
            a = node.func
            while(type(a) == ast.Attribute):
                a = a.value
            if type(a) == ast.Name:
                base = a.id
            else:
                base = None

        #print("call", "base", base, "func name", func_name)
        if base in self.import_mappings:
            # add func call
            print("call", self.import_mappings[base], func_name)
        else:
            print("call", self.filename, func_name)

        # add to db

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        print("class", node.name, node.lineno, node.end_lineno)
        self.generic_visit(node)

def main():
    filename="test.py"
    f = open(filename)

    a = ast.parse(f.read(), filename=filename)

    visitor = Visitor(filename)

    visitor.visit(a)

    # map func calls to functions

    f.close()

main()
