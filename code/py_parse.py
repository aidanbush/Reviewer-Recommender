#!/bin/python3.8
import ast
import pg8000

def trim_filename(filename):
    return filename[:-3]

class Visitor(ast.NodeVisitor):
    def __init__(self, filename, conn):
        self.filename = filename
        self.conn = conn
        self.import_name = trim_filename(filename)
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
        
        c = self.conn.cursor()
        c.execute("INSERT INTO functions (filename, name, start_line, end_line) VALUES (%s, %s, %s, %s)",
                (self.filename, node.name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        print("async func", node.name, node.lineno, node.end_lineno)
        
        c = self.conn.cursor()
        c.execute("INSERT INTO functions (filename, name, start_line, end_line) VALUES (%s, %s, %s, %s)",
                (self.filename, node.name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

    def visit_Call(self, node):
        base = None

        if hasattr(node.func, "id"):
            func_name = node.func.id
        else:
            func_name = node.func.attr
            a = node.func
            while(type(a) == ast.Attribute):
                a = a.value
            if type(a) == ast.Name:
                base = a.id

        if base == None or base == "self":
            base = self.import_name

        if base in self.import_mappings:
            # add func call
            print("call", self.import_mappings[base], func_name)
        else:
            print("call", self.filename, func_name)

        # add to db

        c = self.conn.cursor()
        c.execute("INSERT INTO func_call (filename, base_name, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                (self.filename, base, func_name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        print("class", node.name, node.lineno, node.end_lineno)

        # add to db

        c = self.conn.cursor()
        c.execute("INSERT INTO classes (filename, name, start_line, end_line) VALUES (%s, %s, %s, %s)",
                (self.filename, node.name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

def process_file(filename, conn):
    f = open(filename)

    a = ast.parse(f.read(), filename=filename)

    f.close()

    visitor = Visitor(filename, conn)

    visitor.visit(a)

def find_inner_func(conn, filename, start_line, end_line):
    # results may be greater than one if multiple files have the same name

    c = conn.cursor()
    rows = c.execute("SELECT * FROM functions where filename = (%s) and start_line <= (%s) and end_line >= (%s)",
            (filename, start_line, end_line, ))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    return results

def find_func(conn, base_name, func_name):
    filename = base_name + ".py"

    c = conn.cursor()
    rows = c.execute("SELECT * FROM functions where filename = (%s) and name = (%s)",
            (filename, func_name, ))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    return results

def handle_related_funcs(conn):
    # map func calls to functions
    c = conn.cursor()
    rows = c.execute("SELECT * FROM func_call",)
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    for res in results:
        # Threat to validity dont properly check which file the functions are apart of if both files have the same name and func name
        # Threat to validity dont handle functions that are part of a class differenty from a class

        # TODO also check if in class

        # find func it is in
        callers = find_inner_func(conn, res["filename"], res["start_line"], res["end_line"])

        # find func location
        funcs = find_func(conn, res["base_name"], res["name"])

        # if funcs and callers exist match in related_funcs
        if len(callers) > 0 and len(funcs) > 0:
            # combine
            for caller in callers:
                for func in funcs:
                    c = conn.cursor()
                    c.execute("INSERT INTO related_funcs (caller_id, called_id) VALUES (%s, %s)",
                            (caller["id"], func["id"], ))
                    conn.commit()
                    c.close()


def main():
    # connect to db
    conn = pg8000.connect(user="postgres", password="pass", database="review_recomender")

    # parse python file
    filename="test.py"
    process_file(filename, conn)

    handle_related_funcs(conn)

    conn.close()


main()
